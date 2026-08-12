/**
 * Metanomia newsletter signup endpoint.
 * Google Apps Script web app bound to the subscriber spreadsheet.
 *
 * Deploy: Deploy > New deployment > Web app
 *   - Execute as: Me
 *   - Who has access: Anyone
 * Copy the /exec URL into js/subscribe.js.
 */

var SHEET_NAME = 'subscribers';
var HEADERS = ['timestamp', 'email', 'lang', 'page', 'status'];

function doPost(e) {
  var p = (e && e.parameter) || {};

  // The unsubscribe confirmation form posts back here.
  if (p.unsub) return confirmUnsubscribe(p);

  // Honeypot: bots fill every field they see. Pretend success, write nothing.
  if (String(p.company || '').trim()) return json({ ok: true });

  var email = String(p.email || '').trim().toLowerCase();
  if (!isEmail(email)) return json({ ok: false, error: 'invalid' });

  var lang = p.lang === 'ko' ? 'ko' : 'en';
  var page = String(p.page || '').slice(0, 200);

  var lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    var sheet = getSheet();
    if (findRow(sheet, email)) return json({ ok: true, dup: true });
    sheet.appendRow([new Date(), email, lang, page, 'active']);
  } finally {
    lock.releaseLock();
  }
  return json({ ok: true });
}

/**
 * Unsubscribe link target: .../exec?unsub=<email>&t=<token>
 *
 * The token proves the link came from an email we sent, so knowing someone's
 * address is not enough to unsubscribe them. GET only shows a confirmation
 * button; the sheet is written by the POST it submits. That second step keeps
 * mail scanners and link prefetchers from unsubscribing people who never
 * clicked.
 */
function doGet(e) {
  var p = (e && e.parameter) || {};
  var email = String(p.unsub || '').trim().toLowerCase();
  if (!isEmail(email)) return html('Invalid request.');
  if (!tokenMatches(email, p.t)) return html(EXPIRED_MESSAGE);

  return html(
    '<p>Unsubscribe <strong>' + escapeHtml(email) + '</strong> from the Metanomia newsletter?</p>' +
    '<form method="post" action="' + UNSUB_BASE + '">' +
    '<input type="hidden" name="unsub" value="' + escapeHtml(email) + '">' +
    '<input type="hidden" name="t" value="' + escapeHtml(String(p.t || '')) + '">' +
    '<button type="submit" style="font:inherit;padding:10px 18px;border:1px solid #151515;' +
    'background:#151515;color:#fff;cursor:pointer;">Unsubscribe</button>' +
    '</form>'
  );
}

/** Performs the unsubscribe. Reached only from the confirmation form's POST. */
function confirmUnsubscribe(p) {
  var email = String(p.unsub || '').trim().toLowerCase();
  if (!isEmail(email)) return html('Invalid request.');
  if (!tokenMatches(email, p.t)) return html(EXPIRED_MESSAGE);

  var sheet = getSheet();
  var row = findRow(sheet, email);
  if (!row) return html('This address is not on the list.');

  sheet.getRange(row, HEADERS.indexOf('status') + 1).setValue('unsubscribed');
  return html('Unsubscribed. You will receive no further emails from Metanomia.');
}

function getSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(HEADERS);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

/** 1-indexed sheet row of the email, or 0 if absent. */
function findRow(sheet, email) {
  var last = sheet.getLastRow();
  if (last < 2) return 0;
  var values = sheet.getRange(2, HEADERS.indexOf('email') + 1, last - 1, 1).getValues();
  for (var i = 0; i < values.length; i++) {
    if (String(values[i][0]).trim().toLowerCase() === email) return i + 2;
  }
  return 0;
}

function isEmail(v) {
  return /^[^@\s]+@[^@\s.]+\.[^@\s]+$/.test(v) && v.length <= 254;
}

var SECRET_KEY = 'UNSUB_SECRET';

var EXPIRED_MESSAGE =
  'This unsubscribe link is no longer valid. Use the link in a recent issue, ' +
  'or email <a href="mailto:contact@metanomia.org">contact@metanomia.org</a> and we will remove you.';

/**
 * Run once from the editor before sending the next issue. Generates the signing
 * secret and stores it in Script Properties. Safe to re-run: it never replaces
 * an existing secret, because that would invalidate every link already mailed.
 */
function initUnsubSecret() {
  var props = PropertiesService.getScriptProperties();
  if (props.getProperty(SECRET_KEY)) {
    Logger.log('Secret already set. Nothing to do.');
    return;
  }
  props.setProperty(SECRET_KEY, Utilities.getUuid() + Utilities.getUuid());
  Logger.log('Secret created. Unsubscribe links in future issues will be signed.');
}

/** Signs an address so its unsubscribe link can only come from us. */
function unsubToken(email) {
  var secret = PropertiesService.getScriptProperties().getProperty(SECRET_KEY);
  if (!secret) throw new Error('Run initUnsubSecret() once before sending.');
  var raw = Utilities.computeHmacSha256Signature(String(email).trim().toLowerCase(), secret);
  return Utilities.base64EncodeWebSafe(raw).replace(/=+$/, '').slice(0, 32);
}

/** Length-independent comparison so a wrong token leaks nothing by timing. */
function tokenMatches(email, supplied) {
  var expected;
  try {
    expected = unsubToken(email);
  } catch (error) {
    return false;
  }
  var given = String(supplied || '');
  if (given.length !== expected.length) return false;
  var diff = 0;
  for (var i = 0; i < expected.length; i++) {
    diff |= expected.charCodeAt(i) ^ given.charCodeAt(i);
  }
  return diff === 0;
}

function escapeHtml(v) {
  return String(v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function html(message) {
  return HtmlService.createHtmlOutput(
    '<div style="font:16px/1.6 -apple-system,sans-serif;padding:48px;max-width:520px">' +
    message + '</div>'
  );
}
