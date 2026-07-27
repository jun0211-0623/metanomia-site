/* Metanomia newsletter signup — posts to the Apps Script web app. */
(function () {
  var ENDPOINT = 'https://script.google.com/macros/s/AKfycbxLF2JaW3cBRGjhG-prFFjCk-_QmMWPa09tnBNJXorrgJfd_hbKV2QlrxQcGxr2dXxL/exec';

  var isKo = document.documentElement.lang === 'ko';
  var TEXT = isKo
    ? { ok: '구독 신청이 완료되었습니다.', invalid: '이메일 주소를 확인해 주세요.', fail: '잠시 후 다시 시도해 주세요.', sending: '전송 중...' }
    : { ok: 'You are subscribed.', invalid: 'Please check your email address.', fail: 'Something went wrong. Please try again.', sending: 'Sending...' };

  var EMAIL_RE = /^[^@\s]+@[^@\s.]+\.[^@\s]+$/;

  function setup(form) {
    var input = form.querySelector('.signup__input');
    if (!input) return;

    var honeypot = document.createElement('input');
    honeypot.type = 'text';
    honeypot.name = 'company';
    honeypot.tabIndex = -1;
    honeypot.autocomplete = 'off';
    honeypot.setAttribute('aria-hidden', 'true');
    honeypot.style.cssText = 'position:absolute;left:-9999px;width:1px;height:1px;opacity:0';
    form.appendChild(honeypot);

    var status = document.createElement('p');
    status.className = 'signup__status';
    status.setAttribute('role', 'status');
    form.parentNode.insertBefore(status, form.nextSibling);

    var btn = form.querySelector('.signup__btn');

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();

      var email = input.value.trim();
      if (!EMAIL_RE.test(email)) {
        show(status, TEXT.invalid, false);
        return;
      }
      if (honeypot.value) return;

      var body = new URLSearchParams({
        email: email,
        lang: isKo ? 'ko' : 'en',
        page: location.pathname
      });

      if (btn) btn.disabled = true;
      show(status, TEXT.sending, true);

      // Apps Script sends no CORS headers, so the response is opaque:
      // a resolved promise means the request was delivered, not that it was stored.
      fetch(ENDPOINT, { method: 'POST', mode: 'no-cors', body: body })
        .then(function () {
          show(status, TEXT.ok, true);
          input.value = '';
        })
        .catch(function () {
          show(status, TEXT.fail, false);
        })
        .then(function () {
          if (btn) btn.disabled = false;
        });
    });
  }

  function show(el, message, ok) {
    el.textContent = message;
    el.classList.toggle('is-error', !ok);
  }

  var forms = document.querySelectorAll('.signup__form');
  for (var i = 0; i < forms.length; i++) setup(forms[i]);
})();
