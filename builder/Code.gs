/**
 * Loop — Google Sheet backend.
 *
 * POST (from the swipe game): saves one row to "Responses" and one row per card to "Swipes".
 * GET  ?action=products       : returns the "Products" tab as JSON (read by the GitHub build).
 *
 * Run setup() once from the editor to create the tabs and headers.
 */

const RESPONSES = 'Responses';
const SWIPES = 'Swipes';
const PRODUCTS = 'Products';

const RESPONSE_COLS = ['timestamp', 'name', 'baby_birthdate', 'neighborhood', 'email',
  'dying_to_get_rid_of', 'wish_borrowed', 'ready_to_ditch', 'still_using',
  'have_count', 'cards_seen', 'seconds', 'referred_by', 'status', 'session'];
const SWIPE_COLS = ['timestamp', 'session', 'name', 'item', 'category', 'have', 'status', 'referred_by'];
const PRODUCT_COLS = ['url', 'name', 'category', 'price', 'photo', 'blurb', 'hide'];

function setup() {
  const ss = SpreadsheetApp.getActive();
  [[RESPONSES, RESPONSE_COLS], [SWIPES, SWIPE_COLS], [PRODUCTS, PRODUCT_COLS]].forEach(([name, cols]) => {
    const sh = ss.getSheetByName(name) || ss.insertSheet(name);
    if (sh.getLastRow() === 0) {
      sh.appendRow(cols);
      sh.setFrozenRows(1);
      sh.getRange(1, 1, 1, cols.length).setFontWeight('bold');
    }
  });
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const d = JSON.parse(e.postData.contents);
    const ss = SpreadsheetApp.getActive();
    const now = new Date();
    const clip = v => String(v == null ? '' : v).slice(0, 2000);

    // A "finished" row replaces an earlier "dropped off" row from the same session.
    const resp = ss.getSheetByName(RESPONSES);
    const row = RESPONSE_COLS.map(c => c === 'timestamp' ? now : clip(d[c]));
    const existing = findRow_(resp, RESPONSE_COLS.indexOf('session') + 1, d.session);
    if (existing) resp.getRange(existing, 1, 1, row.length).setValues([row]);
    else resp.appendRow(row);

    const sw = ss.getSheetByName(SWIPES);
    deleteRows_(sw, SWIPE_COLS.indexOf('session') + 1, d.session);
    const swipes = (d.swipes || []).slice(0, 200).map(s => [
      now, clip(d.session), clip(d.name), clip(s.name), clip(s.category),
      s.have ? 'yes' : 'no', clip(s.subStatus || ''), clip(d.referred_by)
    ]);
    if (swipes.length) sw.getRange(sw.getLastRow() + 1, 1, swipes.length, SWIPE_COLS.length).setValues(swipes);

    return ContentService.createTextOutput('ok');
  } finally {
    lock.releaseLock();
  }
}

function doGet(e) {
  if ((e.parameter.action || '') !== 'products') {
    return ContentService.createTextOutput('Loop sheet is running.');
  }
  const sh = SpreadsheetApp.getActive().getSheetByName(PRODUCTS);
  const values = sh.getDataRange().getValues();
  const head = values.shift().map(h => String(h).trim().toLowerCase());
  const rows = values
    .map(r => Object.fromEntries(head.map((h, i) => [h, String(r[i] == null ? '' : r[i]).trim()])))
    .filter(r => (r.url || r.name) && !r.hide);
  return ContentService.createTextOutput(JSON.stringify(rows)).setMimeType(ContentService.MimeType.JSON);
}

function findRow_(sh, col, value) {
  if (!value || sh.getLastRow() < 2) return null;
  const vals = sh.getRange(2, col, sh.getLastRow() - 1, 1).getValues();
  for (let i = vals.length - 1; i >= 0; i--) if (vals[i][0] === value) return i + 2;
  return null;
}

function deleteRows_(sh, col, value) {
  if (!value || sh.getLastRow() < 2) return;
  const vals = sh.getRange(2, col, sh.getLastRow() - 1, 1).getValues();
  for (let i = vals.length - 1; i >= 0; i--) if (vals[i][0] === value) sh.deleteRow(i + 2);
}
