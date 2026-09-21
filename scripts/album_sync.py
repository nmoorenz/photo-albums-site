#!/usr/bin/env python3
"""Sync scanned photo albums to S3 and rebuild the site manifest.

Commands
    index     Add a row to photos.csv for every scan not listed yet.
    check     Join photos.csv to the scans on disk and report problems. No AWS.
    sync      Upload new scans, build derivatives, rebuild manifest.json.
    download  Pull the original scans back from S3 into ./photos.
    rename    Re-key comment threads after a file or album is renamed.
    delete    Remove an album: its scans in S3, its comments, and its rows.

Scans keep whatever name the scanner gave them. Put them in a folder per
album, run `index`, then fill in the page columns in photos/photos.csv.
Both CSVs sit in photos/ so they stay out of git; copy the pair in example/
there to start.

    photos/green-album/IMG_0041.jpg
    photos/green-album/IMG_0042.jpg

    photos/photos.csv:
    album,file,page,kind,order
    green-album,IMG_0041.jpg,3,page,1
    green-album,IMG_0042.jpg,3,,2

S3 layout:

    photos/<album>/orig/<original filename>   untouched scan, never served
    photos/<album>/full/<photo-id>.jpg        lightbox size
    photos/<album>/thumb/<photo-id>.jpg       grid size
    photos/manifest.json                      everything the frontend reads
    comments/<album>.json                     written by comments-api, touched
                                              here only by `rename`

The photo id is the filename slugged (IMG_0042.jpg -> img_0042). It follows
the file, not the page number, so re-ordering pages never orphans a comment
thread.

Keep this file ASCII-only.
"""

import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from PIL import Image, ImageOps

REPO_ROOT = Path(__file__).resolve().parent.parent
PHOTOS_DIR = REPO_ROOT / "photos"
# Both CSVs live inside photos/, which is gitignored, so album titles, family
# names and page structure never reach the repository. example/ holds a
# committed pair showing the shape.
ALBUMS_CSV = PHOTOS_DIR / "albums.csv"
PHOTOS_CSV = PHOTOS_DIR / "photos.csv"
MANIFEST_KEY = "photos/manifest.json"

THUMB_MAX = 600
FULL_MAX = 2000
JPEG_QUALITY = 85
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}

COVER = "cover"
PAGE = "page"
PHOTO = "photo"

QUIET = False


def log(*args):
    if not QUIET:
        print(*args)


def warn(*args):
    print("WARN:", *args, file=sys.stderr)


def die(message):
    print("ERROR:", message, file=sys.stderr)
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Photo ids. The only place that turns a filename into the id used in S3 keys,
# the manifest and comment threads.
# ---------------------------------------------------------------------------


def photo_id(filename):
    stem = Path(filename).stem.lower()
    slug = re.sub(r"[^a-z0-9._-]+", "-", stem).strip("-._")
    return slug or "scan"


# ---------------------------------------------------------------------------
# albums.csv
# ---------------------------------------------------------------------------

ALBUM_COLUMNS = ["id", "title", "sort_date", "end_date", "type", "source", "tags"]


def read_albums_csv():
    if not ALBUMS_CSV.exists():
        die("no albums.csv at %s -- copy example/albums.csv there and edit it."
            % ALBUMS_CSV)

    albums = {}
    with ALBUMS_CSV.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in ALBUM_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            die("albums.csv is missing column(s): %s" % ", ".join(missing))
        for row in reader:
            album_id = (row.get("id") or "").strip()
            if not album_id:
                continue
            albums[album_id] = {
                "id": album_id,
                "title": (row.get("title") or album_id).strip(),
                "sortDate": (row.get("sort_date") or "").strip(),
                "endDate": (row.get("end_date") or "").strip(),
                "type": (row.get("type") or "range").strip().lower(),
                "source": (row.get("source") or "").strip(),
                "tags": sorted(set((row.get("tags") or "").lower().split())),
            }
    return albums


def year_of(value):
    value = (value or "").strip()
    return value[:4] if len(value) >= 4 and value[:4].isdigit() else ""


def decade_of(value):
    year = year_of(value)
    return "%ds" % (int(year) // 10 * 10) if year else ""


def date_display(album):
    start = year_of(album["sortDate"])
    end = year_of(album["endDate"])
    if start and end and end != start:
        return "%s-%s" % (start, end)
    return start or end or ""


# ---------------------------------------------------------------------------
# photos.csv -- one row per scan, the page structure you fill in by hand
# ---------------------------------------------------------------------------

PHOTO_COLUMNS = ["album", "file", "page", "kind", "order"]


def read_photos_csv():
    """Rows in file order, each with album, file, page, kind, order and id."""
    if not PHOTOS_CSV.exists():
        return []

    rows = []
    with PHOTOS_CSV.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in PHOTO_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            die("photos.csv is missing column(s): %s" % ", ".join(missing))
        for index, row in enumerate(reader):
            album = (row.get("album") or "").strip()
            filename = (row.get("file") or "").strip()
            if not album or not filename:
                continue

            page_raw = (row.get("page") or "").strip()
            if page_raw and not page_raw.isdigit():
                warn("%s/%s: page '%s' is not a number, treated as blank"
                     % (album, filename, page_raw))
                page_raw = ""

            order_raw = (row.get("order") or "").strip()
            kind = (row.get("kind") or "").strip().lower() or PHOTO
            if kind not in (COVER, PAGE, PHOTO):
                warn("%s/%s: kind '%s' is not cover/page/blank, treated as a photo"
                     % (album, filename, kind))
                kind = PHOTO

            rows.append({
                "album": album,
                "file": filename,
                "id": photo_id(filename),
                "page": int(page_raw) if page_raw else None,
                "kind": kind,
                "order": int(order_raw) if order_raw.isdigit() else index,
                "row": index + 2,  # spreadsheet line number, for messages
            })
    return rows


def write_photos_csv(rows):
    with PHOTOS_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(PHOTO_COLUMNS)
        for row in rows:
            writer.writerow([
                row["album"],
                row["file"],
                "" if row["page"] is None else row["page"],
                "" if row["kind"] == PHOTO else row["kind"],
                row["order"],
            ])


# ---------------------------------------------------------------------------
# Local scans
# ---------------------------------------------------------------------------


def scan_local():
    """{album_id: {photo_id: Path}} for every readable scan on disk."""
    if not PHOTOS_DIR.exists():
        return {}

    found = {}
    for album_dir in sorted(p for p in PHOTOS_DIR.iterdir() if p.is_dir()):
        if album_dir.name.startswith(("_", ".")):
            continue
        entries = {}
        for path in sorted(album_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            pid = photo_id(path.name)
            if pid in entries:
                warn("%s/%s: same photo id as %s, skipped"
                     % (album_dir.name, path.name, entries[pid].name))
                continue
            entries[pid] = path
        found[album_dir.name] = entries
    return found


def derivative(path, max_edge):
    """JPEG bytes, EXIF-rotated and resized to fit max_edge."""
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.thumbnail((max_edge, max_edge), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return buffer.getvalue()


# ---------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------


def aws_setup():
    load_dotenv(REPO_ROOT / ".env")
    bucket = os.environ.get("S3_BUCKET")
    region = os.environ.get("AWS_REGION")
    profile = os.environ.get("AWS_PROFILE")
    if not bucket:
        die("S3_BUCKET is not set -- copy env.example to .env and fill it in.")
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("s3"), bucket


def list_keys(s3, bucket, prefix):
    keys = {}
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        for obj in page.get("Contents", []):
            keys[obj["Key"]] = obj["Size"]
        if not page.get("IsTruncated"):
            return keys
        token = page["NextContinuationToken"]


def ids_in_s3(keys):
    """{album_id: {photo_id}} from the "full" derivatives present in S3."""
    available = {}
    for key in keys:
        parts = key.split("/")
        if len(parts) != 4 or parts[2] != "full":
            continue
        available.setdefault(parts[1], set()).add(parts[3].rsplit(".", 1)[0])
    return available


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------


def photo_entry(album_id, pid):
    return {
        "id": pid,
        "thumb": "/photos/%s/thumb/%s.jpg" % (album_id, pid),
        "full": "/photos/%s/full/%s.jpg" % (album_id, pid),
    }


def build_album(album, rows, available):
    """rows: this album's photos.csv rows. available: set of photo ids present."""
    album_id = album["id"]
    usable = [r for r in sorted(rows, key=lambda r: (r["order"], r["file"]))
              if r["id"] in available]

    cover = None
    pages = {}
    loose = []

    for row in usable:
        entry = photo_entry(album_id, row["id"])
        if row["kind"] == COVER:
            if cover is None:
                cover = entry
            continue
        if row["page"] is None:
            loose.append(entry)
            continue
        group = pages.setdefault(row["page"], {"scan": None, "photos": []})
        if row["kind"] == PAGE and group["scan"] is None:
            group["scan"] = entry
        else:
            group["photos"].append(entry)

    groups = []
    if cover is not None:
        groups.append({"page": None, "label": "Cover", "scan": cover, "photos": []})
    for page in sorted(pages):
        groups.append({
            "page": page,
            "label": "Page %d" % page,
            "scan": pages[page]["scan"],
            "photos": pages[page]["photos"],
        })
    if loose:
        groups.append({"page": None, "label": "Loose photos", "scan": None, "photos": loose})

    if cover is None:
        for group in groups:
            if group["photos"]:
                cover = group["photos"][0]
                break
            if group["scan"]:
                cover = group["scan"]
                break

    entry = dict(album)
    entry.update({
        "dateDisplay": date_display(album),
        "decade": decade_of(album["sortDate"]),
        "cover": cover,
        "photoCount": len(usable),
        "groups": groups,
    })
    return entry


def build_manifest(albums, rows, available):
    by_album = {}
    for row in rows:
        by_album.setdefault(row["album"], []).append(row)

    entries = []
    for album_id in sorted(by_album):
        album = albums.get(album_id)
        if album is None:
            warn("photos.csv lists album '%s', which has no row in albums.csv" % album_id)
            continue
        present = available.get(album_id, set())
        if not any(r["id"] in present for r in by_album[album_id]):
            continue
        entries.append(build_album(album, by_album[album_id], present))

    entries.sort(key=lambda a: (a["sortDate"] or "9999", a["title"].lower()))

    for album_id in sorted(albums):
        if album_id not in by_album:
            warn("albums.csv row '%s' has no scans in photos.csv" % album_id)

    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "albums": entries,
    }


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_index(args):
    """Add a photos.csv row for every scan on disk that has no row yet."""
    albums = read_albums_csv()
    local = scan_local()
    rows = read_photos_csv()

    known = {(r["album"], r["file"]) for r in rows}
    next_order = {}
    for row in rows:
        next_order[row["album"]] = max(next_order.get(row["album"], 0), row["order"])

    added = 0
    for album_id, entries in sorted(local.items()):
        if album_id not in albums:
            warn("folder photos/%s has no row in albums.csv, not indexed" % album_id)
            continue
        for _pid, path in sorted(entries.items(), key=lambda kv: kv[1].name.lower()):
            if (album_id, path.name) in known:
                continue
            next_order[album_id] = next_order.get(album_id, 0) + 1
            rows.append({
                "album": album_id,
                "file": path.name,
                "id": photo_id(path.name),
                "page": None,
                "kind": PHOTO,
                "order": next_order[album_id],
                "row": 0,
            })
            added += 1
            log("add %s/%s" % (album_id, path.name))

    # Rows whose file is gone are kept: the file may just live on another
    # machine. They are reported by `check`.
    write_photos_csv(rows)
    log("\n%d new row(s); photos.csv now has %d." % (added, len(rows)))
    if added:
        log("Fill in page and kind (cover / page / blank) for the new rows.")


def cmd_check(_args):
    albums = read_albums_csv()
    local = scan_local()
    rows = read_photos_csv()

    if not rows:
        log("photos.csv is empty -- run `album_sync.py index` first.")
        return

    available = {album: set(entries) for album, entries in local.items()}
    manifest = build_manifest(albums, rows, available)

    listed = {(r["album"], r["file"]) for r in rows}
    for album_id, entries in sorted(local.items()):
        for path in entries.values():
            if (album_id, path.name) not in listed:
                warn("%s/%s is on disk but not in photos.csv -- run `index`"
                     % (album_id, path.name))

    for row in rows:
        if row["id"] not in available.get(row["album"], set()):
            log("note %s/%s listed in photos.csv but not on this machine"
                % (row["album"], row["file"]))

    for album in manifest["albums"]:
        pages = [g for g in album["groups"] if g["page"] is not None]
        no_scan = [g["page"] for g in pages if g["scan"] is None]
        unplaced = sum(len(g["photos"]) for g in album["groups"] if g["label"] == "Loose photos")
        notes = []
        if no_scan:
            notes.append("no page scan for %s" % ", ".join(str(p) for p in no_scan))
        if unplaced:
            notes.append("%d with no page" % unplaced)
        log("%-28s %-12s %3d scans, %2d pages%s"
            % (album["id"], album["dateDisplay"] or "-", album["photoCount"], len(pages),
               (", " + "; ".join(notes)) if notes else ""))

    log("\n%d album(s), %d scan(s)."
        % (len(manifest["albums"]), sum(a["photoCount"] for a in manifest["albums"])))


def cmd_sync(args):
    albums = read_albums_csv()
    rows = read_photos_csv()
    local = scan_local()
    if not rows:
        die("photos.csv is empty -- run `album_sync.py index` first.")

    s3, bucket = aws_setup()
    existing = list_keys(s3, bucket, "photos/")
    listed = {(r["album"], r["file"]) for r in rows}
    uploaded = 0

    for album_id, entries in sorted(local.items()):
        if album_id not in albums:
            warn("folder photos/%s has no row in albums.csv, not uploaded" % album_id)
            continue
        for pid, path in sorted(entries.items()):
            if (album_id, path.name) not in listed:
                warn("%s/%s is not in photos.csv, not uploaded -- run `index`"
                     % (album_id, path.name))
                continue

            orig_key = "photos/%s/orig/%s" % (album_id, path.name)
            full_key = "photos/%s/full/%s.jpg" % (album_id, pid)
            thumb_key = "photos/%s/thumb/%s.jpg" % (album_id, pid)

            if not args.force and all(k in existing for k in (orig_key, full_key, thumb_key)):
                continue

            log("up %s/%s" % (album_id, path.name))
            s3.upload_file(str(path), bucket, orig_key)
            for key, max_edge in ((full_key, FULL_MAX), (thumb_key, THUMB_MAX)):
                s3.put_object(Bucket=bucket, Key=key, Body=derivative(path, max_edge),
                              ContentType="image/jpeg")
            uploaded += 1

    if args.prune:
        # Only albums that exist on this machine can be pruned -- for any other
        # album this machine has no idea what the full set should be.
        expected = set()
        for album_id, entries in local.items():
            for pid, path in entries.items():
                expected.add("photos/%s/orig/%s" % (album_id, path.name))
                expected.add("photos/%s/full/%s.jpg" % (album_id, pid))
                expected.add("photos/%s/thumb/%s.jpg" % (album_id, pid))

        for key in sorted(list_keys(s3, bucket, "photos/")):
            parts = key.split("/")
            if key == MANIFEST_KEY or len(parts) != 4:
                continue
            if parts[1] not in local or key in expected:
                continue
            log("rm %s" % key)
            s3.delete_object(Bucket=bucket, Key=key)

    # Rebuild from what is actually in S3, so the manifest stays complete even
    # when this machine only holds some of the albums.
    available = ids_in_s3(list_keys(s3, bucket, "photos/"))
    manifest = build_manifest(albums, rows, available)

    s3.put_object(
        Bucket=bucket,
        Key=MANIFEST_KEY,
        Body=json.dumps(manifest, indent=1).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-cache",
    )

    log("\nuploaded %d scan(s); manifest has %d album(s), %d scan(s)."
        % (uploaded, len(manifest["albums"]), sum(a["photoCount"] for a in manifest["albums"])))
    log("Invalidate CloudFront if you want the change visible immediately.")


def cmd_download(args):
    s3, bucket = aws_setup()
    keys = list_keys(s3, bucket, "photos/")
    origs = {k: size for k, size in keys.items() if k.split("/")[2:3] == ["orig"]}
    total = sum(origs.values())
    log("%d original(s), %.1f MB in s3://%s/photos/" % (len(origs), total / 1e6, bucket))
    if not args.yes:
        log("Re-run with --yes to download them into ./photos.")
        return
    for key in sorted(origs):
        _, album_id, _, filename = key.split("/", 3)
        if args.album and album_id != args.album:
            continue
        target = PHOTOS_DIR / album_id / filename
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        log("dl %s" % key)
        s3.download_file(bucket, key, str(target))


def cmd_rename(args):
    """Move comment threads after a file or album folder has been renamed.

    Photo ids follow the filename, so changing page numbers in photos.csv
    needs nothing; renaming a file does.
    """
    s3, bucket = aws_setup()

    def load(album_id):
        key = "comments/%s.json" % album_id
        try:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        except ClientError as err:
            if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return key, None
            raise
        return key, json.loads(body)

    if args.album_to:
        old_key, data = load(args.album)
        if data is None:
            log("No comments for album '%s' -- nothing to move." % args.album)
            return
        data["albumId"] = args.album_to
        s3.put_object(Bucket=bucket, Key="comments/%s.json" % args.album_to,
                      Body=json.dumps(data).encode("utf-8"),
                      ContentType="application/json", CacheControl="no-cache")
        s3.delete_object(Bucket=bucket, Key=old_key)
        log("Moved %d thread(s) from album '%s' to '%s'."
            % (len(data.get("threads", {})), args.album, args.album_to))
        return

    old_id, new_id = photo_id(args.photo), photo_id(args.photo_to)
    key, data = load(args.album)
    if data is None:
        log("No comments for album '%s' -- nothing to move." % args.album)
        return
    threads = data.get("threads", {})
    if old_id not in threads:
        log("No comments on '%s/%s' -- nothing to move." % (args.album, old_id))
        return
    if new_id in threads:
        die("'%s' already has comments -- merge them by hand first." % new_id)
    threads[new_id] = threads.pop(old_id)
    data["threads"] = threads
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(data).encode("utf-8"),
                  ContentType="application/json", CacheControl="no-cache")
    log("Moved %d comment(s) from '%s' to '%s' in album '%s'."
        % (len(threads[new_id]), old_id, new_id, args.album))


def cmd_delete(args):
    """Remove an album: its scans in S3, its comment threads, and its rows.

    The local scans under photos/<album>/ are left alone -- delete the folder
    yourself once you are happy with the result.
    """
    s3, bucket = aws_setup()

    albums = read_albums_csv()
    rows = read_photos_csv()
    album_rows = [r for r in rows if r["album"] == args.album]
    keys = sorted(list_keys(s3, bucket, "photos/%s/" % args.album))

    if args.album not in albums and not album_rows and not keys:
        die("No album '%s' in albums.csv, photos.csv or S3." % args.album)

    if not args.yes:
        log("Would delete album '%s': %d object(s) in S3, %d row(s) in photos.csv%s."
            % (args.album, len(keys), len(album_rows),
               ", its albums.csv row" if args.album in albums else ""))
        log("Re-run with --yes.")
        return

    for key in keys:
        log("rm %s" % key)
        s3.delete_object(Bucket=bucket, Key=key)

    comments_key = "comments/%s.json" % args.album
    try:
        s3.delete_object(Bucket=bucket, Key=comments_key)
        log("rm %s" % comments_key)
    except ClientError as err:
        if err.response["Error"]["Code"] not in ("NoSuchKey", "404"):
            raise

    if album_rows:
        write_photos_csv([r for r in rows if r["album"] != args.album])

    if args.album in albums:
        with ALBUMS_CSV.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or ALBUM_COLUMNS
            kept = [r for r in reader if (r.get("id") or "").strip() != args.album]
        with ALBUMS_CSV.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(kept)
        log("removed the albums.csv row")

    albums = read_albums_csv()
    rows = read_photos_csv()
    available = ids_in_s3(list_keys(s3, bucket, "photos/"))
    manifest = build_manifest(albums, rows, available)
    s3.put_object(
        Bucket=bucket,
        Key=MANIFEST_KEY,
        Body=json.dumps(manifest, indent=1).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-cache",
    )
    log("Deleted album '%s'. Manifest now has %d album(s)."
        % (args.album, len(manifest["albums"])))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-q", "--quiet", action="store_true", help="only print warnings and errors")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("index", help="add photos.csv rows for new scans").set_defaults(func=cmd_index)
    sub.add_parser("check", help="join photos.csv to the scans on disk, no AWS").set_defaults(func=cmd_check)

    p_sync = sub.add_parser("sync", help="upload new scans and rebuild the manifest")
    p_sync.add_argument("--force", action="store_true", help="re-upload scans already in S3")
    p_sync.add_argument("--prune", action="store_true",
                        help="delete S3 objects for scans no longer present locally")
    p_sync.set_defaults(func=cmd_sync)

    p_dl = sub.add_parser("download", help="pull the original scans back from S3")
    p_dl.add_argument("--yes", action="store_true", help="actually download (otherwise just reports)")
    p_dl.add_argument("--album", help="limit to one album id")
    p_dl.set_defaults(func=cmd_download)

    p_del = sub.add_parser("delete", help="remove an album from S3 and the CSVs")
    p_del.add_argument("--album", required=True, help="album id")
    p_del.add_argument("--yes", action="store_true", help="actually delete")
    p_del.set_defaults(func=cmd_delete)

    p_rn = sub.add_parser("rename", help="move comment threads after a rename")
    p_rn.add_argument("--album", required=True, help="album id the comments are under")
    p_rn.add_argument("--album-to", help="new album id (moves the whole comment file)")
    p_rn.add_argument("--photo", help="old filename or photo id")
    p_rn.add_argument("--photo-to", help="new filename or photo id")
    p_rn.set_defaults(func=cmd_rename)

    args = parser.parse_args()

    if args.command == "rename":
        if args.album_to and (args.photo or args.photo_to):
            die("--album-to renames a whole album; use it on its own.")
        if not args.album_to and not (args.photo and args.photo_to):
            die("give either --album-to, or both --photo and --photo-to.")

    global QUIET
    QUIET = args.quiet
    args.func(args)


if __name__ == "__main__":
    main()
