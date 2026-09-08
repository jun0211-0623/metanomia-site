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
var ORG_ADDRESS = ''; // TODO: 사업장 주소를 넣어야 정보통신망법 요건을 채웁니다.
var SITE_EN = 'https://metanomia.org/';
var SITE_KO = 'https://metanomia.org/ko';

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
  // Checked up front: without the key the unsubscribe links go out unsigned,
  // and the confirmation page then rejects every one of them.
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
  var htmlBody = wrap(issue.body, issue.lang, email, issue.subject);
  GmailApp.sendEmail(email, issue.subject, stripTags(htmlBody), {
    htmlBody: htmlBody,
    name: issue.lang === 'ko' ? ORG_NAME_KO : ORG_NAME_EN,
    attachments: issue.attachments
  });
}

/** The most recently written Gmail draft whose subject starts with [KO] or [EN]. */
function findIssueDraft() {
  var drafts = GmailApp.getDrafts();
  var latest = null;
  var subject;
  var tag;

  for (var i = 0; i < drafts.length; i++) {
    var message = drafts[i].getMessage();
    subject = message.getSubject() || '';
    tag = subject.slice(0, 4).toUpperCase();
    if (tag !== '[KO]' && tag !== '[EN]') continue;
    // getDrafts() promises no particular order, so compare dates rather than
    // trusting the position in the list.
    if (latest && message.getDate() <= latest.getDate()) continue;
    latest = message;
  }
  if (!latest) return null;

  subject = latest.getSubject();
  tag = subject.slice(0, 4).toUpperCase();
  return {
    lang: tag === '[KO]' ? 'ko' : 'en',
    subject: subject.slice(4).trim(),
    body: latest.getBody(),
    // File attachments pass through. Inline images do not survive the copy, so
    // pictures in the body must be linked by URL rather than pasted into the draft.
    attachments: latest.getAttachments()
  };
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

/**
 * Brand shell around the draft body (디자인 v2, Drew 2026-08).
 * Table-based and inline-styled for email clients.
 */
function wrap(body, lang, email, subject) {
  var isKo = lang === 'ko';
  var site = isKo ? SITE_KO : SITE_EN;
  var token = (typeof unsubToken === 'function')
    ? '&t=' + encodeURIComponent(unsubToken(email)) : '';
  var unsubUrl = UNSUB_BASE + '?unsub=' + encodeURIComponent(email) + token;
  var unsubLabel = isKo ? '구독 취소' : 'Unsubscribe';
  var reason = isKo
    ? '메타노미아 뉴스레터를 신청하셔서 받으시는 메일입니다.'
    : 'You are receiving this because you subscribed to the Metanomia newsletter.';

  // 메일 제목에서 [머리말]을 뗀 보고서 제목
  var title = String(subject || '').replace(/^\s*(\[[^\]]*\]\s*)+/, '').trim();

  // 본문의 마지막 링크를 버튼으로 승격시키고, 본문에서는 제거
  var btnUrl = site;
  var links = body.match(/<a[^>]*href="(https?:\/\/[^"]+)"[^>]*>[\s\S]*?<\/a>/gi);
  if (links && links.length) {
    var lastLink = links[links.length - 1];
    var m = lastLink.match(/href="(https?:\/\/[^"]+)"/i);
    if (m) btnUrl = m[1];
    body = body.replace(lastLink, '');
    body = body.replace(/\[\s*전문\s*확인하기\s*\]?/g, '');
    body = body.replace(/자세한 내용은 아래 링크를 통해 확인해 주시기 바랍니다\.?/g, '');
  }
  var btnLabel = isKo ? '보고서 자세히 보기' : 'Read the full report';

  return '' +
    '<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:32px 0;">' +
    '<tr><td align="center">' +
    '<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;">' +

    // ── 마스트헤드 ──
    '<tr><td align="center" style="background:#000000;padding:40px 32px 34px 32px;">' +
    '<a href="' + site + '" style="text-decoration:none;">' +
    '<span style="font:800 30px/1 Helvetica,Arial,sans-serif;letter-spacing:-0.5px;color:#C8FF34;">Metanomia</span>' +
    '</a>' +
    '<div style="font:300 12px/1 Helvetica,Arial,sans-serif;letter-spacing:6px;color:#f2f2f2;margin-top:16px;">RESEARCH&nbsp;LETTER</div>' +
    '<div style="height:3px;width:56px;background:#C8FF34;margin:18px auto 0 auto;"></div>' +
    '</td></tr>' +

    // ── NEW REPORT 라벨 + 보고서 제목 ──
    '<tr><td style="padding:32px 40px 0 40px;">' +
    '<span style="display:inline-block;background:#C8FF34;color:#000000;' +
    'font:800 11px/1 Helvetica,Arial,sans-serif;letter-spacing:2px;padding:6px 12px;">NEW&nbsp;REPORT</span>' +
    (title
      ? '<div style="font:700 24px/1.4 \'Apple SD Gothic Neo\',\'Malgun Gothic\',Helvetica,Arial,sans-serif;color:#000000;margin-top:14px;">' + title + '</div>'
      : '') +
    '</td></tr>' +

    // ── 본문 ──
    '<tr><td style="padding:20px 40px 8px 40px;font:400 15px/1.8 \'Apple SD Gothic Neo\',\'Malgun Gothic\',Helvetica,Arial,sans-serif;color:#1a1a1a;">' +
    body +
    '</td></tr>' +

    // ── 보고서 버튼 ──
    '<tr><td style="padding:8px 40px 40px 40px;">' +
    '<a href="' + btnUrl + '" style="display:inline-block;background:#000000;color:#ffffff;' +
    'font:700 13px/1 Helvetica,Arial,sans-serif;padding:14px 26px;text-decoration:none;">' +
    btnLabel + '</a>' +
    '</td></tr>' +

    // ── 푸터 ──
    '<tr><td style="border-top:1px solid #e5e5e5;padding:22px 40px 32px 40px;' +
    'font:400 12px/1.7 Helvetica,Arial,sans-serif;color:#73757A;">' +
    reason + '<br />' +
    (isKo ? ORG_NAME_KO : ORG_NAME_EN) + (ORG_ADDRESS ? ' · ' + ORG_ADDRESS : '') + '<br />' +
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
    .replace(/&nbsp;/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function alert(message) {
  SpreadsheetApp.getUi().alert(message);
}
