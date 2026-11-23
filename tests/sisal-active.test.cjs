"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {applySisalActive} = require("../ops/apps-script/banco-sisal-active-patch.cjs");

const source = fs.readFileSync(path.join(__dirname, "../ops/apps-script/banco-sisal-active.gs"), "utf8");
const originHeaders = ["Data Apertura", "Chiusura", "Diffida", "Nome Cognome", "Username", "Password", "E-mail"];
const destinationHeaders = ["Data Apertura", "Tipo", "Diffida", "Nome Cognome", "Username", "Password", "E-mail", "Pass E-mail", "Saldo Attuale", "Saldo in Uscita"];
const sourcePassword = "=example-text";
const emailPassword = "existing-password-cell";
const opened = new Date("2026-11-01T00:00:00.000Z");
const email = "fixture@libero.it";
const event = {
  email, amount_cents: 12456, balance_cents: 199,
  event_id: "1".repeat(64), received_at: "2026-11-24T10:30:00.000Z"
};

function sheet(name, rows, headerRow) {
  const metadata = new Map();
  const colors = new Map();
  const dateFormats = [];
  const copies = [];
  function read(row, column) { return rows[row - 1]?.[column - 1] ?? ""; }
  function write(row, column, value) {
    rows[row - 1] ??= [];
    rows[row - 1][column - 1] = value;
  }
  return {
    name, rows, metadata, colors, dateFormats, copies,
    denyCopy: false,
    getName: () => name,
    getLastRow: () => rows.length,
    getMaxRows: () => 100,
    getMaxColumns: () => 26,
    getRange(row, column, count = 1, width = 1) {
      const wholeRow = typeof row === "string";
      if (wholeRow) {
        const match = /^(\d+):\1$/.exec(row);
        assert(match, "metadata range must be an entire single row");
        row = Number(match[1]);
        column = 1;
        width = 26;
      }
      const cells = transform => Array.from({length: count}, (_, dy) =>
        Array.from({length: width}, (_, dx) => transform(read(row + dy, column + dx))));
      function ensureNoPasswordRead() {
        for (const secretColumn of (name === "Sisal Active" ? [6, 8] : [6])) {
          if (row + count - 1 > headerRow && column <= secretColumn && column + width - 1 >= secretColumn) {
            throw new Error("Private password cell was read");
          }
        }
      }
      const range = {
        row, column, sheet: name,
        getDisplayValue() { return this.getDisplayValues()[0][0]; },
        getDisplayValues() { ensureNoPasswordRead(); return cells(String); },
        getValues() { ensureNoPasswordRead(); return cells(value => value); },
        getBackground() { return colors.get(row) ?? "#ffffff"; },
        isBlank() { return cells(value => value).flat().every(value => value === ""); },
        setValue(value) { return this.setValues([[value]]); },
        setValues(values) {
          assert.equal(name, "Sisal Active");
          assert(column !== 6 && column !== 8, "Bank may not read and serialize passwords");
          values.forEach((line, dy) => line.forEach((value, dx) => write(row + dy, column + dx, value)));
          return this;
        },
        setNumberFormat(format) { dateFormats.push({row, column, format}); return this; },
        copyTo(destination, copyType, transposed) {
          assert.notEqual(name, "Sisal Active");
          assert.equal(column, 6);
          assert.equal(destination.column, 6);
          assert.equal(copyType, "PASTE_VALUES");
          assert.equal(transposed, false);
          if (this.denied) throw new Error(sourcePassword);
          copies.push({from: row, to: destination.row});
          destination.writeCopiedPassword(read(row, column));
        },
        writeCopiedPassword(value) {
          assert.equal(name, "Sisal Active");
          assert.equal(column, 6);
          write(row, column, value);
        },
        getDeveloperMetadata() { return metadata.has(row) ? [metadata.get(row)] : []; },
        addDeveloperMetadata(key, value) {
          assert.equal(column, 1);
          assert(wholeRow, "developer metadata must target an unbounded row range");
          metadata.set(row, {
            getKey: () => key,
            getValue: () => value,
            setValue: next => { value = next; },
            getLocation: () => ({getRow: () => ({getRow: () => row})})
          });
        }
      };
      if (this.denyCopy) range.denied = true;
      return range;
    }
  };
}

function fixture() {
  const sport = sheet("Sisal Sport", [...Array.from({length: 7}, () => []), originHeaders], 8);
  const slot = sheet("Sisal Slot 600", [...Array.from({length: 8}, () => []), originHeaders,
    [opened, "", "Sì", "Test Nome", "00123", sourcePassword, email]], 9);
  const target = sheet("Sisal Active", [destinationHeaders, ["", "", "", "", "", "", "", emailPassword]], 1);
  const sheets = new Map([sport, slot, target].map(item => [item.name, item]));
  let held = false;
  const context = vm.createContext({
    Date,
    PropertiesService: {getScriptProperties: () => ({getProperty: key => key === "SPREADSHEET_ID" && "fixture-id"})},
    SpreadsheetApp: {
      openById: id => { assert.equal(id, "fixture-id"); return {getSheetByName: name => sheets.get(name)}; },
      CopyPasteType: {PASTE_VALUES: "PASTE_VALUES"},
      flush() { assert(held); }
    },
    LockService: {getScriptLock: () => ({
      tryLock() { if (held) return false; held = true; return true; },
      releaseLock() { assert(held); held = false; }
    })},
    ContentService: {
      MimeType: {JSON: "json"},
      createTextOutput: text => ({setMimeType: () => JSON.parse(text)})
    }
  });
  vm.runInContext(source, context);
  return {
    sport, slot, target,
    run: (record = event) => context.bancoRiceviPrelievoSisal_(record),
    busy() { held = true; }
  };
}

{
  const f = fixture();
  assert.deepEqual(f.run(), {ok: true, status: "written", event_id: event.event_id});
  assert.deepEqual(f.target.rows[1], [opened, "Sisal 600", "Si", "Test Nome",
    "00123", sourcePassword, email, emailPassword, 1.99, 124.56]);
  assert.equal(f.target.rows.length, 2, "uses an available row even with password email in H");
  assert.deepEqual(f.target.dateFormats, [{row: 2, column: 1, format: "dd/MM/yyyy"}]);
  assert.equal(f.slot.copies.length, 1);
  const marker = f.target.metadata.get(2).getValue();
  assert(!marker.includes(sourcePassword));
  assert.deepEqual(JSON.parse(marker), {id: event.event_id, at: event.received_at,
    key: JSON.stringify(["sisal 600", "00123"])});

  assert.equal(f.run().status, "duplicate");
  assert.equal(f.slot.copies.length, 1);
  const next = {...event, event_id: "2".repeat(64), received_at: "2026-11-24T12:00:00.000Z",
    amount_cents: 18000, balance_cents: 0};
  assert.equal(f.run(next).status, "written");
  assert.equal(f.run(event).status, "stale");
  assert.equal(f.target.rows.length, 2);
  assert.deepEqual(f.target.rows[1].slice(7), [emailPassword, 0, 180]);
}

{
  const f = fixture();
  f.sport.rows.push([opened, "", "", "Other Test", "othertest", "not-copied", email]);
  assert.equal(f.run().status, "ambiguous");
  assert.equal(f.slot.copies.length, 0);
  f.slot.colors.set(10, "#980000");
  assert.equal(f.run().status, "ambiguous");
  f.slot.rows.pop();
  assert.equal(f.run().status, "written");
  assert.deepEqual(f.target.rows[1].slice(1, 5), ["Sisal Sport", "No", "Other Test", "othertest"]);
}

{
  const f = fixture();
  assert.equal(f.run().status, "written");
  f.target.metadata.get(2).setValue(JSON.stringify({
    id: event.event_id, at: event.received_at, key: "other-account"
  }));
  assert.equal(f.run().status, "error");
  assert.equal(f.slot.copies.length, 1);
}

for (const red of ["#ff0000", "#980000"]) {
  const f = fixture();
  f.slot.colors.set(10, red);
  assert.deepEqual(f.run(), {ok: true, status: "excluded", event_id: event.event_id});
  assert.equal(f.slot.copies.length, 0);
}

{
  const f = fixture();
  assert.equal(f.run({...event, email: "different@libero.it"}).status, "unmatched");
  assert.equal(f.run({...event, email: "fixture@gmail.com"}).status, "invalid");
  assert.equal(f.run({...event, received_at: "2026-02-30T12:00:00.000Z"}).status, "invalid");
  assert.equal(f.run({...event, password: sourcePassword}).status, "invalid");
  assert.equal(f.run({...event, amount_cents: 2.34}).status, "invalid");
  f.busy();
  assert.equal(f.run().status, "busy");
  assert.equal(f.slot.copies.length, 0);
}

{
  const f = fixture();
  f.slot.denyCopy = true;
  assert.deepEqual(f.run(), {ok: false, status: "error", event_id: event.event_id});
  assert.equal(f.target.metadata.size, 0);
  f.slot.denyCopy = false;
  assert.equal(f.run().status, "written", "retry repairs the same row");
  assert.equal(f.target.rows.length, 2);
  assert.equal(f.target.rows[1][5], sourcePassword);
}

const hookFixture = `function doPost(e) {
    if (e.parameter.key !== secret) return rispostaOK();
    const update = JSON.parse(e.postData.contents);
    if (bancoDashboardContext_) {segretarioRiceviUpdate_(update);return rispostaOK();}
    // Authenticated state sync uses the same existing webhook secret.
    return rispostaOK();
}`;
const patched = applySisalActive(hookFixture);
assert.throws(() => applySisalActive(patched), /baseline differs/);
const auth = vm.createContext({
  secret: "test-key", bancoDashboardContext_: false,
  rispostaOK: () => "no operation", segretarioRiceviUpdate_: () => {},
  bancoRiceviPrelievoSisal_: () => "handled"
});
vm.runInContext(patched, auth);
const payload = key => ({parameter: {key}, postData: {contents: JSON.stringify({banco_sisal_withdrawal: event})}});
assert.equal(auth.doPost(payload("invalid")), "no operation");
assert.equal(auth.doPost(payload("test-key")), "handled");
auth.bancoDashboardContext_ = true;
assert.equal(auth.doPost(payload("test-key")), "no operation");
console.log("Sisal Active Banco tests passed");
