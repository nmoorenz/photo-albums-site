"""Comment API for the photo albums.

Reached via the CloudFront behaviour for /api/* whose origin is this
function's Lambda Function URL -- see infrastructure/cloudfront.tf.
CloudFront is the only permitted caller (X-Origin-Verify shared secret).
On top of that, every route verifies the `id_token` cookie that auth-callback
sets at login: the signature is always re-checked here, the cookie's contents
are never trusted as they arrive.

Storage is one JSON object per album at comments/<albumId>.json:

    {"albumId": "green-album",
     "updated": "2026-09-13T02:00:00Z",
     "threads": {"img_0042": [{"id": ..., "author": ..., "sub": ...,
                            "at": ..., "body": ...}]}}

Writes are a read-modify-write guarded by S3 conditional PutObject (If-Match
on the current ETag, If-None-Match: * for a first write), with retries if two
people comment at the same moment.

Routes:
    GET    /api/me
    POST   /api/comments/{albumId}/{photoId}     {"body": "..."}
    GET    /api/comments                         comment count per album
    GET    /api/comments/{albumId}
    DELETE /api/comments/{albumId}/{photoId}/{commentId}

Keep this file ASCII-only.
"""

import json
import logging
import os
import re
import urllib.parse
import uuid
from datetime import datetime, timezone

import boto3
import jwt
from botocore.exceptions import ClientError

log = logging.getLogger()
log.setLevel(logging.INFO)

s3 = boto3.client("s3")

BUCKET = os.environ["BUCKET_NAME"]
CLIENT_ID = os.environ["COGNITO_CLIENT_ID"]
USER_POOL_ID = os.environ["COGNITO_USER_POOL_ID"]
REGION = USER_POOL_ID.split("_")[0]
ISSUER = "https://cognito-idp.%s.amazonaws.com/%s" % (REGION, USER_POOL_ID)
JWKS_URL = ISSUER + "/.well-known/jwks.json"

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$", re.I)
UUID_PATTERN = re.compile(r"^[0-9a-f-]{36}$", re.I)
MAX_BODY_CHARS = 2000
MAX_COMMENTS_PER_PHOTO = 200

_jwk_client = None


def get_jwk_client():
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = jwt.PyJWKClient(JWKS_URL, cache_keys=True)
    return _jwk_client


def json_response(status, payload):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(payload),
    }


def read_cookie(event, name):
    for cookie in event.get("cookies") or []:
        key, _, value = cookie.partition("=")
        if key.strip() == name:
            return value.strip()
    return None


def get_claims(event):
    token = read_cookie(event, "id_token")
    if not token:
        return None
    try:
        key = get_jwk_client().get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=CLIENT_ID,
            issuer=ISSUER,
            options={"require": ["exp", "iss", "aud"]},
        )
    except Exception as err:
        log.warning("id_token verification failed: %s", err)
        return None


def is_admin(claims):
    return "admin" in (claims.get("cognito:groups") or [])


def display_name(claims):
    return claims.get("name") or claims.get("email") or claims.get("cognito:username") or "someone"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------


def comments_key(album_id):
    return "comments/%s.json" % album_id


def read_comments(album_id):
    """Returns (data, etag). etag is None when the album has no file yet."""
    try:
        got = s3.get_object(Bucket=BUCKET, Key=comments_key(album_id))
    except ClientError as err:
        if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return {"albumId": album_id, "updated": None, "threads": {}}, None
        raise
    data = json.loads(got["Body"].read())
    data.setdefault("threads", {})
    return data, got["ETag"]


ABORT = object()


def update_comments(album_id, mutate):
    """Read, mutate, write back only if nobody else wrote in between.

    `mutate` may return ABORT to write nothing. Its return value is passed
    back to the caller.
    """
    for attempt in range(5):
        data, etag = read_comments(album_id)
        result = mutate(data)
        if result is ABORT:
            return result
        data["updated"] = now_iso()

        condition = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
        try:
            s3.put_object(
                Bucket=BUCKET,
                Key=comments_key(album_id),
                Body=json.dumps(data).encode("utf-8"),
                ContentType="application/json",
                CacheControl="no-cache",
                **condition,
            )
            return result
        except ClientError as err:
            code = err.response["Error"]["Code"]
            status = err.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if (code == "PreconditionFailed" or status == 412) and attempt < 4:
                continue
            raise
    raise RuntimeError("comment update: too many conflicting writes, gave up")


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


def handle_counts():
    counts = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix="comments/"):
        for obj in page.get("Contents", []):
            match = re.match(r"^comments/(.+)\.json$", obj["Key"])
            if not match:
                continue
            album_id = match.group(1)
            data, _etag = read_comments(album_id)
            counts[album_id] = sum(len(thread) for thread in data["threads"].values())
    return json_response(200, {"counts": counts})


def handle_get_album(album_id):
    data, _etag = read_comments(album_id)
    return json_response(200, {"albumId": album_id, "threads": data["threads"]})


def handle_post(event, claims, album_id, photo_id):
    try:
        body = json.loads(event.get("body") or "{}")
    except ValueError:
        return json_response(400, {"error": "Invalid JSON body."})

    text = str(body.get("body") or "").strip()
    if not text:
        return json_response(400, {"error": "Nothing to say?"})
    if len(text) > MAX_BODY_CHARS:
        return json_response(
            400, {"error": "That comment is too long -- keep it under %d characters." % MAX_BODY_CHARS}
        )

    comment = {
        "id": str(uuid.uuid4()),
        "author": display_name(claims),
        "sub": claims.get("sub"),
        "at": now_iso(),
        "body": text,
    }

    state = {"full": False}

    def mutate(data):
        thread = data["threads"].setdefault(photo_id, [])
        if len(thread) >= MAX_COMMENTS_PER_PHOTO:
            state["full"] = True
            return ABORT
        thread.append(comment)

    update_comments(album_id, mutate)

    if state["full"]:
        return json_response(409, {"error": "This photo already has the maximum number of comments."})
    return json_response(201, {"comment": comment})


def handle_delete(claims, album_id, photo_id, comment_id):
    state = {"outcome": "missing"}

    def mutate(data):
        thread = data["threads"].get(photo_id)
        if not thread:
            return ABORT
        index = next((i for i, c in enumerate(thread) if c.get("id") == comment_id), None)
        if index is None:
            return ABORT
        if thread[index].get("sub") != claims.get("sub") and not is_admin(claims):
            state["outcome"] = "forbidden"
            return ABORT
        thread.pop(index)
        if not thread:
            del data["threads"][photo_id]
        state["outcome"] = "deleted"

    update_comments(album_id, mutate)

    if state["outcome"] == "forbidden":
        return json_response(403, {"error": "You can only delete your own comments."})
    if state["outcome"] == "missing":
        return json_response(404, {"error": "No comment with that id."})
    return json_response(200, {"deleted": comment_id})


def handler(event, _context):
    if (event.get("headers") or {}).get("x-origin-verify") != os.environ["ORIGIN_VERIFY_SECRET"]:
        return {"statusCode": 403, "body": "Forbidden"}

    method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "GET")
    path = event.get("rawPath") or "/"
    claims = get_claims(event)

    if claims is None:
        return json_response(401, {"error": "Please log in again."})

    try:
        if method == "GET" and path == "/api/me":
            return json_response(
                200,
                {"name": display_name(claims), "sub": claims.get("sub"), "admin": is_admin(claims)},
            )

        if method == "GET" and path in ("/api/comments", "/api/comments/"):
            return handle_counts()

        tail = re.sub(r"^/api/comments/?", "", path)
        parts = [urllib.parse.unquote(p) for p in tail.split("/") if p]

        if method == "GET" and len(parts) == 1:
            if not ID_PATTERN.match(parts[0]):
                return json_response(400, {"error": "Bad album id."})
            return handle_get_album(parts[0])

        if method == "POST" and len(parts) == 2:
            if not ID_PATTERN.match(parts[0]) or not ID_PATTERN.match(parts[1]):
                return json_response(400, {"error": "Bad album or photo id."})
            return handle_post(event, claims, parts[0], parts[1])

        if method == "DELETE" and len(parts) == 3:
            if (
                not ID_PATTERN.match(parts[0])
                or not ID_PATTERN.match(parts[1])
                or not UUID_PATTERN.match(parts[2])
            ):
                return json_response(400, {"error": "Bad album, photo or comment id."})
            return handle_delete(claims, parts[0], parts[1], parts[2])

        return json_response(404, {"error": "Not found."})
    except Exception:
        log.exception("comments-api error")
        return json_response(500, {"error": "Something went wrong -- try again."})
