/* Metanomia Media — shared YouTube/video feed renderer */
(function () {
  var roots = document.querySelectorAll('[data-media-feed]');
  var latestRoots = document.querySelectorAll('[data-media-latest]');
  if (!roots.length && !latestRoots.length) return;

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, function (char) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char];
    });
  }

  function youtubeId(url) {
    var match = String(url || '').match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|shorts\/|embed\/))([^?&/]+)/);
    return match ? match[1] : '';
  }

  function render(root, payload) {
    var program = root.getAttribute('data-program') || 'all';
    var items = (payload.items || []).filter(function (item) {
      return program === 'all' || item.program === program;
    });
    var grid = root.querySelector('[data-media-grid]');
    var empty = root.querySelector('[data-media-empty]');
    if (!items.length) {
      if (grid) grid.hidden = true;
      if (empty) empty.hidden = false;
      return;
    }

    items.sort(function (a, b) { return String(b.published || b.date || '').localeCompare(String(a.published || a.date || '')); });
    grid.innerHTML = items.map(function (item) {
      var id = youtubeId(item.url);
      var thumbnail = item.thumbnail || (id ? 'https://i.ytimg.com/vi/' + id + '/maxresdefault.jpg' : '');
      return '<a class="media-video" href="' + escapeHtml(item.url) + '" target="_blank" rel="noopener noreferrer">' +
        '<div class="media-video__media">' + (thumbnail ? '<img src="' + escapeHtml(thumbnail) + '" alt="" />' : '') + '<span class="media-video__play" aria-hidden="true">▶</span></div>' +
        '<span class="media-video__type">' + escapeHtml(item.type || '') + '</span>' +
        '<h3 class="media-video__title">' + escapeHtml(item.title) + '</h3>' +
        (item.date ? '<time class="media-video__date">' + escapeHtml(item.date) + '</time>' : '') +
        '</a>';
    }).join('');
    grid.hidden = false;
    if (empty) empty.hidden = true;
  }

  function hasRemoteSource(payload, program) {
    if (program === 'all') {
      if (payload.channelId) return true;
      return Object.keys(payload.programs || {}).some(function (key) { return payload.programs[key].playlistId; });
    }
    return Boolean(payload.programs && payload.programs[program] && payload.programs[program].playlistId);
  }

  function renderLatest(root, payload) {
    var items = (payload.items || []).slice().sort(function (a, b) {
      return String(b.published || b.date || '').localeCompare(String(a.published || a.date || ''));
    });
    var item = items[0];
    var link = root.querySelector('[data-media-latest-link]');
    var empty = root.querySelector('[data-media-latest-empty]');
    if (!item) {
      if (link) link.hidden = true;
      if (empty) empty.hidden = false;
      return;
    }

    link.href = item.url || '#';
    root.querySelector('[data-media-latest-program]').textContent = item.type || '';
    root.querySelector('[data-media-latest-title]').textContent = item.title || '';
    root.querySelector('[data-media-latest-date]').textContent = item.date || item.published || '';
    link.hidden = false;
    if (empty) empty.hidden = true;
  }

  Array.prototype.forEach.call(roots, function (root) {
    var source = root.getAttribute('data-source');
    var program = root.getAttribute('data-program') || 'all';
    if (!source) return;
    fetch(source, { cache: 'no-store' })
      .then(function (response) { if (!response.ok) throw new Error('media config'); return response.json(); })
      .then(function (payload) {
        render(root, payload);
        if (!hasRemoteSource(payload, program)) return null;
        var lang = source.indexOf('.ko.json') !== -1 ? 'ko' : 'en';
        return fetch('/api/youtube-feed?lang=' + lang + '&program=' + encodeURIComponent(program), { cache: 'no-store' })
          .then(function (response) { if (!response.ok) throw new Error('youtube feed'); return response.json(); })
          .then(function (remotePayload) { render(root, remotePayload); });
      })
      .catch(function () {
        var empty = root.querySelector('[data-media-empty]');
        if (empty) empty.hidden = false;
      });
  });

  Array.prototype.forEach.call(latestRoots, function (root) {
    var source = root.getAttribute('data-source');
    if (!source) return;
    fetch(source, { cache: 'no-store' })
      .then(function (response) { if (!response.ok) throw new Error('media config'); return response.json(); })
      .then(function (payload) {
        renderLatest(root, payload);
        if (!hasRemoteSource(payload, 'all')) return null;
        var lang = source.indexOf('.ko.json') !== -1 ? 'ko' : 'en';
        return fetch('/api/youtube-feed?lang=' + lang + '&program=all', { cache: 'no-store' })
          .then(function (response) { if (!response.ok) throw new Error('youtube feed'); return response.json(); })
          .then(function (remotePayload) { renderLatest(root, remotePayload); });
      })
      .catch(function () {
        var empty = root.querySelector('[data-media-latest-empty]');
        if (empty) empty.hidden = false;
      });
  });
})();
