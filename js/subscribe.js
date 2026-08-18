/* Metanomia email update signup — validated by a same-origin server endpoint. */
(function () {
  var ENDPOINT = '/api/subscribe';

  var isKo = document.documentElement.lang === 'ko';
  var TEXT = isKo
    ? { ok: '알림 신청이 완료되었습니다.', invalid: '이메일 주소를 확인해 주세요.', fail: '잠시 후 다시 시도해 주세요.', sending: '전송 중...' }
    : { ok: 'You’ll receive Metanomia updates by email.', invalid: 'Please check your email address.', fail: 'Something went wrong. Please try again.', sending: 'Sending...' };

  var EMAIL_RE = /^[^@\s]+@[^@\s.]+\.[^@\s]+$/;

  function setup(form) {
    var input = form.querySelector('.signup__input');
    if (!input) return;
    input.type = 'email';
    input.name = 'email';
    input.autocomplete = 'email';
    input.inputMode = 'email';
    input.required = true;

    var label = document.createElement('label');
    var inputId = input.id || 'signup-email-' + Math.random().toString(36).slice(2);
    input.id = inputId;
    label.className = 'sr-only';
    label.htmlFor = inputId;
    label.textContent = isKo ? '이메일 주소' : 'Email address';
    form.insertBefore(label, input);

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

      if (btn) btn.disabled = true;
      show(status, TEXT.sending, true);

      fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          email: email,
          lang: isKo ? 'ko' : 'en',
          page: location.pathname,
          company: honeypot.value
        })
      })
        .then(function (response) {
          return response.json().catch(function () { return {}; }).then(function (data) {
            if (!response.ok || !data.ok) throw new Error(data.error || 'subscription_failed');
            return data;
          });
        })
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
