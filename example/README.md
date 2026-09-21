# example

A working example you can serve locally, with no AWS account, no login and no
photos of your own.

```
python -m pip install -r requirements.txt
python scripts/dev_server.py --sample
```

Open http://localhost:8000/.

That copies this folder into `photos/` -- both CSVs and all 21 images -- and
serves the whole site --
album list, filters, page-grouped albums, lightbox and working comments. You
are signed in as a fake admin called "Local tester", and comments go to
`.dev-comments.json` in the repo root. Delete that file to start over, and
delete `photos/` to regenerate everything.

## What's here

```
example/
  albums.csv
  photos.csv
  blue-album/    IMG_0001.JPG ... IMG_0007.JPG
  pinkerton/     PICT0101.jpg ... PICT0107.jpg
  green-album/   scan 0042.jpg ... scan 0048.jpg
```

The images are real files, committed -- plain blue, pink and green rectangles
labelled with their album, page and filename. Nothing is generated or
downloaded; the example works offline on a fresh clone. All 21 come to about
130 KB.

`albums.csv` -- three albums:

| | type | |
| --- | --- | --- |
| `blue-album` | range | "The blue album", 1994, Nan's, tagged `garden seaside` |
| `pinkerton` | event | "Pinkerton", September 1996, Aunt Jo's, tagged `party music` |
| `green-album` | range | "The green album", 2001, Dad's, tagged `holiday camping` |

They differ on decade, type, source and tags, which is what brings all four
filter dropdowns up: a dropdown shows once it has two values.

`photos.csv` -- seven scans each: a cover, then two pages with two photos on
each. That gives a cover group, then a group per page with its page scan
above its photos.

The three albums use different filenames on purpose -- `IMG_0001.JPG`,
`PICT0101.jpg`, `scan 0042.jpg`. There is no naming convention: scans keep
whatever the scanner called them and `photos.csv` carries the meaning. Photo
ids come from the filenames, so `scan 0042.jpg` becomes `scan-0042`.

## Using it as a starting point

```
cp example/albums.csv example/photos.csv photos/
```

Then empty out the rows and drop your own scans into `photos/<album-id>/`. `python scripts/album_sync.py index` adds a row for
every scan it hasn't seen; you fill in `page`, `kind` and `order`.

Everything inside `photos/` is gitignored; only the folder itself is kept, by
a `.gitkeep`. This folder holds the only committed albums.
