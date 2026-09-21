// Photo albums frontend.
//
// Routes (hash based):
//   #/                        album list
//   #/album/<albumId>         one album, grouped by page
//   #/album/<albumId>/<photo> that album with the lightbox open on a photo
import { MANIFEST_URL, API_BASE } from './config.js';

const state = {
  albums: [],
  byId: new Map(),
  counts: {},
  me: null,
  sort: 'date-asc',
  // One chosen value per dimension; '' means no filter on it.
  filters: { decade: '', type: '', source: '', tags: '' },
  lightbox: null, // { albumId, photos: [], index }
};

const el = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// data
// ---------------------------------------------------------------------------

async function api(path, options) {
  const resp = await fetch(API_BASE + path, { credentials: 'same-origin', ...options });
  if (resp.status === 401) {
    window.location.href = '/login.html';
    throw new Error('not logged in');
  }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || ('Request failed (' + resp.status + ')'));
  return data;
}

async function loadManifest() {
  const resp = await fetch(MANIFEST_URL, { credentials: 'same-origin', cache: 'no-cache' });
  if (!resp.ok) throw new Error('Could not load the albums (' + resp.status + ')');
  const manifest = await resp.json();
  state.albums = manifest.albums || [];
  state.byId = new Map(state.albums.map((a) => [a.id, a]));
}

function photosOf(album) {
  const list = [];
  for (const group of album.groups || []) {
    if (group.scan) list.push({ ...group.scan, page: group.page, isPage: true });
    for (const photo of group.photos) list.push({ ...photo, page: group.page, isPage: false });
  }
  return list;
}

// ---------------------------------------------------------------------------
// album list
// ---------------------------------------------------------------------------

const FILTER_GROUPS = [
  { key: 'decade', label: 'Decade', any: 'Any decade', values: (a) => (a.decade ? [a.decade] : []) },
  { key: 'type', label: 'Type', any: 'Any type', values: (a) => (a.type ? [a.type] : []) },
  { key: 'source', label: 'Album', any: 'Anyone\'s album', values: (a) => (a.source ? [a.source] : []) },
  { key: 'tags', label: 'Tags', any: 'Any tag', values: (a) => a.tags || [] },
];

const TYPE_LABELS = { range: 'Date range', event: 'Event' };

function labelFor(key, value) {
  if (key === 'type') return TYPE_LABELS[value] || value;
  if (key === 'tags') return '#' + value;
  return value;
}

function matchesFilters(album) {
  for (const group of FILTER_GROUPS) {
    const chosen = state.filters[group.key];
    if (!chosen) continue;
    if (!group.values(album).includes(chosen)) return false;
  }
  return true;
}

function sortedAlbums(albums) {
  const copy = albums.slice();
  if (state.sort === 'title') {
    copy.sort((a, b) => a.title.localeCompare(b.title));
  } else {
    copy.sort((a, b) => (a.sortDate || '').localeCompare(b.sortDate || '') ||
                        a.title.localeCompare(b.title));
    if (state.sort === 'date-desc') copy.reverse();
  }
  return copy;
}

function renderFilters() {
  const container = el('filter-groups');
  container.replaceChildren();
  let anyActive = false;

  for (const group of FILTER_GROUPS) {
    const values = new Set();
    for (const album of state.albums) group.values(album).forEach((v) => values.add(v));
    if (values.size < 2) continue;

    const chosen = state.filters[group.key];
    if (chosen) anyActive = true;

    const wrap = document.createElement('label');
    wrap.className = 'filter-group';

    const label = document.createElement('span');
    label.className = 'filter-label';
    label.textContent = group.label;
    wrap.append(label);

    const select = document.createElement('select');

    const anyOption = document.createElement('option');
    anyOption.value = '';
    anyOption.textContent = group.any;
    select.append(anyOption);

    for (const value of Array.from(values).sort()) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = labelFor(group.key, value);
      select.append(option);
    }

    // A value can disappear when the manifest changes; fall back to Any.
    select.value = values.has(chosen) ? chosen : '';
    state.filters[group.key] = select.value;

    select.addEventListener('change', () => {
      state.filters[group.key] = select.value;
      renderAlbumList();
    });

    wrap.append(select);
    container.append(wrap);
  }

  el('clear-filters').hidden = !anyActive;
}

function albumCard(album) {
  const card = document.createElement('a');
  card.className = 'album-card';
  card.href = '#/album/' + encodeURIComponent(album.id);

  const figure = document.createElement('div');
  figure.className = 'album-cover';
  if (album.cover) {
    const img = document.createElement('img');
    img.src = album.cover.thumb;
    img.alt = album.title;
    img.loading = 'lazy';
    figure.append(img);
  }
  card.append(figure);

  const body = document.createElement('div');
  body.className = 'album-body';

  const title = document.createElement('h2');
  title.textContent = album.title;
  body.append(title);

  const meta = document.createElement('p');
  meta.className = 'muted';
  const comments = state.counts[album.id] || 0;
  const bits = [];
  if (album.dateDisplay) bits.push(album.dateDisplay);
  bits.push(album.photoCount + (album.photoCount === 1 ? ' scan' : ' scans'));
  if (comments) bits.push(comments + (comments === 1 ? ' comment' : ' comments'));
  meta.textContent = bits.join(' - ');
  body.append(meta);

  if (album.source) {
    const source = document.createElement('p');
    source.className = 'muted small';
    source.textContent = album.source;
    body.append(source);
  }

  card.append(body);
  return card;
}

function renderAlbumList() {
  renderFilters();
  const shown = sortedAlbums(state.albums.filter(matchesFilters));

  el('album-count').textContent = shown.length === state.albums.length
    ? state.albums.length + (state.albums.length === 1 ? ' album' : ' albums')
    : shown.length + ' of ' + state.albums.length + ' albums';

  const grid = el('album-grid');
  grid.replaceChildren();
  if (shown.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'Nothing matches those filters.';
    grid.append(empty);
    return;
  }
  shown.forEach((album) => grid.append(albumCard(album)));
}

// ---------------------------------------------------------------------------
// album view
// ---------------------------------------------------------------------------

function thumbButton(album, photo, extraClass) {
  const button = document.createElement('a');
  button.className = 'thumb ' + (extraClass || '');
  button.href = '#/album/' + encodeURIComponent(album.id) + '/' + encodeURIComponent(photo.id);
  const img = document.createElement('img');
  img.src = photo.thumb;
  img.alt = '';
  img.loading = 'lazy';
  button.append(img);
  return button;
}

function renderAlbum(album) {
  el('album-title').textContent = album.title;

  const bits = [];
  if (album.dateDisplay) bits.push(album.dateDisplay);
  if (album.source) bits.push(album.source);
  bits.push(album.photoCount + (album.photoCount === 1 ? ' scan' : ' scans'));
  if (album.tags && album.tags.length) bits.push(album.tags.map((t) => '#' + t).join(' '));
  el('album-meta').textContent = bits.join(' - ');

  const container = el('album-groups');
  container.replaceChildren();

  for (const group of album.groups || []) {
    const section = document.createElement('section');
    section.className = 'page-group';
    if (group.page !== null) section.id = 'page-' + group.page;

    const heading = document.createElement('h2');
    heading.textContent = group.label;
    section.append(heading);

    if (group.scan) {
      const pageWrap = document.createElement('div');
      pageWrap.className = 'page-scan';
      pageWrap.append(thumbButton(album, group.scan, 'page-thumb'));
      section.append(pageWrap);
    }

    if (group.photos.length) {
      const grid = document.createElement('div');
      grid.className = 'photo-grid';
      group.photos.forEach((photo) => grid.append(thumbButton(album, photo)));
      section.append(grid);
    }

    container.append(section);
  }
}

// ---------------------------------------------------------------------------
// lightbox and comments
// ---------------------------------------------------------------------------

function timeAgo(iso) {
  const then = new Date(iso);
  if (isNaN(then)) return '';
  return then.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function renderComments(comments) {
  const list = el('comment-list');
  list.replaceChildren();

  if (!comments.length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'No comments yet.';
    list.append(empty);
    return;
  }

  for (const comment of comments) {
    const item = document.createElement('article');
    item.className = 'comment';

    const head = document.createElement('p');
    head.className = 'comment-head';
    head.textContent = comment.author + ' - ' + timeAgo(comment.at);
    item.append(head);

    const body = document.createElement('p');
    body.className = 'comment-body';
    body.textContent = comment.body;
    item.append(body);

    const mine = state.me && comment.sub === state.me.sub;
    if (mine || (state.me && state.me.admin)) {
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'text-button danger';
      remove.textContent = 'Delete';
      remove.addEventListener('click', () => deleteComment(comment.id));
      item.append(remove);
    }

    list.append(item);
  }
}

async function loadThread() {
  const { albumId, photos, index } = state.lightbox;
  const photoId = photos[index].id;
  renderComments([]);
  try {
    const data = await api('/comments/' + encodeURIComponent(albumId));
    state.lightbox.threads = data.threads || {};
    renderComments(state.lightbox.threads[photoId] || []);
  } catch (err) {
    el('comment-error').textContent = err.message;
  }
}

async function postComment(event) {
  event.preventDefault();
  const box = el('comment-body');
  const text = box.value.trim();
  if (!text || !state.lightbox) return;

  const { albumId, photos, index } = state.lightbox;
  const photoId = photos[index].id;
  el('comment-error').textContent = '';
  el('comment-submit').disabled = true;

  try {
    const data = await api('/comments/' + encodeURIComponent(albumId) + '/' + encodeURIComponent(photoId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body: text }),
    });
    box.value = '';
    const threads = state.lightbox.threads || (state.lightbox.threads = {});
    threads[photoId] = (threads[photoId] || []).concat(data.comment);
    renderComments(threads[photoId]);
    state.counts[albumId] = (state.counts[albumId] || 0) + 1;
  } catch (err) {
    el('comment-error').textContent = err.message;
  } finally {
    el('comment-submit').disabled = false;
  }
}

async function deleteComment(commentId) {
  const { albumId, photos, index, threads } = state.lightbox;
  const photoId = photos[index].id;
  try {
    await api('/comments/' + encodeURIComponent(albumId) + '/' + encodeURIComponent(photoId) +
              '/' + encodeURIComponent(commentId), { method: 'DELETE' });
    threads[photoId] = (threads[photoId] || []).filter((c) => c.id !== commentId);
    renderComments(threads[photoId]);
    state.counts[albumId] = Math.max(0, (state.counts[albumId] || 1) - 1);
  } catch (err) {
    el('comment-error').textContent = err.message;
  }
}

function renderLightbox() {
  const { albumId, photos, index } = state.lightbox;
  const album = state.byId.get(albumId);
  const photo = photos[index];

  el('lightbox').hidden = false;
  el('lightbox-img').src = photo.full;
  el('comment-error').textContent = '';
  el('comment-body').value = '';

  const caption = el('lightbox-caption');
  caption.replaceChildren();
  const parts = [album.title];
  if (photo.isPage) parts.push('page ' + photo.page + ' of the album');
  else if (photo.page !== null && photo.page !== undefined) parts.push('from page ' + photo.page);
  caption.append(document.createTextNode(parts.join(' - ')));

  // Jump to the page scan this photo came from, when there is one.
  if (!photo.isPage && photo.page !== null && photo.page !== undefined) {
    const pageScan = photos.find((p) => p.isPage && p.page === photo.page);
    if (pageScan) {
      caption.append(document.createTextNode(' '));
      const link = document.createElement('a');
      link.href = '#/album/' + encodeURIComponent(albumId) + '/' + encodeURIComponent(pageScan.id);
      link.textContent = 'see the page';
      caption.append(link);
    }
  }

  loadThread();
}

function closeLightbox() {
  state.lightbox = null;
  el('lightbox').hidden = true;
  el('lightbox-img').removeAttribute('src');
}

function step(delta) {
  if (!state.lightbox) return;
  const { albumId, photos, index } = state.lightbox;
  const next = (index + delta + photos.length) % photos.length;
  window.location.hash = '#/album/' + encodeURIComponent(albumId) + '/' + encodeURIComponent(photos[next].id);
}

// ---------------------------------------------------------------------------
// routing
// ---------------------------------------------------------------------------

function showStatus(message) {
  const status = el('status');
  status.hidden = !message;
  status.textContent = message || '';
}

function route() {
  const hash = window.location.hash.replace(/^#\/?/, '');
  const parts = hash.split('/').filter(Boolean).map(decodeURIComponent);

  if (parts[0] !== 'album' || !parts[1]) {
    closeLightbox();
    el('album-view').hidden = true;
    el('album-list-view').hidden = false;
    renderAlbumList();
    return;
  }

  const album = state.byId.get(parts[1]);
  if (!album) {
    closeLightbox();
    el('album-list-view').hidden = true;
    el('album-view').hidden = true;
    showStatus('No album called "' + parts[1] + '".');
    return;
  }

  showStatus('');
  el('album-list-view').hidden = true;
  el('album-view').hidden = false;
  renderAlbum(album);

  if (!parts[2]) {
    closeLightbox();
    window.scrollTo(0, 0);
    return;
  }

  const photos = photosOf(album);
  const index = photos.findIndex((p) => p.id === parts[2]);
  if (index === -1) {
    closeLightbox();
    return;
  }
  state.lightbox = { albumId: album.id, photos, index, threads: {} };
  renderLightbox();
}

// ---------------------------------------------------------------------------
// startup
// ---------------------------------------------------------------------------

function wireEvents() {
  el('sort-select').addEventListener('change', (e) => {
    state.sort = e.target.value;
    renderAlbumList();
  });

  el('clear-filters').addEventListener('click', () => {
    for (const group of FILTER_GROUPS) state.filters[group.key] = '';
    renderAlbumList();
  });

  el('comment-form').addEventListener('submit', postComment);
  el('lightbox-close').addEventListener('click', () => { window.location.hash =
    '#/album/' + encodeURIComponent(state.lightbox.albumId); });
  el('lightbox-prev').addEventListener('click', () => step(-1));
  el('lightbox-next').addEventListener('click', () => step(1));

  document.addEventListener('keydown', (e) => {
    if (!state.lightbox) return;
    if (e.target.tagName === 'TEXTAREA') return;
    if (e.key === 'Escape') window.location.hash = '#/album/' + encodeURIComponent(state.lightbox.albumId);
    if (e.key === 'ArrowLeft') step(-1);
    if (e.key === 'ArrowRight') step(1);
  });

  window.addEventListener('hashchange', route);
}

async function start() {
  wireEvents();
  showStatus('Loading...');

  try {
    await loadManifest();
  } catch (err) {
    showStatus(err.message);
    return;
  }
  showStatus('');

  // Neither of these is needed to browse, so a failure is not fatal.
  api('/me').then((me) => {
    state.me = me;
    el('who').textContent = me.name;
  }).catch(() => {});

  api('/comments').then((data) => {
    state.counts = data.counts || {};
    if (!el('album-list-view').hidden) renderAlbumList();
  }).catch(() => {});

  route();
}

start();
