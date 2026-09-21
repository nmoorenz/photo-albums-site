# site

Plain HTML, CSS and one ES module. No build step, no dependencies. Deployed
to the `site/` prefix in S3 by `scripts/deploy_site.sh`.

| file | contents |
| --- | --- |
| `index.html` | the shell: header, album list, album view, lightbox |
| `app.js` | everything -- routing, filtering, rendering, comments |
| `style.css` | the whole theme |
| `login.html` | the public page a signed-out viewer lands on |
| `config.js` | generated at deploy time from Terraform's outputs |

`config.js` in git holds local-dev defaults, with login left unconfigured,
and is never modified by a deploy. `deploy_site.sh` generates the deployed
copy -- real `MANIFEST_URL`, Cognito domain, client id and redirect URI --
into `build/` and uploads that, so no Cognito id ever appears as a local
change.

## Routing

Hash based, so CloudFront serves one file for every view.

```
#/                         album list
#/album/<albumId>          one album, grouped by page
#/album/<albumId>/<photo>  that album with the lightbox open on a photo
```

The lightbox is a route, so browser Back closes it and any view can be
linked to directly.

## Album list

One card per album: cover, title, date or date range, scan count, comment
count. Comment counts come from `GET /api/comments` and arrive after the
first paint.

Sort: date oldest first, date newest first, title A-Z.

Four filter dropdowns -- Decade, Type, Album (whose it was), Tags. Each holds
one value at a time and defaults to "any"; the four combine with AND. A
dropdown only appears when there are at least two values to choose between,
so the row stays out of the way until there is enough to filter. Add a
dimension by adding an entry to `FILTER_GROUPS` in `app.js`.

## Album view

Grouped by page: the album-page scan full width, with the photos lifted from
that page in a grid beneath it. The cover is its own group at the top; photos
with no page number fall into a "loose photos" group at the end. The groups
come straight from `manifest.json` -- the frontend does no grouping of its
own.

## Lightbox

The photo at its natural aspect ratio, arrow keys and on-screen arrows to
move through the album, Escape to close. Alongside it: the album and page
reference, a "see the page" link to the page scan the photo came from, and
the comment thread.

Anyone signed in can post; author or admin can delete. The whole album's
threads arrive in one `GET /api/comments/{albumId}` when the lightbox opens.

## Theme

White throughout -- page, cards and lightbox are `#ffffff`. Hairline borders
do the separating, which is what lets a scan with pale edges still read as an
object. `color-scheme: light` on `:root` keeps a dark-mode browser from
rendering the dropdowns, textarea and scrollbars dark. Colours are tokens at
the top of `style.css`.

Layout is responsive down to phone width; below 820px the lightbox stacks the
photo above the comments.

## Constraints

- No browser storage. Nothing in the UI needs to persist per viewer, and
  state that matters belongs in the comment API.
- No external requests beyond the site's own origin.
- `app.js` builds DOM with `textContent`, never `innerHTML`, so comment text
  from other people cannot inject markup.
