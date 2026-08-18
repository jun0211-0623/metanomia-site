/* Same-origin proxy for the Metanomia email update form. */
const ENDPOINT = 'https://script.google.com/macros/s/AKfycbxLF2JaW3cBRGjhG-prFFjCk-_QmMWPa09tnBNJXorrgJfd_hbKV2QlrxQcGxr2dXxL/exec';
const EMAIL_RE = /^[^@\s]+@[^@\s.]+\.[^@\s]+$/;

function readBody(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  if (typeof req.body !== 'string') return {};
  try {
    return JSON.parse(req.body);
  } catch (error) {
    return Object.fromEntries(new URLSearchParams(req.body));
  }
}

module.exports = async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ ok: false, error: 'method_not_allowed' });
  }

  const body = readBody(req);
  const email = String(body.email || '').trim().toLowerCase();
  const lang = body.lang === 'ko' ? 'ko' : 'en';
  const page = String(body.page || '').slice(0, 300);
  const company = String(body.company || '');

  if (company) return res.status(200).json({ ok: true });
  if (!EMAIL_RE.test(email) || email.length > 254) {
    return res.status(400).json({ ok: false, error: 'invalid_email' });
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const upstream = await fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded;charset=UTF-8' },
      body: new URLSearchParams({ email, lang, page }),
      redirect: 'follow',
      signal: controller.signal
    });
    const responseText = await upstream.text();
    if (!upstream.ok) throw new Error('Email backend ' + upstream.status);

    let responseData = null;
    try { responseData = JSON.parse(responseText); } catch (error) {}
    if (responseData && responseData.ok === false) {
      throw new Error(String(responseData.error || 'Email backend rejected request'));
    }

    return res.status(200).json({ ok: true });
  } catch (error) {
    console.error('[subscribe]', error);
    return res.status(502).json({ ok: false, error: 'upstream_unavailable' });
  } finally {
    clearTimeout(timeout);
  }
};
