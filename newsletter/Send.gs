/**
 * Metanomia newsletter sending.
 *
 * Write the issue as a normal Gmail draft with the subject prefixed [KO] or [EN],
 * then run the send from the spreadsheet's "Metanomia" menu. The prefix is stripped
 * before sending and decides which subscribers receive it.
 *
 * Sends one message per recipient (never BCC) so each carries its own unsubscribe link.
 */

var SEND_LOG_SHEET = 'sendlog';
var SEND_LOG_HEADERS = ['timestamp', 'subject', 'email'];

// The deployed web app URL, used for unsubscribe links. Hardcoded rather than read from
// ScriptApp so that a test run from the editor still produces the public /exec address.
var UNSUB_BASE = 'https://script.google.com/macros/s/AKfycbxLF2JaW3cBRGjhG-prFFjCk-_QmMWPa09tnBNJXorrgJfd_hbKV2QlrxQcGxr2dXxL/exec';

// Shown in the footer of every issue. Sender identity is a legal requirement in Korea.
var ORG_NAME_EN = 'Metanomia';
var ORG_NAME_KO = '메타노미아';
var ORG_CONTACT = 'libertas.hson@gmail.com'; // Public contact from the site's 문의하기 page.
var SITE_EN = 'https://metanomia-site.vercel.app/';
var SITE_KO = 'https://metanomia-site.vercel.app/ko';

// Leave headroom under the daily quota so a mistake cannot burn the whole allowance.
var SAFETY_MARGIN = 20;

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Metanomia')
    .addItem('1. 초안 확인', 'previewDraft')
    .addItem('2. 나에게만 시험 발송', 'sendTest')
    .addSeparator()
    .addItem('3. 전체 발송', 'sendToAll')
    .addSeparator()
    .addItem('반송 주소 정리', 'markBounces')
    .addToUi();
}

/** Reports which draft would be sent, to whom, and how much quota remains. */
function previewDraft() {
  var issue = findIssueDraft();
  if (!issue) return alert('[KO] 또는 [EN]으로 시작하는 Gmail 초안이 없습니다.');

  var recipients = activeSubscribers(issue.lang);
  var already = sentEmailsFor(issue.subject);
  var remaining = recipients.filter(function (r) { return already.indexOf(r.email) === -1; });

  alert(
    '제목: ' + issue.subject + '\n' +
    '언어: ' + issue.lang + '\n' +
    '대상 구독자: ' + recipients.length + '명\n' +
    '이미 발송됨: ' + already.length + '명\n' +
    '이번에 보낼 대상: ' + remaining.length + '명\n\n' +
    '오늘 남은 발송 한도: ' + MailApp.getRemainingDailyQuota() + '통'
  );
}

/** Sends the issue to the script owner only. */
function sendTest() {
  var issue = findIssueDraft();
  if (!issue) return alert('[KO] 또는 [EN]으로 시작하는 Gmail 초안이 없습니다.');

  var me = Session.getEffectiveUser().getEmail();
  deliver(issue, me);
  alert('시험 발송 완료: ' + me);
}

/**
 * Sends to every active subscriber of the issue's language.
 * Safe to re-run: recipients already logged for this subject are skipped, so a run
 * cut short by the 6-minute execution limit resumes where it stopped.
 */
function sendToAll() {
  // Checked up front: without the key every unsubscribe link would throw
  // mid-loop, after part of the list had already been mailed.
  if (!PropertiesService.getScriptProperties().getProperty(SECRET_KEY)) {
    return alert('구독 취소 링크 서명 키가 없습니다.\n\nCode.gs의 initUnsubSecret()를 한 번 실행한 뒤 다시 시도해 주세요.');
  }

  var issue = findIssueDraft();
  if (!issue) return alert('[KO] 또는 [EN]으로 시작하는 Gmail 초안이 없습니다.');

  var already = sentEmailsFor(issue.subject);
  var targets = activeSubscribers(issue.lang).filter(function (r) {
    return already.indexOf(r.email) === -1;
  });

  if (!targets.length) return alert('보낼 대상이 없습니다. 이미 전원에게 발송되었습니다.');

  var quota = MailApp.getRemainingDailyQuota() - SAFETY_MARGIN;
  if (quota < targets.length) {
    return alert(
      '오늘 남은 발송 한도가 부족합니다.\n' +
      '대상 ' + targets.length + '명 / 발송 가능 ' + Math.max(quota, 0) + '통\n\n' +
      '내일 다시 실행하면 남은 사람부터 이어서 보냅니다.'
    );
  }

  var ui = SpreadsheetApp.getUi();
  var confirmed = ui.alert(
    '전체 발송',
    '"' + issue.subject + '"을(를) ' + targets.length + '명에게 발송합니다. 진행할까요?',
    ui.ButtonSet.YES_NO
  );
  if (confirmed !== ui.Button.YES) return;

  var deadline = new Date().getTime() + 5 * 60 * 1000; // stop before the 6-minute limit
  var log = getLogSheet();
  var sent = 0;

  for (var i = 0; i < targets.length; i++) {
    if (new Date().getTime() > deadline) break;
    deliver(issue, targets[i].email);
    log.appendRow([new Date(), issue.subject, targets[i].email]);
    sent++;
  }

  alert(
    sent + '명에게 발송했습니다.' +
    (sent < targets.length ? '\n\n실행 시간 제한으로 ' + (targets.length - sent) + '명이 남았습니다. 다시 실행하면 이어서 보냅니다.' : '')
  );
}

/** Sends one message, wrapped in the brand shell with a per-recipient unsubscribe link. */
function deliver(issue, email) {
  var htmlBody = wrap(issue.body, issue.lang, email);
  GmailApp.sendEmail(email, issue.subject, stripTags(htmlBody), {
    htmlBody: htmlBody,
    name: issue.lang === 'ko' ? ORG_NAME_KO : ORG_NAME_EN,
    attachments: issue.attachments
  });
}

/** Most recent Gmail draft whose subject starts with [KO] or [EN]. */
function findIssueDraft() {
  var drafts = GmailApp.getDrafts();
  for (var i = drafts.length - 1; i >= 0; i--) {
    var message = drafts[i].getMessage();
    var subject = message.getSubject() || '';
    var tag = subject.slice(0, 4).toUpperCase();
    if (tag !== '[KO]' && tag !== '[EN]') continue;
    return {
      lang: tag === '[KO]' ? 'ko' : 'en',
      subject: subject.slice(4).trim(),
      body: message.getBody(),
      // File attachments pass through. Inline images do not survive the copy, so
      // pictures in the body must be linked by URL rather than pasted into the draft.
      attachments: message.getAttachments()
    };
  }
  return null;
}

/** Active subscribers for one language. */
function activeSubscribers(lang) {
  var sheet = getSheet();
  var last = sheet.getLastRow();
  if (last < 2) return [];

  var rows = sheet.getRange(2, 1, last - 1, HEADERS.length).getValues();
  var iEmail = HEADERS.indexOf('email');
  var iLang = HEADERS.indexOf('lang');
  var iStatus = HEADERS.indexOf('status');

  var out = [];
  for (var i = 0; i < rows.length; i++) {
    if (rows[i][iStatus] !== 'active') continue;
    if (rows[i][iLang] !== lang) continue;
    var email = String(rows[i][iEmail]).trim().toLowerCase();
    if (email) out.push({ email: email, row: i + 2 });
  }
  return out;
}

function getLogSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SEND_LOG_SHEET);
  if (!sheet) {
    sheet = ss.insertSheet(SEND_LOG_SHEET);
    sheet.appendRow(SEND_LOG_HEADERS);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

/** Emails already logged as sent for this subject. */
function sentEmailsFor(subject) {
  var sheet = getLogSheet();
  var last = sheet.getLastRow();
  if (last < 2) return [];

  var rows = sheet.getRange(2, 2, last - 1, 2).getValues(); // subject, email
  var out = [];
  for (var i = 0; i < rows.length; i++) {
    if (rows[i][0] === subject) out.push(String(rows[i][1]).trim().toLowerCase());
  }
  return out;
}

/**
 * Scans recent delivery-failure notices and marks those addresses bounced,
 * so they drop out of the next send.
 */
function markBounces() {
  var threads = GmailApp.search('from:mailer-daemon OR from:postmaster newer_than:30d');
  var sheet = getSheet();
  var iEmail = HEADERS.indexOf('email');
  var iStatus = HEADERS.indexOf('status');
  var last = sheet.getLastRow();
  if (last < 2) return alert('구독자가 없습니다.');

  var rows = sheet.getRange(2, 1, last - 1, HEADERS.length).getValues();
  var marked = [];

  for (var r = 0; r < rows.length; r++) {
    if (rows[r][iStatus] !== 'active') continue;
    var email = String(rows[r][iEmail]).trim().toLowerCase();
    if (!email) continue;

    for (var t = 0; t < threads.length; t++) {
      if (threads[t].getFirstMessageSubject().toLowerCase().indexOf(email) !== -1 ||
          bodyMentions(threads[t], email)) {
        sheet.getRange(r + 2, iStatus + 1).setValue('bounced');
        marked.push(email);
        break;
      }
    }
  }

  alert(marked.length
    ? marked.length + '개 주소를 bounced로 표시했습니다:\n' + marked.join('\n')
    : '반송된 주소를 찾지 못했습니다.');
}

function bodyMentions(thread, email) {
  var messages = thread.getMessages();
  for (var i = 0; i < messages.length; i++) {
    if (messages[i].getPlainBody().toLowerCase().indexOf(email) !== -1) return true;
  }
  return false;
}

/** Brand shell around the draft body. Table-based and inline-styled for email clients. */
function wrap(body, lang, email) {
  var isKo = lang === 'ko';
  var site = isKo ? SITE_KO : SITE_EN;
  var unsubUrl = UNSUB_BASE + '?unsub=' + encodeURIComponent(email) +
    '&t=' + encodeURIComponent(unsubToken(email));
  var unsubLabel = isKo ? '구독 취소' : 'Unsubscribe';
  var reason = isKo
    ? '메타노미아 뉴스레터를 신청하셔서 받으시는 메일입니다.'
    : 'You are receiving this because you subscribed to the Metanomia newsletter.';

  return '' +
    '<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:32px 0;">' +
    '<tr><td align="center">' +
    '<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;">' +

    '<tr><td style="background:#000000;padding:28px 32px;">' +
    '<a href="' + site + '" style="font:700 22px/1 Helvetica,Arial,sans-serif;letter-spacing:-0.5px;color:#ffffff;text-decoration:none;">' +
    (isKo ? ORG_NAME_KO : ORG_NAME_EN) + '</a>' +
    '<div style="height:3px;width:40px;background:#C8FF34;margin-top:14px;"></div>' +
    '</td></tr>' +

    '<tr><td style="padding:32px;font:400 16px/1.7 Helvetica,Arial,sans-serif;color:#1a1a1a;">' +
    body +
    '</td></tr>' +

    '<tr><td style="border-top:1px solid #e5e5e5;padding:24px 32px;font:400 12px/1.7 Helvetica,Arial,sans-serif;color:#73757A;">' +
    reason + '<br />' +
    (isKo ? ORG_NAME_KO : ORG_NAME_EN) +
    (ORG_CONTACT ? ' · <a href="mailto:' + ORG_CONTACT + '" style="color:#73757A;">' + ORG_CONTACT + '</a>' : '') +
    '<br />' +
    '<a href="' + site + '" style="color:#73757A;">' + site + '</a> · ' +
    '<a href="' + unsubUrl + '" style="color:#73757A;">' + unsubLabel + '</a>' +
    '</td></tr>' +

    '</table></td></tr></table>';
}

function stripTags(html) {
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|div|tr|h[1-6])>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function alert(message) {
  SpreadsheetApp.getUi().alert(message);
}
