/* Metanomia site search — nav dropdown, client-side over search-index.json */
(function () {
  var triggers = document.querySelectorAll('.nav__search');
  if (!triggers.length) return;

  var isKo = document.documentElement.lang === 'ko';
  var TEXT = isKo
    ? { placeholder: '보고서, 사람, 페이지 검색', empty: '결과가 없습니다.', hint: '검색어를 입력하세요.', close: '닫기' }
    : { placeholder: 'Search reports, people, pages', empty: 'No results.', hint: 'Type to search.', close: 'Close' };

  var index = null, loading = false, panel, input, results;

  function build() {
    panel = document.createElement('div');
    panel.className = 'sitesearch';
    panel.hidden = true;
    panel.innerHTML =
      '<div class="container sitesearch__inner">' +
      '<input class="sitesearch__input" type="search" autocomplete="off" spellcheck="false" />' +
      '<div class="sitesearch__results"></div>' +
      '</div>';
    var nav = document.getElementById('siteNav') || document.querySelector('.nav');
    nav.appendChild(panel);
    input = panel.querySelector('.sitesearch__input');
    results = panel.querySelector('.sitesearch__results');
    input.placeholder = TEXT.placeholder;
    input.addEventListener('input', render);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') close();
      if (e.key === 'Enter') {
        var first = results.querySelector('.sitesearch__item');
        if (first) window.location.href = first.getAttribute('href');
      }
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    document.addEventListener('click', function (e) {
      if (panel.hidden) return;
      if (panel.contains(e.target)) return;
      for (var i = 0; i < triggers.length; i++) if (triggers[i].contains(e.target)) return;
      close();
    });
  }

  function load() {
    if (index || loading) return;
    loading = true;
    Promise.all([
      fetch('/search-index.json').then(function (r) { return r.json(); }),
      fetch('/data/crypto-news.json', { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : { items: [] }; })
        .catch(function () { return { items: [] }; })
    ])
      .then(function (payload) {
        index = payload[0].filter(function (d) { return d.lang === (isKo ? 'ko' : 'en'); });
        if (isKo) {
          index.push({
            lang: 'ko', type: '페이지', title: 'Crypto News',
            sub: '화폐·금융·크립토의 변화를 메타노미아의 관점으로 읽는 크립토 뉴스.',
            meta: '메타노미아', url: '/crypto-news.ko.html'
          });
          (payload[1].items || []).forEach(function (item) {
            if (!item || !item.slug || !item.title) return;
            index.push({
              lang: 'ko', type: 'Crypto News', title: item.title,
              sub: item.content || '', meta: item.date_kst || '',
              url: '/crypto-news-detail.ko.html?slug=' + encodeURIComponent(item.slug)
            });
          });
        }
        loading = false;
        render();
      })
      .catch(function () { loading = false; });
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function render() {
    var q = (input.value || '').trim().toLowerCase();
    if (!q) { results.innerHTML = '<p class="sitesearch__msg">' + TEXT.hint + '</p>'; return; }
    if (!index) { results.innerHTML = ''; return; }

    var hits = index.filter(function (d) {
      return (d.title + ' ' + d.sub + ' ' + d.meta + ' ' + d.type).toLowerCase().indexOf(q) !== -1;
    }).slice(0, 12);

    if (!hits.length) { results.innerHTML = '<p class="sitesearch__msg">' + TEXT.empty + '</p>'; return; }

    var html = '', lastType = null;
    hits.forEach(function (d) {
      if (d.type !== lastType) { html += '<div class="sitesearch__group">' + esc(d.type) + '</div>'; lastType = d.type; }
      html += '<a class="sitesearch__item" href="' + esc(d.url) + '">' +
              '<span class="sitesearch__title">' + esc(d.title) + '</span>' +
              (d.meta ? '<span class="sitesearch__meta">' + esc(d.meta) + '</span>' : '') +
              '</a>';
    });
    results.innerHTML = html;
  }

  function open() {
    if (!panel) build();
    load();
    panel.hidden = false;
    render();
    input.focus();
  }
  function close() { if (panel) { panel.hidden = true; input.value = ''; } }

  Array.prototype.forEach.call(triggers, function (t) {
    t.addEventListener('click', function (e) {
      e.preventDefault();
      if (panel && !panel.hidden) close(); else open();
    });
  });
})();
