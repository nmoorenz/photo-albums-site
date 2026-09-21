# scripts

| script | what it does |
| --- | --- |
| `album_sync.py` | index scans, join them to the CSVs, upload to S3, rebuild the manifest |
| `dev_server.py` | run the whole site locally with no AWS |
| `tf.py` | run terraform with the deployment's names from `.env` |
| `build_lambdas.py` | assemble the Lambda bundles Terraform zips |
| `deploy_site.py` | push `site/` to S3 with a generated config.js |

## The data model

Scans keep whatever name the scanner gives them. One folder per album, named
by the album slug:

```
photos/green-album/
  DSC_0100.jpeg
  IMG_0041.JPG
  IMG_0042.JPG
  scan 44 (1).jpg
```

A photo's id is its filename slugged -- `IMG_0042.JPG` becomes `img_0042`.
S3 keys, the manifest and comment threads all use it. `photo_id()` in
`album_sync.py` is the only place that maps a filename to an id. Changing a
page number or reordering rows leaves ids untouched; renaming a file changes
one, and `rename` moves its comment thread.

**`photos/photos.csv`**, one row per scan. `index` writes the rows; you fill
in the rest. It lives under `photos/`, which is gitignored; copy
`example/photos.csv` there to start, or let `index` create it.

| column | notes |
| --- | --- |
| `album` | album id, matches the folder name |
| `file` | filename exactly as it sits on disk |
| `page` | page number in the album; blank for the cover and loose photos |
| `kind` | `cover`, `page` for an album-page scan, blank for an ordinary photo |
| `order` | position within its page; written by `index`, yours to change |

**`photos/albums.csv`**, one row per album. Also gitignored; copy
`example/albums.csv` there and edit it.

| column | notes |
| --- | --- |
| `id` | slug, matches the folder name -- `green-album` |
| `title` | display title -- `The green album` |
| `sort_date` | `YYYY` or `YYYY-MM-DD`, start of the album |
| `end_date` | optional, for date-range albums |
| `type` | `range` or `event` |
| `source` | whose album it was |
| `tags` | space separated, e.g. `holiday beach` |

The decade dropdown and the displayed date range are derived from
`sort_date` and `end_date`. Save both CSVs as UTF-8 if any title contains a
macron.

**S3 layout.**

```
site/                          the static site
photos/<album>/orig/<file>     untouched scan under its own name
photos/<album>/full/<id>.jpg   lightbox size, 2000px
photos/<album>/thumb/<id>.jpg  grid size, 600px
photos/manifest.json           everything the frontend reads
comments/<album>.json          one file per album
```

## album_sync.py

```
python scripts/album_sync.py index              add photos.csv rows for new scans
python scripts/album_sync.py check              join photos.csv to the scans on disk, no AWS
python scripts/album_sync.py sync               upload new scans, rebuild the manifest
python scripts/album_sync.py sync --force       re-upload scans already in S3
python scripts/album_sync.py sync --prune       delete S3 objects with no local scan
python scripts/album_sync.py download --yes     pull the originals back to set up a machine
python scripts/album_sync.py rename --album A --photo IMG_0042.JPG --photo-to IMG_0099.JPG
python scripts/album_sync.py rename --album A --album-to B
```

`-q` quietens everything but warnings.

`index` only appends; rows for files not on this machine are left alone.
`sync` generates the thumb and full derivatives with Pillow as it uploads,
then rebuilds `manifest.json` from what is in S3. `--prune` touches only
albums that exist locally.

`rename` moves comment threads in `comments/<album>.json`. Run it before
`sync --prune`.

Needs `.env` in the repo root (see `env.example`) for everything except
`index` and `check`.

## dev_server.py

```
python scripts/dev_server.py --sample     first run: make placeholder scans
python scripts/dev_server.py              then just serve
```

Stands in for CloudFront, S3 and both Lambdas at http://localhost:8000/:
serves `site/` as-is, builds the manifest in memory from the CSVs and
`photos/`, generates derivatives on the fly, signs you in as a fake admin
called "Local tester", and stores comments in `.dev-comments.json` in the
repo root. No AWS credentials, no login, nothing written to S3.

`--sample` copies `example/` into `photos/` -- both CSVs and all the images
-- skipping anything already there. Drop real scans into
`photos/<album-id>/` and run `index` to replace them. Delete
`.dev-comments.json` to clear the comments, or `photos/` to start over.
`--port` changes the port. See `example/README.md`.

It does not exercise the Cognito login round-trip.

## tf.py

```
python scripts/tf.py init
python scripts/tf.py cert                            first-stage certificate apply
python scripts/tf.py apply
python scripts/tf.py output cloudfront_domain_name
```

`cert` is the only argument tf.py handles itself: it applies the certificate
alone and prints its DNS validation record. Everything else goes through to
terraform untouched.

Passes every argument through to terraform, adds `-chdir=infrastructure`, and
maps `.env` to the variables terraform expects:

| `.env` | terraform variable |
| --- | --- |
| `S3_BUCKET` | `bucket_name` |
| `DOMAIN_NAME` | `domain_name` |
| `COGNITO_DOMAIN_PREFIX` | `cognito_domain_prefix` |
| `AWS_REGION` | `aws_region` |
| `AWS_PROFILE` | `aws_profile` |

The first three are required. `.env` is the only file holding your own
names, and it is gitignored. Set `TERRAFORM` to use a terraform binary that
is not on PATH.

`tf.py` will not run while `infrastructure/terraform.tfvars` or any
`*.auto.tfvars` exists, and it builds any missing
`infrastructure/build/<name>/` bundle before calling terraform.

## build_lambdas.py

`python scripts/build_lambdas.py` -- see `infrastructure/README.md`.

## deploy_site.py

`python scripts/deploy_site.py` syncs `site/` to the `site/` prefix in S3 and
invalidates CloudFront. It writes the deployed `config.js` from Terraform's
outputs into `build/` and uploads it from there; the committed
`site/config.js` keeps its placeholders. Run it after an apply, or after any
frontend change. Needs `.env` and terraform on PATH.
