
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const crypto = require("node:crypto");
const script = fs.readFileSync(path.join(__dirname, "..", "EmailMatcher_aggiornato.gs"), "utf8");

class Range {
  constructor(sheet, row, col, height = 1, width = 1) {
    Object.assign(this, {sheet, row, col, height, width});
  }
  getDisplayValues() {
    return Array.from({length: this.height}, (_, r) =>
      Array.from({length: this.width}, (_, c) => {
        const v = this.sheet.cells[this.row + r - 1]?.[this.col + c - 1];
        return v === undefined || v === null ? "" : String(v);
      }));
  }
  getDisplayValue() { return this.getDisplayValues()[0][0]; }
  getBackgrounds() {
    return Array.from({length: this.height}, (_, r) =>
      Array.from({length: this.width}, () => this.sheet.colors[this.row + r] || "#ffffff"));
  }
  setValue(value) { return this.setValues([[value]]); }
  setValues(values) {
    this.sheet.writes++;
    values.forEach((row, r) => row.forEach((value, c) => {
      const i = this.row + r - 1;
      this.sheet.cells[i] ||= [];
      this.sheet.cells[i][this.col + c - 1] = value;
    }));
    return this;
  }
  addDeveloperMetadata(key, value) {
    assert.equal(this.col, 1);
    assert.equal(this.width, this.sheet.getMaxColumns(), "metadata must cover entire row");
    this.sheet.meta.push(new Metadata(this.sheet, this.row, key, value));
    return this;
  }
  setNumberFormat() { return this; }
  setFontWeight() { return this; }
  setBackground() { return this; }
}
class Metadata {
  constructor(sheet, row, key, value) { Object.assign(this, {sheet, row, key, value}); }
  getKey() { return this.key; }
  getValue() { return this.value; }
  setValue(value) { this.value = value; return this; }
  getLocation() { return {getRow: () => ({getRow: () => this.row})}; }
}
class Sheet {
  constructor(book, name, id, cells) {
    Object.assign(this, {book, name, id, cells, meta: [], colors: {}, writes: 0});
  }
  getName() { return this.name; }
  getSheetId() { return this.id; }
  getParent() { return this.book; }
  getLastRow() { return this.cells.length; }
  getLastColumn() { return Math.max(1, ...this.cells.map(r => r.length)); }
  getMaxRows() { return Math.max(100, this.cells.length); }
  getMaxColumns() { return Math.max(30, this.getLastColumn()); }
  getRange(row, col, height, width) {
    if (row === "A1") return new Range(this, 1, 1);
    return new Range(this, row, col, height, width);
  }
  createDeveloperMetadataFinder() {
    return {withKey: key => ({find: () => this.meta.filter(m => m.key === key)})};
  }
  setFrozenRows() {}
  autoResizeColumns() {}
}
class Book {
  constructor(id) { this.id = id; this.sheets = new Map(); }
  getId() { return this.id; }
  getSheetByName(name) { return this.sheets.get(name); }
  insertSheet(name, cells = []) {
    const sheet = new Sheet(this, name, this.sheets.size + 1, cells);
    this.sheets.set(name, sheet);
    return sheet;
  }
  getSpreadsheetTimeZone() { return "Europe/Rome"; }
}
const headers = ["Data apertura", "Nome e Cognome", "Username", "E-mail", "Password", "Provenienza", "ID_MULINO"];
const account = (user, date = "01/11/2026", email = "", name = "Mario Rossi") =>
  [date, name, user, email, "unused-password", "fixture", "account-" + crypto.createHash("sha256").update(JSON.stringify([user,date,name])).digest("hex").slice(0,16)];
function fixture(prior = account("old", "01/11/2026", "old@example.test"),
                 target = account("new", "21/11/2026")) {
  let serial = 0, releases = 0, notifications = [], failNotify = false;
  const books = new Map(), props = new Map([
    ["SPREADSHEET_ID", "main"], ["SPREADSHEET_ID_ARCHIVIO_MATCHED", "archive"],
    ["SPREADSHEET_ID_SLOTTING", "slot"], ["SPREADSHEET_ID_LOG_MAIL", "log"],
    ["SPREADSHEET_ID_CREAZIONE_MAIL", "queue"]
  ]);
  const context = vm.createContext({
    console: {log() {}, warn() {}, error() {}},
    LockService: {getScriptLock: () => ({tryLock: () => true, releaseLock: () => releases++})},
    PropertiesService: {getScriptProperties: () => ({getProperty: key => props.get(key) || null})},
    SpreadsheetApp: {openById: id => {
      assert(books.has(id), "unexpected workbook " + id);
      return books.get(id);
    }, flush() {}},
    ADMIN_TELEGRAM_ID: "fixture-owner",
    inviaTelegram(id, text) {
      assert.equal(id, "fixture-owner");
      if (failNotify) throw Error("mock transport failure");
      notifications.push(text); return notifications.length;
    },
    Utilities: {
      getUuid: () => "fixture-uuid-" + (++serial),
      DigestAlgorithm: {SHA_256: "sha256"}, Charset: {UTF_8: "utf8"},
      computeDigest: (alg, text) => [...crypto.createHash(alg).update(text).digest()],
      formatDate: () => "2026-11-14 12:00:00"
    }
  });
  vm.runInContext(script, context);
  const groups = JSON.parse(vm.runInContext("JSON.stringify(EM_SOURCE_GROUPS)", context));
  for (const g of groups) {
    const id = props.get(g.property);
    if (!books.has(id)) books.set(id, new Book(id));
    for (const name of g.sheets) books.get(id).insertSheet(name, [headers.slice()]);
  }
  const sheet = books.get("main").getSheetByName("Sisal Sport");
  sheet.cells = [headers.slice(), ...(prior ? [prior] : []), target];
  books.set("log", new Book("log"));
  books.get("log").insertSheet("Log", []);
  books.set("queue", new Book("queue"));
  books.get("queue").insertSheet("Coda", [
    JSON.parse(vm.runInContext("JSON.stringify(EM_CODA_HEADERS)", context))
  ]);
  return {
    context, books, props, sheet, notifications,
    get releases() { return releases; },
    failNotifications(value) { failNotify = value; },
    run() { return context.completaEmailRiga("Sisal Sport", sheet.cells.length); },
    queue() { return books.get("queue").getSheetByName("Coda").cells; },
    review() { return books.get("log").getSheetByName("RevisioniOmonimi"); },
    index() { return context.EM_costruisciIndiceEmail({getProperty: k => props.get(k)}); },
    reg(row = sheet.cells.length, persist = false) {
      return context.EM_leggiRegistrazione_(sheet, context.EM_trovaTabellaDestinazione(sheet),
        row, sheet.cells[row - 1], persist);
    },
    direct() { return context.EM_cercaNomeInIndice_(this.index(), this.reg().nome, this.reg()); }
  };
}
let count = 0;
function test(name, work) {
  try { work(); count++; process.stdout.write("ok " + count + " - " + name + "\n"); }
  catch (e) { process.stderr.write("FAIL - " + name + "\n"); throw e; }
}
function ambiguous(f) {
  assert.equal(f.run().stato, "AMBIGUA");
  assert.equal(f.queue().length, 1);
  assert.equal(f.sheet.cells.at(-1)[3], "");
  assert.equal(f.review().cells[1][2], "DA_REVISIONARE");
}

test("20 days inclusive creates a fresh request, never copies email", () => {
  const f = fixture(); assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
  assert.equal(f.sheet.cells[2][3], ""); assert.equal(f.queue().length, 2);
  assert.equal(f.queue()[1][8], "Mario Rossi"); assert.equal(f.releases, 1);
});
test("same day is included", () => {
  const f = fixture(undefined, account("new", "01/11/2026"));
  assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
});
test("dates may arrive in reverse order", () => {
  const f = fixture(account("old", "21/11/2026", "old@example.test"), account("new"));
  assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
});
test("21 days requires review and one notification across repeated runs", () => {
  const f = fixture(undefined, account("new", "22/11/2026"));
  ambiguous(f); ambiguous(f);
  assert.equal(f.review().cells.length, 2); assert.equal(f.notifications.length, 1);
});
test("missing current username", () => ambiguous(fixture(undefined, account(""))));
test("missing previous username", () => ambiguous(fixture(account("", undefined, "old@example.test"))));
for (const user of ["//", "-", "??", "n/a", "da inserire", "n.d.", "bad user", "username"]) {
  test("unreliable username " + user, () => ambiguous(fixture(undefined, account(user))));
}
test("case and edge spaces do not create a second username", () => {
  ambiguous(fixture(account(" USER.One ", undefined, "old@example.test"), account("user.one")));
});
test("punctuation remains significant in usernames", () => {
  const f = fixture(account("a.b", undefined, "old@example.test"), account("ab"));
  assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
});
for (const date of ["", "31/02/2026", "01/11", "11-01-2026", "2026-11-01", "01/11/2026 12:00"]) {
  test("unknown or invalid date " + date, () => ambiguous(fixture(undefined, account("new", date))));
}
test("invalid previous date", () => ambiguous(fixture(account("old", "bad", "old@example.test"))));
test("leap years parsed strictly", () => {
  const f = fixture(), c = f.context;
  assert.notEqual(c.EM_giornoRegistrazione_("29/02/2024"), null);
  assert.equal(c.EM_giornoRegistrazione_("29/02/2025"), null);
});
test("DST does not change calendar day distance", () => {
  const f = fixture(account("old", "20/03/2026", "old@example.test"), account("new", "09/04/2026"));
  assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
});
test("name normalized with accents, spacing and punctuation", () => {
  const f = fixture(account("old", undefined, "old@example.test", "Màrio  Rossi"),
    account("new", "21/11/2026", "", "MARIO-ROSSI"));
  assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
});
test("different sites retain legacy matching regardless of date", () => {
  const f = fixture(null, account("", ""));
  f.books.get("main").getSheetByName("PokerStars").cells.push(account("new", "", "cross@example.test"));
  assert.equal(f.run().stato, "TROVATA");
  assert.equal(f.sheet.cells[1][3], "cross@example.test");
  assert.equal(f.queue().length, 1);
});
test("known distinct person cannot leak through cross-site alias email", () => {
  const f = fixture();
  f.books.get("main").getSheetByName("PokerStars").cells.push(account("other", "", "old@example.test"));
  assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
  assert.equal(f.sheet.cells[2][3], "");
});
test("same site in an archive also participates", () => {
  const f = fixture(null);
  const main = f.books.get("main").getSheetByName("PokerStars");
  const archive = f.books.get("archive").getSheetByName("PokerStars Old");
  main.cells.push(account("new", "22/11/2026"));
  archive.cells.push(account("old", "01/11/2026", "archive@example.test"));
  assert.equal(f.context.completaEmailRiga("PokerStars", 2).stato, "AMBIGUA");
});
test("site normalization never merges old sheet names", () => {
  const c = fixture().context;
  assert.equal(c.EM_normalizzaSito_(" SISAL  Sport "), c.EM_normalizzaSito_("Sisal Sport"));
  assert.notEqual(c.EM_normalizzaSito_("Sisal Old"), c.EM_normalizzaSito_("Sisal Sport"));
});
test("same name without previous email still blocks ambiguous matching", () => {
  ambiguous(fixture(account("old", "01/10/2026"), account("new")));
});
test("multiple recent distinct usernames create a third email", () => {
  const f = fixture();
  f.sheet.cells.splice(2, 0, account("second", "05/11/2026", "second@example.test"));
  assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
});
test("one old peer wins over recent distinct peers", () => {
  const f = fixture();
  f.sheet.cells.splice(2, 0, account("older", "01/10/2026", "older@example.test"));
  ambiguous(f);
});
test("same row is not compared to itself", () => {
  const f = fixture(null);
  assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
  assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
  assert.equal(f.queue().length, 2);
});
test("correcting a username on the same row requires review, never a new request", () => {
  const f = fixture(null); f.reg(undefined, true);
  f.sheet.cells[1][2] = "corrected";
  ambiguous(f); ambiguous(f);
});
test("corrected source cannot be taken as a second valid account", () => {
  const f = fixture(); f.reg(2, true); f.sheet.cells[1][2] = "corrected";
  ambiguous(f);
});
test("explicit incomplete previous registration requires review", () => {
  const f = fixture();
  f.context.impostaValiditaRegistrazione_("SPREADSHEET_ID", "Sisal Sport", 2, false);
  ambiguous(f);
});
test("explicit incomplete current registration requires review", () => {
  const f = fixture();
  f.context.impostaValiditaRegistrazione_("SPREADSHEET_ID", "Sisal Sport", 3, false);
  ambiguous(f);
});
test("manual NEW persists, queue is idempotent, review resolves", () => {
  const f = fixture(undefined, account("new", "22/11/2026")); ambiguous(f);
  f.context.decidiOmonimo_("Sisal Sport", 3, "NUOVA_MAIL");
  assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
  assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
  assert.equal(f.queue().length, 2); assert.equal(f.review().cells[1][2], "RISOLTA");
});
test("manual email selection persists and is actually written", () => {
  const f = fixture(undefined, account("new", "22/11/2026")); ambiguous(f);
  f.context.decidiOmonimo_("Sisal Sport", 3, "USA_EMAIL", "chosen@example.test");
  assert.equal(f.run().stato, "TROVATA");
  assert.equal(f.sheet.cells[2][3], "chosen@example.test");
  f.sheet.cells[2][3] = "";
  assert.equal(f.run().stato, "TROVATA"); assert.equal(f.queue().length, 1);
});
test("manual selection applies to one registration, not all names", () => {
  const f = fixture(undefined, account("new", "22/11/2026"));
  f.context.decidiOmonimo_("Sisal Sport", 3, "USA_EMAIL", "chosen@example.test");
  f.sheet.cells.push(account("third", "25/12/2026"));
  ambiguous(f);
});
test("new candidate invalidates decision and stays blocked on next run", () => {
  const f = fixture(undefined, account("new", "22/11/2026"));
  f.context.decidiOmonimo_("Sisal Sport", 3, "NUOVA_MAIL");
  f.books.get("main").getSheetByName("PokerStars").cells.push(account("third", "", "third@example.test"));
  ambiguous(f); ambiguous(f);
});
test("an invalidated decision cannot resurrect when candidates revert", () => {
  const f = fixture(undefined, account("new", "22/11/2026"));
  f.context.decidiOmonimo_("Sisal Sport", 3, "NUOVA_MAIL");
  const other = f.books.get("main").getSheetByName("PokerStars");
  other.cells.push(account("third", "", "third@example.test")); ambiguous(f);
  other.cells.pop(); ambiguous(f);
});
test("manual decision survives row insertion with row metadata", () => {
  const f = fixture(undefined, account("new", "22/11/2026"));
  f.context.decidiOmonimo_("Sisal Sport", 3, "NUOVA_MAIL");
  f.sheet.cells.splice(2, 0, account("unrelated", "", "", "Other Person"));
  f.sheet.meta.filter(m => m.row >= 3).forEach(m => m.row++);
  assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
});
test("editing name, username or date invalidates the row decision", () => {
  for (const [col, value] of [[1, "Other Person"], [2, "corrected"], [0, "23/11/2026"]]) {
    const f = fixture(undefined, account("new", "22/11/2026"));
    f.context.decidiOmonimo_("Sisal Sport", 3, "NUOVA_MAIL");
    f.sheet.cells[2][col] = value; ambiguous(f);
  }
});
test("manual acknowledgement allows a corrected row", () => {
  const f = fixture(); f.reg(3, true); f.sheet.cells[2][2] = "corrected"; ambiguous(f);
  f.context.decidiOmonimo_("Sisal Sport", 3, "NUOVA_MAIL");
  assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
});
test("notification failure does not unblock matching; next scan retries", () => {
  const f = fixture(undefined, account("new", "22/11/2026"));
  f.failNotifications(true); ambiguous(f); assert.equal(f.notifications.length, 0);
  f.failNotifications(false); ambiguous(f); assert.equal(f.notifications.length, 1);
});
test("preview produces no mail, queue, metadata, review or Telegram writes", () => {
  const f = fixture(undefined, account("new", "22/11/2026"));
  f.context.testEmailMatcher();
  assert.equal(f.sheet.meta.length, 0); assert.equal(f.queue().length, 1);
  assert.equal(f.sheet.cells[2][3], ""); assert.equal(f.notifications.length, 0);
  assert.equal(f.review(), undefined);
});
test("bulk real path enqueues and follows the same rule", () => {
  const f = fixture(); f.context.cercaEmailMancanti();
  assert.equal(f.queue().length, 2); assert.equal(f.sheet.cells[2][3], "");
});
test("bulk real path blocks and notifies ambiguity", () => {
  const f = fixture(undefined, account("new", "22/11/2026"));
  f.context.cercaEmailMancanti();
  assert.equal(f.queue().length, 1); assert.equal(f.notifications.length, 1);
  assert.equal(f.review().cells[1][2], "DA_REVISIONARE");
});
test("existing email and colored row are preserved", () => {
  const f = fixture(undefined, account("new", undefined, "existing@example.test"));
  assert.equal(f.run().stato, "EMAIL_GIA_PRESENTE");
  f.sheet.cells[2][3] = ""; f.sheet.colors[3] = "#ffeeee";
  assert.equal(f.run().stato, "IGNORATA_COLORE");
  assert.equal(f.queue().length, 1); assert.equal(f.sheet.meta.length, 0);
});
test("missing username column requires review", () => {
  const f = fixture(); f.sheet.cells[0][2] = "Unknown";
  ambiguous(f);
});
test("unrecognized date or status column cannot become registration evidence", () => {
  const f = fixture(); f.sheet.cells[0][0] = "Data di nascita";
  ambiguous(f);
});
test("duplicate username headers are not guessed", () => {
  const f = fixture(); f.sheet.cells[0].push("Username");
  ambiguous(f);
});
test("horizontal tables require review and keep distinct registration identities", () => {
  const f = fixture(null), c = f.context;
  const cells = [
    ["Data apertura", "Nome e Cognome", "Username", "E-mail", "",
     "Data apertura", "Nome e Cognome", "Username", "E-mail"],
    ["01/11/2026", "Mario Rossi", "old", "old@example.test", "",
     "21/11/2026", "Mario Rossi", "new", ""]
  ];
  f.sheet.cells = cells;
  const tables = c.EM_trovaTabelleSorgente(cells);
  assert.equal(tables.length, 2);
  assert.equal(tables[0].usernameCol, null); assert.equal(tables[0].dateCol, null);
  assert.equal(tables[1].usernameCol, null); assert.equal(tables[1].dateCol, null);
  const a = c.EM_leggiRegistrazione_(f.sheet, tables[0], 2, cells[1], true);
  const b = c.EM_leggiRegistrazione_(f.sheet, tables[1], 2, cells[1], true);
  assert.notEqual(a.id, b.id); assert.equal(c.EM_stessaRiga_(a, b), false);
  assert.equal(f.sheet.meta.length, 2);
});
test("malformed metadata fails closed and releases lock", () => {
  const f = fixture(); f.reg(3, true); f.sheet.meta[0].value = "invalid-json";
  assert.throws(() => f.run()); assert.equal(f.queue().length, 1);
  assert.equal(f.releases, 1);
});
test("invalid manual inputs are rejected without queue writes", () => {
  const f = fixture();
  assert.throws(() => f.context.decidiOmonimo_("Sisal Sport", 3, "USA_EMAIL", "bad"));
  assert.throws(() => f.context.decidiOmonimo_("Sisal Sport", 1, "NUOVA_MAIL"));
  assert.throws(() => f.context.impostaValiditaRegistrazione_("SPREADSHEET_ID", "Sisal Sport", 2, "yes"));
  assert.equal(f.queue().length, 1);
});

test("20-day inference is disabled on other configured sites", () => {
  const f = fixture(null);
  for (const name of ["MyLotteriesPlay"]) {
    const sheet = f.books.get("main").getSheetByName(name);
    sheet.cells.push(account("old", "01/11/2026", "old@example.test"), account("new", "21/11/2026"));
    f.context.impostaValiditaRegistrazione_("SPREADSHEET_ID", name, 2, true);
    f.context.impostaValiditaRegistrazione_("SPREADSHEET_ID", name, 3, true);
    assert.equal(f.context.completaEmailRiga(name, 3).stato, "AMBIGUA");
  }
  assert.equal(f.queue().length, 1);
});
test("explicit validity can be restored after an incomplete account is verified", () => {
  const f = fixture();
  f.context.impostaValiditaRegistrazione_("SPREADSHEET_ID", "Sisal Sport", 2, false);
  ambiguous(f);
  f.context.impostaValiditaRegistrazione_("SPREADSHEET_ID", "Sisal Sport", 2, true);
  assert.equal(f.run().stato, "ACCODATA_CREAZIONE");
});
test("manual decisions survive an independent script runtime", () => {
  const first = fixture(undefined, account("new", "22/11/2026"));
  first.context.decidiOmonimo_("Sisal Sport", 3, "NUOVA_MAIL");
  const next = fixture(undefined, account("new", "22/11/2026"));
  next.sheet.meta = first.sheet.meta.map(m => new Metadata(next.sheet, m.row, m.key, m.value));
  assert.equal(next.run().stato, "ACCODATA_CREAZIONE");
  assert.equal(next.queue().length, 2);
});
test("metadata stores signatures instead of account credentials", () => {
  const f = fixture();
  f.context.decidiOmonimo_("Sisal Sport", 3, "NUOVA_MAIL");
  for (const m of f.sheet.meta) {
    assert(!m.value.includes("unused-password"));
    assert(!m.value.includes("Mario Rossi"));
    assert(!m.value.includes("21/11/2026"));
  }
});
test("absence of registration context fails closed", () => {
  const f = fixture();
  assert.equal(f.context.EM_cercaNomeInIndice_(f.index(), "Mario Rossi").stato, "AMBIGUA");
});


for (const name of ["PokerStars"]) {
  test("20-day rule is active on " + name, () => {
    const f = fixture(null);
    const sheet = f.books.get("main").getSheetByName(name);
    sheet.cells.push(account("old", "01/11/2026", "old@example.test"), account("new", "21/11/2026"));
    assert.equal(f.context.completaEmailRiga(name, 3).stato, "ACCODATA_CREAZIONE");
    assert.equal(sheet.cells[2][3], "");
    assert.equal(f.queue().length, 2);
  });
}


test("actual Sisal and PokerStars headers identify date, username and existing ID", () => {
  const c=fixture().context;
  const sisal=["Data Apertura","Chiusura","Diffida","Nome Cognome","Username","Password","E-mail",
    "Password E-mail","Provenienza","Lordo Sport","Pulizia","Netto Sport","Prima Tappa","Seconda Tappa",
    "Terza Tappa","Quarta Tappa","Totale","ID_MULINO"];
  const poker=["Data Apertura","Chiusura","Diffida","Nome Cognome","Username","Password","E-mail",
    "Pass E-mail","Provenienza","Slot","Sport","Poker","Perdita Roulette","Lordo","","ID_MULINO"];
  for (const [row,head,idCol] of [[8,sisal,18],[9,poker,16]]) {
    const values=Array.from({length:row-1},()=>[]).concat([head]);
    const tables=c.EM_trovaTabelleSorgente(values);
    assert.equal(tables.length,1);
    assert.equal(tables[0].headerRow,row);
    assert.equal(tables[0].nameCol,4);assert.equal(tables[0].usernameCol,5);
    assert.equal(tables[0].emailCol,7);assert.equal(tables[0].dateCol,1);
    assert.equal(tables[0].idCol,idCol);
  }
});
test("new request preserves the existing eighteen-column queue schema", () => {
  const f=fixture();f.run();
  assert.equal(f.queue()[0].length,18);assert.equal(f.queue()[0][17],"ID_ACCOUNT");
  assert.equal(f.queue()[1].length,18);
  assert.equal(f.queue()[1][17],f.sheet.cells.at(-1)[6]);
});
test("completed requests remain idempotent through the stable account identifier", () => {
  const f=fixture(), first=f.run();
  f.queue()[1][3]="CREATA";
  const second=f.run();
  assert.equal(second.richiestaId,first.richiestaId);assert.equal(f.queue().length,2);
});
test("moving a queued account reuses the same request by ID_ACCOUNT", () => {
  const f=fixture(), first=f.run();
  f.sheet.cells.splice(2,0,account("unrelated","","","Other Person"));
  f.sheet.meta.filter(m=>m.row>=3).forEach(m=>m.row++);
  assert.equal(f.run().richiestaId,first.richiestaId);assert.equal(f.queue().length,2);
});
test("duplicate existing ID_MULINO fails closed", () => {
  const f=fixture();f.sheet.cells[2][6]=f.sheet.cells[1][6];
  assert.throws(()=>f.run(),/duplicato/);assert.equal(f.queue().length,1);
});
test("existing ID_MULINO is reused without adding an account column", () => {
  const f=fixture(), before=f.sheet.getLastColumn(), id=f.sheet.cells[2][6];
  const reg=f.reg(3,true);
  assert.equal(f.sheet.getLastColumn(),before);assert(reg.id.includes(id));
});
test("a renamed archive can block but never trigger a cross-sheet 20-day inference", () => {
  const f=fixture(null);
  f.books.get("archive").getSheetByName("Sisal Old").cells.push(account("archived","01/11/2026","archived@example.test"));
  ambiguous(f);
});
test("archived source resolver keeps its existing read-only transition fallback", () => {
  const f=fixture(null), archive=f.books.get("archive"), main=f.books.get("main");
  archive.sheets.delete("GoldBet Old");
  const source=main.insertSheet("GoldBet",[headers.slice()]);
  const result=f.context.EM_risolviSorgenteArchiviata_(archive,
    {property:"SPREADSHEET_ID_ARCHIVIO_MATCHED",label:"Archivio Matched"},"GoldBet Old",
    {getProperty:k=>f.props.get(k)},{});
  assert.equal(result.foglio,source);assert.equal(result.legacy,true);
});
test("Snai rule can classify records without activating the archived sheet", () => {
  const f=fixture(null), sheet=f.books.get("archive").getSheetByName("Snai Sport");
  sheet.cells.push(account("old","01/11/2026","old@example.test"),account("new","21/11/2026"));
  const table=f.context.EM_trovaTabellaDestinazione(sheet);
  const reg=f.context.EM_leggiRegistrazione_(sheet,table,3,sheet.cells[2],false);
  assert.equal(f.context.EM_cercaNomeInIndice_(f.index(),reg.nome,reg).stato,"NON TROVATA");
  assert.equal(f.queue().length,1);
});

process.stdout.write(count + " EmailMatcher regression cases passed.\n");
