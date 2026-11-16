/**
 * Loop — Google Sheet backend (v2: category deck).
 *
 * POST (from the game): one row per player in "Responses", one row per category answered in "Swipes".
 *   Called after the email screen (card 3), after every later card, and at the end, so partial plays
 *   are saved against an email. Each call replaces that session's earlier rows.
 * GET ?action=categories : returns the "Categories" tab as JSON (read by the GitHub build).
 * GET ?action=products   : old Products tab, kept so nothing that still calls it breaks.
 *
 * Run setupV2() once from the editor. It creates any missing tabs; if Responses or Swipes still
 * have the v1 headers it renames them "(v1)" and starts fresh ones, so old rows are kept but not mixed in.
 *
 * GET ?action=add&key=…  : the "Add to Loop" bookmark button. Still writes to the Products tab;
 *   copy a photo link from there into Categories if you want it on a keypad.
 */

const RESPONSES = 'Responses';
const SWIPES = 'Swipes';
const CATEGORIES = 'Categories';
const PRODUCTS = 'Products';

const RESPONSE_COLS = ['timestamp', 'session', 'email', 'name', 'baby_birthdate', 'neighborhood',
  'cards_seen', 'have_count', 'space_count', 'saving_count', 'sqft_freed',
  'seconds', 'referred_by', 'status'];
const SWIPE_COLS = ['timestamp', 'session', 'email', 'category', 'have', 'version', 'status', 'referred_by'];
const CATEGORY_COLS = ['category', 'order', 'color', 'icon', 'sqft', 'intake_only',
  'hero1_name', 'hero1_photo', 'hero1_preview', 'hero2_name', 'hero2_photo', 'hero2_preview',
  'hero3_name', 'hero3_photo', 'hero3_preview', 'hide'];

function setupV2() {
  const ss = SpreadsheetApp.getActive();
  [[RESPONSES, RESPONSE_COLS], [SWIPES, SWIPE_COLS], [CATEGORIES, CATEGORY_COLS]].forEach(([name, cols]) => {
    let sh = ss.getSheetByName(name);
    if (sh && sh.getLastRow() > 0) {
      const head = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(String);
      if (head.join('|') !== cols.join('|') && name !== CATEGORIES) {
        sh.setName(name + ' (v1)');
        sh = null;
      }
    }
    if (!sh) sh = ss.insertSheet(name);
    if (sh.getLastRow() === 0) {
      sh.appendRow(cols);
      sh.setFrozenRows(1);
      sh.getRange(1, 1, 1, cols.length).setFontWeight('bold');
    }
  });
}

// Secret for the "Add to Loop" bookmark button. Must match the one in the button.
// The real key lives only in the Sheet's script editor; never commit it.
const ADD_KEY = 'KEY_HERE';

function doPost(e) {
  const d = JSON.parse(e.postData.contents);
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const ss = SpreadsheetApp.getActive();
    const now = new Date();
    const clip = v => String(v == null ? '' : v).slice(0, 500);

    const resp = ss.getSheetByName(RESPONSES);
    const row = RESPONSE_COLS.map(c => c === 'timestamp' ? now : clip(d[c]));
    const existing = findRow_(resp, RESPONSE_COLS.indexOf('session') + 1, d.session);
    if (existing) resp.getRange(existing, 1, 1, row.length).setValues([row]);
    else resp.appendRow(row);

    const sw = ss.getSheetByName(SWIPES);
    deleteRows_(sw, SWIPE_COLS.indexOf('session') + 1, d.session);
    const swipes = (d.swipes || []).slice(0, 50).map(s => [
      now, clip(d.session), clip(d.email), clip(s.category),
      s.have ? 'yes' : 'no', clip(s.version), clip(s.status), clip(d.referred_by)
    ]);
    if (swipes.length) sw.getRange(sw.getLastRow() + 1, 1, swipes.length, SWIPE_COLS.length).setValues(swipes);

    return ContentService.createTextOutput('ok');
  } finally {
    lock.releaseLock();
  }
}

function doGet(e) {
  const action = e.parameter.action || '';
  if (action === 'add') return addProduct_(e.parameter);
  const tab = { categories: CATEGORIES, products: PRODUCTS }[action];
  if (!tab) return ContentService.createTextOutput('Loop sheet is running.');
  const sh = SpreadsheetApp.getActive().getSheetByName(tab);
  if (!sh) return json_([]);
  const values = sh.getDataRange().getValues();
  const head = values.shift().map(h => String(h).trim().toLowerCase());
  const rows = values
    .map(r => Object.fromEntries(head.map((h, i) => [h, String(r[i] == null ? '' : r[i]).trim()])))
    .filter(r => (r.category || r.url || r.name) && !r.hide);
  return json_(rows);
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
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

/** Called by the "Add to Loop" bookmark button. Adds (or updates) one row in Products. */
function addProduct_(p) {
  const page = (title, body) => HtmlService.createHtmlOutput(
    '<div style="font-family:-apple-system,Helvetica,sans-serif;max-width:420px;margin:40px auto;padding:0 16px;color:#3A2E4D">' +
    '<h2 style="margin:0 0 12px">' + title + '</h2>' + body +
    '<p style="color:#7D7191;font-size:14px;margin-top:20px">It will show up in the game after the next build (nightly, or Actions &rarr; Run workflow). You can close this tab.</p></div>'
  ).setTitle('Loop');
  const esc = v => String(v || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

  if (p.key !== ADD_KEY) return page('Not allowed', '<p>This button has the wrong key.</p>');
  if (!p.url && !p.name) return page('Nothing to add', '<p>No product found on that page.</p>');

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const sh = SpreadsheetApp.getActive().getSheetByName(PRODUCTS);
    const head = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(h => String(h).trim().toLowerCase());
    const col = name => head.indexOf(name);
    const row = head.map(h => ({url: p.url, name: p.name, category: p.category, price: p.price, photo: p.photo}[h] || ''));

    // Same link already in the sheet? Update it instead of adding a duplicate.
    let existing = null;
    if (p.url && col('url') >= 0 && sh.getLastRow() > 1) {
      const urls = sh.getRange(2, col('url') + 1, sh.getLastRow() - 1, 1).getValues();
      for (let i = 0; i < urls.length; i++) if (urls[i][0] === p.url) { existing = i + 2; break; }
    }
    if (existing) sh.getRange(existing, 1, 1, row.length).setValues([row]);
    else sh.appendRow(row);

    const img = p.photo ? '<img src="' + esc(p.photo) + '" style="width:100%;max-height:260px;object-fit:contain;border-radius:12px;background:#fff">' : '<p>(No photo found on the page. Paste one into the photo cell.)</p>';
    return page((existing ? 'Updated' : 'Added') + ' to Loop', img +
      '<p style="font-size:18px;margin:12px 0 4px"><b>' + esc(p.name) + '</b></p>' +
      '<p style="margin:0;color:#7D7191">' + esc(p.category || 'No category') + (p.price ? ' &middot; $' + esc(p.price) : '') + '</p>');
  } finally {
    lock.releaseLock();
  }
}