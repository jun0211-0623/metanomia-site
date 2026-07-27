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

/** Unsubscribe link target: .../exec?unsub=<email> */
function doGet(e) {
  var email = String(((e && e.parameter) || {}).unsub || '').trim().toLowerCase();
  if (!isEmail(email)) return html('Invalid request.');

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
