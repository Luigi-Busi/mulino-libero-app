const BANCO_SISAL_ACTIVE_META = 'BANCO_SISAL_ACTIVE_EVENT_V1';
const BANCO_SISAL_ACTIVE_SOURCES = [
  {name: 'Sisal Sport', type: 'Sisal Sport', headerRow: 8},
  {name: 'Sisal Slot 600', type: 'Sisal 600', headerRow: 9}
];
const BANCO_SISAL_ACTIVE_HEADERS = [
  'data apertura', 'tipo', 'diffida', 'nome cognome', 'username',
  'password', 'e mail', 'pass e mail', 'saldo attuale', 'saldo in uscita'
];

function bancoRiceviPrelievoSisal_(event) {
  const eventId = event && event.event_id;
  let reply = {ok: false, status: 'invalid'};
  try {
    if (bancoPrelievoSisalValido_(event)) {
      reply = bancoAllineaSisalActive_(event);
    }
  } catch (_) {
    // Sheets service exceptions are intentionally not returned or logged.
    reply = {ok: false, status: 'error'};
  }
  if (typeof eventId === 'string' && /^[a-f0-9]{64}$/.test(eventId)) {
    reply.event_id = eventId;
  }
  return ContentService.createTextOutput(JSON.stringify(reply))
    .setMimeType(ContentService.MimeType.JSON);
}

function bancoPrelievoSisalValido_(event) {
  if (!event || typeof event !== 'object' || Array.isArray(event)) return false;
  const keys = ['amount_cents', 'balance_cents', 'email', 'event_id', 'received_at'];
  if (Object.keys(event).sort().join('|') !== keys.join('|')) return false;
  return typeof event.email === 'string' &&
    event.email.length <= 254 && /^[a-z0-9.!#$%&'*+\/=?^_`{|}~-]+@libero\.it$/i.test(event.email) &&
    Number.isSafeInteger(event.amount_cents) && event.amount_cents > 0 &&
    Number.isSafeInteger(event.balance_cents) &&
    typeof event.event_id === 'string' && /^[a-f0-9]{64}$/.test(event.event_id) &&
    typeof event.received_at === 'string' &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(event.received_at) &&
    Number.isFinite(Date.parse(event.received_at)) &&
    new Date(event.received_at).toISOString() === event.received_at;
}

function bancoAllineaSisalActive_(event) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(15000)) return {ok: false, status: 'busy'};
  try {
    const id = PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID');
    if (!id) throw new Error('Spreadsheet not configured');
    const book = SpreadsheetApp.openById(id);
    const email = event.email.toLowerCase();
    const found = bancoCercaSisalActive_(book, email);
    if (!found.length) return {ok: false, status: 'unmatched'};
    const current = found.filter(account =>
      account.sheet.getRange(account.row, 7).getDisplayValue().trim().toLowerCase() === email);
    if (!current.length) return {ok: false, status: 'unmatched'};
    if (current.every(account =>
      bancoFondoRossoSisalActive_(account.sheet.getRange(account.row, 7).getBackground()))) {
      return {ok: true, status: 'excluded'};
    }
    if (current.length !== 1) return {ok: false, status: 'ambiguous'};

    const account = current[0];
    const sourceCells = account.sheet.getRange(account.row, 1, 1, 3).getValues()[0];
    const identity = account.sheet.getRange(account.row, 4, 1, 2).getDisplayValues()[0];
    const date = sourceCells[0];
    const name = String(identity[0]).trim();
    const username = String(identity[1]).trim();
    if (!name || !username || !date ||
        (date instanceof Date && !Number.isFinite(date.getTime()))) {
      throw new Error('Incomplete source account');
    }
    const diffida = bancoDiffidaSisalActive_(sourceCells[2]);
    const target = book.getSheetByName('Sisal Active');
    if (!target || target.getName() !== 'Sisal Active' ||
        !bancoIntestazioniSisalActive_(target.getRange(1, 1, 1, 10).getDisplayValues()[0],
          BANCO_SISAL_ACTIVE_HEADERS)) {
      throw new Error('Sisal Active layout not recognized');
    }
    const location = bancoDestinazioneSisalActive_(target, account.type, username.toLowerCase());
    if (location.ambiguous) return {ok: false, status: 'ambiguous'};
    const row = location.row;
    const key = JSON.stringify([account.type.toLowerCase(), username.toLowerCase()]);
    const fullRow = target.getRange(row + ':' + row);
    const records = bancoMetadatiSisalActive_(fullRow, row);
    if (records.length > 1) throw new Error('Unexpected event metadata');
    if (records.length === 1) {
      const previous = JSON.parse(records[0].getValue());
      if (previous.key !== key) throw new Error('Event row identity changed');
      if (previous.id === event.event_id) return {ok: true, status: 'duplicate'};
      if (previous.at >= event.received_at) return {ok: true, status: 'stale'};
    }

    target.getRange(row, 1, 1, 5).setValues([[
      bancoValoreSisalActive_(date), account.type, diffida,
      bancoValoreSisalActive_(name), bancoValoreSisalActive_(username)
    ]]);
    if (date instanceof Date) target.getRange(row, 1).setNumberFormat('dd/MM/yyyy');
    target.getRange(row, 7).setValue(bancoValoreSisalActive_(email));
    target.getRange(row, 9, 1, 2).setValues([[event.balance_cents / 100, event.amount_cents / 100]]);
    // Keep the password entirely inside Sheets. Read no value from column F in this function.
    account.sheet.getRange(account.row, 6).copyTo(target.getRange(row, 6),
      SpreadsheetApp.CopyPasteType.PASTE_VALUES, false);
    SpreadsheetApp.flush();

    const marker = JSON.stringify({id: event.event_id, at: event.received_at, key: key});
    if (records.length === 1) records[0].setValue(marker);
    else fullRow.addDeveloperMetadata(BANCO_SISAL_ACTIVE_META, marker);
    SpreadsheetApp.flush();
    return {ok: true, status: 'written'};
  } finally {
    lock.releaseLock();
  }
}

function bancoIntestazioniSisalActive_(headers, expected) {
  const normalized = headers.map(value => String(value).toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, ' ').trim());
  return expected.every((header, index) => typeof header === 'string'
    ? normalized[index] === header : header.includes(normalized[index]));
}

function bancoCercaSisalActive_(book, email) {
  const matches = [];
  BANCO_SISAL_ACTIVE_SOURCES.forEach(source => {
    const sheet = book.getSheetByName(source.name);
    if (!sheet || sheet.getName() !== source.name) throw new Error('Sisal source unavailable');
    const headers = sheet.getRange(source.headerRow, 1, 1, 7).getDisplayValues()[0];
    if (!bancoIntestazioniSisalActive_(headers, [
      'data apertura', 'chiusura', 'diffida', ['nome cognome', 'nome e cognome'],
      'username', 'password', ['e mail', 'email']
    ])) throw new Error('Sisal source layout not recognized');
    const size = sheet.getLastRow() - source.headerRow;
    if (size <= 0) return;
    const first = source.headerRow + 1;
    sheet.getRange(first, 7, size, 1).getDisplayValues().forEach((cells, index) => {
      if (String(cells[0]).trim().toLowerCase() === email) {
        matches.push({sheet: sheet, type: source.type, row: first + index});
      }
    });
  });
  return matches;
}

function bancoDestinazioneSisalActive_(sheet, type, username) {
  const matches = [];
  let free;
  const last = sheet.getLastRow();
  if (last >= 2) {
    // A:E and G are safe to read. Never include F or H in row scans.
    const left = sheet.getRange(2, 1, last - 1, 5).getDisplayValues();
    const emails = sheet.getRange(2, 7, last - 1, 1).getDisplayValues();
    const amounts = sheet.getRange(2, 9, last - 1, 2).getDisplayValues();
    left.forEach((cells, index) => {
      const row = index + 2;
      if (String(cells[1]).trim().toLowerCase() === type.toLowerCase() &&
          String(cells[4]).trim().toLowerCase() === username) {
        matches.push(row);
      }
      if (!free && cells.concat(emails[index], amounts[index]).every(value => !String(value).trim()) &&
          sheet.getRange(row, 1, 1, 7).isBlank() && sheet.getRange(row, 9, 1, 2).isBlank() &&
          !bancoMetadatiSisalActive_(sheet.getRange(row + ':' + row), row).length) {
        free = row;
      }
    });
  }
  if (matches.length > 1) return {ambiguous: true};
  if (matches.length === 1) return {row: matches[0]};
  const row = free || last + 1;
  if (row > sheet.getMaxRows()) sheet.insertRowsAfter(sheet.getMaxRows(), row - sheet.getMaxRows());
  return {row: row};
}

function bancoMetadatiSisalActive_(fullRow, row) {
  return fullRow.getDeveloperMetadata().filter(item => {
    if (item.getKey() !== BANCO_SISAL_ACTIVE_META) return false;
    const location = item.getLocation().getRow();
    return location && location.getRow() === row;
  });
}

function bancoDiffidaSisalActive_(value) {
  if (typeof value === 'boolean') return value ? 'Si' : 'No';
  const plain = String(value == null ? '' : value).trim().toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  if (plain === 'si') return 'Si';
  if (plain === '' || plain === 'no') return 'No';
  throw new Error('Unsupported diffida value');
}

function bancoValoreSisalActive_(value) {
  return typeof value === 'string' && value.startsWith('=') ? "'" + value : value;
}

function bancoFondoRossoSisalActive_(color) {
  const hex = /^#([a-f0-9]{2})([a-f0-9]{2})([a-f0-9]{2})$/i.exec(color);
  if (!hex) return false;
  const [red, green, blue] = hex.slice(1).map(part => parseInt(part, 16));
  return red > green && red > blue &&
    Math.max(green, blue) <= 0.45 * red && Math.abs(green - blue) <= 0.2 * red;
}
