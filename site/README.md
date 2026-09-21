# site

Plain HTML, CSS and one ES module. No build step, no dependencies. Deployed
to the `site/` prefix in S3 by `scripts/deploy_site.py`.

| file | contents |
| --- | --- |
| `index.html` | the shell: header, album list, album view, lightbox |
| `app.js` | everything -- routing, filtering, rendering, comments |
| `style.css` | the whole theme |
| `login.html` | the public page a signed-out viewer lands on |
| `config.js` | generated at deploy time from Terraform's outputs |

`config.js` in git holds local-dev defaults, with login left unconfigured. A
deploy never modifies it: `deploy_site.py` writes the deployed copy -- real
`MANIFEST_URL`, Cognito domain, client id and redirect URI -- into `build/`
and uploads it from there.

## Routing

Hash based; CloudFront serves one file for every view.

```
#/                         album list
#/album/<albumId>          one album, grouped by page
#/album/<albumId>/<photo>  that album with the lightbox open on a photo
```

The lightbox is a route: browser Back closes it, and any view can be linked
to directly.

## Album list

One card per album: cover, title, date or date range, scan count, comment
count. Comment counts come from `GET /api/comments` and arrive after the
first paint.

Sort: date oldest first, date newest first, title A-Z.

Four filter dropdowns -- Decade, Type, Album (whose it was), Tags. Each holds
one value at a time and defaults to "any"; the four combine with AND. A
dropdown appears only when it has at least two values to choose between. Add
a dimension with an entry in `FILTER_GROUPS` in `app.js`.

## Album view

Grouped by page: the album-page scan full width, with the photos lifted from
that page in a grid beneath it. The cover is its own group at the top; photos
with no page number fall into a "loose photos" group at the end. The groups
come straight from `manifest.json`; the frontend does no grouping of its own.

## Lightbox

The photo at its natural aspect ratio, arrow keys and on-screen arrows to
move through the album, Escape to close. Alongside it: the album and page
reference, a "see the page" link to the page scan the photo came from, and
the comment thread.

Anyone signed in can post; author or admin can delete. The whole album's
threads arrive in one `GET /api/comments/{albumId}` when the lightbox opens.

## Theme

White throughout -- page, cards and lightbox are `#ffffff`, with hairline
borders separating them. `color-scheme: light` on `:root` keeps a dark-mode
browser from rendering the dropdowns, textarea and scrollbars dark. Colours
are tokens at the top of `style.css`.

Layout is responsive down to phone width; below 820px the lightbox stacks the
photo above the comments.

## Constraints

- No browser storage.
- No external requests beyond the site's own origin.
- `app.js` builds DOM with `textContent`, never `innerHTML`.
