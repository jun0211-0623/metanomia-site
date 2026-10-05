(function () {
  var root = document.querySelector('[data-papers-index]');
  if (!root) return;

  var lang = document.documentElement.lang === 'ko' ? 'ko' : 'en';
  var labels = lang === 'ko'
    ? { research: '연구논문', journal: '학술지 게재논문', conference: '학술대회 논문' }
    : { research: 'Research Papers', journal: 'Journal Articles', conference: 'Conference Papers' };
  var type = new URLSearchParams(window.location.search).get('type');
  var cards = Array.prototype.slice.call(root.querySelectorAll('[data-paper-type]'));
  var heading = root.querySelector('[data-papers-heading]');
  var empty = root.querySelector('[data-papers-empty]');
  var filters = document.querySelectorAll('[data-paper-filter]');

  if (!Object.prototype.hasOwnProperty.call(labels, type)) {
    if (empty) empty.hidden = true;
    return;
  }

  var visible = 0;
  cards.forEach(function (card) {
    var show = card.getAttribute('data-paper-type') === type;
    card.hidden = !show;
    if (show) visible += 1;
  });
  filters.forEach(function (filter) {
    var active = filter.getAttribute('data-paper-filter') === type;
    filter.classList.toggle('is-active', active);
    if (active) filter.setAttribute('aria-current', 'page');
  });
  if (heading) heading.textContent = labels[type];
  if (empty) empty.hidden = visible !== 0;
})();
