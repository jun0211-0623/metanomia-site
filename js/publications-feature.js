(function () {
  'use strict';

  function text(root, selector) {
    var element = root.querySelector(selector);
    return element ? element.textContent.trim() : '';
  }

  var grid = document.querySelector('.cat-grid');
  var feature = document.querySelector('.pub-featured__link');
  if (!grid || !feature) return;

  var cards = Array.prototype.slice.call(grid.querySelectorAll('.cat-card'));
  cards.sort(function (a, b) {
    var aDate = a.getAttribute('data-published') || a.getAttribute('data-date') || '0000';
    var bDate = b.getAttribute('data-published') || b.getAttribute('data-date') || '0000';
    return aDate > bDate ? -1 : aDate < bDate ? 1 : 0;
  });
  cards.forEach(function (card) { grid.appendChild(card); });

  var latest = cards[0];
  if (!latest) return;
  var sourceImage = latest.querySelector('.cat-card__media img');
  var featureImage = feature.querySelector('.pub-featured__media img');
  var tag = feature.querySelector('.pub-featured__tag');
  var title = feature.querySelector('.pub-featured__title');
  var byline = feature.querySelector('.pub-featured__byline');
  var excerpt = feature.querySelector('.pub-featured__excerpt');

  feature.href = latest.getAttribute('href') || '#';
  if (sourceImage && featureImage) {
    featureImage.src = sourceImage.getAttribute('src') || '';
    featureImage.alt = text(latest, '.cat-card__title');
  }
  if (tag) tag.textContent = text(latest, '.cat-card__tag');
  if (title) title.textContent = text(latest, '.cat-card__title');
  if (byline) {
    byline.textContent = '';
    var author = document.createElement('span');
    author.textContent = text(latest, '.cat-card__authors');
    var dot = document.createElement('span');
    dot.className = 'dot';
    var date = document.createElement('span');
    date.textContent = text(latest, '.cat-card__date');
    byline.appendChild(author);
    byline.appendChild(dot);
    byline.appendChild(date);
  }
  if (excerpt) excerpt.textContent = latest.getAttribute('data-excerpt') || '';
})();
