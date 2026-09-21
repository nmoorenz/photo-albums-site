# photo-albums-site

Scanned family photo albums on your own domain, behind individual logins,
with per-photo comments so people who remember more can name faces, places
and dates.

Albums are browsed as a list, then page by page: each album-page scan appears
with the individual photos lifted from that page beneath it. Every photo has
its own comment thread. Photos carry no captions -- all text about a photo is
comments.

## Layout

| folder | what's in it |
| --- | --- |
| `site/` | the frontend: album list, album page, lightbox, comments. [README](site/README.md) |
| `scripts/` | the CLI that gets scans to S3, the local dev server, the deploy and build scripts, and the data model. [README](scripts/README.md) |
| `infrastructure/` | Terraform for S3, CloudFront, Cognito and the two Lambdas. [README](infrastructure/README.md) |
| `example/` | three example albums, images included -- serve them locally without AWS. [README](example/README.md) |
| `photos/` | your scans and the two CSVs describing them. Contents gitignored. |

## Privacy

Nothing that identifies the family is in this repository. The scans and the
two CSVs that describe them -- `photos/albums.csv` and `photos/photos.csv`,
holding album titles, whose album it was and the page structure -- all live
under `photos/`, gitignored except for a `.gitkeep`. `example/` holds three
invented albums with their own images, and is the only committed album data.

Deployment details are the same: domain, bucket name, Cognito prefix and AWS
profile live only in `.env`, which is gitignored -- `env.example` is
committed in its place. `scripts/tf.py` feeds them to Terraform as `TF_VAR_*`.

Photos are uploaded to a private S3 bucket and served through CloudFront to
signed-in viewers only. They never go near git.

## Getting started

```
python -m pip install -r requirements.txt
python scripts/dev_server.py --sample
```

That serves the whole site at http://localhost:8000/ -- three example albums,
working comments, no AWS and no login. See `example/README.md`.

## Deploying

A two-stage apply, with a DNS record added by hand between the stages. The
sequence is in
[infrastructure/README.md](infrastructure/README.md).

## Adding scans

1. Scan into `photos/<album-id>/`, leaving the scanner's filenames alone.
2. `python scripts/album_sync.py index` -- adds a row per new scan to
   `photos.csv`.
3. Fill in `page`, `kind` and `order` in `photos.csv`.
4. `python scripts/album_sync.py check`, then `sync`.
