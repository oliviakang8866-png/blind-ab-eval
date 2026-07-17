// This project is a pure JSON API backend — the evaluation page itself is
// static HTML hosted on GitHub Pages (see scripts/build_report.py), which
// calls this web app via fetch() for every vote/remark/quality-review save.
// There is deliberately no Index.html here: an earlier version tried to also
// serve the page from Apps Script and that's a common source of "No HTML
// file named Index was found" deploy errors plus corporate-Workspace
// accounts blocking navigation to externally-owned Apps Script web apps.
// Keep this project GET/POST-API-only.
const SHEET_NAME = 'votes';

function doGet(e) {
  if (e && e.parameter && e.parameter.action === 'getMyVotes') {
    return jsonOut_({ ok: true, votes: getMyVotes_(e.parameter.evaluator || '') });
  }
  if (e && e.parameter && e.parameter.action === 'getAllVotes') {
    return jsonOut_({ ok: true, rows: getAllVotes_(), completions: getAllCompletions_() });
  }
  return jsonOut_({ ok: true, message: 'This is a JSON API backend, not a page. See the GitHub Pages link you were given.' });
}

function doPost(e) {
  const data = JSON.parse(e.postData.contents);
  if (data.action === 'complete') {
    return jsonOut_(submitCompletion_(data.evaluator));
  }
  const result = submitVote_(data);
  return jsonOut_(result);
}

function jsonOut_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function getSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
  }
  if (sheet.getLastRow() === 0) {
    sheet.appendRow([
      'timestamp', 'evaluator', 'row_index', 'item_id', 'choice',
      'A_model', 'B_model', 'A_url', 'B_url', 'user_image_url', 'remark',
      'A_quality_status', 'A_quality_reason', 'B_quality_status', 'B_quality_reason'
    ]);
  }
  return sheet;
}

function submitVote_(data) {
  const lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    const sheet = getSheet_();

    // upsert: find existing row for this evaluator + row_index and overwrite it
    const values = sheet.getDataRange().getValues();
    let targetRow = -1;
    for (let r = 1; r < values.length; r++) {
      if (values[r][1] === data.evaluator && String(values[r][2]) === String(data.rowIndex)) {
        targetRow = r + 1; // 1-indexed sheet row
        break;
      }
    }

    const rowValues = [
      new Date(), data.evaluator, data.rowIndex, data.itemId, data.choice,
      data.aModel, data.bModel, data.aUrl, data.bUrl, data.userImg, data.remark || '',
      data.aQualityStatus || '', data.aQualityReason || '',
      data.bQualityStatus || '', data.bQualityReason || ''
    ];

    if (targetRow > 0) {
      sheet.getRange(targetRow, 1, 1, rowValues.length).setValues([rowValues]);
    } else {
      sheet.appendRow(rowValues);
    }

    return { ok: true };
  } finally {
    lock.releaseLock();
  }
}

// Returns which row_indexes this evaluator has already voted on, so the page
// can restore progress if they open it on a different device/browser.
function getMyVotes_(evaluator) {
  const sheet = getSheet_();
  const values = sheet.getDataRange().getValues();
  const result = {};
  for (let r = 1; r < values.length; r++) {
    if (values[r][1] === evaluator) {
      result[values[r][2]] = values[r][4];
    }
  }
  return result;
}

// Returns every row of the votes sheet as an array of {header: value} objects,
// for the results dashboard (results.html) to aggregate client-side. Public
// (no evaluator filter) — the results page is meant to show everyone's data.
function getAllVotes_() {
  const sheet = getSheet_();
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) return [];
  const headers = values[0];
  const rows = [];
  for (let r = 1; r < values.length; r++) {
    const obj = {};
    headers.forEach(function(h, i) {
      const cell = values[r][i];
      obj[h] = (cell instanceof Date) ? cell.toISOString() : cell;
    });
    rows.push(obj);
  }
  return rows;
}

function getAllCompletions_() {
  const sheet = getCompletionsSheet_();
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) return [];
  const rows = [];
  for (let r = 1; r < values.length; r++) {
    rows.push({ timestamp: values[r][0] instanceof Date ? values[r][0].toISOString() : values[r][0], evaluator: values[r][1] });
  }
  return rows;
}

function getCompletionsSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName('completions');
  if (!sheet) {
    sheet = ss.insertSheet('completions');
  }
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(['timestamp', 'evaluator']);
  }
  return sheet;
}

function submitCompletion_(evaluator) {
  const lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    const sheet = getCompletionsSheet_();
    const values = sheet.getDataRange().getValues();
    let targetRow = -1;
    for (let r = 1; r < values.length; r++) {
      if (values[r][1] === evaluator) {
        targetRow = r + 1;
        break;
      }
    }
    if (targetRow > 0) {
      sheet.getRange(targetRow, 1, 1, 2).setValues([[new Date(), evaluator]]);
    } else {
      sheet.appendRow([new Date(), evaluator]);
    }
    return { ok: true };
  } finally {
    lock.releaseLock();
  }
}
