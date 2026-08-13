(function () {
  'use strict';

  var isKo = document.documentElement.lang === 'ko';
  var catalogUrl = isKo ? 'publications.ko.html' : 'publications.html';

  function make(tagName, className, text) {
    var element = document.createElement(tagName);
    if (className) element.className = className;
    if (typeof text === 'string') element.textContent = text;
    return element;
  }

  function getText(root, selector) {
    var element = root.querySelector(selector);
    return element ? element.textContent.trim() : '';
  }

  function readReport(card, index) {
    var image = card.querySelector('.cat-card__media img');
    return {
      href: card.getAttribute('href') || '#',
      image: image ? image.getAttribute('src') || '' : '',
      title: getText(card, '.cat-card__title'),
      series: getText(card, '.cat-card__tag'),
      author: getText(card, '.cat-card__authors'),
      date: getText(card, '.cat-card__date'),
      excerpt: card.getAttribute('data-excerpt') || '',
      published: card.getAttribute('data-published') || card.getAttribute('data-date') || '0000',
      sourceIndex: index
    };
  }

  function newestFirst(a, b) {
    if (a.published > b.published) return -1;
    if (a.published < b.published) return 1;
    return a.sourceIndex - b.sourceIndex;
  }

  function buildReportTitle(tagName, className, report) {
    var title = make(tagName, className);
    if (isKo && report.href.indexOf('bitcoin-quantum-computing') !== -1) {
      title.classList.add('quantum-report-title');
      title.setAttribute('aria-label', report.title);
      title.appendChild(make('span', 'quantum-report-title__line', '비트코인은 양자컴퓨팅 시대에도'));
      title.appendChild(make('span', 'quantum-report-title__line', '살아남을 수 있는가'));
    } else {
      title.textContent = report.title;
    }
    return title;
  }

  function buildLeadTitle(report) {
    if (isKo && report.href.indexOf('where-is-ethereum-going') !== -1) {
      var title = make('h1', 'lead__title ethereum-report-title');
      title.setAttribute('aria-label', report.title);
      title.appendChild(make('span', 'ethereum-report-title__line', '2026년,'));
      title.appendChild(make('span', 'ethereum-report-title__line', '이더리움은 어디로 가고 있는가'));
      return title;
    }
    if (!isKo && report.href.indexOf('bitcoin-quantum-computing') !== -1) {
      var quantumTitle = make('h1', 'lead__title quantum-report-title quantum-report-title--en');
      quantumTitle.setAttribute('aria-label', report.title);
      quantumTitle.appendChild(make('span', 'quantum-report-title__line', 'Can Bitcoin Survive'));
      quantumTitle.appendChild(make('span', 'quantum-report-title__line', 'the Age of Quantum Computing?'));
      return quantumTitle;
    }
    return buildReportTitle('h1', 'lead__title', report);
  }

  function buildLeadSlide(report) {
    var link = make('a', 'lead__slide');
    link.href = report.href;
    link.setAttribute('data-published', report.published);

    var image = make('img', 'lead__img');
    image.src = report.image;
    image.alt = report.title;
    link.appendChild(image);

    var overlay = make('div', 'lead__overlay');
    overlay.appendChild(make('span', 'lead__tag', report.series));
    overlay.appendChild(buildLeadTitle(report));
    if (report.excerpt) overlay.appendChild(make('p', 'lead__excerpt', report.excerpt));

    var byline = make('div', 'lead__byline');
    byline.appendChild(make('span', '', report.author));
    byline.appendChild(make('span', 'dot'));
    byline.appendChild(make('span', '', report.date));
    overlay.appendChild(byline);
    link.appendChild(overlay);
    return link;
  }

  function renderHero(reports) {
    var track = document.querySelector('#lead .lead__track');
    var dots = document.querySelector('#lead .lead__dots');
    if (!track || !dots) return;

    track.textContent = '';
    dots.textContent = '';
    reports.slice(0, 4).forEach(function (report, index) {
      track.appendChild(buildLeadSlide(report));
      var button = make('button', index === 0 ? 'is-active' : '');
      button.type = 'button';
      button.setAttribute('aria-label', String(index + 1));
      dots.appendChild(button);
    });
  }

  function buildSubcard(report) {
    var link = make('a', 'subcard');
    link.href = report.href;
    link.setAttribute('data-published', report.published);

    var media = make('div', 'subcard__media');
    var image = make('img');
    image.src = report.image;
    image.alt = '';
    media.appendChild(image);
    media.appendChild(make('span', 'subcard__tag', report.series));
    link.appendChild(media);
    link.appendChild(buildReportTitle('h3', 'subcard__title', report));

    var meta = make('div', 'subcard__meta');
    meta.appendChild(make('span', '', report.date));
    meta.appendChild(make('span', 'dot'));
    meta.appendChild(make('span', '', report.author));
    link.appendChild(meta);
    return link;
  }

  function renderSubfeed(reports) {
    var subfeed = document.querySelector('.subfeed');
    if (!subfeed) return;
    subfeed.textContent = '';
    reports.slice(4, 7).forEach(function (report) {
      subfeed.appendChild(buildSubcard(report));
    });
  }

  function buildReportCard(report, index) {
    var isFeature = index === 0;
    var link = make('a', isFeature ? 'card card--feature' : 'card');
    link.href = report.href;
    link.setAttribute('data-series', report.series);
    link.setAttribute('data-format', 'REPORT');
    link.setAttribute('data-published', report.published);

    var media = make('div', 'card__media');
    var image = make('img');
    image.src = report.image;
    image.alt = '';
    media.appendChild(image);
    link.appendChild(media);

    var body = make('div', 'card__body');
    var row = make('div', 'card__row');
    row.appendChild(make('span', 'tag', report.series));
    if (!isKo || !isFeature) {
      row.appendChild(make('span', 'card__date', isKo ? report.author : report.date));
    }
    body.appendChild(row);
    body.appendChild(buildReportTitle('h3', 'card__title', report));
    if (report.excerpt) body.appendChild(make('p', 'card__excerpt', report.excerpt));
    if (report.author) body.appendChild(make('span', 'card__author', report.author));
    link.appendChild(body);
    return link;
  }

  function renderCards(reports) {
    var grid = document.querySelector('.cards');
    if (!grid) return;
    grid.textContent = '';
    reports.forEach(function (report, index) {
      grid.appendChild(buildReportCard(report, index));
    });
  }

  function bindFilters() {
    var main = document.querySelector('.filters--main');
    var cards = Array.prototype.slice.call(document.querySelectorAll('.cards .card'));
    var featureCard = cards[0];
    var emptyState = document.querySelector('.cards-empty');
    if (!main || !cards.length) return;

    main.querySelectorAll('.filter').forEach(function (button) {
      button.addEventListener('click', function () {
        main.querySelectorAll('.filter').forEach(function (item) {
          item.classList.remove('is-active');
        });
        button.classList.add('is-active');
        var series = button.getAttribute('data-series-filter');
        var showAll = series === 'all';
        if (featureCard) featureCard.classList.toggle('card--feature', showAll);

        var visibleCount = 0;
        cards.forEach(function (card) {
          var visible = showAll || card.getAttribute('data-series') === series;
          card.style.display = visible ? '' : 'none';
          if (visible) visibleCount += 1;
        });
        if (emptyState) emptyState.hidden = visibleCount > 0;
      });
    });
  }

  function bindCarousel() {
    var lead = document.getElementById('lead');
    if (!lead) return;
    var track = lead.querySelector('.lead__track');
    var slides = Array.prototype.slice.call(lead.querySelectorAll('.lead__slide'));
    var dots = Array.prototype.slice.call(lead.querySelectorAll('.lead__dots button'));
    if (!track || !slides.length) return;

    var current = 0;
    var timer;
    function show(index) {
      current = (index + slides.length) % slides.length;
      track.style.transform = 'translateX(-' + (current * 100) + '%)';
      dots.forEach(function (dot, dotIndex) {
        dot.classList.toggle('is-active', dotIndex === current);
      });
    }
    function start() {
      if (slides.length < 2) return;
      timer = window.setInterval(function () { show(current + 1); }, 6000);
    }
    function reset() {
      window.clearInterval(timer);
      start();
    }
    dots.forEach(function (dot, dotIndex) {
      dot.addEventListener('click', function () {
        show(dotIndex);
        reset();
      });
    });
    show(0);
    start();
  }

  function finishSetup() {
    bindFilters();
    bindCarousel();
  }

  function init() {
    window.fetch(catalogUrl, { cache: 'no-store' })
      .then(function (response) {
        if (!response.ok) throw new Error('Report catalog request failed: ' + response.status);
        return response.text();
      })
      .then(function (html) {
        var catalog = new window.DOMParser().parseFromString(html, 'text/html');
        var cards = Array.prototype.slice.call(catalog.querySelectorAll('.cat-grid .cat-card'));
        var reports = cards.map(readReport).sort(newestFirst);
        if (!reports.length) throw new Error('Report catalog is empty.');
        renderHero(reports);
        renderSubfeed(reports);
        renderCards(reports);
      })
      .catch(function (error) {
        // The server-rendered HTML remains a complete fallback when the catalog cannot load.
        window.console.warn('[home-reports] Using static fallback.', error);
      })
      .then(finishSetup);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();