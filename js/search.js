/* Metanomia site search — nav dropdown, client-side over search-index.json */
(function () {
  var nav = document.getElementById('siteNav') || document.querySelector('.nav');
  var navToggle = document.getElementById('navToggle');
  var languageMenuStateKey = 'metanomia:language-menu-open';

  if (nav && navToggle) {
    try {
      if (window.sessionStorage.getItem(languageMenuStateKey) === '1') {
        window.sessionStorage.removeItem(languageMenuStateKey);
        nav.classList.add('is-open');
        navToggle.setAttribute('aria-expanded', 'true');
      }
    } catch (error) {}

    var headerLanguageLink = nav.querySelector('.nav__lang');
    if (headerLanguageLink) {
      headerLanguageLink.addEventListener('click', function () {
        if (!nav.classList.contains('is-open')) return;
        try { window.sessionStorage.setItem(languageMenuStateKey, '1'); } catch (error) {}
      });
    }

    var drawerLanguageLinks = nav.querySelectorAll('.nav__drawer > .nav__drawer-link:last-child');
    Array.prototype.forEach.call(drawerLanguageLinks, function (link) {
      link.addEventListener('click', function () {
        try { window.sessionStorage.setItem(languageMenuStateKey, '1'); } catch (error) {}
      });
    });
  }

  var triggers = document.querySelectorAll('.nav__search');
  if (!triggers.length) return;

  var isKo = document.documentElement.lang === 'ko';
  var TEXT = isKo
    ? { placeholder: '보고서, 저자, 뉴스 검색', empty: '결과가 없습니다.', hint: '검색어를 입력하세요.', close: '닫기' }
    : { placeholder: 'Search reports, authors, news', empty: 'No results.', hint: 'Type to search.', close: 'Close' };

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
    input.setAttribute('aria-label', TEXT.placeholder);
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
    var news = isKo ? {
      manifest: '/data/crypto-news.json',
      detailUrl: '/crypto-news-detail.ko.html',
      itemType: '뉴스'
    } : {
      manifest: '/data/crypto-news.en.json',
      detailUrl: '/crypto-news-detail.html',
      itemType: 'News'
    };

    Promise.all([
      fetch('/search-index.json').then(function (r) { return r.json(); }),
      fetch(news.manifest, { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : { items: [] }; })
        .catch(function () { return { items: [] }; })
    ])
      .then(function (payload) {
        var lang = isKo ? 'ko' : 'en';
        var reportType = isKo ? '보고서' : 'Report';
        var peopleType = isKo ? '사람' : 'People';
        var authorType = isKo ? '저자' : 'Author';
        var base = payload[0].filter(function (d) { return d.lang === lang; });
        var reports = base.filter(function (d) { return d.type === reportType; });
        var authorNames = {};

        reports.forEach(function (report) {
          var authorText = String(report.meta || '').split('·')[0];
          authorText.split(',').forEach(function (name) {
            name = name.trim();
            if (name) authorNames[name] = true;
          });
        });

        var authors = base.filter(function (d) {
          return d.type === peopleType && authorNames[d.title];
        }).map(function (d) {
          return {
            lang: d.lang, type: authorType, title: d.title,
            sub: d.sub, meta: d.meta, url: d.url
          };
        });

        index = reports.concat(authors);
        (payload[1].items || []).forEach(function (item) {
          if (!item || !item.slug || !item.title) return;
          index.push({
            lang: lang, type: news.itemType, title: item.title,
            sub: item.content || '', meta: item.date_kst || '',
            url: news.detailUrl + '?slug=' + encodeURIComponent(item.slug)
          });
        });
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

    var terms = q.split(/\s+/).filter(Boolean);
    var hits = index.filter(function (d) {
      var haystack = (d.title + ' ' + d.sub + ' ' + d.meta + ' ' + d.type).toLowerCase();
      return terms.every(function (term) { return haystack.indexOf(term) !== -1; });
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
/* Keep the quantum-computing report title to two balanced lines. */
(function () {
  var titles = document.querySelectorAll('.quantum-report-title');
  if (!titles.length) return;

  function setText(title, compact) {
    var lines = title.querySelectorAll('.quantum-report-title__line');
    if (lines.length !== 2) return;
    lines[0].textContent = compact ? '비트코인은 양자컴퓨팅' : '비트코인은 양자컴퓨팅 시대에도';
    lines[1].textContent = compact ? '시대에도 살아남을 수 있는가' : '살아남을 수 있는가';
  }

  function fit(title) {
    title.style.fontSize = '';
    setText(title, false);
    var computed = window.getComputedStyle(title);
    var lineHeight = parseFloat(computed.lineHeight);
    if (!lineHeight) return;

    if (title.getBoundingClientRect().height > lineHeight * 2.35) {
      setText(title, true);
      computed = window.getComputedStyle(title);
      var fontSize = parseFloat(computed.fontSize);
      lineHeight = parseFloat(computed.lineHeight);
      var attempts = 0;
      while (title.getBoundingClientRect().height > lineHeight * 2.35 && fontSize > 16 && attempts < 6) {
        fontSize = Math.max(16, fontSize * 0.92);
        title.style.fontSize = fontSize + 'px';
        lineHeight = parseFloat(window.getComputedStyle(title).lineHeight);
        attempts += 1;
      }
    }
  }

  function fitAll() {
    Array.prototype.forEach.call(titles, fit);
  }

  var resizeTimer;
  window.addEventListener('resize', function () {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(fitAll, 80);
  });
  window.requestAnimationFrame(fitAll);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitAll);
})();
