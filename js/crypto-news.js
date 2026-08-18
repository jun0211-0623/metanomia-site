/* Metanomia Crypto News — one manifest powers the public list and detail pages. */
(function () {
  'use strict';

  var listRoot = document.querySelector('[data-crypto-news-list]');
  var detailRoot = document.querySelector('[data-crypto-news-detail]');
  if (!listRoot && !detailRoot) return;

  var isKo = document.documentElement.lang === 'ko';

  var COPY = isKo ? {
    manifest: 'data/crypto-news.json',
    detailHref: 'crypto-news-detail.ko.html',
    titleSuffix: ' | 메타노미아 크립토 뉴스',
    count: function (n) { return '총 ' + n + '건'; },
    emptyTitle: '아직 게시된 뉴스가 없습니다.',
    emptyBody: '승인된 크립토 뉴스가 이곳에 순서대로 게시됩니다.',
    missingTitle: '뉴스를 찾을 수 없습니다.',
    missingBody: '목록으로 돌아가 다른 뉴스를 확인해 주세요.',
    failedTitle: '뉴스를 불러오지 못했습니다.',
    failedBody: '잠시 후 다시 시도해 주세요.',
    noSources: '출처 정보 준비 중',
    previousNews: '이전 뉴스',
    nextNews: '다음 뉴스'
  } : {
    manifest: 'data/crypto-news.en.json',
    detailHref: 'crypto-news-detail.html',
    titleSuffix: ' | Metanomia Crypto News',
    count: function (n) { return n + (n === 1 ? ' item' : ' items'); },
    emptyTitle: 'No news published yet.',
    emptyBody: 'Approved crypto news will appear here in order.',
    missingTitle: 'This story could not be found.',
    missingBody: 'Head back to the list to read something else.',
    failedTitle: 'The news could not be loaded.',
    failedBody: 'Please try again in a moment.',
    noSources: 'Sources to follow',
    previousNews: 'Previous News',
    nextNews: 'Next News'
  };

  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'];

  var manifestUrl = COPY.manifest;

  function text(value) {
    return typeof value === 'string' ? value.trim() : '';
  }

  function itemKey(item) {
    return text(item.slug) || text(item.id);
  }

  function formatDate(value, longForm) {
    var match = text(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return text(value);
    if (longForm) {
      return isKo
        ? Number(match[1]) + '년 ' + Number(match[2]) + '월 ' + Number(match[3]) + '일'
        : MONTHS[Number(match[2]) - 1] + ' ' + Number(match[3]) + ', ' + match[1];
    }
    return match[1] + '.' + match[2] + '.' + match[3];
  }

  function excerpt(value, limit) {
    var clean = text(value).replace(/\s+/g, ' ');
    if (clean.length <= limit) return clean;
    return clean.slice(0, limit).replace(/\s+\S*$/, '') + '…';
  }

  function safeExternalUrl(value) {
    try {
      var url = new URL(value);
      return (url.protocol === 'https:' || url.protocol === 'http:') ? url.href : '';
    } catch (error) {
      return '';
    }
  }

  function emptyState(root, title, message) {
    root.replaceChildren();
    var state = document.createElement('div');
    state.className = 'crypto-news-state';
    var heading = document.createElement('strong');
    heading.textContent = title;
    var copy = document.createElement('span');
    copy.textContent = message;
    state.append(heading, copy);
    root.appendChild(state);
  }

  function validItems(data) {
    if (!data || !Array.isArray(data.items)) return [];
    return data.items.filter(function (item) {
      return item && itemKey(item) && text(item.title) && text(item.content);
    }).sort(function (a, b) {
      var dateOrder = text(b.date_kst).localeCompare(text(a.date_kst));
      return dateOrder || itemKey(a).localeCompare(itemKey(b));
    });
  }

  function loadManifest() {
    return fetch(manifestUrl, { cache: 'no-store' }).then(function (response) {
      if (!response.ok) throw new Error('manifest');
      return response.json();
    });
  }

  function renderList(items) {
    var count = document.querySelector('[data-crypto-news-count]');
    if (count) count.textContent = COPY.count(items.length);
    if (!items.length) {
      emptyState(listRoot, COPY.emptyTitle, COPY.emptyBody);
      return;
    }

    var fragment = document.createDocumentFragment();
    items.forEach(function (item) {
      var link = document.createElement('a');
      link.className = 'crypto-news-card';
      link.href = detailUrl(item);

      var time = document.createElement('time');
      time.className = 'crypto-news-card__date';
      time.dateTime = text(item.date_kst);
      time.textContent = formatDate(item.date_kst, false);

      var copy = document.createElement('div');
      var title = document.createElement('h2');
      title.className = 'crypto-news-card__title';
      title.textContent = text(item.title);
      var summary = document.createElement('p');
      summary.className = 'crypto-news-card__excerpt';
      summary.textContent = excerpt(item.content, 180);
      copy.append(title, summary);

      var arrow = document.createElement('span');
      arrow.className = 'crypto-news-card__arrow';
      arrow.setAttribute('aria-hidden', 'true');
      arrow.textContent = '→';

      link.append(time, copy, arrow);
      fragment.appendChild(link);
    });
    listRoot.replaceChildren(fragment);
  }

  function appendParagraphs(root, value) {
    var blocks = text(value).split(/\n\s*\n/).filter(Boolean);
    blocks.forEach(function (block) {
      var paragraph = document.createElement('p');
      paragraph.textContent = block;
      root.appendChild(paragraph);
    });
  }

  function updateMetadata(item) {
    var title = text(item.title) + COPY.titleSuffix;
    var description = excerpt(item.content, 155);
    document.title = title;

    var descriptionMeta = document.querySelector('meta[name=description]');
    if (descriptionMeta) descriptionMeta.content = description;
    var ogTitle = document.querySelector('meta[property="og:title"]');
    if (ogTitle) ogTitle.content = title;
    var ogDescription = document.querySelector('meta[property="og:description"]');
    if (ogDescription) ogDescription.content = description;
    var twitterTitle = document.querySelector('meta[name="twitter:title"]');
    if (twitterTitle) twitterTitle.content = title;
    var twitterDescription = document.querySelector('meta[name="twitter:description"]');
    if (twitterDescription) twitterDescription.content = description;
    var canonical = document.querySelector('link[rel=canonical]');
    if (canonical && window.location.protocol !== 'file:') {
      var articleUrl = window.location.origin + window.location.pathname + '?slug=' + encodeURIComponent(itemKey(item));
      canonical.href = articleUrl;
      var ogUrl = document.querySelector('meta[property="og:url"]');
      if (ogUrl) ogUrl.content = articleUrl;
    }
  }

  function detailUrl(item) {
    return 'crypto-news-' + encodeURIComponent(itemKey(item)) + (isKo ? '.ko.html' : '.html');
  }

  function updateDetailLanguageLinks(slug) {
    var counterpart = isKo ? 'crypto-news-detail.html' : 'crypto-news-detail.ko.html';
    var href = counterpart + (slug ? '?slug=' + encodeURIComponent(slug) : '');
    document.querySelectorAll('.nav__lang, .nav__drawer-link[href^="crypto-news-detail"]')
      .forEach(function (link) {
        link.href = href;
      });
  }

  function renderDetailNavigation(items, currentIndex) {
    var previousLink = detailRoot.querySelector('[data-news-previous]');
    var nextLink = detailRoot.querySelector('[data-news-next]');

    function configure(link, item, titleSelector, label) {
      if (!link) return;
      if (!item) {
        link.hidden = true;
        link.removeAttribute('href');
        return;
      }
      var itemTitle = text(item.title);
      link.href = detailUrl(item);
      link.hidden = false;
      link.setAttribute('aria-label', label + ': ' + itemTitle);
      var title = link.querySelector(titleSelector);
      if (title) title.textContent = itemTitle;
    }

    // Items are newest first: previous moves to an older story, next to a newer one.
    configure(previousLink, items[currentIndex + 1], '[data-news-previous-title]', COPY.previousNews);
    configure(nextLink, items[currentIndex - 1], '[data-news-next-title]', COPY.nextNews);
  }

  function renderDetail(items) {
    var slug = new URLSearchParams(window.location.search).get('slug') || '';
    updateDetailLanguageLinks(slug);
    var item = items.find(function (candidate) { return itemKey(candidate) === slug; });
    if (!item) {
      emptyState(detailRoot, COPY.missingTitle, COPY.missingBody);
      return;
    }

    updateMetadata(item);
    renderDetailNavigation(items, items.indexOf(item));
    var date = detailRoot.querySelector('[data-news-date]');
    var title = detailRoot.querySelector('[data-news-title]');
    var body = detailRoot.querySelector('[data-news-content]');
    var thought = detailRoot.querySelector('[data-news-thought]');
    var sources = detailRoot.querySelector('[data-news-sources]');

    date.dateTime = text(item.date_kst);
    date.textContent = formatDate(item.date_kst, true);
    title.textContent = text(item.title);
    body.replaceChildren();
    appendParagraphs(body, item.content);
    thought.textContent = text(item.metanomia_thought);
    sources.replaceChildren();

    var safeSources = Array.isArray(item.sources) ? item.sources.filter(function (source) {
      return source && text(source.title) && safeExternalUrl(source.url);
    }) : [];

    if (!safeSources.length) {
      var unavailable = document.createElement('li');
      unavailable.className = 'crypto-news-sources__empty';
      unavailable.textContent = COPY.noSources;
      sources.appendChild(unavailable);
      return;
    }

    safeSources.forEach(function (source) {
      var row = document.createElement('li');
      row.className = 'crypto-news-sources__item';
      var link = document.createElement('a');
      link.className = 'crypto-news-sources__link';
      link.href = safeExternalUrl(source.url);
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = text(source.title);
      row.appendChild(link);
      sources.appendChild(row);
    });
  }

  loadManifest()
    .then(function (data) {
      var items = validItems(data);
      if (listRoot) renderList(items);
      if (detailRoot) renderDetail(items);
    })
    .catch(function () {
      var root = listRoot || detailRoot;
      emptyState(root, COPY.failedTitle, COPY.failedBody);
    });
})();
