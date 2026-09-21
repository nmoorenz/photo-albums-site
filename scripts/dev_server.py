#!/usr/bin/env python3
"""Serve the site locally, standing in for CloudFront, S3 and both Lambdas.

    python scripts/dev_server.py --sample     first run: copy example/ into photos/
    python scripts/dev_server.py              then just serve

Open http://localhost:8000/.

What it serves:

    /                      site/ as-is
    /manifest.json         built from photos/albums.csv + photos/, in memory
    /photos/.../full/...   derivatives generated on the fly from photos/
    /api/me                a fake signed-in admin -- no Cognito, no login
    /api/comments...       the real routes, backed by .dev-comments.json

Comments written here go to .dev-comments.json in the repo root (gitignored)
and never touch S3. Nothing in this script runs in production.

Keep this file ASCII-only.
"""

import argparse
import io
import json
import re
import sys
import urllib.parse
import uuid
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import album_sync as core  # noqa: E402

REPO_ROOT = core.REPO_ROOT
SITE_DIR = REPO_ROOT / "site"
COMMENTS_FILE = REPO_ROOT / ".dev-comments.json"

ME = {"name": "Local tester", "sub": "local-tester", "admin": True}

_derivative_cache = {}


# ---------------------------------------------------------------------------
# sample data
# ---------------------------------------------------------------------------


EXAMPLE_DIR = REPO_ROOT / "example"


def make_sample_scans():
    """Copy example/ into photos/ -- both CSVs and every album's images.

    example/ holds real (if very plain) JPEGs, so the sample site works with
    nothing generated and nothing downloaded.
    """
    import shutil

    core.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("albums.csv", "photos.csv"):
        target = core.PHOTOS_DIR / name
        if not target.exists():
            shutil.copyfile(EXAMPLE_DIR / name, target)
            print("seeded %s from example/%s" % (target, name))

    rows = core.read_photos_csv()
    if not rows:
        core.die("example/photos.csv has no rows.")

    copied = missing = 0
    for row in rows:
        source = EXAMPLE_DIR / row["album"] / row["file"]
        target = core.PHOTOS_DIR / row["album"] / row["file"]
        if target.exists():
            continue
        if not source.exists():
            core.warn("example/%s/%s is listed in photos.csv but not in example/"
                      % (row["album"], row["file"]))
            missing += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied += 1

    print("copied %d example scan(s) into %s%s"
          % (copied, core.PHOTOS_DIR, " (%d missing)" % missing if missing else ""))


# ---------------------------------------------------------------------------
# manifest and images, built from the local folders
# ---------------------------------------------------------------------------


def build_manifest():
    albums = core.read_albums_csv()
    rows = core.read_photos_csv()
    local = core.scan_local()
    available = {album_id: set(entries) for album_id, entries in local.items()}
    return core.build_manifest(albums, rows, available), local


def find_source(local, album_id, pid):
    return local.get(album_id, {}).get(pid)


def derivative_bytes(path, size_name):
    key = (str(path), size_name, path.stat().st_mtime_ns)
    if key not in _derivative_cache:
        max_edge = core.THUMB_MAX if size_name == "thumb" else core.FULL_MAX
        _derivative_cache.clear()  # one photo at a time is plenty for a dev server
        _derivative_cache[key] = core.derivative(path, max_edge)
    return _derivative_cache[key]


# ---------------------------------------------------------------------------
# comments, in a local file
# ---------------------------------------------------------------------------


def load_comments():
    if COMMENTS_FILE.exists():
        return json.loads(COMMENTS_FILE.read_text(encoding="utf-8"))
    return {}


def save_comments(data):
    COMMENTS_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# request handling
# ---------------------------------------------------------------------------


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE_DIR), **kwargs)

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or "") or self.path in ("/", "/manifest.json"):
            super().log_message(fmt, *args)

    # -- helpers ---------------------------------------------------------

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except ValueError:
            return {}

    def api_parts(self):
        tail = re.sub(r"^/api/comments/?", "", self.path.split("?")[0])
        return [urllib.parse.unquote(p) for p in tail.split("/") if p]

    # -- routes ----------------------------------------------------------

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/manifest.json", "/photos/manifest.json"):
            manifest, _local = build_manifest()
            return self.send_bytes(json.dumps(manifest, indent=1).encode("utf-8"), "application/json")

        image = re.match(r"^/photos/([^/]+)/(thumb|full)/(.+)\.jpg$", path)
        if image:
            album_id, size_name, pid = image.groups()
            _manifest, local = build_manifest()
            source = find_source(local, album_id, pid)
            if source is None:
                return self.send_error(404, "No scan %s/%s" % (album_id, pid))
            return self.send_bytes(derivative_bytes(source, size_name), "image/jpeg")

        if path == "/api/me":
            return self.send_json(200, ME)

        if path in ("/api/comments", "/api/comments/"):
            data = load_comments()
            counts = {album: sum(len(t) for t in threads.values())
                      for album, threads in data.items()}
            return self.send_json(200, {"counts": counts})

        if path.startswith("/api/comments/"):
            parts = self.api_parts()
            if len(parts) == 1:
                return self.send_json(200, {"albumId": parts[0],
                                            "threads": load_comments().get(parts[0], {})})
            return self.send_json(404, {"error": "Not found."})

        if path.startswith("/auth/logout"):
            return self.send_json(200, {"note": "No login to log out of in dev."})

        return super().do_GET()

    def do_POST(self):
        parts = self.api_parts()
        if not self.path.startswith("/api/comments/") or len(parts) != 2:
            return self.send_json(404, {"error": "Not found."})

        album_id, photo_id = parts
        text = str(self.read_body().get("body") or "").strip()
        if not text:
            return self.send_json(400, {"error": "Nothing to say?"})
        if len(text) > 2000:
            return self.send_json(400, {"error": "That comment is too long."})

        comment = {"id": str(uuid.uuid4()), "author": ME["name"], "sub": ME["sub"],
                   "at": now_iso(), "body": text}
        data = load_comments()
        data.setdefault(album_id, {}).setdefault(photo_id, []).append(comment)
        save_comments(data)
        return self.send_json(201, {"comment": comment})

    def do_DELETE(self):
        parts = self.api_parts()
        if not self.path.startswith("/api/comments/") or len(parts) != 3:
            return self.send_json(404, {"error": "Not found."})

        album_id, photo_id, comment_id = parts
        data = load_comments()
        thread = data.get(album_id, {}).get(photo_id, [])
        remaining = [c for c in thread if c["id"] != comment_id]
        if len(remaining) == len(thread):
            return self.send_json(404, {"error": "No comment with that id."})

        if remaining:
            data[album_id][photo_id] = remaining
        else:
            del data[album_id][photo_id]
            if not data[album_id]:
                del data[album_id]
        save_comments(data)
        return self.send_json(200, {"deleted": comment_id})


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--sample", action="store_true",
                        help="copy the example albums and their images into photos/")
    args = parser.parse_args()

    if args.sample:
        make_sample_scans()

    manifest, _local = build_manifest()
    if not manifest["albums"]:
        print("No albums to show. Put scans under photos/<album-id>/ and run"
              " `album_sync.py index`, or re-run this with --sample.")
        return

    print("%d album(s), %d scan(s)."
          % (len(manifest["albums"]), sum(a["photoCount"] for a in manifest["albums"])))
    print("Signed in as '%s' (admin). Comments go to %s" % (ME["name"], COMMENTS_FILE.name))
    print("Serving http://localhost:%d/  -- Ctrl-C to stop" % args.port)

    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
