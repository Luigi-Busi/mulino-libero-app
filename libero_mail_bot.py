#!/usr/bin/env python3
"""Bot Telegram e worker Playwright per la creazione assistita di Libero Mail.

Il programma:
- legge una coda generata da EmailMatcher in Google Sheets;
- chiede all'amministratore i dati anagrafici reali, senza salvarli;
- compila il modulo Libero in un contesto browser nuovo per ogni richiesta;
- chiede un numero alla whitelist tramite un pulsante nel gruppo;
- accetta l'OTP solo dall'utente che ha preso in carico la richiesta;
- richiede una conferma amministrativa prima dell'invio finale;
- scrive l'e-mail creata nella riga Google Sheets originaria.

Non risolve né aggira CAPTCHA. Quando ne rileva uno, mantiene aperta la
sessione e chiede l'intervento manuale dell'amministratore.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import tempfile
import json
import logging
import os
import random
import re
import secrets
import sqlite3
import sys
import time
import unicodedata
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Optional
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit
from zipfile import ZipFile, ZIP_DEFLATED

import gspread
from browser_diagnostics import BrowserDiagnostics, error_kind
from runtime_health import HealthRequest, RuntimeHealth
from telegram_panel import PanelReply, PanelSessions, ReusablePanel, controls_text, keyboard as panel_keyboard
from dotenv import load_dotenv
from gspread.utils import rowcol_to_a1
from playwright.async_api import (
    Error as PlaywrightError,
    Browser,
    BrowserContext,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("libero-mail-bot")
# httpx registra normalmente l'URL completo delle chiamate Telegram, che contiene
# il token. Il formatter protegge anche gli errori provenienti da altre librerie.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
_SECRET_VALUES: set[str] = set()


def redact_secrets(text: str) -> str:
    for value in sorted(_SECRET_VALUES, key=len, reverse=True):
        if value:
            text = text.replace(value, "[segreto omesso]")
    return re.sub(r"(api\.telegram\.org/bot)[^/\s]+", r"\1[segreto omesso]", text)


class SecretFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


for _handler in logging.getLogger().handlers:
    _handler.setFormatter(SecretFormatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))


QUEUE_HEADERS = [
    "ID_RICHIESTA",
    "CREATA_IL",
    "AGGIORNATA_IL",
    "STATO",
    "SPREADSHEET_DESTINAZIONE",
    "FOGLIO_DESTINAZIONE",
    "RIGA_DESTINAZIONE",
    "COLONNA_EMAIL",
    "NOME_COMPLETO",
    "TELEGRAM_ASSEGNATO",
    "TELEFONO_MASCHERATO",
    "USERNAME_LIBERO",
    "EMAIL_CREATA",
    "TENTATIVI",
    "ERRORE",
    "MESSAGGIO_GRUPPO_ID",
    "NOTE",
]

WHITELIST_HEADERS = ["TELEGRAM_ID", "NUMERO_TELEFONO"]
MANUAL_SHEET = "Richieste Manuali"
MANUAL_HEADERS = ["ID_MULINO", "Nome e Cognome", "Email", "Nome", "Cognome", "Creata il"]
MANUAL_PENDING = "MANUALE_DA_CONFERMARE"

TRANSIENT_STATUSES = {
    "ATTESA_ANAGRAFICA",
    "IN_CREAZIONE",
    "ATTESA_CAPTCHA",
    "ATTESA_UTENTE",
    "ATTESA_CODICE",
    "VERIFICA_CODICE",
    "ATTESA_CONFERMA",
}

FINAL_STATUSES = {"CREATA", "ANNULLATA"}


class ConfigurationError(RuntimeError):
    """Configurazione mancante o non valida."""


class RegistrationError(RuntimeError):
    """Errore gestito durante la registrazione."""


class RegistrationProviderCooldown(RegistrationError):
    def __init__(self, safe_to_retry: bool):
        super().__init__("Libero segnala attività anomala e richiede di attendere alcuni minuti.")
        self.safe_to_retry = safe_to_retry


class RegistrationSessionReset(RegistrationError):
    """Il modulo iniziale è riapparso dopo l'avvio della verifica telefonica."""


class RequestCancelled(RegistrationError):
    """Richiesta annullata dall'amministratore."""


class TesterChangeRequested(Exception):
    """Cambio assegnazione richiesto; gestito nella stessa sessione browser."""


def env_required(name: str, *aliases: str) -> str:
    value = next((os.getenv(key, "").strip() for key in (name, *aliases) if os.getenv(key, "").strip()), "")
    if not value:
        raise ConfigurationError(f"Variabile obbligatoria mancante: {name}")
    return value


def env_int(name: str, *aliases: str) -> int:
    value = env_required(name, *aliases)
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} deve essere un numero intero") from exc


def secret_required(name: str) -> str:
    """Legge prima NAME_FILE; accetta NAME solo per le installazioni precedenti."""
    filename = os.getenv(f"{name}_FILE", "").strip()
    if filename:
        try:
            value = Path(filename).read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeError):
            raise ConfigurationError(f"Impossibile leggere il file per {name}") from None
    else:
        value = os.getenv(name, "")
    if not value:
        raise ConfigurationError(f"Segreto obbligatorio mancante: {name}")
    _SECRET_VALUES.add(value)
    return value


def validate_libero_password(password: str) -> None:
    """Requisiti pubblicati nella pagina di registrazione Libero il 16/09/2026."""
    if not (
        8 <= len(password) <= 20
        and re.search(r"[A-Z]", password)
        and re.search(r"[0-9]", password)
        and any(char in "@.+$-_!" for char in password)
        and "\n" not in password
        and "\r" not in password
    ):
        raise ConfigurationError(
            "Password Libero non conforme: servono 8-20 caratteri, "
            "una maiuscola, un numero e un simbolo fra @ . + $ - _ !. "
            "Modifica soltanto secrets/libero-password."
        )


def now_text() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_ascii(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_phone(value: str) -> str:
    raw = str(value or "").strip()
    plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not digits:
        raise ValueError("numero di telefono vuoto")
    if plus:
        return f"+{digits}"
    if digits.startswith("39") and len(digits) >= 11:
        return f"+{digits}"
    return f"+39{digits}"


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) <= 4:
        return "••••"
    return f"••••••{digits[-4:]}"


def split_name(full_name: str) -> tuple[str, str]:
    parts = normalize_spaces(full_name).split(" ")
    if len(parts) < 2:
        raise ValueError("Nome e Cognome devono contenere almeno due parole")
    return " ".join(parts[:-1]), parts[-1]


def calculate_age(born: date, today: Optional[date] = None) -> int:
    today = today or date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


@dataclass(slots=True)
class Settings:
    telegram_token: str = field(repr=False)
    admin_id: int
    group_chat_id: int
    spreadsheet_id: str
    credentials_file: str
    libero_password: str = field(repr=False)
    registration_url: str
    remote_browser_url: str
    headless: bool
    poll_seconds: int
    data_dir: Path
    queue_sheet: str = "Coda"
    whitelist_sheet: str = "Whitelist"
    anagrafica_group_id: int = 0
    anagrafica_bot_id: int = 0

    @classmethod
    def from_env(cls) -> "Settings":
        headless_raw = os.getenv("HEADLESS", "false").strip().lower()
        try:
            data_group = int(os.getenv("TELEGRAM_ANAGRAFICA_GROUP_ID", "0").strip() or "0")
            data_bot = int(os.getenv("TELEGRAM_ANAGRAFICA_BOT_ID", "0").strip() or "0")
        except ValueError:
            raise ConfigurationError("Gli ID del gruppo anagrafica e dell'Apprendista devono essere numerici") from None
        if (data_group or data_bot) and not (data_group < 0 and data_bot > 0):
            raise ConfigurationError("Configura insieme TELEGRAM_ANAGRAFICA_GROUP_ID (negativo) e TELEGRAM_ANAGRAFICA_BOT_ID (positivo)")
        settings = cls(
            anagrafica_group_id=data_group,
            anagrafica_bot_id=data_bot,
            telegram_token=secret_required("TELEGRAM_BOT_TOKEN"),
            admin_id=env_int("TELEGRAM_ADMIN_ID", "ADMIN_TELEGRAM_ID"),
            group_chat_id=env_int("TELEGRAM_GROUP_ID", "TELEGRAM_GROUP_CHAT_ID"),
            spreadsheet_id=env_required("GOOGLE_SPREADSHEET_ID"),
            credentials_file=env_required("GOOGLE_SERVICE_ACCOUNT_FILE"),
            libero_password=secret_required("LIBERO_PASSWORD"),
            registration_url=os.getenv(
                "LIBERO_REGISTRATION_URL", "https://registrazione.libero.it/"
            ).strip(),
            remote_browser_url=os.getenv("REMOTE_BROWSER_URL", "").strip(),
            headless=headless_raw in {"1", "true", "yes", "si", "sì"},
            poll_seconds=max(5, int(os.getenv("POLL_SECONDS", "10"))),
            data_dir=Path(os.getenv("DATA_DIR", "/data")).resolve(),
            queue_sheet=os.getenv("GOOGLE_QUEUE_SHEET", "Coda").strip(),
            whitelist_sheet=os.getenv("GOOGLE_WHITELIST_SHEET", "Whitelist").strip(),
        )
        validate_libero_password(settings.libero_password)
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", settings.telegram_token):
            raise ConfigurationError("Il file del token Telegram non contiene un token nel formato previsto")
        if settings.admin_id <= 0 or settings.group_chat_id >= 0:
            raise ConfigurationError("Controlla TELEGRAM_ADMIN_ID e TELEGRAM_GROUP_ID")
        if not settings.queue_sheet or not settings.whitelist_sheet:
            raise ConfigurationError("Nomi delle schede Google mancanti")
        if not Path(settings.credentials_file).is_file():
            raise ConfigurationError(
                f"File credenziali Google non trovato: {settings.credentials_file}"
            )
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        return settings


@dataclass(slots=True)
class QueueRequest:
    row: int
    request_id: str
    status: str
    destination_spreadsheet: str
    destination_sheet: str
    destination_row: int
    email_column: int
    full_name: str
    claimed_by: str = ""
    group_message_id: str = ""
    account_id: str = ""


@dataclass(slots=True)
class PersonalData:
    first_name: str
    last_name: str
    birth_date: str
    gender: str
    city: str


class GoogleQueueStore:
    """Accesso sincrono a Sheets, chiamato tramite asyncio.to_thread."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = gspread.service_account(
            filename=settings.credentials_file,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        self._header_index = {name: index + 1 for index, name in enumerate(QUEUE_HEADERS)}

    def __getattr__(self, name: str) -> Any:
        if name not in {"book", "queue", "whitelist"}:
            raise AttributeError(name)
        book = self.client.open_by_key(self.settings.spreadsheet_id)
        queue = book.worksheet(self.settings.queue_sheet)
        whitelist = book.worksheet(self.settings.whitelist_sheet)
        self._validate_headers(queue, QUEUE_HEADERS)
        self._validate_headers(whitelist, WHITELIST_HEADERS)
        self.book, self.queue, self.whitelist = book, queue, whitelist
        return self.__dict__[name]

    @staticmethod
    def _validate_headers(sheet: gspread.Worksheet, expected: list[str]) -> None:
        actual = [str(value).strip() for value in sheet.row_values(1)[: len(expected)]]
        if actual != expected:
            raise ConfigurationError(
                f'Intestazioni non valide nel foglio "{sheet.title}". '
                "Esegui inizializzaSistemaCreazioneMail() in Apps Script."
            )

    def _read_requests(self) -> list[QueueRequest]:
        records, malformed = audit_queue_records(self.queue.get_all_values())
        for row in malformed:
            LOGGER.error("Riga coda %s non valida", row)
        return [request for request, _, _ in records]

    def next_request(self) -> Optional[QueueRequest]:
        for request in self._read_requests():
            if request.status == "DA_COMPLETARE_ANAGRAFICA":
                return request
        return None

    def find_request(self, request_id: str) -> Optional[QueueRequest]:
        matches = [r for r in self._read_requests() if r.request_id == request_id]
        if len(matches) > 1:
            raise RegistrationError("ID richiesta duplicato in Coda: nessuna modifica.")
        return matches[0] if matches else None

    def manual_sheet(self) -> gspread.Worksheet:
        """Use the existing queue book; never repair an occupied unrelated tab."""
        try:
            sheet = self.book.worksheet(MANUAL_SHEET)
        except gspread.WorksheetNotFound:
            sheet = self.book.add_worksheet(title=MANUAL_SHEET, rows=100, cols=len(MANUAL_HEADERS))
        values = sheet.get_all_values()
        if not any(str(value).strip() for row in values for value in row):
            sheet.update(range_name="A1:F1", values=[MANUAL_HEADERS], value_input_option="RAW")
        self._validate_headers(sheet, MANUAL_HEADERS)
        return sheet

    def manual_name_parts(self, request: QueueRequest) -> tuple[str, str]:
        if not is_manual_request(request, self.settings.spreadsheet_id):
            raise RegistrationError("La richiesta non appartiene allo storico manuale.")
        sheet = self.book.worksheet(MANUAL_SHEET)
        self._validate_headers(sheet, MANUAL_HEADERS)
        values = sheet.get_all_values()
        row, _, _, _ = resolve_account_target(request, values)
        first, last = parse_manual_name(audit_cell(values, row, 4) + " | " + audit_cell(values, row, 5))
        if audit_normalize(first + " " + last) != audit_normalize(request.full_name):
            raise RegistrationError("Nome e cognome dello storico manuale sono cambiati: richiesta bloccata.")
        return first, last

    def create_manual_request(self, first: str, last: str) -> tuple[QueueRequest, str, bool]:
        first, last = parse_manual_name(first + " | " + last)
        full_name = first + " " + last
        rows = self.queue.get_all_values()
        records, malformed = audit_queue_records(rows)
        if malformed:
            raise RegistrationError("Coda incompleta: usa /controlla prima di aggiungere richieste.")
        if sum(str(x).strip() == "ID_ACCOUNT" for x in rows[0]) != 1:
            raise RegistrationError("Colonna ID_ACCOUNT mancante o duplicata: nessun accodamento.")
        same = [(r, email) for r, email, _ in records
                if audit_normalize(r.full_name) == audit_normalize(full_name)]
        if len(same) > 1:
            raise RegistrationError("Esistono più richieste per questo nominativo. Verifica /recupera o /controlla.")
        rid = str(uuid.uuid5(uuid.NAMESPACE_URL,
            "mulino-manual:" + self.settings.spreadsheet_id + ":" + audit_normalize(full_name)))
        if same:
            request, email = same[0]
            if request.status != MANUAL_PENDING:
                return request, email, False
            if (request.request_id != rid or request.account_id != rid
                    or not is_manual_request(request, self.settings.spreadsheet_id)):
                raise RegistrationError("Richiesta manuale incompleta o modificata: nessun nuovo tentativo.")
            if self.manual_name_parts(request) != (first, last):
                raise RegistrationError("La separazione Nome/Cognome differisce dalla richiesta precedente.")
        else:
            sheet = self.manual_sheet()
            values = sheet.get_all_values()
            targets = [i for i in range(2, len(values) + 1) if audit_cell(values, i, 1) == rid]
            if len(targets) > 1:
                raise RegistrationError("Identificativo duplicato nello storico manuale: nessun accodamento.")
            if not targets:
                sheet.append_row([rid, full_name, "", first, last, now_text()], value_input_option="RAW")
                values = sheet.get_all_values()
                targets = [i for i in range(2, len(values) + 1) if audit_cell(values, i, 1) == rid]
            if len(targets) != 1:
                raise RegistrationError("Salvataggio dello storico non confermato. Ripeti lo stesso comando per ricontrollare.")
            target = targets[0]
            if (audit_cell(values, target, 2) != full_name
                    or audit_cell(values, target, 4) != first or audit_cell(values, target, 5) != last
                    or audit_cell(values, target, 3)):
                raise RegistrationError("Lo storico contiene dati diversi o una mail già presente. Verifica prima di riprovare.")
            fields = dict(ID_RICHIESTA=rid, CREATA_IL=now_text(), AGGIORNATA_IL=now_text(),
                STATO=MANUAL_PENDING, SPREADSHEET_DESTINAZIONE=self.settings.spreadsheet_id,
                FOGLIO_DESTINAZIONE=MANUAL_SHEET, RIGA_DESTINAZIONE=target,
                COLONNA_EMAIL=3, NOME_COMPLETO=full_name, ID_ACCOUNT=rid,
                TENTATIVI=0, NOTE="Richiesta manuale dell'amministratore; accodamento da confermare")
            # Prima riserva una riga non eseguibile. Un append dall'esito incerto
            # non può avviare il browser né essere ripetuto automaticamente.
            self.queue.append_row([fields.get(str(header).strip(), "") for header in rows[0]],
                value_input_option="RAW")
            request = self.find_request(rid)
            if request is None:
                raise RegistrationError("Accodamento non confermato: ripeti lo stesso comando per ricontrollare.")
        self.validate_start(request)
        self.update(request, STATO="DA_COMPLETARE_ANAGRAFICA", NOTE="Richiesta manuale dell'amministratore")
        return request, "", True

    def update(self, request: QueueRequest, **fields: Any) -> None:
        current = self.find_request(request.request_id)
        if (not current or not compatible_destination(request, current)
                or audit_normalize(current.full_name) != audit_normalize(request.full_name)):
            raise RegistrationError("Richiesta spostata o modificata in Coda: aggiornamento bloccato.")
        request.row = current.row  # Anche Coda puo essere ordinata: usa sempre ID_RICHIESTA.
        fields = {**fields, "AGGIORNATA_IL": now_text()}
        updates = []
        for header, value in fields.items():
            if header not in self._header_index:
                raise KeyError(f"Colonna coda sconosciuta: {header}")
            cell = rowcol_to_a1(request.row, self._header_index[header])
            updates.append({"range": cell, "values": [[value]]})
        self.queue.batch_update(updates, value_input_option="RAW")
        if "STATO" in fields:
            request.status = str(fields["STATO"])
        if "TELEGRAM_ASSEGNATO" in fields:
            request.claimed_by = str(fields["TELEGRAM_ASSEGNATO"])
        if "MESSAGGIO_GRUPPO_ID" in fields:
            request.group_message_id = str(fields["MESSAGGIO_GRUPPO_ID"])

    def whitelist_map(self) -> dict[int, str]:
        rows = self.whitelist.get_all_values()[1:]
        result: dict[int, str] = {}
        for row in rows:
            if len(row) < 2:
                continue
            telegram_id = str(row[0]).strip()
            phone = str(row[1]).strip()
            if not telegram_id or not phone:
                continue
            try:
                result[int(telegram_id)] = normalize_phone(phone)
            except (ValueError, TypeError):
                LOGGER.error("Voce whitelist non valida per Telegram ID %s", telegram_id)
        return result

    def write_created_email(
        self, request: QueueRequest, email: str, username: str
    ) -> None:
        # Ricontrolla anche Coda: la richiesta in memoria puo precedere un ordinamento.
        self.validate_audit_restore(request, email)
        worksheet = self.client.open_by_key(request.destination_spreadsheet).worksheet(request.destination_sheet)
        values = worksheet.get_all_values()
        row, column, name_column, id_column = resolve_account_target(request, values)
        latest = worksheet.row_values(row)
        if (audit_normalize(audit_cell([latest], 1, name_column)) != audit_normalize(request.full_name)
                or (request.account_id and audit_cell([latest], 1, id_column) != request.account_id)):
            raise RegistrationError("La riga e cambiata durante il salvataggio: nessuna scrittura.")
        current = audit_cell([latest], 1, column)
        if not audit_email_writable(current, email):
            raise RegistrationError("La cella email contiene un valore diverso: nessuna sovrascrittura.")
        worksheet.update_cell(row, column, email)
        # Prima aggiorna usando la vecchia identita legacy; poi aggiorna i riferimenti in memoria.
        self.update(request, STATO="CREATA", USERNAME_LIBERO=username, EMAIL_CREATA=email,
            RIGA_DESTINAZIONE=row, COLONNA_EMAIL=column, ERRORE="",
            NOTE="E-mail scritta nella riga identificata dell'account")
        request.destination_row, request.email_column = row, column

    def consistency_snapshot(self) -> dict[str, Any]:
        records, malformed = audit_queue_records(self.queue.get_all_values())
        active_sheets = {"PokerStars", "Sisal Sport", "GoldBet", "MyLotteriesPlay"}
        books = {r.destination_spreadsheet for r, _, _ in records if r.destination_sheet in active_sheets}
        keys = {(r.destination_spreadsheet, r.destination_sheet) for r, _, _ in records}
        keys.update((book, name) for book in books for name in active_sheets)
        clients, tables = {}, {}
        for book_id, name in sorted(keys):
            try:
                if book_id not in clients:
                    clients[book_id] = self.client.open_by_key(book_id)
                values = clients[book_id].worksheet(name).get_all_values()
                layout = audit_layout(values)
                tables[(book_id, name)] = {"values": values, "layout": layout}
            except Exception as exc:
                tables[(book_id, name)] = {"error": type(exc).__name__}
        return {"records": records, "malformed": malformed, "tables": tables,
                "scan_keys": {(b, n) for b in books for n in active_sheets}}

    def validate_audit_restore(self, request: QueueRequest, email: str) -> None:
        # Rilettura al clic: il rapporto precedente non autorizza una scrittura cieca.
        rows = self.queue.get_all_values()
        records, malformed = audit_queue_records(rows)
        matches = [(r, email, username) for r, email, username in records if r.request_id == request.request_id]
        destinations = [r for r, _, _ in records if account_target_key(r) == account_target_key(request)]
        if malformed:
            raise RegistrationError("Ci sono righe Coda incomplete: correggile e ripeti /controlla.")
        if len(matches) != 1 or len(destinations) != 1 or recovery_signature(matches[0][0]) != recovery_signature(request):
            raise RegistrationError("Richiesta duplicata o modificata: ripeti /controlla.")
        _, queued_email, username = matches[0]
        if ((queued_email and queued_email.lower() != email.lower())
                or (username and username.lower() + "@libero.it" != email.lower())):
            raise RegistrationError("L'indirizzo in Coda differisce dal registro VPS: ripristino bloccato.")
        sheet = self.client.open_by_key(request.destination_spreadsheet).worksheet(request.destination_sheet)
        values = sheet.get_all_values()
        row, email_col, _, _ = resolve_account_target(request, values)
        for other, _, _ in records:
            if (other.request_id == request.request_id or
                    (other.destination_spreadsheet, other.destination_sheet) !=
                    (request.destination_spreadsheet, request.destination_sheet)):
                continue
            try:
                other_row, _, _, _ = resolve_account_target(other, values)
            except RegistrationError:
                continue
            if other_row == row:
                raise RegistrationError("Piu richieste puntano allo stesso account: ripristino bloccato.")
        current = audit_cell(values, row, email_col)
        if not audit_email_writable(current, email):
            raise RegistrationError("La riga contiene un valore diverso: ripristino bloccato.")

    def validate_start(self, request: QueueRequest) -> None:
        self.validate_audit_restore(request, "")

    def recover_interrupted(self, skip_ids: Any = ()) -> int:
        recovered = 0
        for request in self._read_requests():
            if request.status in TRANSIENT_STATUSES and request.request_id not in skip_ids:
                self.update(
                    request,
                    STATO="ERRORE",
                    ERRORE="Server riavviato durante la registrazione",
                    NOTE="Controllare l'eventuale account parziale, poi usare /riprova",
                )
                recovered += 1
        return recovered

    def existing_created_details(self, request_id: str) -> tuple[QueueRequest, str, str]:
        request = self.find_request(request_id)
        if not request or request.status not in {"ERRORE", "ANNULLATA"}:
            raise RegistrationError("Serve una richiesta esistente in stato ERRORE o ANNULLATA.")
        username = str(self.queue.cell(
            request.row, self._header_index["USERNAME_LIBERO"]
        ).value or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", username):
            raise RegistrationError("Username mancante o non valido nella coda: nessuna modifica.")
        email = username + "@libero.it"
        return request, username, email

    def confirm_existing_created(self, request_id: str) -> str:
        request, username, email = self.existing_created_details(request_id)
        self.write_created_email(request, email, username)
        return email

    def retry(self, request_id: str) -> bool:
        request = self.find_request(request_id)
        if not request or request.status not in ({"ERRORE", "ANNULLATA"} | TRANSIENT_STATUSES):
            return False
        self.update(
            request,
            STATO="DA_COMPLETARE_ANAGRAFICA",
            TELEGRAM_ASSEGNATO="",
            TELEFONO_MASCHERATO="",
            USERNAME_LIBERO="",
            ERRORE="",
            MESSAGGIO_GRUPPO_ID="",
            NOTE="Riavviata dall'amministratore",
        )
        return True


def is_manual_request(request: QueueRequest, book_id: str) -> bool:
    return request.destination_sheet == MANUAL_SHEET and request.destination_spreadsheet == book_id


def parse_manual_name(text: str) -> tuple[str, str]:
    if len(text) > 200 or any(ord(x) < 32 or ord(x) == 127 for x in text):
        raise ValueError("Nome non valido. Usa /creamail Nome | Cognome.")
    parts = text.split("|") if "|" in text else text.split()
    if len(parts) != 2:
        raise ValueError("Usa /creamail Nome | Cognome. Per nomi composti il separatore | è necessario.")
    first, last = (normalize_spaces(x) for x in parts)
    for value in (first, last):
        if (not value or len(value) > 80 or not any(x.isalpha() for x in value)
                or any(not (x.isalpha() or x in " '-.’" or unicodedata.category(x).startswith("M")) for x in value)):
            raise ValueError("Nome e cognome devono contenere lettere, spazi, apostrofi o trattini.")
    return first, last


def parse_personal_data(text: str, full_name: str, *, name_parts: Optional[tuple[str, str]] = None) -> PersonalData:
    parts = [normalize_spaces(part) for part in text.split("|")]
    if len(parts) == 3:
        first_name, last_name = name_parts or split_name(full_name)
        birth_text, gender_text, city_text = parts
    elif len(parts) == 5:
        first_name, last_name, birth_text, gender_text, city_text = parts
    else:
        raise ValueError(
            "Usa: GG/MM/AAAA | M/F | Città (PR). "
            "Per correggere il nome: Nome | Cognome | GG/MM/AAAA | M/F | Città (PR)."
        )

    if not first_name or not last_name:
        raise ValueError("Nome e cognome non possono essere vuoti")

    try:
        born = datetime.strptime(birth_text, "%d/%m/%Y").date()
    except ValueError as exc:
        raise ValueError("Data non valida: usa il formato GG/MM/AAAA") from exc

    age = calculate_age(born)
    if age < 18:
        raise ValueError(
            "La procedura automatica gestisce soltanto maggiorenni. "
            "Per un minore serve la registrazione manuale con consenso del responsabile."
        )
    if age > 110:
        raise ValueError("Data di nascita non plausibile")

    gender = gender_text.strip().upper()
    if gender not in {"M", "F"}:
        raise ValueError("Il genere deve essere M oppure F")

    if len(city_text) < 2:
        raise ValueError("Città di residenza mancante")

    return PersonalData(
        first_name=first_name,
        last_name=last_name,
        birth_date=born.strftime("%d/%m/%Y"),
        gender=gender,
        city=city_text,
    )


def username_candidates(first_name: str, last_name: str) -> list[str]:
    first = re.sub(r"[^a-z0-9]", "", normalize_ascii(first_name).lower())
    last = re.sub(r"[^a-z0-9]", "", normalize_ascii(last_name).lower())
    if not first or not last:
        raise RegistrationError("Nome o cognome non utilizzabile per creare lo username")

    bases = [
        f"{first}.{last}",
        f"{first}{last}",
        f"{first[0]}{last}",
        f"{last}.{first}",
    ]
    candidates: list[str] = []
    for base in bases:
        clean = base.strip("._-")[:20]
        if len(clean) >= 6 and clean not in candidates:
            candidates.append(clean)

    for _ in range(12):
        suffix = str(secrets.randbelow(9000) + 1000)
        base = random.choice(bases).strip("._-")
        clean = f"{base[: 20 - len(suffix)]}{suffix}".strip("._-")
        if len(clean) >= 6 and clean not in candidates:
            candidates.append(clean)
    return candidates


def recovery_email_candidate(personal: PersonalData) -> str:
    first = re.sub(r"[^a-z0-9]", "", normalize_ascii(personal.first_name).lower())
    last = re.sub(r"[^a-z0-9]", "", normalize_ascii(personal.last_name).lower())
    if not first or not last:
        raise RegistrationError("Nome o cognome non utilizzabile per il contatto di recupero")
    # Compila il recapito nel formato configurato; non crea una casella Gmail.
    return f"{first}{last}{secrets.randbelow(1000):03d}@gmail.com"


class RegistrationBrowser:
    def __init__(self, settings: Settings, coordinator: "Coordinator") -> None:
        self.settings = settings
        self.coordinator = coordinator
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.stage = "avvio del browser"
        self.expected_email: Optional[str] = None
        self.phone_verification_started = False
        self.diagnostics: Optional[BrowserDiagnostics] = None

    @property
    def stage(self) -> str:
        return self._stage

    @stage.setter
    def stage(self, value: str) -> None:
        self._stage = value
        if getattr(self, "diagnostics", None):
            self.diagnostics.set_phase(value)

    async def _cleanup_browser(self) -> None:
        # Retain the original failure even when an already closed target rejects
        # cleanup. Close the context before the browser, with bounded waits.
        for component, target, method in (
            ("cookies", self.context, "clear_cookies"),
            ("context", self.context, "close"),
            ("browser", self.browser, "close"),
        ):
            if target is None:
                continue
            try:
                await asyncio.wait_for(getattr(target, method)(), timeout=5)
            except Exception as exc:
                self.diagnostics.emit("cleanup_error", component=component, error=error_kind(exc))

    async def create_account(
        self, request: QueueRequest, personal: PersonalData
    ) -> tuple[str, str]:
        self.diagnostics = BrowserDiagnostics(request.request_id)
        self.diagnostics.emit("session_start")
        reason = "error"
        try:
            async with async_playwright() as playwright:
                try:
                    self.browser = await playwright.chromium.launch(
                        headless=self.settings.headless,
                        args=["--disable-dev-shm-usage", "--no-sandbox"],
                    )
                    self.diagnostics.attach_browser(self.browser)
                    self.context = await self.browser.new_context(
                        locale="it-IT",
                        timezone_id="Europe/Rome",
                        viewport={"width": 1365, "height": 900},
                    )
                    self.diagnostics.attach_context(self.context)
                    self.page = await self.context.new_page()
                    self.diagnostics.attach_page(self.page)
                    self.coordinator.monitor_browser = self
                    self.stage = "apertura della pagina Libero"
                    await self.page.goto(
                        self.settings.registration_url,
                        wait_until="domcontentloaded",
                        timeout=45_000,
                    )
                    self.stage = "gestione del banner cookie"
                    await self._dismiss_cookie_banner()
                    username = await self._fill_credentials(request, personal)
                    await self._fill_personal_data(request, personal)
                    await self._complete_remaining_steps(request, username, personal)
                    self.coordinator.record_created(request, username, f"{username}@libero.it")
                    reason = "completed"
                    return username, f"{username}@libero.it"
                except BaseException as exc:
                    if isinstance(exc, (RegistrationSessionReset, RegistrationProviderCooldown)):
                        self.coordinator.invalidate_phone_session()
                    self.diagnostics.failure(exc)
                    reason = self.diagnostics.reason
                    if isinstance(exc, PlaywrightTimeoutError):
                        raise RegistrationError(f"Tempo scaduto durante: {self.stage}.") from None
                    raise
                finally:
                    self.coordinator.monitor_browser = None
                    self.diagnostics.begin_cleanup(reason)
                    await self._cleanup_browser()
        except BaseException as exc:
            if not self.diagnostics.failure_seen:
                self.diagnostics.failure(exc, component="driver")
                reason = self.diagnostics.reason
            raise
        finally:
            self.diagnostics.reason = reason
            self.diagnostics.emit("session_end")

    async def _dismiss_cookie_banner(self) -> None:
        assert self.page
        buttons = [
            "Installa solo i cookie strettamente necessari",
            "Continua senza accettare",
            "Accetta e Chiudi",
        ]
        for label in buttons:
            # Il banner può essere in un iframe e usare testo in maiuscolo.
            for frame in self.page.frames:
                locator = frame.get_by_role(
                    "button", name=re.compile(rf"^{re.escape(label)}$", re.IGNORECASE)
                )
                for button in await locator.all():
                    try:
                        if await button.is_visible():
                            await button.click(timeout=2_000)
                            await self.page.wait_for_timeout(500)
                            return
                    except PlaywrightTimeoutError:
                        continue

    async def _fill_credentials(
        self, request: QueueRequest, personal: PersonalData
    ) -> str:
        assert self.page
        self.stage = "ricerca del campo nome utente"
        username_input = self.page.locator("#username")
        password_input = self.page.locator("#password")
        await username_input.wait_for(state="visible", timeout=15_000)

        for candidate in username_candidates(personal.first_name, personal.last_name):
            await self._check_cancelled()
            self.stage = "verifica della disponibilità del nome utente"
            await username_input.fill(candidate)
            await username_input.press("Tab")
            await self.page.wait_for_timeout(1_300)
            await self._handle_captcha_if_needed(request)
            if await self._username_unavailable():
                continue

            self.stage = "compilazione della password"
            await password_input.fill(self.settings.libero_password)
            await self._handle_captcha_if_needed(request)
            # Il controllo definitivo puo arrivare solo dopo Avanti/CAPTCHA.
            # Non considerare scelto il candidato finche non si apre l'anagrafica.
            if not await self._open_personal_data_page(request):
                continue
            await self.coordinator.set_queue_fields(
                request, USERNAME_LIBERO=candidate, STATO="IN_CREAZIONE"
            )
            return candidate

        raise RegistrationError("Non ho trovato uno username Libero disponibile dopo i tentativi previsti.")

    async def _username_unavailable(self) -> bool:
        assert self.page
        # Un avviso nascosto o appartenente a un passaggio precedente non vale.
        if not await self.page.locator("#username").is_visible():
            return False
        error = self.page.locator("#username_error")
        if await error.count() and await error.is_visible():
            text = normalize_spaces(await error.inner_text()).lower()
            if re.search(r"gi[àa] in uso|esiste gi[àa]|non (?:è |e' |e’ )?disponibile", text):
                return True
        # Libero puo mostrare l'avviso insieme ai suggerimenti, fuori da username_error.
        body = normalize_spaces(await self.page.locator("body").inner_text()).lower()
        return bool(re.search(
            r"(?:nome utente|username|indirizzo (?:e-mail|email))\s*"
            r"(?:(?:è|e'|e’)\s+)?(?:gi[àa] in uso|non (?:è |e' |e’ )?disponibile|esiste gi[àa])",
            body,
        ))

    async def _initial_page_outcome_ready(self) -> bool:
        return await self._personal_data_page_ready() or await self._username_unavailable()

    async def _personal_data_page_ready(self) -> bool:
        assert self.page
        try:
            await self.page.locator("#firstname").wait_for(state="visible", timeout=2_000)
        except PlaywrightTimeoutError:
            return False
        return await self.page.locator("#lastname").is_visible()

    async def _initial_captcha_advance_ready(
        self, starting_url: str, expected_username: str, expected_password: str
    ) -> bool:
        """Only advance the initial form after an observed human CAPTCHA completion."""
        assert self.page
        await self._check_cancelled()
        await self._raise_if_provider_blocked()
        before, after = urlsplit(starting_url), urlsplit(self.page.url)
        if (after.scheme != "https" or after.hostname != "registrazione.libero.it"
                or (before.hostname, before.path) != (after.hostname, after.path)):
            return False
        if await self._personal_data_page_ready() or await self._username_unavailable():
            return False
        username, password = self.page.locator("#username"), self.page.locator("#password")
        if (not await username.is_visible() or not await password.is_visible()
                or not expected_username or not expected_password
                or await username.input_value() != expected_username
                or await password.input_value() != expected_password
                or not await self._captcha_completed()):
            return False
        buttons = self.page.get_by_role("button", name=re.compile(r"^(?:Avanti|Continua)$", re.I))
        if await buttons.count() != 1:
            return False
        button = buttons.first
        if (await button.get_attribute("id") != "button_submit"
                or not await button.is_visible() or not await button.is_enabled()):
            return False
        try:
            await button.click(trial=True, timeout=1_000)
        except PlaywrightTimeoutError:
            return False
        return True

    async def _open_personal_data_page(self, request: QueueRequest) -> bool:
        assert self.page
        starting_url = self.page.url
        expected_username = await self.page.locator("#username").input_value()
        expected_password = await self.page.locator("#password").input_value()
        captcha_was_complete = await self._captcha_completed()
        auto_advanced = False
        self.stage = "gestione dei cookie prima del passaggio alle informazioni personali"
        await self._dismiss_cookie_banner()
        self.stage = "passaggio alle informazioni personali"
        try:
            await self._click_and_wait_for_change("#button_submit")
        except PlaywrightTimeoutError:
            pass  # Banner o CAPTCHA: conservare la sessione per l'intervento umano.

        async def initial_ready() -> bool:
            nonlocal auto_advanced
            await self._check_cancelled()
            if await self._initial_page_outcome_ready():
                return True
            if (not captcha_was_complete and not auto_advanced
                    and await self._initial_captcha_advance_ready(
                        starting_url, expected_username, expected_password)):
                # Mark before the click: an uncertain response must never repeat it.
                auto_advanced = True
                await self._check_cancelled()
                self.stage = "Avanti dopo il CAPTCHA completato manualmente"
                try:
                    await self._click_and_wait_for_change("#button_submit")
                except PlaywrightTimeoutError:
                    pass
                return await self._initial_page_outcome_ready()
            return False

        while not await self._personal_data_page_ready():
            await self._check_cancelled()
            if await self._username_unavailable():
                return False
            self.stage = "attesa intervento manuale su cookie o CAPTCHA della prima pagina"
            await self.coordinator.wait_for_manual_captcha(
                request,
                instructions=(
                    "🧩 Libero è ancora al primo passaggio. Il browser resta aperto.\n\n"
                    "Nel browser remoto gestisci il banner cookie e risolvi l'eventuale CAPTCHA. "
                    "Quando ne rilevo il completamento premo Avanti una volta, se l'username "
                    "è valido e i campi iniziali non sono cambiati.\n\n"
                    "Non modificare manualmente il nome utente: se occupato, "
                    "provo automaticamente un’alternativa @libero.it. "
                    "Quando compaiono Nome e Cognome riprendo automaticamente: "
                    "non serve confermare su Telegram. "
                    "Se resto in attesa o non riesco a premere Avanti, puoi premerlo nel browser. "
                    "Se il sito mostra un errore, mandane uno screenshot all'assistente. "
                    "Puoi interrompere la richiesta con /annulla."
                ),
                ready_check=initial_ready,
            )
            await self._check_cancelled()
            await self.coordinator.set_queue_fields(
                request, STATO="IN_CREAZIONE", NOTE="Verifica del passaggio completato manualmente"
            )
        return True

    async def _fill_personal_data(
        self, request: QueueRequest, personal: PersonalData
    ) -> None:
        assert self.page
        self.stage = "verifica di sicurezza prima dei dati anagrafici"
        await self._handle_captcha_if_needed(request)
        self.stage = "compilazione del nome"
        await self.page.locator("#firstname").fill(personal.first_name)
        self.stage = "compilazione del cognome"
        await self.page.locator("#lastname").fill(personal.last_name)
        self.stage = "compilazione della data di nascita"
        birth = self.page.locator("#dateofbirth")
        birth_type = (await birth.get_attribute("type") or "text").lower()
        birth_value = personal.birth_date
        if birth_type == "date":
            birth_value = datetime.strptime(personal.birth_date, "%d/%m/%Y").strftime("%Y-%m-%d")
        await birth.fill(birth_value)
        # Completa la modifica del campo prima di interagire con il selettore.
        await birth.press("Tab")

        self.stage = "selezione del genere"
        await self._select_gender(personal.gender)

        self.stage = "compilazione del comune di residenza"
        city = self.page.locator("#comune_provincia")
        await city.fill(personal.city)
        await self.page.wait_for_timeout(1_000)
        self.stage = "selezione del comune nell'elenco dei suggerimenti"
        suggestions = self.page.locator(".mdb-autocomplete-wrap li:visible")
        if await suggestions.count():
            wanted = suggestions.filter(has_text=personal.city).first
            if await wanted.count():
                await wanted.click()
            else:
                await suggestions.first.click()
        else:
            await city.press("ArrowDown")
            await city.press("Enter")

        await self._handle_captcha_if_needed(request)
        self.stage = "pulsante Avanti delle informazioni personali"
        await self._click_and_wait_for_change("#button_submit")

    async def _select_gender(self, gender: str) -> None:
        """Seleziona l'etichetta visibile dei radio personalizzati, se presente."""
        assert self.page
        field_id = "male" if gender == "M" else "female"
        radio = self.page.locator(f"#{field_id}")
        await radio.wait_for(state="attached", timeout=15_000)
        if await radio.is_checked():
            return

        labels = [
            self.page.locator(f'label[for="{field_id}"]'),
            radio.locator("xpath=ancestor::label[1]"),
        ]
        clicked_label = False
        for label in labels:
            if await label.count() and await label.first.is_visible():
                await label.first.click()
                clicked_label = True
                break
        if not clicked_label:
            await radio.check()

        if not await radio.is_checked():
            raise RegistrationError(
                "Il selettore del genere non ha confermato la scelta."
            )

    async def _complete_remaining_steps(
        self, request: QueueRequest, username: str, personal: PersonalData
    ) -> None:
        assert self.page
        self.expected_email = f"{username}@libero.it".lower()
        phone_sent = False
        final_confirmed = False
        protection_submitted = False
        final_submitted = False

        for _ in range(12):
            self.stage = "riconoscimento del passaggio successivo ai dati personali"
            await self._check_cancelled()
            await self.page.wait_for_timeout(700)
            await self._handle_captcha_if_needed(request)

            if await self._is_success_page():
                if not final_confirmed:
                    raise RegistrationError(
                        "Schermata di completamento rilevata prima della conferma finale. "
                        "Verificare manualmente se l'account esiste prima di riprovare."
                    )
                return

            protection_page = await self._is_account_protection_page()
            if protection_page and not protection_submitted:
                await self._fill_account_protection(personal)
                await self._handle_captcha_if_needed(request)
                button = await self._find_final_button()
                if button is None:
                    raise RegistrationError("Non trovo Registrati nella schermata Protezione Account.")
                if not final_confirmed:
                    await self.coordinator.request_final_confirmation(request, username)
                    final_confirmed = True
                await self._check_cancelled()
                self.stage = "invio di Protezione Account dopo la conferma amministrativa"
                await self._click_and_wait_for_change(button)
                protection_submitted = True
                final_submitted = True
                continue

            phone_input = await self._find_phone_input()
            if phone_input and not phone_sent:
                await self._choose_phone_and_send(request)
                phone_sent = True
                continue

            if phone_sent:
                # La stessa sessione resta aperta durante correzioni e reinvii.
                if not final_confirmed:
                    await self.coordinator.request_final_confirmation(
                        request, username, ready_check=self._assert_phone_session
                    )
                    final_confirmed = True
                await self._verify_sms_until_completed(request)
                return

            # La verifica telefonica può comparire sopra Protezione Account,
            # senza cambiare URL o rimuovere il titolo della pagina sottostante.
            # Prima si gestiscono telefono e OTP; il modulo iniziale resta già inviato.
            if final_submitted:
                result = await self._wait_for_registration_step(
                    request, username, final_submitted=True
                )
                if result == "created":
                    return
                continue

            final_button = await self._find_final_button()
            if final_button:
                if not final_confirmed:
                    await self.coordinator.request_final_confirmation(request, username)
                    final_confirmed = True
                await self._check_required_boxes()
                await self._handle_captcha_if_needed(request)
                self.stage = "invio finale della registrazione"
                await final_button.click()
                final_submitted = True
                await self.page.wait_for_timeout(1_500)
                continue

            next_button = await self._find_button(["Continua", "Avanti"])
            if next_button:
                self.stage = "pulsante Avanti dopo i dati personali"
                await next_button.click()
                await self.page.wait_for_timeout(1_000)
                continue

            await self._wait_for_registration_step(request, username, final_submitted=False)

        raise RegistrationError("Troppi passaggi senza completare la registrazione")

    async def _wait_for_registration_step(
        self, request: QueueRequest, username: str, *, final_submitted: bool
    ) -> str:
        """Keep the current session open; never submit again to resolve uncertainty."""
        assert self.page
        self.stage = "attesa dell'esito della registrazione nel browser aperto"

        async def ready() -> Optional[str]:
            await self._check_cancelled()
            try:
                if await self._is_success_page():
                    return "created"
                if await self._find_phone_input():
                    return "next"
                if not final_submitted and (
                    await self._is_account_protection_page()
                    or await self._find_final_button()
                    or await self._find_button(["Continua", "Avanti"])
                ):
                    return "next"
            except PlaywrightError:
                # A navigation can temporarily replace the page body.
                if self.page.is_closed():
                    raise RegistrationError("Il browser è stato chiuso durante l'attesa dell'esito.") from None
            return None

        # Give redirects and delayed content time before asking the operator.
        for _ in range(10):
            result = await ready()
            if result:
                return result
            await self.page.wait_for_timeout(1_000)
        return await self.coordinator.wait_for_registration_outcome(
            request, username, ready_check=ready, allow_confirmation=final_submitted
        )

    async def _is_account_protection_page(self) -> bool:
        assert self.page
        title = self.page.get_by_text("Protezione Account", exact=True)
        return bool(await title.count() and await title.first.is_visible())

    async def _fill_account_protection(self, personal: PersonalData) -> None:
        """Compila la schermata Sicurezza e Privacy mostrata durante il collaudo."""
        assert self.page
        self.stage = "ricerca del campo Mail o Cellulare"
        contact = self.page.get_by_label("Mail o Cellulare", exact=True)
        if await contact.count() != 1:
            contact = self.page.get_by_placeholder("Mail o Cellulare", exact=True)
        if await contact.count() != 1:
            raise RegistrationError("Non riesco a identificare il campo Mail o Cellulare.")
        self.stage = "compilazione della mail alternativa"
        await contact.fill(recovery_email_candidate(personal))
        await contact.press("Tab")

        self.stage = "scelta Non presto il consenso per pubblicità e personalizzazione"
        refusals = self.page.get_by_role(
            "radio", name="Non presto il consenso", exact=True, include_hidden=True
        )
        labels = self.page.get_by_text("Non presto il consenso", exact=True)
        if await refusals.count() != 2 or await labels.count() != 2:
            raise RegistrationError(
                "Le due scelte Non presto il consenso non sono riconoscibili. "
                "La registrazione non viene inviata."
            )
        for index in range(2):
            radio = refusals.nth(index)
            if not await radio.is_checked():
                await labels.nth(index).click()
            if not await radio.is_checked():
                raise RegistrationError("Il rifiuto di un consenso facoltativo non è stato confermato.")

    async def _find_phone_input(self) -> Optional[Locator]:
        assert self.page
        selectors = [
            'input[type="tel"]:visible',
            'input[name*="mobile" i]:visible',
            'input[id*="mobile" i]:visible',
            'input[name*="phone" i]:visible',
            'input[id*="phone" i]:visible',
            'input[name*="cell" i]:visible',
            'input[id*="cell" i]:visible',
        ]
        locators = [
            self.page.get_by_role("textbox", name=re.compile(r"telefono|cellulare", re.IGNORECASE)),
            *(self.page.locator(selector) for selector in selectors),
        ]
        for locator in locators:
            for candidate in await locator.all():
                if not await candidate.is_visible() or not await candidate.is_editable():
                    continue
                if await candidate.get_attribute("type") == "email":
                    continue
                if await candidate.get_attribute("autocomplete") == "one-time-code":
                    continue
                # Non scambiare Mail o Cellulare della pagina sottostante per
                # il numero richiesto dalla verifica aggiuntiva. Si leggono
                # soltanto etichette del controllo, mai il valore inserito.
                combined_contact = await candidate.evaluate("""element => {
                    const texts = [
                        element.getAttribute('aria-label') || '',
                        element.getAttribute('placeholder') || '',
                        ...Array.from(element.labels || [], label => label.textContent || '')
                    ];
                    return texts.some(text => /mail\\s*o\\s*cellulare/i.test(text));
                }""")
                if not combined_contact:
                    return candidate
        return None

    async def _find_otp_input(self, *, require_editable: bool = True) -> Optional[Locator]:
        assert self.page
        label = re.compile(r"codice\s+(?:di\s+)?(?:conferma|verifica)|codice\s+sms", re.I)
        selectors = [
            'input[autocomplete="one-time-code"]:visible',
            'input[name*="otp" i]:visible',
            'input[id*="otp" i]:visible',
            'input[name*="code" i]:visible',
            'input[id*="code" i]:visible',
            'input[name*="codice" i]:visible',
            'input[id*="codice" i]:visible',
        ]
        for frame in self.page.frames:
            locators = [
                frame.get_by_label(label),
                frame.get_by_role("textbox", name=label),
                frame.get_by_placeholder(label),
                *(frame.locator(selector) for selector in selectors),
            ]
            for locator in locators:
                for candidate in await locator.all():
                    if await candidate.is_visible() and (not require_editable or await candidate.is_editable()):
                        return candidate
        return None

    @staticmethod
    def _classify_otp_feedback(text: str) -> Optional[str]:
        """Classifica solo errori espliciti; mai dedurre l'esito dal campo presente."""
        for line in text.splitlines():
            line = normalize_spaces(line).lower()
            if re.search(r"^(?:se |nel caso |qualora )", line):
                continue
            if re.search(r"troppi tentativi|numero massimo di tentativi|"
                         r"tentativi (?:massimi |disponibili )?(?:superati|esauriti)|"
                         r"verifica (?:temporaneamente )?bloccata", line):
                return "blocked"
        for line in text.splitlines():
            line = normalize_spaces(line).lower()
            if re.search(r"^(?:se |nel caso |qualora )", line):
                continue
            prefix = r"\bcodice(?: di (?:conferma|verifica))?(?: che hai inserito| inserito| sms)?(?: è| risulta)? "
            if re.search(prefix + r"scaduto\b|validità del codice (?:è )?scaduta", line):
                return "expired"
            if re.search(prefix + r"(?:errato|sbagliato|non valido|non corretto|non corrisponde)\b|"
                         r"\bcodice(?: di (?:conferma|verifica))?(?: che hai inserito| inserito)? non (?:è )?(?:più )?(?:valido|corretto)\b", line):
                return "invalid"
        return None

    async def _otp_feedback(self) -> Optional[str]:
        assert self.page
        feedback = None
        # get_by_text individua i messaggi; is_visible esclude errori nascosti.
        # Non si leggono valori input e nessun testo viene salvato o inviato.
        label = re.compile(r"codice|tentativi|verifica.*bloccata", re.I)
        for frame in self.page.frames:
            for candidate in await frame.get_by_text(label).all():
                if not await candidate.is_visible():
                    continue
                kind = self._classify_otp_feedback(await candidate.inner_text(timeout=2_000))
                if kind == "blocked":
                    return kind
                feedback = feedback or kind
        return feedback

    async def _wait_for_otp_outcome(
        self, request: QueueRequest, previous_feedback: Optional[str]
    ) -> str:
        assert self.page
        cleared = previous_feedback is None
        while True:
            for _ in range(30):
                await self._check_cancelled()
                await self._handle_captcha_if_needed(request)
                if await self._is_success_page():
                    return "success"
                await self._assert_phone_session()
                try:
                    feedback = await self._otp_feedback()
                except PlaywrightError:
                    if self.page.is_closed():
                        raise RegistrationError("Il browser è stato chiuso durante la verifica SMS.")
                    # Un frame transitorio non prova che il vecchio errore sia sparito.
                    await self.page.wait_for_timeout(1_000)
                    continue
                if feedback is None:
                    cleared = True
                elif feedback == "blocked":
                    break
                elif cleared or feedback != previous_feedback:
                    return feedback
                await self.page.wait_for_timeout(1_000)
            # Nessun secondo clic sul codice, sul numero o su Registrati.
            # Un esito sconosciuto/limite del sito richiede controllo umano.
            await self.coordinator.wait_for_manual_captcha(
                request,
                instructions=(
                    "⚠️ La verifica SMS non ha un esito riconosciuto oppure Libero "
                    "segnala un limite ai tentativi. La sessione resta aperta.\n\n"
                    "Controlla il browser remoto. Non ripetere Registrati e non "
                    "inviare nuovamente il codice mentre il sito sta rispondendo. "
                    "Dopo il controllo premi il pulsante per rileggere l'esito, "
                    "oppure usa /annulla. Non verrà ripetuto alcun invio automaticamente."
                ),
            )
            await self.coordinator.set_queue_fields(request, STATO="VERIFICA_CODICE")
            # Dopo il controllo esplicito dell'amministratore si può rileggere
            # anche un identico messaggio d'errore rimasto sulla pagina.
            cleared = True

    async def _assert_phone_session(self) -> None:
        """Observe only: visible initial credentials are a reset, never a retry."""
        assert self.page
        await self._check_cancelled()
        await self._raise_if_provider_blocked()
        try:
            if self.page.is_closed():
                raise RegistrationError("Il browser è stato chiuso durante l'attesa della verifica telefonica.")
            if await self._find_otp_input(require_editable=False) is not None:
                return  # Non scambiare la pagina sotto la finestra SMS per un reset.
            if (await self.page.locator("#username").is_visible()
                    and await self.page.locator("#password").is_visible()):
                raise RegistrationSessionReset(
                    "Libero è tornato all'inizio durante l'attesa della verifica telefonica. "
                    "Sessione scaduta o reimpostata: tentativo interrotto. "
                    "Verificare se la casella esiste prima di riprovare. Non ripetere Registrati.")
        except PlaywrightError:
            if self.page.is_closed():
                raise RegistrationError("Il browser è stato chiuso durante l'attesa della verifica telefonica.") from None
            # Un cambio pagina può sostituire momentaneamente il documento.

    async def _phone_edit_ready(self) -> bool:
        # La finestra OTP deve essere scomparsa: il campo Mail o Cellulare
        # della pagina sottostante non deve mai essere usato per questo cambio.
        try:
            if await self._find_otp_input(require_editable=False) is not None:
                return False
            await self._assert_phone_session()
            field = await self._find_phone_input()
            if field is None:
                return False
            # Controllo di raggiungibilità, senza effettuare il clic: una
            # finestra sovrapposta potrebbe coprire un campo ancora visibile.
            await field.click(trial=True, timeout=1_000)
            return True
        except PlaywrightError:
            if self.page.is_closed():
                raise RegistrationError("Il browser è stato chiuso durante il cambio tester.")
            return False

    async def _return_to_phone_form(self, request: QueueRequest) -> None:
        assert self.page
        if await self._phone_edit_ready():
            return
        label = re.compile(
            r"^\s*(?:modifica|cambia|correggi) (?:il )?(?:numero(?: di (?:telefono|cellulare))?|cellulare)\s*$", re.I
        )
        candidates = []
        for frame in self.page.frames:
            # Solo controlli espliciti. Mai X, Indietro generico o Registrati.
            for role in ("button", "link"):
                for candidate in await frame.get_by_role(role, name=label).all():
                    if await candidate.is_visible() and await candidate.is_enabled():
                        candidates.append(candidate)
        if len(candidates) == 1:
            try:
                await self._check_cancelled()
                await candidates[0].click(timeout=5_000)
            except PlaywrightTimeoutError:
                pass  # Non ripetere un clic dall'esito incerto.
            for _ in range(20):
                await self._check_cancelled()
                if await self._phone_edit_ready():
                    return
                await self.page.wait_for_timeout(500)
        while not await self._phone_edit_ready():
            await self.coordinator.wait_for_manual_captcha(
                request,
                instructions=(
                    "⚠️ Il precedente tester è stato scollegato dalla richiesta, "
                    "ma non riconosco un modo sicuro per cambiare numero su Libero.\n\n"
                    "La sessione resta aperta. Controlla il browser remoto: se il sito "
                    "lo consente, torna al campo Cellulare della verifica. Riprenderò "
                    "quando rilevo quel campo e la finestra del codice è chiusa. "
                    "Non ripetere Registrati. Se Libero non permette il cambio, usa /annulla."
                ),
                ready_check=self._phone_edit_ready,
            )
            await self._check_cancelled()

    async def _choose_phone_and_send(self, request: QueueRequest) -> None:
        self.phone_verification_started = True
        while True:
            await self._assert_phone_session()
            phone, user_id = await self.coordinator.request_phone(
                request, ready_check=self._assert_phone_session
            )
            if self.coordinator.change_tester_event.is_set():
                await self.coordinator.revoke_tester(request)
                continue
            # Dal riempimento all'invio numero il cambio è escluso.
            self.coordinator.change_tester_allowed = False
            await self._check_cancelled()
            await self._assert_phone_session()
            field = await self._find_phone_input()
            if field is None:
                await self._return_to_phone_form(request)
                field = await self._find_phone_input()
            if field is None:
                raise RegistrationError("Campo Cellulare non più disponibile.")
            self.stage = "compilazione del numero di telefono"
            await self._fill_phone(field, phone)
            await self._assert_phone_session()
            self.coordinator.otp_future = asyncio.get_running_loop().create_future()
            await self.coordinator.set_queue_fields(
                request, STATO="ATTESA_CODICE", TELEGRAM_ASSEGNATO=str(user_id),
                TELEFONO_MASCHERATO=mask_phone(phone),
            )
            self.stage = "richiesta del codice SMS"
            await self._check_cancelled()
            await self._assert_phone_session()
            await self._click_first_button(["Invia codice", "Ricevi codice", "Continua", "Avanti"])
            await self._assert_phone_session()
            await self.coordinator.notify_otp_sent(request, user_id, phone)
            return

    async def _replace_phone_tester(self, request: QueueRequest) -> None:
        await self.coordinator.revoke_tester(request)
        await self._return_to_phone_form(request)
        await self._choose_phone_and_send(request)

    async def _verify_sms_until_completed(self, request: QueueRequest) -> None:
        assert self.page
        while True:
            await self._check_cancelled()
            try:
                code = await self.coordinator.request_otp(
                    request, resend=self._resend_sms, ready_check=self._assert_phone_session
                )
            except TesterChangeRequested:
                await self._replace_phone_tester(request)
                continue
            # Un reinvio può sostituire la finestra: cercare di nuovo il campo.
            otp_input = await self._wait_for_otp_input(request)
            await self._assert_phone_session()
            self.stage = "compilazione del codice SMS"
            await otp_input.fill(code)
            code = None  # Non conservare il codice oltre la compilazione.
            previous_feedback = await self._otp_feedback()
            await self.coordinator.set_queue_fields(request, STATO="VERIFICA_CODICE")
            await self._check_cancelled()
            await self._assert_phone_session()
            self.stage = "verifica del codice SMS"
            try:
                await self._click_first_button(["Verifica", "Conferma", "Continua", "Avanti"])
            except PlaywrightTimeoutError:
                # Il clic potrebbe essere già arrivato: osservare l'esito,
                # senza ritentare l'invio e senza chiudere subito il browser.
                pass
            result = await self._wait_for_otp_outcome(request, previous_feedback)
            if result == "success":
                self.coordinator.mark_sms_verified(request)
                return
            await self.coordinator.retry_otp(request, expired=result == "expired")

    async def _wait_for_otp_input(self, request: QueueRequest) -> Locator:
        """Attende la finestra SMS senza reinviare numero, codice o modulo."""
        assert self.page
        async def otp_ready() -> bool:
            await self._assert_phone_session()
            return await self._find_otp_input() is not None

        while True:
            self.stage = "attesa del campo Codice di conferma SMS"
            for _ in range(30):
                await self._check_cancelled()
                await self._assert_phone_session()
                candidate = await self._find_otp_input()
                if candidate is not None:
                    return candidate
                await self.page.wait_for_timeout(500)
            LOGGER.warning("Campo SMS non riconosciuto; attesa intervento amministratore")
            await self.coordinator.wait_for_manual_captcha(
                request,
                instructions=(
                    "⚠️ L'invio SMS è stato richiesto, ma non riconosco ancora il campo "
                    "Codice di conferma. Il browser resta aperto.\n\n"
                    "Controlla il browser remoto e manda all'assistente uno screenshot "
                    "senza numero di telefono o codice. Il tester può rispondere al bot "
                    "in privato: il codice ricevuto resta in attesa.\n\n"
                    "Non premere Invia di nuovo o Registrati e non inserire il codice "
                    "manualmente. Premi il pulsante qui sotto per ripetere soltanto "
                    "il riconoscimento del campo. Puoi interrompere con /annulla."
                ),
                ready_check=otp_ready,
            )
            await self._check_cancelled()
            await self.coordinator.set_queue_fields(request, STATO="ATTESA_CODICE")

    async def _fill_phone(self, locator: Locator, phone: str) -> None:
        assert self.page
        prefix_selectors = [
            'select[name*="prefix" i]:visible',
            'select[id*="prefix" i]:visible',
            'select[name*="country" i]:visible',
        ]
        has_prefix = False
        for selector in prefix_selectors:
            prefix = self.page.locator(selector)
            if await prefix.count():
                try:
                    options = await prefix.first.locator("option").all()
                    for option in options:
                        label = normalize_spaces(await option.inner_text())
                        if "Italia" in label or "+39" in label:
                            value = await option.get_attribute("value")
                            if value is not None:
                                await prefix.first.select_option(value=value)
                                has_prefix = True
                                break
                    if has_prefix:
                        break
                except Exception:
                    LOGGER.debug("Prefisso telefonico non selezionabile con %s", selector)
        digits = re.sub(r"\D", "", phone)
        if has_prefix and digits.startswith("39"):
            digits = digits[2:]
        await locator.fill(digits if has_prefix else phone)

    async def _resend_sms(self) -> None:
        assert self.page
        await self._check_cancelled()
        await self._assert_phone_session()
        label = re.compile(r"^\s*Invia di nuovo\s*$", re.I)
        for frame in self.page.frames:
            locators = [frame.get_by_role("link", name=label),
                        frame.get_by_role("button", name=label),
                        frame.get_by_text(label)]
            for locator in locators:
                for candidate in await locator.all():
                    if await candidate.is_visible() and await candidate.is_enabled():
                        # Un solo clic per richiesta, senza reinvii automatici.
                        await candidate.click(timeout=5_000)
                        await self._assert_phone_session()
                        return
        await self._assert_phone_session()
        raise RegistrationError("Il comando Invia di nuovo non è disponibile sul sito.")

    async def _find_final_button(self) -> Optional[Locator]:
        return await self._find_button(
            ["Registrati", "Crea account", "Crea la tua mail", "Completa registrazione"]
        )

    async def _find_button(self, names: list[str]) -> Optional[Locator]:
        assert self.page
        for name in names:
            locator = self.page.get_by_role(
                "button", name=re.compile(rf"^{re.escape(name)}$", re.IGNORECASE)
            )
            if await locator.count() and await locator.first.is_visible():
                return locator.first
        return None

    async def _click_first_button(self, names: list[str]) -> None:
        button = await self._find_button(names)
        if not button:
            raise RegistrationError(
                "Non trovo il pulsante previsto: " + ", ".join(names)
            )
        await button.click()
        assert self.page
        await self.page.wait_for_timeout(1_000)

    async def _check_required_boxes(self) -> None:
        assert self.page
        required = self.page.locator('input[type="checkbox"][required]:visible')
        for index in range(await required.count()):
            checkbox = required.nth(index)
            if not await checkbox.is_checked():
                await checkbox.check()

    async def _click_and_wait_for_change(self, selector: str | Locator) -> None:
        assert self.page
        old_url = self.page.url
        target = self.page.locator(selector) if isinstance(selector, str) else selector
        await target.click()
        try:
            await self.page.wait_for_url(
                lambda url: str(url) != old_url,
                timeout=15_000,
                wait_until="domcontentloaded",
            )
        except PlaywrightTimeoutError:
            await self.page.wait_for_timeout(1_000)

    async def _captcha_visible(self) -> bool:
        assert self.page
        selectors = [
            "#captcha_box:visible",
            ".g-recaptcha:visible",
            'iframe[title*="challenge" i]:visible',
        ]
        for selector in selectors:
            locator = self.page.locator(selector)
            if await locator.count() and await locator.first.is_visible():
                box = await locator.first.bounding_box()
                if box and box.get("height", 0) >= 40:
                    return True
        return False

    async def _captcha_completed(self) -> bool:
        """Legge solo segnali di completamento; non risolve o modifica la verifica."""
        assert self.page
        try:
            for frame in self.page.frames:
                # Leggere soltanto un booleano: mai estrarre o salvare il token.
                completed = await frame.evaluate("""() => {
                    const fields = document.querySelectorAll(
                        '[name="g-recaptcha-response"], [name="h-captcha-response"], '
                        + '[name="cf-turnstile-response"]'
                    );
                    return Array.from(fields).some(field => Boolean((field.value || '').trim()));
                }""")
                if completed:
                    return True
                checked = frame.locator('#recaptcha-anchor[aria-checked="true"]')
                for candidate in await checked.all():
                    if await candidate.is_visible():
                        return True
            # La sola scomparsa del riquadro non dimostra il superamento.
            return False
        except PlaywrightError:
            if self.page.is_closed():
                raise RegistrationError("Il browser è stato chiuso durante l'attesa del CAPTCHA.")
            return False  # Un frame può essere sostituito durante la verifica.

    async def _handle_captcha_if_needed(self, request: QueueRequest) -> None:
        assert self.page
        if not await self._captcha_visible() or await self._captcha_completed():
            return

        previous_status = request.status
        starting_url = self.page.url
        await self.coordinator.wait_for_manual_captcha(
            request, ready_check=lambda: self._captcha_resume_ready(starting_url)
        )
        await self.coordinator.set_queue_fields(
            request,
            STATO=previous_status,
            NOTE="CAPTCHA completato manualmente",
        )

    async def _captcha_resume_ready(self, starting_url: str) -> bool:
        assert self.page
        if await self._captcha_completed():
            return True
        # Se l'utente ha già premuto Avanti nel sito, il widget e il suo segnale
        # possono non esistere più. Serve una pagina successiva riconosciuta,
        # non un semplice cambio URL o la chiusura della finestra di verifica.
        before, after = urlsplit(starting_url), urlsplit(self.page.url)
        if (before.hostname, before.path) == (after.hostname, after.path):
            return False
        if after.hostname != "registrazione.libero.it" or after.scheme != "https":
            return False
        try:
            if await self._captcha_visible():
                return False
            if (await self.page.locator("#firstname").is_visible()
                    and await self.page.locator("#lastname").is_visible()):
                return True
            if await self._is_account_protection_page():
                return True
            if after.path == "/end.phtml":
                return await self._is_success_page()
            return False
        except PlaywrightError:
            if self.page.is_closed():
                raise RegistrationError("Il browser è stato chiuso durante l'attesa del CAPTCHA.")
            return False

    async def _raise_if_provider_blocked(self, body: Optional[str] = None) -> None:
        assert self.page
        parts = urlsplit(self.page.url)
        if parts.scheme != "https" or parts.hostname != "registrazione.libero.it":
            return
        pattern = re.compile(r"attività\s+anomala[.\s]+riprova\s+ad\s+eseguire\s+l[’']operazione\s+tra\s+alcuni\s+minuti", re.I)
        matches = self.page.get_by_text(pattern)
        if not any([await node.is_visible() for node in await matches.all()]):
            return
        body = body if body is not None else normalize_spaces(await self.page.locator("body").inner_text()).lower()
        success = any(x in body for x in ("registrazione completata", "account creato", "entra nella tua mail"))
        safe = (parts.path == "/join3.phtml" and not success and not self.phone_verification_started
                and await self._is_account_protection_page()
                and await self._find_otp_input(require_editable=False) is None)
        raise RegistrationProviderCooldown(bool(safe))

    async def _is_success_page(self) -> bool:
        assert self.page
        parts = urlsplit(self.page.url)
        end_page = (
            parts.scheme == "https"
            and parts.hostname == "registrazione.libero.it"
            and parts.path == "/end.phtml"
        )
        if end_page:
            await self.page.wait_for_load_state("domcontentloaded")
            await self.page.wait_for_timeout(1_000)
        body = normalize_spaces(await self.page.locator("body").inner_text()).lower()
        await self._raise_if_provider_blocked(body)
        failure = re.search(
            r"non (?:è |e' |e’ )?(?:stato )?possibile (?:\w+ ){0,4}"
            r"(?:creare|completare|registrare|creazione|registrazione)"
            r"|(?:registrazione|creazione (?:dell.account|della (?:casella|mail))) "
            r"(?:non (?:è |e' |e’ )?(?:stata )?(?:completata|riuscita|andata a buon fine)|fallita)"
            r"|(?:errore|problema) (?:\w+ ){0,4}(?:registrazione|creazione)",
            body,
        )
        end_error = end_page and re.search(
            r"impossibile (?:\w+ ){0,4}(?:creare|completare|registrare)"
            r"|non siamo riusciti a (?:creare|completare|registrare)"
            r"|(?:account|casella|mail) non (?:è |e' |e’ )?(?:stat[oa] )?creat[oa]"
            r"|(?:si è verificato|si e' verificato|si e’ verificato) un errore"
            r"|qualcosa è andato storto|riprova più tardi", body
        )
        if failure or end_error:
            raise RegistrationError(
                "Libero segnala che la creazione o registrazione non è riuscita. "
                "La richiesta non viene segnata come CREATA."
            )
        signals = [
            "registrazione completata",
            "account creato",
            "entra nella tua mail",
        ]
        # Alcune registrazioni portano direttamente alla casella aperta,
        # con la guida iniziale, senza restare su end.phtml.
        host = (parts.hostname or "").lower()
        trusted = parts.scheme == "https" and (
            host == "libero.it" or host.endswith(".libero.it")
        )
        expected = self.expected_email
        matching_email = bool(expected and re.search(
            r"(?<![a-z0-9._%+@-])" + re.escape(expected) + r"(?![a-z0-9._%+@-])",
            body,
        ))
        mailbox = (
            trusted and matching_email
            and "leggi la posta" in body
            and re.search(r"\besci\b", body) is not None
            and ("benvenuto nella libero mail" in body or "nuove mail" in body)
        )
        return trusted and (
            (end_page and bool(body)) or mailbox or any(signal in body for signal in signals)
        )

    async def _report_unknown_step(self, request: QueueRequest) -> None:
        assert self.page
        # Il testo della pagina può contenere anagrafica e codice SMS.
        # Non salvarlo in log o messaggi Telegram.
        parts = urlsplit(self.page.url)
        await self.coordinator.send_unknown_step(
            request,
            urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
            "Il contenuto della pagina non viene salvato per proteggere i dati personali.",
        )

    async def _check_cancelled(self) -> None:
        if self.coordinator.cancel_event.is_set():
            raise RequestCancelled("Richiesta annullata dall'amministratore")


def audit_queue_records(rows: list) -> tuple[list, list]:
    if not rows or [str(x).strip() for x in rows[0][:len(QUEUE_HEADERS)]] != QUEUE_HEADERS:
        raise RegistrationError("Intestazioni Coda non valide: controllo interrotto.")
    account_columns = [i for i, v in enumerate(rows[0]) if str(v).strip() == "ID_ACCOUNT"]
    if len(account_columns) > 1:
        raise RegistrationError("Colonna ID_ACCOUNT duplicata in Coda.")
    account_column = account_columns[0] if account_columns else None
    records = []
    malformed = []
    for number, row in enumerate(rows[1:], 2):
        if not any(str(v).strip() for v in row):
            continue
        record = dict(zip(QUEUE_HEADERS, row + [""] * len(QUEUE_HEADERS)))
        try:
            request = QueueRequest(number, str(record["ID_RICHIESTA"]).strip(),
                str(record["STATO"]).strip(), str(record["SPREADSHEET_DESTINAZIONE"]).strip(),
                str(record["FOGLIO_DESTINAZIONE"]).strip(), int(record["RIGA_DESTINAZIONE"]),
                int(record["COLONNA_EMAIL"]), str(record["NOME_COMPLETO"]).strip(),
                str(record["TELEGRAM_ASSEGNATO"]).strip(), str(record["MESSAGGIO_GRUPPO_ID"]).strip(),
                str(row[account_column]).strip() if account_column is not None and len(row) > account_column else "")
            if (not request.request_id or not request.destination_spreadsheet
                    or not request.destination_sheet or request.destination_row < 2 or request.email_column < 1):
                raise ValueError()
            records.append((request, str(record["EMAIL_CREATA"]).strip(), str(record["USERNAME_LIBERO"]).strip()))
        except (TypeError, ValueError):
            malformed.append(number)
    return records, malformed


def audit_normalize(value: str) -> str:
    return normalize_spaces(re.sub(r"[^a-z0-9]+", " ", normalize_ascii(str(value)).lower()))


def audit_cell(values: list, row: int, column: int) -> str:
    if row < 1 or column < 1 or row > len(values) or column > len(values[row - 1]):
        return ""
    return str(values[row - 1][column - 1]).strip()


def audit_empty_email(value: str) -> bool:
    return str(value).strip().lower() in {"", "//", "/", "-", "--", ".", "..", "?", "??",
        "n/a", "na", "null", "nessuna", "nessuno", "non presente", "da inserire", "da trovare", "la sua"}


def audit_email_writable(value: str, expected: str) -> bool:
    # Stessi segnaposto accettati dal normale salvataggio, senza sovrascrivere testo.
    return value in {"", "//", "/", "-", "--", ".", "..", "?", "??"} or value.lower() == expected.lower()


def audit_layout(values: list) -> tuple[int, int, int]:
    layouts = []
    for row, cells in enumerate(values[:100], 1):
        names = [i + 1 for i, v in enumerate(cells) if audit_normalize(v) in
                 {"nome cognome", "nome e cognome", "nome cliente"}]
        emails = [i + 1 for i, v in enumerate(cells) if audit_normalize(v) in
                  {"email", "e mail", "email usata", "e mail usata"}]
        if names and emails:
            if len(names) != 1 or len(emails) != 1:
                raise RegistrationError("Intestazioni ambigue: controllo manuale necessario.")
            layouts.append((row, names[0], emails[0]))
    if not layouts:
        raise RegistrationError("Intestazioni nome/email non riconosciute.")
    return layouts[-1]


def audit_destination(request: QueueRequest) -> tuple:
    return (request.destination_spreadsheet, request.destination_sheet,
            request.destination_row, request.email_column)


def account_target_key(request: QueueRequest) -> tuple:
    return (request.destination_spreadsheet, request.destination_sheet,
            ("id", request.account_id) if request.account_id else ("row", request.destination_row))


def compatible_destination(recorded: QueueRequest, current: QueueRequest) -> bool:
    if (recorded.destination_spreadsheet, recorded.destination_sheet) != (current.destination_spreadsheet, current.destination_sheet):
        return False
    if recorded.account_id:
        return bool(current.account_id and recorded.account_id == current.account_id)
    # Un esito precedente alla migrazione puo essere collegato solo dalla vecchia destinazione.
    return audit_destination(recorded) == audit_destination(current)


def resolve_account_target(request: QueueRequest, values: list) -> tuple[int, int, int, int]:
    header, name_col, email_col = audit_layout(values)
    id_cols = [i + 1 for i, v in enumerate(values[header - 1]) if str(v).strip() == "ID_MULINO"]
    if len(id_cols) > 1:
        raise RegistrationError("Colonna ID_MULINO duplicata: scrittura bloccata.")
    id_col = id_cols[0] if id_cols else 0
    if request.account_id:
        if not id_col:
            raise RegistrationError("Colonna ID_MULINO mancante: ripristinala senza cambiare gli identificativi.")
        rows = [r for r in range(header + 1, len(values) + 1)
                if audit_cell(values, r, id_col) == request.account_id]
        if len(rows) != 1:
            raise RegistrationError("ID account assente o duplicato nel foglio: scrittura bloccata.")
        row = rows[0]
    else:
        row = request.destination_row
        # Le vecchie richieste non vengono trasferite ad un omonimo cercando per nome.
        same_names = [r for r in range(header + 1, len(values) + 1)
                      if audit_normalize(audit_cell(values, r, name_col)) == audit_normalize(request.full_name)]
        if len(same_names) != 1 or request.email_column != email_col:
            raise RegistrationError("Richiesta senza ID stabile: nome ambiguo o colonne cambiate. Completa la migrazione.")
    name = audit_cell(values, row, name_col)
    if (row <= header or not name or not request.full_name
            or audit_normalize(name) != audit_normalize(request.full_name)):
        raise RegistrationError("Il nome della riga non corrisponde alla richiesta: scrittura bloccata.")
    return row, email_col, name_col, id_col


def build_consistency_report(snapshot: dict, outcomes: dict, active_id: str = "") -> dict:
    issues = []
    records = snapshot["records"]
    tables = snapshot["tables"]
    ids, destinations, positions, located_rows = {}, {}, {}, {}
    for request, _, _ in records:
        ids.setdefault(request.request_id, []).append(request)
        table = tables.get((request.destination_spreadsheet, request.destination_sheet), {})
        try:
            row, _, _, _ = resolve_account_target(request, table.get("values", []))
            key = (request.destination_spreadsheet, request.destination_sheet, ("row", row))
        except RegistrationError:
            key = account_target_key(request)
        positions[(request.request_id, request.row)] = key
        destinations.setdefault(key, []).append(request)
    def issue(code, message, request=None, *, sheet="Coda", row=0, restore=False, email=""):
        issues.append({"code": code, "message": message, "request": request,
                       "sheet": request.destination_sheet if request else sheet,
                       "row": located_rows.get(request.request_id, request.destination_row) if request else row,
                       "restore": restore, "email": email})
    for row in snapshot["malformed"]:
        issue("CODA_NON_VALIDA", "Riga Coda incompleta o non valida; non e stata modificata.", row=row)
    for (book, sheet), table in tables.items():
        if "error" in table:
            issue("NON_VERIFICABILE", "Foglio non leggibile o intestazioni non riconosciute. Controlla nome della scheda e accesso del service account.", sheet=sheet)
    ok = 0
    for request, queued_email, username in records:
        rid = request.request_id
        if len(ids[rid]) > 1 or len(destinations[positions[(request.request_id, request.row)]]) > 1:
            issue("DUPLICATO", "Piu richieste condividono ID o destinazione. Verificare prima di riprovare.", request)
            continue
        saved = outcomes.get(rid)
        if saved and not compatible_destination(saved[0], request):
            issue("DESTINAZIONE_CAMBIATA", "La destinazione in Coda differisce dal registro VPS. Ripristino bloccato.", request)
            continue
        table = tables.get((request.destination_spreadsheet, request.destination_sheet), {})
        if "layout" not in table:
            continue
        values = table["values"]
        try:
            actual_row, email_col, _, _ = resolve_account_target(request, values)
        except RegistrationError as exc:
            issue("RIGA_DA_VERIFICARE", str(exc), request)
            continue
        located_rows[rid] = actual_row
        email = audit_cell(values, actual_row, email_col)
        if request.account_id and (actual_row, email_col) != (request.destination_row, request.email_column):
            issue("RIGA_RITROVATA", f"Account ritrovato tramite ID alla riga {actual_row}, colonna email {email_col}. Il salvataggio usera questa posizione.", request)
        if rid == active_id or request.status == "DA_COMPLETARE_ANAGRAFICA":
            if saved or queued_email or not audit_empty_email(email):
                issue("AVVIO_DA_VERIFICARE", "La richiesta e attiva/in coda, ma esiste gia un indirizzo o un esito locale. Usa /pausa e verifica.", request)
            else:
                ok += 1
            continue
        if saved:
            expected = saved[2]
            if ((queued_email and queued_email.lower() != expected.lower())
                    or (username and username.lower() + "@libero.it" != expected.lower())):
                issue("INDIRIZZI_DISCORDANTI", "Coda e registro VPS indicano indirizzi diversi. Nessuna correzione automatica.", request)
            elif audit_empty_email(email):
                writable = audit_email_writable(email, expected)
                message = "Casella presente nel registro VPS, ma email assente nella destinazione."
                if not writable:
                    message += " Rimuovi il segnaposto testuale nella cella e ripeti /controlla prima del ripristino."
                issue("CREATA_NON_SCRITTA", message, request, restore=writable, email=expected)
            elif email.lower() != expected.lower():
                issue("INDIRIZZI_DISCORDANTI", "Il foglio contiene un indirizzo diverso dal registro VPS. Nessuna sovrascrittura.", request)
            elif request.status != "CREATA" or not saved[3]:
                issue("STATO_DA_ALLINEARE", "Email corretta nel foglio; stato Coda o conferma di salvataggio da riallineare.", request, restore=True, email=expected)
            else:
                ok += 1
        elif request.status == "CREATA":
            if queued_email and email.lower() == queued_email.lower():
                issue("ESITO_SOLO_IN_CODA", "Coda e foglio concordano, ma manca l'esito nel registro VPS. Non creare di nuovo la casella.", request)
            else:
                issue("CREATA_DA_VERIFICARE", "Coda segna CREATA, ma manca un esito locale e l'email non e allineata. Verifica l'accesso alla casella.", request)
        elif not audit_empty_email(email):
            issue("EMAIL_GIA_PRESENTE", "Il foglio contiene gia un valore email, ma la richiesta non e completata. Verifica prima di riprovare.", request)
        elif request.status not in ({"ERRORE", "ANNULLATA"} | TRANSIENT_STATUSES):
            issue("STATO_DA_VERIFICARE", "Stato Coda non riconosciuto: correggerlo solo dopo aver verificato l'esito della richiesta.", request)
        else:
            issue("DA_RECUPERARE", "Richiesta senza email: usa /recupera. Una registrazione parziale va verificata prima di ripartire.", request)
    for rid, saved in outcomes.items():
        if rid not in ids:
            issue("ESITO_SENZA_CODA", "Esito presente sul VPS, ma richiesta assente dalla Coda. Non creare nuovamente la casella.", saved[0])
    covered = set()
    for r, _, _ in records:
        table = tables.get((r.destination_spreadsheet, r.destination_sheet), {})
        try:
            row, _, _, _ = resolve_account_target(r, table.get("values", []))
        except RegistrationError:
            # Non attribuire la vecchia riga a chi adesso la occupa.
            continue
        covered.add((r.destination_spreadsheet, r.destination_sheet, row))
    for book, sheet in sorted(snapshot["scan_keys"]):
        table = tables.get((book, sheet), {})
        if "layout" not in table:
            continue
        header, name_col, email_col = table["layout"]
        for row in range(header + 1, len(table["values"]) + 1):
            if ((book, sheet, row) not in covered and audit_cell(table["values"], row, name_col)
                    and audit_empty_email(audit_cell(table["values"], row, email_col))):
                issue("SENZA_RICHIESTA", "Email assente e nessuna richiesta in Coda. Esegui recuperaEmailMancanti in Apps Script; le righe colorate possono essere escluse intenzionalmente.", sheet=sheet, row=row)
    return {"issues": issues, "requests": len(records), "ok": ok,
            "sheets": sum("layout" in t for t in tables.values()),
            "books": len({b for b, _ in snapshot["scan_keys"]}),
            "legacy": sum(not r.account_id for r, _, _ in records)}


class TesterLedger:
    """Append-only completions and reset boundaries in the outcome database."""
    def __init__(self, db):
        self.db = db
        db.execute("""CREATE TABLE IF NOT EXISTS tester_completions (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL UNIQUE,
            tester_id INTEGER NOT NULL CHECK(tester_id>0),
            verified_at TEXT NOT NULL, completed_at TEXT NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS tester_user_seq ON tester_completions(tester_id,seq)")
        db.execute("""CREATE TABLE IF NOT EXISTS tester_resets (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, tester_id INTEGER NOT NULL CHECK(tester_id>0),
            cutoff INTEGER NOT NULL, reset_at TEXT NOT NULL, admin_id INTEGER NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS tester_reset_user ON tester_resets(tester_id,seq)")
        db.execute("INSERT OR IGNORE INTO runtime_settings(key,value) VALUES ('tester_counting_started',?)",
                   (self.now(),))

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat(timespec='seconds')

    @staticmethod
    def valid_id(value):
        return type(value) is int and 0 < value < 2**63

    def credit(self, request_id, tester_id, verified_at):
        # Called only inside the transaction inserting a NEW confirmed outcome.
        if not self.valid_id(tester_id):
            raise ValueError('Invalid tester ID')
        proof = datetime.fromisoformat(verified_at)
        if proof.tzinfo is None:
            raise ValueError('Invalid verification timestamp')
        self.db.execute("INSERT INTO tester_completions(request_id,tester_id,verified_at,completed_at) VALUES (?,?,?,?)",
                        (request_id, tester_id, verified_at, self.now()))

    def known_ids(self):
        return {r[0] for r in self.db.execute(
            'SELECT tester_id FROM tester_completions UNION SELECT tester_id FROM tester_resets')}

    def stats(self, tester_id):
        if not self.valid_id(tester_id):
            raise ValueError('Invalid tester ID')
        reset = self.db.execute('SELECT seq,cutoff,reset_at FROM tester_resets WHERE tester_id=? ORDER BY seq DESC LIMIT 1',
                                (tester_id,)).fetchone()
        reset_seq, cutoff, started = reset if reset else (0, 0,
            self.db.execute("SELECT value FROM runtime_settings WHERE key='tester_counting_started'").fetchone()[0])
        count, last_seq = self.db.execute(
            'SELECT COUNT(*),COALESCE(MAX(seq),0) FROM tester_completions WHERE tester_id=? AND seq>?',
            (tester_id, cutoff)).fetchone()
        total = self.db.execute('SELECT COUNT(*) FROM tester_completions WHERE tester_id=?', (tester_id,)).fetchone()[0]
        return dict(tester_id=tester_id, count=count, total=total, started=started,
                    snapshot=(count, last_seq, reset_seq))

    def reset(self, tester_id, admin_id, expected):
        if not self.valid_id(admin_id):
            raise ValueError('Invalid admin ID')
        self.db.execute('SAVEPOINT tester_reset')
        try:
            current = self.stats(tester_id)
            if tuple(expected) != current['snapshot']:
                raise RegistrationError('Conteggio cambiato: rileggi il tester e conferma nuovamente.')
            cutoff = self.db.execute('SELECT COALESCE(MAX(seq),0) FROM tester_completions').fetchone()[0]
            self.db.execute('INSERT INTO tester_resets(tester_id,cutoff,reset_at,admin_id) VALUES (?,?,?,?)',
                            (tester_id, cutoff, self.now(), admin_id))
            self.db.execute('RELEASE tester_reset')
        except BaseException:
            self.db.execute('ROLLBACK TO tester_reset')
            self.db.execute('RELEASE tester_reset')
            raise


class CreatedOutcomes:
    """Esiti durevoli: un errore Sheets non deve riaprire il browser."""

    def __init__(self, directory: Optional[Path] = None) -> None:
        path = directory / "created-outcomes.sqlite3" if directory else None
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
            path.chmod(0o600)
        self.db = sqlite3.connect(str(path) if path else ":memory:", isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS outcomes (
            request_id TEXT PRIMARY KEY, request_json TEXT NOT NULL,
            username TEXT NOT NULL, email TEXT NOT NULL,
            synced INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
            next_try REAL NOT NULL DEFAULT 0)""")
        self.db.execute("CREATE TABLE IF NOT EXISTS runtime_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.testers = TesterLedger(self.db)

    def queue_paused(self) -> bool:
        row = self.db.execute("SELECT value FROM runtime_settings WHERE key='queue_paused'").fetchone()
        return row is not None and row[0] == "1"

    def set_queue_paused(self, paused: bool) -> None:
        self.db.execute("INSERT INTO runtime_settings(key,value) VALUES ('queue_paused',?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("1" if paused else "0",))


    def provider_cooldown(self) -> Optional[dict]:
        row = self.db.execute("SELECT value FROM runtime_settings WHERE key='provider_cooldown'").fetchone()
        if not row or row[0] == "null":
            return None
        state = json.loads(row[0])
        if (not isinstance(state, dict) or not isinstance(state.get('until'), (int, float))
                or not isinstance(state.get('request_id'), str)
                or type(state.get('retry')) is not bool or type(state.get('reconciled')) is not bool):
            raise RegistrationError("Stato pausa Libero non valido: ripresa bloccata.")
        return state

    def save_provider_cooldown(self, state: Optional[dict]) -> None:
        self.db.execute("INSERT INTO runtime_settings(key,value) VALUES ('provider_cooldown',?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(state),))

    def start_provider_cooldown(self, request_id: str, safe: bool) -> dict:
        self.db.execute('SAVEPOINT provider_block')
        try:
            key = 'provider_retry_count:' + request_id
            row = self.db.execute('SELECT value FROM runtime_settings WHERE key=?', (key,)).fetchone()
            count = (int(row[0]) if row else 0) + 1
            self.db.execute('INSERT INTO runtime_settings(key,value) VALUES (?,?) '
                            'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(count)))
            state = dict(until=time.time() + 300, request_id=request_id,
                         retry=bool(safe and count <= 3), reconciled=False)
            self.save_provider_cooldown(state)
            self.db.execute('RELEASE provider_block')
            return state
        except BaseException:
            self.db.execute('ROLLBACK TO provider_block')
            self.db.execute('RELEASE provider_block')
            raise

    def save(self, request: QueueRequest, username: str, email: str, *, sms_proof=None) -> None:
        previous = self.get(request.request_id)
        if previous:
            if previous[1:3] != (username, email):
                raise RegistrationError("Esiste già un esito locale diverso per questa richiesta.")
            return
        names = ("row", "request_id", "destination_spreadsheet", "destination_sheet",
                 "destination_row", "email_column", "claimed_by", "account_id")
        payload = {name: getattr(request, name) for name in names}
        payload.update(full_name="", status="CREATA_DA_SALVARE")
        self.db.execute('SAVEPOINT outcome_with_tester')
        try:
            self.db.execute("INSERT INTO outcomes(request_id,request_json,username,email) VALUES (?,?,?,?)",
                            (request.request_id, json.dumps(payload), username, email))
            if sms_proof is not None:
                tester_id, verified_at = sms_proof
                if str(tester_id) != request.claimed_by:
                    raise RegistrationError('Il tester della verifica non coincide con quello assegnato.')
                self.testers.credit(request.request_id, tester_id, verified_at)
            self.db.execute('RELEASE outcome_with_tester')
        except BaseException:
            self.db.execute('ROLLBACK TO outcome_with_tester')
            self.db.execute('RELEASE outcome_with_tester')
            raise

    def get(self, request_id: str) -> Any:
        row = self.db.execute("SELECT request_json,username,email,synced FROM outcomes WHERE request_id=?",
                              (request_id,)).fetchone()
        return (QueueRequest(**json.loads(row[0])), row[1], row[2], bool(row[3])) if row else None

    def bind_account(self, request: QueueRequest) -> None:
        previous = self.get(request.request_id)
        if not previous or not compatible_destination(previous[0], request):
            raise RegistrationError("Esito locale incompatibile con la destinazione corrente.")
        if request.account_id and not previous[0].account_id:
            raw = self.db.execute("SELECT request_json FROM outcomes WHERE request_id=?", (request.request_id,)).fetchone()[0]
            payload = json.loads(raw)
            payload["account_id"] = request.account_id
            self.db.execute("UPDATE outcomes SET request_json=? WHERE request_id=?", (json.dumps(payload), request.request_id))

    def ids(self) -> set[str]:
        return {row[0] for row in self.db.execute("SELECT request_id FROM outcomes")}

    def due(self) -> list[str]:
        return [row[0] for row in self.db.execute(
            "SELECT request_id FROM outcomes WHERE synced=0 AND next_try<=? LIMIT 10", (time.time(),))]

    def pending_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM outcomes WHERE synced=0").fetchone()[0]

    def completed(self, request_id: str) -> None:
        self.db.execute("UPDATE outcomes SET synced=1 WHERE request_id=?", (request_id,))

    def defer(self, request_id: str) -> None:
        attempts = self.db.execute("SELECT attempts FROM outcomes WHERE request_id=?", (request_id,)).fetchone()[0]
        delay = min(300, 30 * 2 ** min(attempts, 4))
        self.db.execute("UPDATE outcomes SET attempts=attempts+1,next_try=? WHERE request_id=?",
                        (time.time() + delay, request_id))

    def close(self) -> None:
        self.db.close()


class MessageCleanup:
    """Registro dei soli ID dei messaggi temporanei, mai del loro contenuto."""

    def __init__(self, directory: Optional[Path] = None) -> None:
        path = directory / "telegram-cleanup.sqlite3" if directory else None
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(descriptor)
            path.chmod(0o600)
        self.db = sqlite3.connect(str(path) if path else ":memory:", isolation_level=None)
        self.db.execute("""CREATE TABLE IF NOT EXISTS messages (
            chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
            request_id TEXT NOT NULL, phase TEXT NOT NULL,
            obsolete INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, message_id))""")
        self.lock = asyncio.Lock()
        self.retry_at = 0.0

    def track(self, request_id: str, phase: str, message: Any,
              chat_id: Optional[int] = None, *, obsolete: bool = False) -> None:
        message_id = getattr(message, "message_id", None)
        chat_id = chat_id if chat_id is not None else getattr(message, "chat_id", None)
        if not isinstance(chat_id, int) or not isinstance(message_id, int):
            return
        self.db.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id, message_id) DO UPDATE "
            "SET obsolete=MAX(messages.obsolete, excluded.obsolete)",
            (chat_id, message_id, request_id, phase, int(obsolete)),
        )

    def forget(self, message: Any) -> None:
        self.db.execute("DELETE FROM messages WHERE chat_id=? AND message_id=?",
                        (message.chat_id, message.message_id))

    def mark(self, request_id: str, phase: Optional[str] = None) -> None:
        if phase is None:
            self.db.execute("UPDATE messages SET obsolete=1 WHERE request_id=?", (request_id,))
        else:
            self.db.execute("UPDATE messages SET obsolete=1 WHERE request_id=? AND phase=?",
                            (request_id, phase))

    def recover(self) -> None:
        self.db.execute("UPDATE messages SET obsolete=1")

    async def drain(self, bot: Any) -> None:
        async with self.lock:
            if time.monotonic() < self.retry_at:
                return
            rows = self.db.execute(
                "SELECT chat_id, message_id FROM messages WHERE obsolete=1 LIMIT 40"
            ).fetchall()
            for chat_id, message_id in rows:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=message_id,
                                             read_timeout=5, write_timeout=5, connect_timeout=5)
                except RetryAfter as exc:
                    delay = exc.retry_after
                    seconds = delay.total_seconds() if hasattr(delay, "total_seconds") else float(delay)
                    self.retry_at = time.monotonic() + seconds + 1
                    return
                except (BadRequest, Forbidden):
                    # Messaggio già eliminato, troppo vecchio o permessi insufficienti.
                    LOGGER.warning("Messaggio temporaneo non eliminabile da Telegram")
                except (TelegramError, RuntimeError):
                    self.retry_at = time.monotonic() + 10
                    LOGGER.warning("Pulizia messaggi rinviata per indisponibilità Telegram")
                    return
                self.db.execute("DELETE FROM messages WHERE chat_id=? AND message_id=?",
                                (chat_id, message_id))

    def close(self) -> None:
        self.db.close()


class LocalBackups:
    """Snapshot SQLite verificati; nessuna lettura dei file di credenziali."""

    filenames = ("created-outcomes.sqlite3", "telegram-cleanup.sqlite3")
    pattern = re.compile(r"^(daily|manual)-[0-9]{8}T[0-9]{12}Z-[0-9a-f]{16}\.zip$")

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.directory = self.data_dir / "backups"

    @staticmethod
    def digest(path: Path) -> str:
        result = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                result.update(chunk)
        return result.hexdigest()

    @staticmethod
    def database_info(path: Path, name: str) -> dict:
        # mode=ro evita di creare per errore un database vuoto se la sorgente manca.
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RegistrationError("Database del backup non integro.")
            if name == "created-outcomes.sqlite3":
                db.execute("SELECT request_id,request_json,username,email,synced,attempts,next_try FROM outcomes LIMIT 0")
                db.execute("SELECT key,value FROM runtime_settings LIMIT 0")
                rows, pending = db.execute("SELECT COUNT(*),COALESCE(SUM(synced=0),0) FROM outcomes").fetchone()
                return {"rows": rows, "pending": pending}
            db.execute("SELECT chat_id,message_id,request_id,phase,obsolete FROM messages LIMIT 0")
            return {"rows": db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]}

    @classmethod
    def verify(cls, archive: Path) -> dict:
        with ZipFile(archive, "r") as zipped:
            expected = {*cls.filenames, "manifest.json"}
            if set(zipped.namelist()) != expected or len(zipped.namelist()) != len(expected):
                raise RegistrationError("Contenuto del backup non riconosciuto.")
            if zipped.getinfo("manifest.json").file_size > 65536:
                raise RegistrationError("Manifest del backup non valido.")
            manifest = json.loads(zipped.read("manifest.json"))
            if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
                raise RegistrationError("Manifest del backup non valido.")
            created = manifest.get("created_at")
            if (manifest.get("format") != "mulino-sqlite-backup-v1"
                    or manifest.get("kind") not in {"daily", "manual"}
                    or not isinstance(created, (int, float)) or not 0 < created < 253402300799
                    or set(manifest.get("files", {})) != set(cls.filenames)):
                raise RegistrationError("Manifest del backup non valido.")
            # Non usa extractall: estrae solo i due nomi consentiti in una cartella privata.
            with tempfile.TemporaryDirectory(prefix="mulino-backup-check-") as temporary:
                for name in cls.filenames:
                    item = manifest["files"][name]
                    if not isinstance(item, dict):
                        raise RegistrationError("Manifest del backup non valido.")
                    target = Path(temporary) / name
                    with zipped.open(name) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
                    target.chmod(0o600)
                    if target.stat().st_size != item.get("bytes") or cls.digest(target) != item.get("sha256"):
                        raise RegistrationError("Checksum del backup non valido.")
                    if cls.database_info(target, name) != item.get("database"):
                        raise RegistrationError("Dati del backup non coerenti con il manifest.")
        return {**manifest, "filename": archive.name}

    def candidates(self, kind: str) -> list[Path]:
        if not self.directory.exists():
            return []
        return sorted((p for p in self.directory.iterdir()
            if not p.is_symlink() and p.is_file() and self.pattern.fullmatch(p.name)
            and p.name.startswith(kind + "-")), reverse=True)

    def latest(self, kind: str) -> tuple[Optional[dict], int]:
        invalid = 0
        for path in self.candidates(kind):
            try:
                info = self.verify(path)
                if info["kind"] != kind:
                    raise RegistrationError("Tipo backup non coerente.")
                return info, invalid
            except Exception:
                # Anche errori di decompressione devono permettere il tentativo sulla copia precedente.
                invalid += 1
        return None, invalid

    def prune(self, kind: str) -> bool:
        keep = 14 if kind == "daily" else 3
        valid = []
        ok = True
        for path in self.candidates(kind):
            try:
                if self.verify(path)["kind"] == kind:
                    valid.append(path)
            except Exception:
                # File danneggiati o non riconosciuti non vengono cancellati alla cieca.
                continue
        for path in valid[keep:]:
            try:
                path.unlink()
            except OSError:
                ok = False
        return ok

    def create(self, kind: str) -> dict:
        if kind not in {"daily", "manual"}:
            raise ValueError("Tipo backup non valido")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise RegistrationError("La cartella backup deve essere una directory locale.")
        self.directory.chmod(0o700)
        created = time.time()
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(created)) + f"{int(created % 1 * 1000000):06d}Z"
        filename = f"{kind}-{stamp}-{secrets.token_hex(8)}.zip"
        manifest = {"format": "mulino-sqlite-backup-v1", "kind": kind, "created_at": created, "files": {}}
        deadline = time.monotonic() + 45
        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise TimeoutError("Tempo massimo del backup superato")
        with tempfile.TemporaryDirectory(prefix=".tmp-mulino-", dir=self.directory) as temporary:
            stage = Path(temporary)
            for name in self.filenames:
                source_path = self.data_dir / name
                destination = stage / name
                fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
                with closing(sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as source:
                    with closing(sqlite3.connect(destination)) as target:
                        source.backup(target, pages=256, progress=progress, sleep=0.1)
                manifest["files"][name] = {"bytes": destination.stat().st_size,
                    "sha256": self.digest(destination), "database": self.database_info(destination, name)}
            staged_archive = stage / filename
            with ZipFile(staged_archive, "x", compression=ZIP_DEFLATED) as zipped:
                for name in self.filenames:
                    zipped.write(stage / name, name)
                zipped.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
            staged_archive.chmod(0o600)
            self.verify(staged_archive)
            with staged_archive.open("rb") as archive_file:
                os.fsync(archive_file.fileno())
            final = self.directory / filename
            os.replace(staged_archive, final)
            descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        # Solo dopo aver pubblicato una copia verificata si ruotano quelle precedenti.
        try:
            retention_ok = self.prune(kind)
        except OSError:
            retention_ok = False
        return {**manifest, "filename": filename, "retention_ok": retention_ok}


async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    if (not update.effective_user or not update.effective_chat
            or update.effective_user.id != coordinator.settings.admin_id
            or update.effective_chat.type != ChatType.PRIVATE):
        return
    if context.args not in ([], ["stato"]):
        await update.effective_message.reply_text("Uso: /backup per creare una copia; /backup stato per verificare le ultime copie.")
        return
    if coordinator.backups is None:
        await update.effective_message.reply_text("Backup non disponibile: cartella dati persistente non configurata.")
        return
    if coordinator.backup_lock.locked() or (coordinator.backup_task and not coordinator.backup_task.done()):
        await update.effective_message.reply_text("Operazione di backup gia in corso. Attendi l'esito.")
        return
    await update.effective_message.reply_text("Verifico le ultime copie…" if context.args else "Creo e verifico il backup. Il Mugnaio resta disponibile per SMS e CAPTCHA.")
    coordinator.backup_task = asyncio.create_task(run_backup_command(coordinator, update.effective_message, bool(context.args)))


async def run_backup_command(coordinator: Coordinator, message: Any, status_only: bool,
                             *, panel_revision: Optional[int] = None) -> None:
    async def notify(text: str, *, urgent: bool = False) -> None:
        if panel_revision is None:
            await message.reply_text(text)
        else:
            await finish_panel_backup(coordinator, text, panel_revision, urgent=urgent)
    try:
        async with coordinator.backup_lock:
            if status_only:
                lines = ["Backup locali del registro (copie sul VPS):"]
                for kind, label in (("daily", "Automatico"), ("manual", "Manuale")):
                    info, invalid = await asyncio.to_thread(coordinator.backups.latest, kind)
                    if info:
                        when = datetime.fromtimestamp(info["created_at"]).strftime("%d/%m/%Y %H:%M")
                        lines.append(f"{label}: {when} — integrita verificata.\n{info['filename']}")
                        if time.time() - info["created_at"] > 86400:
                            lines.append("Questa copia ha piu di 24 ore.")
                    else:
                        lines.append(f"{label}: nessuna copia valida disponibile.")
                    if invalid:
                        lines.append(f"Attenzione: {invalid} copie piu recenti non leggibili o non valide.")
                if coordinator.backup_error:
                    lines.append("L'ultimo tentativo di backup ha segnalato un problema. Usa /backup per riprovare.")
                await notify("\n".join(lines))
                return
            coordinator.persist_before_backup()
            info = await asyncio.to_thread(coordinator.backups.create, "manual")
            coordinator.backup_error = not info["retention_ok"]
        rows = info["files"]["created-outcomes.sqlite3"]["database"]["rows"]
        text = (f"✅ Backup creato e verificato: {rows} esiti conservati.\n"
            f"File: {info['filename']}\nCartella dati: backups/\n"
            "Conservazione: 14 copie automatiche e 3 manuali. La copia si trova sul VPS.")
        warning = "La copia e valida, ma non ho completato la pulizia dei vecchi backup. Controlla spazio e permessi del disco."
        if panel_revision is not None:
            await notify(text + ('\n⚠️ ' + warning if not info['retention_ok'] else ''), urgent=not info['retention_ok'])
        else:
            await notify(text)
            if not info['retention_ok']:
                await notify(warning)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        coordinator.backup_error = True
        LOGGER.warning("Operazione backup non completata (%s)", type(exc).__name__)
        try:
            await notify("❌ Operazione di backup non completata. Usa /backup stato per verificare le copie disponibili; controlla lo spazio e i permessi del VPS prima di riprovare.", urgent=True)
        except TelegramError:
            LOGGER.warning("Notifica backup non recapitata")


class Coordinator:
    def __init__(self, settings: Settings, store: GoogleQueueStore) -> None:
        self.settings = settings
        self.store = store
        self.application: Optional[Application] = None
        self.active: Optional[QueueRequest] = None
        self.personal_future: Optional[asyncio.Future[PersonalData]] = None
        self.personal_prompt_id: Optional[int] = None
        self.personal_name_parts: Optional[tuple[str, str]] = None
        self.manual_request_lock = asyncio.Lock()
        self.personal_prompt_ready = asyncio.Event()
        self.personal_invalid_notified = False
        self.personal_last_message_id = 0
        self.phone_future: Optional[asyncio.Future[tuple[str, int]]] = None
        self.otp_future: Optional[asyncio.Future[str]] = None
        self.captcha_future: Optional[asyncio.Future[bool]] = None
        self.final_future: Optional[asyncio.Future[bool]] = None
        self.outcome_review: Optional[dict[str, Any]] = None
        self.cancel_event = asyncio.Event()
        self.processing_task: Optional[asyncio.Task[None]] = None
        self._claim_lock = asyncio.Lock()
        self.recovery_buttons: dict[str, dict[str, Any]] = {}
        self.recovery_lock = asyncio.Lock()
        self.consistency_task: Optional[asyncio.Task] = None
        self.consistency_report: Optional[dict] = None
        self.resend_event = asyncio.Event()
        self.change_tester_event = asyncio.Event()
        self.change_tester_allowed = False
        self.claim_token = ""
        self.assignment_token = ""
        self.assigned_phone = ""
        self.revoked_testers: set[int] = set()
        self.revoked_phones: set[str] = set()
        self.resend_busy = False
        self.last_sms_request_at = float("-inf")
        self.tester_sms_deadline: Optional[float] = None
        self.tester_change_reason = "manual"
        self.messages = MessageCleanup(getattr(settings, "data_dir", None))
        self.outcomes = CreatedOutcomes(getattr(settings, "data_dir", None))
        self.outcomes.db.execute("""CREATE TABLE IF NOT EXISTS recovery_ignored (
            request_id TEXT PRIMARY KEY, signature TEXT NOT NULL)""")
        self.paused = self.outcomes.queue_paused()
        self.provider_cooldown = self.outcomes.provider_cooldown()
        self.provider_deadline = time.monotonic() + max(0, self.provider_cooldown['until'] - time.time()) if self.provider_cooldown else 0
        self.pause_persisted = True
        self.created_in_memory: dict[str, Any] = {}
        self.sms_verified: dict[str, tuple[int, str]] = {}
        self._sync_lock = asyncio.Lock()
        self.recovery_pending = False
        data_dir = getattr(settings, "data_dir", None)
        self.backups = LocalBackups(data_dir) if data_dir is not None else None
        self.backup_lock = asyncio.Lock()
        self.backup_task: Optional[asyncio.Task] = None
        self.backup_error = False
        self.backup_notice_at = float("-inf")
        self.panel_sessions = PanelSessions()
        self.panel = ReusablePanel(self.outcomes.db, settings.admin_id)
        self.health = RuntimeHealth('mugnaio', '/tmp/mulino-health/status.json')
        self.health.snapshot = self.health_snapshot
        self.last_queue_ok = None
        self.monitor_browser: Optional[RegistrationBrowser] = None

    async def health_snapshot(self) -> dict[str, bool]:
        session = self.monitor_browser
        expected = session is not None
        browser_ok = True
        if session is not None:
            try:
                browser_ok = bool(session.browser and session.browser.is_connected()
                                  and session.page and not session.page.is_closed())
                if browser_ok:
                    await asyncio.wait_for(session.page.title(), timeout=5)
            except Exception:
                browser_ok = False
        queue_task = self.application.bot_data.get('queue_task') if self.application else None
        queue_ok = bool(queue_task and not queue_task.done() and self.last_queue_ok is not None
                        and 0 <= time.monotonic() - self.last_queue_ok
                        < max(180, getattr(self.settings, 'poll_seconds', 10) * 3))
        waiting = any(future is not None and not future.done() for future in
                      (self.personal_future, self.phone_future, self.otp_future,
                       self.captcha_future, self.final_future)) or self.outcome_review is not None
        return dict(paused=bool(self.paused), busy=self.registration_busy(),
                    human_wait=bool(waiting), queue_ok=queue_ok,
                    browser_expected=expected, browser_ok=browser_ok)

    def persist_before_backup(self) -> None:
        # La connessione SQLite del coordinator rimane nel thread principale.
        for request, username, email in list(self.created_in_memory.values()):
            self.record_created(request, username, email)

    async def backup_tick(self) -> None:
        if self.backups is None or self.backup_lock.locked():
            return
        async with self.backup_lock:
            latest, invalid = await asyncio.to_thread(self.backups.latest, "daily")
            if latest and not invalid and 0 <= time.time() - latest["created_at"] < 86400:
                return
            self.persist_before_backup()
            info = await asyncio.to_thread(self.backups.create, "daily")
            self.backup_error = not info["retention_ok"]
            if not info["retention_ok"]:
                raise RegistrationError("Rotazione dei backup da verificare")

    async def backup_loop(self) -> None:
        while True:
            try:
                await self.backup_tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.backup_error = True
                LOGGER.warning("Backup automatico non completato (%s)", type(exc).__name__)
                if time.monotonic() - self.backup_notice_at >= 21600:
                    self.backup_notice_at = time.monotonic()
                    try:
                        await self.bot.send_message(chat_id=self.settings.admin_id,
                            text="⚠️ Backup automatico non completato o rotazione da verificare. "
                            "Il Mugnaio continua a funzionare. Controlla spazio/permessi del VPS e usa /backup stato.")
                    except TelegramError:
                        pass
            await asyncio.sleep(900)

    def set_paused(self, paused: bool) -> None:
        if paused:
            # Blocca subito anche se il disco non consente di salvare la preferenza.
            self.paused = True
            self.pause_persisted = False
        try:
            self.outcomes.set_queue_paused(paused)
        except Exception:
            raise RegistrationError(
                "Pausa attiva solo in memoria: non riesco a salvarla sul VPS. "
                "Non riavviare per aggiornare; riprova /pausa."
                if paused else "Ripresa non completata: non riesco a salvare la preferenza. Controlla /stato."
            ) from None
        self.paused = paused
        self.pause_persisted = True

    def provider_waiting(self) -> bool:
        return time.monotonic() < self.provider_deadline

    async def reconcile_provider_cooldown(self) -> None:
        state = self.provider_cooldown
        if not state:
            return
        if not state['reconciled']:
            request = await asyncio.to_thread(self.store.find_request, state['request_id'])
            retry = False
            if (request and request.request_id not in self.outcomes.ids()
                    and request.request_id not in self.created_in_memory
                    and request.status not in {'CREATA', 'CREATA_DA_SALVARE', 'ANNULLATA'}):
                retry = state['retry']
                if retry:
                    try:
                        await asyncio.to_thread(self.store.validate_start, request)
                    except RegistrationError:
                        retry = False
                async with self._claim_lock:
                    await self.set_queue_fields(request,
                        STATO='DA_COMPLETARE_ANAGRAFICA' if retry else 'ERRORE',
                        TELEGRAM_ASSEGNATO='', TELEFONO_MASCHERATO='', MESSAGGIO_GRUPPO_ID='',
                        ERRORE='Libero: attività anomala; attesa di 5 minuti',
                        NOTE=('Tentativo rifiutato da Libero; ripresa dopo la pausa automatica'
                              if retry else 'Verificare esito o blocco ripetuto con /recupera prima di riprovare'))
            next_state = dict(state, reconciled=True, retry=retry)
            self.outcomes.save_provider_cooldown(next_state)
            self.provider_cooldown = state = next_state
        if not self.provider_waiting():
            self.outcomes.save_provider_cooldown(None)
            self.provider_cooldown = None

    async def handle_provider_cooldown(self, request: QueueRequest, exc: RegistrationProviderCooldown) -> None:
        self.invalidate_phone_session()
        self.provider_deadline = time.monotonic() + 300
        try:
            safe = (exc.safe_to_retry and request.request_id not in self.sms_verified
                    and request.request_id not in self.outcomes.ids()
                    and request.request_id not in self.created_in_memory)
            self.provider_cooldown = self.outcomes.start_provider_cooldown(request.request_id, safe)
        except Exception:
            self.set_paused(True)
            await self.safe_notice(self.settings.admin_id,
                '⚠️ Libero ha bloccato il tentativo. Pausa di sicurezza: non riesco a salvare il timer. Controlla /stato.')
            raise
        if request.claimed_by:
            await self.safe_notice(int(request.claimed_by),
                '⌛ Libero ha interrotto questo tentativo. Non inviare altri codici; il bot attende prima di riprendere.')
        await self.reconcile_provider_cooldown()
        await self.safe_notice(self.settings.admin_id,
            '⌛ Libero segnala attività anomala. Tentativo chiuso; attendo almeno 5 minuti prima di avviare altre registrazioni.\n'
            + ('La richiesta interrotta resta in coda e ripartirà con l’Apprendista.'
               if self.provider_cooldown and self.provider_cooldown['retry'] else
               'Questa richiesta richiede verifica con /recupera: esito incerto o limite di tre riprese automatiche raggiunto.')
            + '\nUna tua /pausa resta valida anche dopo il timer; /riprendi non accorcia l’attesa.')

    def queue_status_text(self) -> str:
        wait = (f"\nAttesa Libero: {max(1, int(self.provider_deadline - time.monotonic()) + 1)} secondi."
                if self.provider_waiting() else '')
        if not self.paused:
            return "Coda: ATTIVA." + wait
        if not self.pause_persisted:
            return "Coda: IN PAUSA solo in memoria; pausa non salvata sul VPS." + wait
        return "Coda: IN PAUSA (salvata anche per i riavvii)." + wait

    def registration_busy(self) -> bool:
        return self.active is not None or bool(self.processing_task and not self.processing_task.done())

    async def next_request_unless_paused(self) -> Optional[QueueRequest]:
        if self.paused or self.provider_waiting() or (self.provider_cooldown and not self.provider_cooldown["reconciled"]):
            return None
        request = await asyncio.to_thread(self.store.next_request)
        # /pausa puo arrivare mentre Google Sheets risponde nel thread.
        return None if self.paused or self.provider_waiting() else request

    def record_created(self, request: QueueRequest, username: str, email: str) -> None:
        self.created_in_memory[request.request_id] = (request, username, email)
        self.outcomes.save(request, username, email, sms_proof=self.sms_verified.get(request.request_id))
        self.created_in_memory.pop(request.request_id, None)
        self.sms_verified.pop(request.request_id, None)

    def mark_sms_verified(self, request: QueueRequest) -> None:
        # Success page after an OTP submitted by the currently assigned tester.
        tester = int(request.claimed_by) if request.claimed_by.isdecimal() else 0
        if (self.active is not request or not TesterLedger.valid_id(tester)
                or not self.assigned_phone or tester in self.revoked_testers):
            raise RegistrationError('Verifica SMS senza un tester valido: attribuzione bloccata.')
        self.sms_verified[request.request_id] = (tester, TesterLedger.now())

    async def safe_notice(self, chat_id: int, text: str) -> None:
        try:
            await self.bot.send_message(chat_id=chat_id, text=text)
        except TelegramError:
            LOGGER.warning("Notifica non recapitata; esito della creazione conservato")

    async def sync_outcome(self, request_id: str, *, force: bool = False) -> bool:
        async with self._sync_lock:
            saved = self.outcomes.get(request_id)
            if not saved:
                return False
            recorded, username, email, synced = saved
            if synced and not force:
                return True
            try:
                current = await asyncio.to_thread(self.store.find_request, request_id)
                if current is None:
                    raise RegistrationError("Richiesta non trovata nella coda")
                if not compatible_destination(recorded, current):
                    raise RegistrationError("Destinazione modificata: verificare la coda")
                if current.account_id and not recorded.account_id:
                    await asyncio.to_thread(self.store.validate_audit_restore, current, email)
                    self.outcomes.bind_account(current)
                await asyncio.to_thread(self.store.write_created_email, current, email, username)
            except Exception as exc:
                self.outcomes.defer(request_id)
                LOGGER.warning("Salvataggio Sheets rinviato per richiesta %s (%s)", request_id, type(exc).__name__)
                return False
            self.outcomes.completed(request_id)
            if not synced:
                await self.safe_notice(self.settings.admin_id,
                    (f"✅ Libero Mail creata:\n{email}\nSalvata nello storico delle richieste manuali."
                     if is_manual_request(current, getattr(self.settings, "spreadsheet_id", "")) else
                     f"✅ Libero Mail creata e inserita nel foglio:\n{email}"))
            return True

    async def restore_audited_outcome(self, request: QueueRequest) -> None:
        # Condivide il lock con i salvataggi ordinari, ma rilegge anche nome e Coda.
        async with self._sync_lock:
            saved = self.outcomes.get(request.request_id)
            if not saved or not compatible_destination(saved[0], request):
                raise RegistrationError("Esito assente o destinazione diversa dal registro VPS: ripristino bloccato.")
            if self.active and self.active.request_id == request.request_id:
                raise RegistrationError("Richiesta ancora attiva: attendi la conclusione e ripeti /controlla.")
            await asyncio.to_thread(self.store.validate_audit_restore, request, saved[2])
            self.outcomes.bind_account(request)
            await asyncio.to_thread(self.store.write_created_email, request, saved[2], saved[1])
            self.outcomes.completed(request.request_id)

    async def sync_pending_outcomes(self) -> None:
        for request, username, email in list(self.created_in_memory.values()):
            self.record_created(request, username, email)
        for request_id in self.outcomes.due():
            await self.sync_outcome(request_id)

    @property
    def bot(self):
        if not self.application:
            raise RuntimeError("Applicazione Telegram non inizializzata")
        return self.application.bot

    async def set_queue_fields(self, request: QueueRequest, **fields: Any) -> None:
        await asyncio.to_thread(self.store.update, request, **fields)

    async def send_temporary(self, request: QueueRequest, phase: str, **kwargs: Any) -> Any:
        message = await self.bot.send_message(**kwargs)
        self.messages.track(request.request_id, phase, message, kwargs.get("chat_id"),
                            obsolete=self.active is not request)
        return message

    async def reply_temporary(self, request: QueueRequest, phase: str,
                              original: Any, text: str) -> None:
        message = await original.reply_text(text)
        self.messages.track(request.request_id, phase, message,
                            obsolete=self.active is not request)

    async def cleanup_messages(self, request: QueueRequest, phase: Optional[str] = None) -> None:
        self.messages.mark(request.request_id, phase)
        await self.messages.drain(self.bot)

    async def delete_input(self, request: QueueRequest, message: Any) -> None:
        self.messages.track(request.request_id, "input", message, obsolete=True)
        try:
            await message.delete()
        except TelegramError:
            return  # Il registro conserva l'ID per la successiva pulizia.
        if isinstance(getattr(message, "chat_id", None), int):
            self.messages.forget(message)

    async def loop(self) -> None:
        while True:
            try:
                await self.sync_pending_outcomes()
                if self.recovery_pending:
                    await asyncio.to_thread(self.store.recover_interrupted, self.outcomes.ids())
                    self.recovery_pending = False
                await self.reconcile_provider_cooldown()
                if not self.processing_task or self.processing_task.done():
                    if self.processing_task:
                        try:
                            self.processing_task.result()
                        except Exception:
                            LOGGER.exception("Task di registrazione terminato con errore")
                    self.processing_task = None
                    request = await self.next_request_unless_paused()
                    if request:
                        if request.request_id in self.outcomes.ids():
                            if self.outcomes.get(request.request_id)[3]:
                                await self.sync_outcome(request.request_id, force=True)
                            self.last_queue_ok = time.monotonic()
                            await asyncio.sleep(self.settings.poll_seconds)
                            continue
                        self.processing_task = asyncio.create_task(
                            self.process_request(request),
                            name=f"request-{request.request_id}",
                        )
                await asyncio.sleep(self.settings.poll_seconds)
                await self.messages.drain(self.bot)
                await self.panel.cleanup.drain(self.bot, lambda: self.panel.message_id(self.bot.id))
                self.last_queue_ok = time.monotonic()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Errore nel controllo della coda")
                await asyncio.sleep(max(10, self.settings.poll_seconds))

    async def process_request(self, request: QueueRequest) -> None:
        # Protegge anche il task selezionato ma non ancora iniziato.
        if self.paused or self.provider_waiting() or (self.provider_cooldown and not self.provider_cooldown["reconciled"]):
            return
        if request.request_id in self.outcomes.ids() or request.request_id in self.created_in_memory:
            await self.sync_pending_outcomes()
            return
        self.active = request
        self.sms_verified.pop(request.request_id, None)
        self.change_tester_event.clear()
        self.change_tester_allowed = False
        self.claim_token = self.assignment_token = self.assigned_phone = ""
        self.revoked_testers.clear()
        self.revoked_phones.clear()
        self.resend_event.clear()
        self.resend_busy = False
        self.last_sms_request_at = float("-inf")
        self.tester_sms_deadline: Optional[float] = None
        self.tester_change_reason = "manual"
        self.cancel_event = asyncio.Event()
        self.personal_future = asyncio.get_running_loop().create_future()
        self.personal_name_parts = None
        try:
            if request.account_id:
                await asyncio.to_thread(self.store.validate_start, request)
            if is_manual_request(request, getattr(self.settings, "spreadsheet_id", "")):
                self.personal_name_parts = await asyncio.to_thread(self.store.manual_name_parts, request)
            await self.set_queue_fields(
                request,
                STATO="ATTESA_ANAGRAFICA",
                ERRORE="",
                NOTE="In attesa dei dati reali dall'amministratore",
            )
            personal = await self.request_personal_data(request)
            await self.set_queue_fields(
                request,
                STATO="IN_CREAZIONE",
                NOTE="Dati anagrafici ricevuti; avvio browser",
            )
            username, email = await RegistrationBrowser(
                self.settings, self
            ).create_account(request, personal)
            self.record_created(request, username, email)
            if not await self.sync_outcome(request.request_id):
                await self.safe_notice(self.settings.admin_id,
                    f"✅ Casella creata: {email}\n"
                    "⏳ Esito salvato sul VPS. La scrittura su Google Sheets è in attesa. "
                    "Riproverò automaticamente soltanto il salvataggio. Non usare /riprova.")
            if request.claimed_by:
                await self.safe_notice(int(request.claimed_by),
                    "✅ Registrazione completata. Grazie per il codice.")
        except RegistrationProviderCooldown as exc:
            await self.handle_provider_cooldown(request, exc)
        except RequestCancelled as exc:
            await self.set_queue_fields(
                request, STATO="ANNULLATA", ERRORE=str(exc), NOTE=""
            )
        except Exception as exc:
            if request.request_id in self.outcomes.ids() or request.request_id in self.created_in_memory:
                await self.safe_notice(self.settings.admin_id,
                    "⚠️ Casella già creata: il completamento del salvataggio richiede attenzione. "
                    "Non ripetere la registrazione. Il bot ritenta il salvataggio disponibile.")
                return
            if isinstance(exc, RegistrationSessionReset):
                self.invalidate_phone_session()
                if request.claimed_by:
                    await self.safe_notice(int(request.claimed_by),
                        "⌛ La sessione di Libero è scaduta o ripartita dall'inizio. "
                        "Questo tentativo è stato interrotto: non attendere né inviare altri codici. "
                        "L'amministratore verificherà l'esito.")
            error_text = (
                redact_secrets(str(exc))
                if isinstance(exc, RegistrationError)
                else f"Errore tecnico: {type(exc).__name__}"
            )
            LOGGER.error("Registrazione %s fallita (%s)", request.request_id, type(exc).__name__)
            # Attendere eventuali scritture di un claim iniziato prima del reset.
            async with self._claim_lock:
                await self.set_queue_fields(
                    request,
                    STATO="ERRORE",
                    ERRORE=error_text[:500],
                    NOTE="Verificare se la casella esiste; usare /recupera prima di riprovare",
                )
            await self.bot.send_message(
                chat_id=self.settings.admin_id,
                text=(
                    "⚠️ Esito della registrazione Libero da verificare\n\n"
                    f"ID: {request.request_id}\n"
                    f"Errore: {error_text[:1000]}\n\n"
                    "Controlla prima se la casella esiste già. Usa /recupera: "
                    "se hai verificato l'accesso scegli Casella già creata. "
                    "Ripeti la registrazione solo se la casella non è stata creata."
                ),
            )
        finally:
            self.personal_future = None
            self.personal_name_parts = None
            self.personal_prompt_id = None
            self.personal_prompt_ready.set()
            self.phone_future = None
            self.change_tester_event.clear()
            self.change_tester_allowed = False
            self.claim_token = self.assignment_token = self.assigned_phone = ""
            self.revoked_testers.clear()
            self.revoked_phones.clear()
            self.otp_future = None
            self.tester_sms_deadline = None
            self.tester_change_reason = "manual"
            self.resend_event.clear()
            self.resend_busy = False
            self.captcha_future = None
            self.final_future = None
            self.active = None
            self.cancel_event.clear()
            await self.cleanup_messages(request)
            if self.paused:
                await self.safe_notice(self.settings.admin_id,
                    "⏸ La richiesta e terminata. La coda resta in pausa. "
                    + ("Ora puoi aggiornare il programma; al termine usa /riprendi."
                       if self.pause_persisted else "La pausa non e salvata: riprova /pausa prima di riavviare."))

    async def request_personal_data(self, request: QueueRequest) -> PersonalData:
        self.personal_prompt_id = None
        self.personal_prompt_ready.clear()
        self.personal_invalid_notified = False
        self.personal_last_message_id = 0
        group_id = getattr(self.settings, "anagrafica_group_id", 0)
        text = (
            "🪪 Nuova registrazione Libero da completare\n\n" +
            (f"Nome: {self.personal_name_parts[0]}\nCognome: {self.personal_name_parts[1]}\n\n"
             if self.personal_name_parts else f"Nome presente nel foglio: {request.full_name}\n\n") +
            "Invia:\nGG/MM/AAAA | M/F | Città (Provincia)\n\n"
            "Se devo correggere la separazione Nome/Cognome:\n"
            "Nome | Cognome | GG/MM/AAAA | M/F | Città (Provincia)\n\n"
            "I dati saranno usati solo per questa registrazione e non salvati."
        )
        if group_id:
            text = (
                "@Apprendista_Mugnaio_bot\n" + text +
                f"\n\nID richiesta: {request.request_id}\n"
                "Rispondi direttamente a QUESTO messaggio con i dati nel formato indicato, "
                "senza testo aggiuntivo."
            )
        try:
            prompt = await self.send_temporary(request, "personal",
                chat_id=group_id or self.settings.admin_id, text=text)
            self.personal_prompt_id = prompt.message_id
        finally:
            # Una risposta istantanea può precedere il ritorno di send_message.
            self.personal_prompt_ready.set()
        personal = await self._wait_future(self.personal_future)
        await self.cleanup_messages(request, "personal")
        return personal

    async def _wait_future(self, future: asyncio.Future[Any], *, ready_check: Any = None) -> Any:
        cancel_task = asyncio.create_task(self.cancel_event.wait())
        try:
            while True:
                if self.cancel_event.is_set():
                    if not future.done():
                        future.cancel()
                    raise RequestCancelled("Richiesta annullata dall'amministratore")
                if ready_check is not None:
                    await ready_check()
                if self.cancel_event.is_set():
                    raise RequestCancelled("Richiesta annullata dall'amministratore")
                if future.done():
                    return future.result()
                await asyncio.wait({future, cancel_task},
                    timeout=2 if ready_check is not None else None,
                    return_when=asyncio.FIRST_COMPLETED)
        except (RegistrationSessionReset, RegistrationProviderCooldown):
            self.invalidate_phone_session()
            raise
        finally:
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)

    def invalidate_phone_session(self) -> None:
        # Invalida prima delle attese di rete, inclusi claim/reinvii in arrivo.
        self.claim_token = self.assignment_token = ""
        self.change_tester_allowed = False
        self.tester_sms_deadline = None
        self.resend_event.clear()
        for future in (self.phone_future, self.otp_future):
            if future is not None and not future.done():
                future.cancel()

    async def request_phone(self, request: QueueRequest, *, ready_check: Any = None) -> tuple[str, int]:
        self.phone_future = asyncio.get_running_loop().create_future()
        self.claim_token = secrets.token_hex(4)
        await self.set_queue_fields(
            request,
            STATO="ATTESA_UTENTE",
            NOTE="In attesa del primo whitelistato",
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Usa il mio numero", callback_data=f"claim:{request.request_id}:{self.claim_token}")]]
        )
        message = await self.send_temporary(request, "claim",
            chat_id=self.settings.group_chat_id,
            text=(
                "📱 Serve un numero di telefono per completare una registrazione.\n"
                "Chi è disponibile a ricevere il codice?"
            ),
            reply_markup=keyboard,
        )
        await self.set_queue_fields(
            request,
            MESSAGGIO_GRUPPO_ID=str(message.message_id),
        )
        result = await self._wait_future(self.phone_future, ready_check=ready_check)
        await self.cleanup_messages(request, "claim")
        await self.show_tester_control(request)
        return result

    async def claim_phone(self, telegram_id: int, *, token: Optional[str] = None) -> tuple[bool, str]:
        async with self._claim_lock:
            request = self.active
            if not request or request.status != "ATTESA_UTENTE" or not self.phone_future:
                return False, "Questa richiesta non è più disponibile."
            if token is not None and token != self.claim_token:
                return False, "Questa richiesta al gruppo è stata sostituita."
            if telegram_id in self.revoked_testers:
                return False, "La tua assegnazione è stata revocata per questa registrazione."
            if self.phone_future.done():
                return False, "La richiesta è già stata presa in carico."
            claim_future, claim_token = self.phone_future, self.claim_token
            def still_available():
                return (self.active is request and self.phone_future is claim_future
                        and not claim_future.done() and self.claim_token == claim_token)
            whitelist = await asyncio.to_thread(self.store.whitelist_map)
            if not still_available():
                return False, "La sessione non è più disponibile."
            phone = whitelist.get(telegram_id)
            if not phone:
                return False, "Il tuo Telegram ID non è presente nella whitelist."
            if self.phone_key(phone) in self.revoked_phones:
                return False, "Per questa richiesta serve un numero diverso dal precedente."
            try:
                await self.send_temporary(request, "availability",
                    chat_id=telegram_id,
                    text="📱 Disponibilità ricevuta. Attendi qui la richiesta del codice SMS.",
                )
            except (Forbidden, BadRequest):
                return False, "Apri prima la chat privata del bot e premi Avvia, poi riprova."
            if not still_available():
                return False, "La sessione non è più disponibile."
            await self.set_queue_fields(
                request,
                TELEGRAM_ASSEGNATO=str(telegram_id),
                TELEFONO_MASCHERATO=mask_phone(phone),
                NOTE="Numero preso in carico",
            )
            if not still_available():
                return False, "La sessione non è più disponibile."
            self.assignment_token = secrets.token_hex(4)
            self.assigned_phone = phone
            self.phone_future.set_result((phone, telegram_id))
            return True, "Numero preso in carico. Ti scriverò in privato."

    @staticmethod
    def phone_key(phone: str) -> str:
        digits = re.sub(r"\D", "", phone)
        if digits.startswith("0039"):
            digits = digits[4:]
        elif len(digits) == 12 and digits.startswith("39"):
            digits = digits[2:]
        return digits

    async def show_tester_control(self, request: QueueRequest) -> None:
        await self.cleanup_messages(request, "tester_control")
        self.change_tester_allowed = True
        await self.send_temporary(request, "tester_control",
            chat_id=self.settings.admin_id,
            text="📱 Tester assegnato. Se non è disponibile, puoi richiedere il cambio. "
                 "Dopo l'invio del numero il cambio dipende dalle opzioni disponibili su Libero.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                "🔄 Cambia tester", callback_data=f"tester:{request.request_id}:{self.assignment_token}"
            )]]),
        )

    def queue_tester_change(self, request_id: str, telegram_id: int, token: str) -> tuple[bool, str]:
        request = self.active
        if telegram_id != self.settings.admin_id:
            return False, "Operazione riservata all'amministratore."
        if (not request or request.request_id != request_id or not token
                or token != self.assignment_token or not request.claimed_by):
            return False, "Assegnazione non più attiva."
        if self.change_tester_event.is_set():
            return False, "Cambio già richiesto: attendi."
        if (not self.change_tester_allowed or self.resend_busy or self.resend_event.is_set()
                or request.status not in {"ATTESA_UTENTE", "ATTESA_CODICE"}
                or (self.otp_future is not None and self.otp_future.done())):
            return False, "Cambio non disponibile durante l'invio o la verifica del codice."
        self.change_tester_event.set()
        return True, "Cambio richiesto. Attendi la nuova richiesta o le istruzioni del bot."

    async def revoke_tester(self, request: QueueRequest) -> None:
        old_id = int(request.claimed_by) if request.claimed_by else None
        if old_id is not None:
            self.revoked_testers.add(old_id)
        if self.assigned_phone:
            self.revoked_phones.add(self.phone_key(self.assigned_phone))
        # Invalida localmente prima di qualsiasi attesa di rete.
        self.change_tester_allowed = False
        self.assignment_token = self.claim_token = self.assigned_phone = ""
        self.tester_sms_deadline = None
        automatic = self.tester_change_reason == "timeout"
        self.tester_change_reason = "manual"
        request.claimed_by = ""
        self.phone_future = None
        if self.otp_future is not None and not self.otp_future.done():
            self.otp_future.cancel()
        self.otp_future = None
        self.resend_event.clear()
        self.change_tester_event.clear()
        await self.set_queue_fields(request, STATO="IN_CREAZIONE", TELEGRAM_ASSEGNATO="",
                                    TELEFONO_MASCHERATO="", MESSAGGIO_GRUPPO_ID="",
                                    NOTE=("Cambio tester automatico: 5 minuti senza codice" if automatic else
                                          "Cambio tester richiesto dall'amministratore"))
        for phase in ("otp", "availability", "tester_control", "claim"):
            await self.cleanup_messages(request, phase)
        if old_id is not None:
            await self.safe_notice(old_id,
                ("⌛ Sono trascorsi 5 minuti senza codice: passo a un altro tester. " if automatic else
                 "ℹ️ L'amministratore ha richiesto un altro tester. ") +
                "Non inviare altri codici per questa registrazione.")

    async def notify_otp_sent(
        self, request: QueueRequest, telegram_id: int, phone: str
    ) -> None:
        if self.otp_future is None:
            self.otp_future = asyncio.get_running_loop().create_future()
        # Parte dal primo invio di questa assegnazione, prima delle attese Telegram/Sheets.
        self.last_sms_request_at = asyncio.get_running_loop().time()
        self.tester_sms_deadline = self.last_sms_request_at + 300
        await self.set_queue_fields(request, STATO="ATTESA_CODICE")
        await self.send_temporary(request, "otp",
            chat_id=telegram_id,
            text=(
                f"📨 Invio del codice richiesto al numero {mask_phone(phone)}.\n\n"
                "Rispondi qui in privato scrivendo soltanto il codice ricevuto. "
                "Se non arriva, dopo 20 secondi puoi chiedere il reinvio con il pulsante. "
                "Dopo 5 minuti dal primo invio, senza codice ricevuto, cambio tester. "
                "Il reinvio non prolunga questo limite."
            ),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                "📨 Invia di nuovo SMS", callback_data=f"resend:{request.request_id}:{self.assignment_token}"
            )]]),
        )
        await self.cleanup_messages(request, "availability")
        await self.show_tester_control(request)

    async def retry_otp(self, request: QueueRequest, *, expired: bool) -> None:
        # Chiamato solo dopo un rifiuto esplicito del sito. Mai riutilizzare
        # il Future completato (e quindi il codice rifiutato).
        self.otp_future = asyncio.get_running_loop().create_future()
        self.resend_event.clear()
        await self.cleanup_messages(request, "otp")
        await self.set_queue_fields(request, STATO="ATTESA_CODICE")
        text = (
            "⌛ Libero segnala che il codice è scaduto. Premi Invia di nuovo SMS "
            "e rispondi qui con il nuovo codice."
            if expired else
            "⚠️ Libero non ha accettato il codice. Controlla l'ultimo SMS e "
            "invia nuovamente il codice corretto, rispettando maiuscole e minuscole. "
            "Puoi anche richiedere un nuovo SMS con il pulsante."
        )
        await self.send_temporary(request, "otp", chat_id=int(request.claimed_by),
            text=text + "\nLa registrazione resta aperta. Tra due richieste SMS devono passare almeno 20 secondi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                "📨 Invia di nuovo SMS", callback_data=f"resend:{request.request_id}:{self.assignment_token}"
            )]]),
        )

        await self.show_tester_control(request)

    def tester_sms_expired(self) -> bool:
        return (self.tester_sms_deadline is not None
                and asyncio.get_running_loop().time() >= self.tester_sms_deadline)

    def queue_sms_resend(self, request_id: str, telegram_id: int, *, token: Optional[str] = None) -> tuple[bool, str]:
        request = self.active
        if not request or request.request_id != request_id:
            return False, "Richiesta non più attiva."
        if token is not None and token != self.assignment_token:
            return False, "Pulsante di una precedente assegnazione."
        if self.change_tester_event.is_set() or self.tester_sms_expired():
            return False, "Cambio tester in corso."
        if str(request.claimed_by) != str(telegram_id):
            return False, "Pulsante riservato al tester assegnato."
        if request.status != "ATTESA_CODICE" or self.otp_future is None or self.otp_future.done():
            return False, "Il reinvio non è disponibile in questo passaggio."
        if self.resend_busy or self.resend_event.is_set():
            return False, "Reinvio già richiesto: attendi."
        remaining = 20 - (asyncio.get_running_loop().time() - self.last_sms_request_at)
        if remaining > 0:
            return False, f"Attendi ancora {int(remaining) + 1} secondi."
        self.resend_event.set()
        return True, "Reinvio richiesto. Attendi il messaggio del bot."

    async def request_otp(self, request: QueueRequest, *, resend: Any = None, ready_check: Any = None) -> str:
        # Un codice può arrivare prima che il browser rilevi il campo OTP.
        # Il risultato già ricevuto non deve essere sostituito da un nuovo Future.
        if self.otp_future is None:
            self.otp_future = asyncio.get_running_loop().create_future()
        await self.set_queue_fields(request, STATO="ATTESA_CODICE")
        cancel_task = asyncio.create_task(self.cancel_event.wait())
        resend_task = None
        change_task = asyncio.create_task(self.change_tester_event.wait())
        try:
            while True:
                if self.cancel_event.is_set():
                    raise RequestCancelled("Richiesta annullata dall'amministratore")
                if ready_check is not None:
                    await ready_check()
                if resend is not None:
                    resend_task = asyncio.create_task(self.resend_event.wait())
                waiting = {self.otp_future, cancel_task, change_task}
                if resend_task is not None:
                    waiting.add(resend_task)
                remaining = (None if self.tester_sms_deadline is None else
                             max(0, self.tester_sms_deadline - asyncio.get_running_loop().time()))
                if ready_check is not None:
                    remaining = min(2, remaining) if remaining is not None else 2
                await asyncio.wait(waiting, timeout=remaining,
                                   return_when=asyncio.FIRST_COMPLETED)
                # Annullamento prima di tutto; un codice già accettato non va perso.
                if self.cancel_event.is_set():
                    raise RequestCancelled("Richiesta annullata dall'amministratore")
                if ready_check is not None:
                    await ready_check()
                if self.otp_future.done():
                    self.change_tester_event.clear()
                    return self.otp_future.result()
                if self.change_tester_event.is_set():
                    raise TesterChangeRequested()
                if self.tester_sms_expired():
                    # Invalida subito l'accettazione dei codici, prima di attese di rete.
                    self.tester_change_reason = "timeout"
                    self.change_tester_allowed = False
                    self.change_tester_event.set()
                    try:
                        await self.send_temporary(request, "progress",
                            chat_id=self.settings.admin_id,
                            text="⌛ Nessun codice ricevuto entro 5 minuti. Avvio il cambio tester. "
                                 "Procedo solo se Libero permette di modificare il numero in sicurezza.")
                    except TelegramError:
                        LOGGER.warning("Avviso di cambio tester automatico non recapitato")
                    raise TesterChangeRequested()
                if not self.resend_event.is_set():
                    if resend_task is not None:
                        resend_task.cancel()
                        await asyncio.gather(resend_task, return_exceptions=True)
                        resend_task = None
                    continue
                self.resend_event.clear()
                self.resend_busy = True
                self.last_sms_request_at = asyncio.get_running_loop().time()
                try:
                    await resend()
                    text = (
                        "📨 Ho premuto Invia di nuovo sul sito. "
                        "Attendi il nuovo SMS e rispondi qui soltanto con il nuovo codice."
                    )
                except (RegistrationSessionReset, RegistrationProviderCooldown):
                    raise  # Un reset non è un reinvio dall'esito incerto.
                except (RegistrationError, PlaywrightTimeoutError):
                    if ready_check is not None:
                        await ready_check()
                    text = (
                        "⚠️ Non posso confermare il reinvio sul sito. "
                        "Attendi un eventuale SMS; se non arriva, avvisa l'amministratore."
                    )
                finally:
                    self.resend_busy = False
                await self.send_temporary(request, "otp", chat_id=int(request.claimed_by), text=text)
                if resend_task is not None:
                    resend_task.cancel()
                    await asyncio.gather(resend_task, return_exceptions=True)
                    resend_task = None
        except (RegistrationSessionReset, RegistrationProviderCooldown):
            self.invalidate_phone_session()
            raise
        finally:
            self.resend_event.clear()
            self.change_tester_allowed = False
            tasks = [task for task in (cancel_task, resend_task, change_task) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.cleanup_messages(request, "otp")
            await self.cleanup_messages(request, "tester_control")

    async def wait_for_manual_captcha(
        self, request: QueueRequest, *, instructions: Optional[str] = None,
        ready_check: Any = None,
    ) -> None:
        self.captcha_future = asyncio.get_running_loop().create_future()
        label = ("🔎 Ricontrolla" if ready_check is not None else
                 "✅ Ho completato il passaggio" if instructions else "✅ CAPTCHA completato")
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(label, callback_data=f"captcha:{request.request_id}")]]
        )
        text = instructions or (
            "🧩 Libero richiede un CAPTCHA.\n\n"
            "Completa manualmente la verifica nel browser remoto. "
            "Riprendo automaticamente quando ne rilevo il completamento; "
            "non serve premere un pulsante su Telegram. "
            "Se la verifica risulta superata ma resto in attesa, avvisa l'assistente."
        )
        if self.settings.remote_browser_url:
            text += f"\n\nBrowser remoto: {self.settings.remote_browser_url}"
        await self.set_queue_fields(
            request, STATO="ATTESA_CAPTCHA", NOTE="Intervento manuale richiesto"
        )
        await self.send_temporary(request, "captcha",
            chat_id=self.settings.admin_id, text=text, reply_markup=keyboard
        )
        if ready_check is None:
            await self._wait_future(self.captcha_future)
            await self.cleanup_messages(request, "captcha")
            return
        cancel_task = asyncio.create_task(self.cancel_event.wait())
        try:
            while True:
                if self.cancel_event.is_set():
                    raise RequestCancelled("Richiesta annullata dall'amministratore")
                if await ready_check():
                    if self.cancel_event.is_set():
                        raise RequestCancelled("Richiesta annullata dall'amministratore")
                    return
                if self.captcha_future.done():
                    self.captcha_future = asyncio.get_running_loop().create_future()
                await asyncio.wait(
                    {self.captcha_future, cancel_task}, timeout=1,
                    return_when=asyncio.FIRST_COMPLETED,
                )
        finally:
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)
            if self.captcha_future and not self.captcha_future.done():
                self.captcha_future.cancel()
            self.captcha_future = None
            await self.cleanup_messages(request, "captcha")

    async def request_final_confirmation(
        self, request: QueueRequest, username: str, *, ready_check: Any = None
    ) -> None:
        self.final_future = asyncio.get_running_loop().create_future()
        keyboard = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton(
                    "✅ Conferma creazione", callback_data=f"final:{request.request_id}"
                ),
                InlineKeyboardButton("❌ Annulla", callback_data=f"cancel:{request.request_id}"),
            ]]
        )
        await self.set_queue_fields(
            request,
            STATO="ATTESA_CONFERMA",
            NOTE="Conferma amministrativa prima dell'invio finale",
        )
        await self.send_temporary(request, "final",
            chat_id=self.settings.admin_id,
            text=(
                "⚠️ Il modulo è pronto per creare definitivamente l'account.\n\n"
                f"Indirizzo previsto: {username}@libero.it\n\n"
                "Conferma soltanto se l'intestatario ha autorizzato la creazione "
                "e i dati inseriti sono corretti."
            ),
            reply_markup=keyboard,
        )
        result = await self._wait_future(self.final_future, ready_check=ready_check)
        await self.cleanup_messages(request, "final")
        if not result:
            raise RequestCancelled("Creazione finale non autorizzata")

    async def wait_for_registration_outcome(
        self, request: QueueRequest, username: str, *, ready_check: Any,
        allow_confirmation: bool,
    ) -> str:
        review = {
            "request_id": request.request_id, "email": f"{username}@libero.it",
            "token": secrets.token_hex(8), "confirmation_token": "",
            "allow_confirmation": allow_confirmation,
            "future": asyncio.get_running_loop().create_future(),
        }
        self.outcome_review = review
        cancel_task = asyncio.create_task(self.cancel_event.wait())
        try:
            await self.set_queue_fields(
                request, STATO="ATTESA_CONFERMA",
                NOTE="Esito da verificare; browser mantenuto aperto",
            )
            text = (
                "🔎 Non riconosco ancora il passaggio mostrato da Libero. "
                "Il browser resta aperto e questa richiesta resta in attesa.\n\n"
                f"Indirizzo previsto: {review['email']}\n\n"
                "Controlla la schermata nel browser remoto. Se riconosco l'esito "
                "o il passaggio successivo, riprendo automaticamente. "
            )
            keyboard = None
            if allow_confirmation:
                text += (
                    "Se riesci già ad accedere alla casella, puoi confermarla "
                    "con il pulsante qui sotto. Non ripetere la registrazione. "
                )
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
                    "✅ Casella già creata", callback_data=f"outcome:{review['token']}"
                )]])
            text += "Per interrompere usa /annulla; poi /recupera per verificare l'esito."
            if self.settings.remote_browser_url:
                text += f"\n\nBrowser remoto: {self.settings.remote_browser_url}"
            await self.send_temporary(
                request, "outcome", chat_id=self.settings.admin_id,
                text=text, reply_markup=keyboard,
            )
            while True:
                if self.cancel_event.is_set():
                    raise RequestCancelled("Richiesta annullata dall'amministratore")
                result = await ready_check()
                if self.cancel_event.is_set():
                    raise RequestCancelled("Richiesta annullata dall'amministratore")
                if not result and review["future"].done():
                    result = review["future"].result()
                if result:
                    if result == "created" and allow_confirmation:
                        # Preserve the confirmed outcome before any Telegram cleanup.
                        self.record_created(request, username, review["email"])
                    return result
                await asyncio.wait(
                    {review["future"], cancel_task}, timeout=1,
                    return_when=asyncio.FIRST_COMPLETED,
                )
        finally:
            if self.outcome_review is review:
                self.outcome_review = None
            if not review["future"].done():
                review["future"].cancel()
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)
            await self.cleanup_messages(request, "outcome")

    async def handle_outcome_confirmation(self, query: Any) -> None:
        if (query.from_user.id != self.settings.admin_id or not query.message
                or query.message.chat.type != ChatType.PRIVATE
                or query.message.chat.id != self.settings.admin_id):
            await query.answer("Operazione riservata alla chat privata dell'amministratore.", show_alert=True)
            return
        review = self.outcome_review
        action, _, token = (query.data or "").partition(":")
        expected_token = (review.get("confirmation_token") if action == "outcome_yes"
                          else review.get("token")) if review else None
        if (not review or not review["allow_confirmation"] or not token
                or token != expected_token or not self.active
                or self.active.request_id != review["request_id"]
                or review["future"].done() or self.cancel_event.is_set()):
            await query.answer("Pulsante scaduto: usa la richiesta attuale.", show_alert=True)
            return
        if action == "outcome_yes":
            review["future"].set_result("created")
            await query.answer("Verifica dell'accesso confermata. Salvataggio in corso.")
            return
        if review["confirmation_token"]:
            await query.answer("Conferma l'indirizzo nell'ultimo messaggio del bot.")
            return
        review["confirmation_token"] = secrets.token_hex(8)
        try:
            await self.send_temporary(
                self.active, "outcome", chat_id=self.settings.admin_id,
                text=(f"Indirizzo da salvare: {review['email']}\n\n"
                      "Conferma solo dopo avere verificato personalmente l'accesso "
                      "a questa esatta casella. Il bot salverà l'esito senza creare "
                      "un altro account."),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    "Ho verificato l'accesso: salva la casella",
                    callback_data=f"outcome_yes:{review['confirmation_token']}",
                )]]),
            )
        except Exception:
            review["confirmation_token"] = ""
            raise
        await query.answer("Controlla l'indirizzo e conferma nel nuovo messaggio.")

    async def send_unknown_step(
        self, request: QueueRequest, url: str, visible_text: str
    ) -> None:
        text = (
            "Passaggio Libero non riconosciuto.\n"
            f"URL: {url}\n\n"
            "Testo visibile della pagina:\n"
            f"{visible_text}"
        )
        await self.bot.send_message(chat_id=self.settings.admin_id, text=text)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    user = update.effective_user
    if not user or not update.effective_chat:
        return
    if user.id == coordinator.settings.admin_id and update.effective_chat.type == ChatType.PRIVATE:
        await panel_command(update, context)
        return
    whitelist = await asyncio.to_thread(coordinator.store.whitelist_map)
    if user.id == coordinator.settings.admin_id or user.id in whitelist:
        await update.effective_message.reply_text(
            "✅ Bot Creazione Libero Mail attivo.\n"
            f"Il tuo Telegram ID è: {user.id}"
            + ("\nGestione richieste: /recupera. Controllo coerenza: /controlla. Copie di sicurezza: /backup. Pausa coda: /pausa. Ripresa: /riprendi (in privato)." if user.id == coordinator.settings.admin_id else "")
        )
    else:
        await update.effective_message.reply_text(
            "⛔ Il tuo Telegram ID non è presente nella whitelist.\n"
            f"ID: {user.id}"
        )


def panel_status_text(coordinator: Coordinator) -> str:
    try:
        version = Path(__file__).with_name('VERSION').read_text().strip()
        if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
            raise ValueError('version')
    except (OSError, ValueError):
        version = 'non disponibile'
    lines = ['🌾 Mulino Libero — pannello privato', 'Versione: ' + version,
             coordinator.queue_status_text()]
    if coordinator.active:
        lines.extend([f'Richiesta attiva: {coordinator.active.request_id}',
                      f'Stato: {coordinator.active.status}'])
    elif coordinator.registration_busy():
        lines.append('Registrazione in avvio o chiusura: attendi prima di aggiornare.')
    else:
        lines.append('Nessuna registrazione attiva.')
    lines.append(f'Caselle create in attesa di scrittura su Sheets: {coordinator.outcomes.pending_count()}.')
    lines.append('Premi Stato per aggiornare, Chiudi per ridurre il pannello. /menu porta un nuovo pannello in fondo alla chat e rimuove il precedente quando possibile.')
    return '\n'.join(lines)


async def render_admin_panel(coordinator: Coordinator, message: Any, *, text: Optional[str] = None,
                             view: str = 'home', edit: bool = False,
                             expected_revision: Optional[int] = None, extra_rows=(),
                             session_payload=None, force_new: bool = False) -> Optional[int]:
    panel = coordinator.panel
    async with panel.lock:
        if expected_revision is not None and panel.revision != expected_revision:
            return None
        token, actions, markup = panel_keyboard(coordinator.paused, view, extra_rows=extra_rows)
        text = text or ('🌾 Pannello Mulino Libero — chiuso' if view == 'closed' else panel_status_text(coordinator))
        if panel.persistence_error:
            text += '\n⚠️ Non riesco a salvare il riferimento del pannello: dopo un riavvio potrebbe essere ricreato.'
        message_id = panel.message_id(coordinator.bot.id)
        sent = None
        if message_id and not force_new:
            try:
                sent = await coordinator.bot.edit_message_text(chat_id=coordinator.settings.admin_id,
                    message_id=message_id, text=text, reply_markup=markup, disable_web_page_preview=True)
            except BadRequest as exc:
                # Only a definitively missing/uneditable message permits replacement.
                if not any(reason in str(exc).lower() for reason in (
                        'message to edit not found', "message can't be edited", 'message_id_invalid')):
                    raise
        if sent is None:
            sent = await coordinator.bot.send_message(chat_id=coordinator.settings.admin_id,
                text=text, reply_markup=markup, disable_web_page_preview=True)
        if (panel.message_id(coordinator.bot.id) != sent.message_id or panel.persistence_error):
            panel.bind(coordinator.bot.id, sent.message_id,
                       retired_message=message_id if force_new else None)
        if force_new and message_id and message_id != sent.message_id:
            coordinator.panel_sessions.entries = {k:v for k,v in coordinator.panel_sessions.entries.items()
                if (v['chat'],v['message']) != (coordinator.settings.admin_id,message_id)}
        panel.revision += 1
        panel.view = view
        coordinator.panel_sessions.remember(token, sent.chat.id, sent.message_id, actions, payload=session_payload)
        return panel.revision


async def finish_panel_backup(coordinator: Coordinator, text: str, revision: int, *, urgent: bool = False) -> None:
    coordinator.panel.backup_result = text
    try:
        await render_admin_panel(coordinator, None, text=text, view='backup', expected_revision=revision)
    except TelegramError:
        # Delivery failures must not turn a valid backup into a failed operation.
        LOGGER.warning('Risultato backup disponibile, pannello non aggiornato')
    if urgent:
        await coordinator.safe_notice(coordinator.settings.admin_id, text)


async def start_panel_backup(coordinator: Coordinator, *, status_only: bool) -> None:
    if coordinator.backups is None:
        await render_admin_panel(coordinator, None, text='Backup non disponibile: cartella dati persistente non configurata.', view='backup')
        return
    if coordinator.backup_lock.locked() or (coordinator.backup_task and not coordinator.backup_task.done()):
        await render_admin_panel(coordinator, None, text='Operazione di backup già in corso. Attendi l’esito; poi premi Backup per rileggerlo.', view='backup')
        return
    text = 'Verifico le ultime copie…' if status_only else 'Creo e verifico il backup del registro. Il bot resta disponibile per SMS e CAPTCHA.'
    revision = await render_admin_panel(coordinator, None, text=text, view='backup')
    coordinator.backup_task = asyncio.create_task(run_backup_command(coordinator, None, status_only, panel_revision=revision))


ADMIN_CLEAN_COMMANDS = frozenset(('start','menu','pannello','conteggio','conteggi','azzera',
    'id','idgruppo','stato','recupera','controlla','backup','pausa','browser','riprendi',
    'annulla','riprova','conferma_creata','creamail'))


def admin_command(callback):
    """Clean only an observed owner command AFTER its registered handler succeeds."""
    async def wrapped(update, context):
        coordinator = context.application.bot_data['coordinator']
        user, chat, message = update.effective_user, update.effective_chat, update.effective_message
        words = (getattr(message, 'text', '') or '').split()
        command = words[0].split('@')[0].lower() if words else ''
        eligible = bool(user and chat and message
            and user.id == coordinator.settings.admin_id
            and chat.type == ChatType.PRIVATE and chat.id == coordinator.settings.admin_id
            and getattr(message, 'chat', None) and message.chat.id == chat.id
            and getattr(message, 'from_user', None) and message.from_user.id == user.id
            and not getattr(message, 'forward_origin', None)
            and not getattr(message, 'is_automatic_forward', False)
            and command.startswith('/') and command[1:] in ADMIN_CLEAN_COMMANDS
            and type(message.message_id) is int and 0 < message.message_id < 2**63)
        target = message.message_id if eligible else None
        await callback(update, context)
        if target is not None:
            try:
                coordinator.panel.cleanup.enqueue(coordinator.bot.id, target, 'command')
            except (sqlite3.Error, ValueError):
                LOGGER.warning('Comando gestito; registrazione della pulizia non disponibile')
            await coordinator.panel.cleanup.drain(coordinator.bot,
                                                 lambda: coordinator.panel.message_id(coordinator.bot.id))
    return wrapped


async def manual_mail_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    user, chat, message = update.effective_user, update.effective_chat, update.effective_message
    if (not user or not chat or not message or user.id != coordinator.settings.admin_id
            or chat.type != ChatType.PRIVATE or chat.id != coordinator.settings.admin_id
            or getattr(message, "forward_origin", None) or getattr(message, "is_automatic_forward", False)):
        return
    parts = (message.text or "").split(maxsplit=1)
    try:
        first, last = parse_manual_name(parts[1] if len(parts) == 2 else "")
    except ValueError as exc:
        await message.reply_text(str(exc))
        return
    async with coordinator.manual_request_lock:
        try:
            request, email, added = await asyncio.to_thread(coordinator.store.create_manual_request, first, last)
        except RegistrationError as exc:
            await message.reply_text(str(exc))
            return
        except Exception as exc:
            LOGGER.warning("Accodamento manuale non confermato (%s)", type(exc).__name__)
            await message.reply_text("⚠️ Non posso confermare l'accodamento. "
                "Ripeti lo stesso /creamail con lo stesso nominativo per ricontrollare, "
                "senza avviare tentativi separati. La richiesta non viene duplicata intenzionalmente.")
            return
    if not added:
        saved = coordinator.outcomes.get(request.request_id)
        if saved:
            email = saved[2]
        if email and (saved or request.status == "CREATA"):
            await message.reply_text(f"✅ Per questo nominativo risulta già creata la mail:\n{email}\n"
                                     f"ID: {request.request_id}\nNon ho avviato una nuova registrazione.")
        else:
            await message.reply_text(f"ℹ️ Esiste già una richiesta per questo nominativo.\n"
                f"ID: {request.request_id}\nStato: {request.status}\n"
                "Attendi il completamento; se è fallita o annullata verifica prima l'esito con /recupera.")
        return
    await message.reply_text(f"📬 Richiesta manuale accodata.\nID: {request.request_id}\n"
        "Userò la procedura e la password già configurate. Chiederò i dati anagrafici nel gruppo all’Apprendista "
        "e ti comunicherò in privato la mail al completamento.\n" + coordinator.queue_status_text())


async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data['coordinator']
    if (not update.effective_user or not update.effective_chat or not update.effective_message
            or update.effective_user.id != coordinator.settings.admin_id
            or update.effective_chat.type != ChatType.PRIVATE
            or update.effective_chat.id != coordinator.settings.admin_id):
        return
    words = (getattr(update.effective_message, 'text', '') or '').split()
    force_new = bool(words and words[0].split('@')[0].lower() == '/menu')
    await render_admin_panel(coordinator, update.effective_message, force_new=force_new)


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data['coordinator']
    query = update.callback_query
    if not query or not query.from_user:
        return
    if (query.from_user.id != coordinator.settings.admin_id or not query.message
            or not getattr(query.message, 'is_accessible', True)
            or query.message.chat.type != ChatType.PRIVATE
            or query.message.chat.id != coordinator.settings.admin_id
            or not query.message.from_user or query.message.from_user.id != coordinator.bot.id):
        await query.answer('Pannello riservato alla chat privata del proprietario.', show_alert=True)
        return
    if query.message.message_id != coordinator.panel.message_id(coordinator.bot.id):
        await query.answer('Questo pannello è stato sostituito. Apri quello attuale con /menu.', show_alert=True)
        return
    session_token = query.data.rsplit(':', 1)[-1] if isinstance(query.data, str) else ''
    tester_payload = coordinator.panel_sessions.entries.get(session_token, {}).get('payload')
    action = coordinator.panel_sessions.take(query.data, query.message.chat.id, query.message.message_id)
    if action is None and isinstance(query.data, str) and re.fullmatch(r'panel:(?:home|open|close):[a-f0-9]{16}', query.data):
        # Read-only navigation can refresh the current owner's panel after expiry/restart.
        action = query.data.split(':')[1]
    if action is None:
        await query.answer('Pulsante scaduto o già usato. Riapri con /menu.', show_alert=True)
        return
    # Consume the message-bound capability before any await or side effect.
    await query.answer('Aggiorno il pannello…')
    captured = PanelReply()
    adapted = SimpleNamespace(effective_user=query.from_user, effective_chat=query.message.chat,
                              effective_message=captured)
    command_context = SimpleNamespace(application=context.application, args=[])
    if action == 'testers' or action.startswith('tester_'):
        await tester_panel_action(coordinator, query.message, action, tester_payload)
        return
    if action == 'controls':
        await render_admin_panel(coordinator, query.message, text=await asyncio.to_thread(controls_text), edit=True)
        return
    if action == 'backup':
        await render_admin_panel(coordinator, query.message, text=(
            '💾 Backup del registro\n\n'
            'Qui puoi verificare o creare le copie locali di esiti e stato del Mugnaio sul VPS. '
            'La copia manuale non avvia il backup completo cifrato né il trasferimento sul PC. '
            'Per controllare questi ultimi usa Controlli.'
            + ('\n\nUltimo risultato:\n' + coordinator.panel.backup_result if coordinator.panel.backup_result else '')), view='backup', edit=True)
        return
    if action == 'backup_confirm':
        await render_admin_panel(coordinator, query.message, text=(
            'Creare e verificare una copia manuale del registro sul VPS? '
            'Saranno conservate le tre copie manuali più recenti. Il bot resta disponibile.'),
            view='confirm_backup', edit=True)
        return
    if action in ('backup_status', 'backup_yes'):
        await start_panel_backup(coordinator, status_only=action == 'backup_status')
        return
    elif action == 'close':
        await render_admin_panel(coordinator, query.message, view='closed', edit=True)
        return
    elif action == 'browser':
        await browser_command(adapted, command_context)
    elif action == 'pause':
        await pause_command(adapted, command_context)
    elif action == 'resume':
        await resume_command(adapted, command_context)
    text = '\n'.join(captured.texts)
    if action in ('pause', 'resume') and text:
        text += '\n\n' + panel_status_text(coordinator)
    await render_admin_panel(coordinator, query.message, text=text or None, edit=True)


async def tester_ids(coordinator):
    known = coordinator.outcomes.testers.known_ids()
    try:
        whitelist = await asyncio.to_thread(coordinator.store.whitelist_map)
        ids = {i for i in whitelist if TesterLedger.valid_id(i)}
        return sorted(known | ids), True
    except Exception:
        # Never expose the sheet, phone numbers or provider error text.
        return sorted(known), False


def tester_detail_text(stats):
    started = datetime.fromisoformat(stats['started']).astimezone(ZoneInfo('Europe/Rome'))
    return (f"👤 Tester — ID {stats['tester_id']}\n\n"
            f"Operazioni completate: {stats['count']}\n"
            f"Conteggio iniziato: {started.strftime('%d/%m/%Y %H:%M:%S')} (Italia)\n"
            f"Totale nello storico: {stats['total']}\n\n"
            "Conta solo nuove registrazioni riuscite con verifica SMS riconosciuta. "
            "I recuperi manuali senza questa prova e le caselle senza SMS non aggiungono crediti.")


async def show_tester_list(coordinator, message, page=0):
    ids, complete = await tester_ids(coordinator)
    pages = max(1, (len(ids) + 9) // 10)
    page = max(0, min(int(page), pages - 1))
    selected = ids[page*10:(page+1)*10]
    payload, rows, lines = {}, [], ['👥 Tester — completamenti SMS', f'Pagina {page+1}/{pages}']
    for index, tester in enumerate(selected):
        count = coordinator.outcomes.testers.stats(tester)['count']
        action = f'tester_select_{index}'
        payload[action] = tester
        rows.append([(f'ID {tester} · {count}', action)])
    if not ids:
        lines.append('Nessun tester disponibile.')
    if not complete:
        lines.append('⚠️ Whitelist non raggiungibile: elenco limitato ai tester già registrati.')
    navigation = []
    for label, action, destination in (('⬅️ Precedenti', 'tester_prev', page-1),
                                       ('➡️ Successivi', 'tester_next', page+1)):
        if 0 <= destination < pages:
            navigation.append((label, action))
            payload[action] = destination
    if navigation:
        rows.append(navigation)
    lines.append('Seleziona un ID per dettagli e azzeramento. /conteggio ID e /azzera ID sono disponibili solo qui in privato.')
    await render_admin_panel(coordinator, message, text='\n'.join(lines), view='testers',
                             extra_rows=rows, session_payload=payload)


async def show_tester_detail(coordinator, message, tester, *, confirm=False, notice=''):
    stats = coordinator.outcomes.testers.stats(tester)
    payload = dict(tester=tester, snapshot=stats['snapshot'])
    text = tester_detail_text(stats)
    if confirm:
        text = (f"Azzerare il conteggio del tester ID {tester}?\n"
                f"Operazioni da azzerare: {stats['count']}.\n"
                "Ripartirà da zero; lo storico e gli altri tester saranno conservati.\n\n" + text)
        rows = [[('✅ Conferma azzeramento', 'tester_reset_yes'), ('↩️ Annulla', 'tester_detail')]]
    else:
        rows = [[('🗑 Azzera questo tester', 'tester_reset'), ('🔄 Aggiorna', 'tester_detail')]]
    rows.append([('👥 Elenco tester', 'testers')])
    await render_admin_panel(coordinator, message, text=(notice+'\n\n' if notice else '')+text,
                             view='tester_confirm' if confirm else 'tester_detail',
                             extra_rows=rows, session_payload=payload)


async def tester_panel_action(coordinator, message, action, payload):
    try:
        if action == 'testers':
            await show_tester_list(coordinator, message)
        elif action in ('tester_next', 'tester_prev') and payload and action in payload:
            await show_tester_list(coordinator, message, payload[action])
        elif action.startswith('tester_select_') and payload and action in payload:
            await show_tester_detail(coordinator, message, payload[action])
        elif action in ('tester_detail', 'tester_reset', 'tester_reset_yes') and payload and 'tester' in payload:
            tester = payload['tester']
            notice = ''
            if action == 'tester_reset_yes':
                try:
                    coordinator.outcomes.testers.reset(tester, coordinator.settings.admin_id, payload['snapshot'])
                    notice = '✅ Conteggio azzerato. Storico conservato.'
                except RegistrationError:
                    notice = '⚠️ Conteggio cambiato: verifica i nuovi dati e richiedi nuovamente l’azzeramento.'
            await show_tester_detail(coordinator, message, tester, confirm=action == 'tester_reset', notice=notice)
        else:
            await render_admin_panel(coordinator, message, text='Selezione non più disponibile. Premi Tester per aggiornare.')
    except (sqlite3.Error, ValueError, TypeError):
        await render_admin_panel(coordinator, message, text='⚠️ Registro tester non disponibile. Non posso confermare il conteggio o l’azzeramento. Riprova da Tester.')


async def tester_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator = context.application.bot_data['coordinator']
    if (not update.effective_user or not update.effective_chat or not update.effective_message
            or update.effective_user.id != coordinator.settings.admin_id
            or update.effective_chat.type != ChatType.PRIVATE
            or update.effective_chat.id != coordinator.settings.admin_id):
        return
    words = (getattr(update.effective_message, 'text', '') or '').split()
    name = words[0].split('@')[0].lower() if words else ''
    args = context.args
    try:
        if name == '/conteggi' and not args:
            await show_tester_list(coordinator, update.effective_message)
            return
        if name not in ('/conteggio', '/azzera') or len(args) != 1 or not re.fullmatch(r'[1-9][0-9]{0,18}', args[0]):
            await render_admin_panel(coordinator, update.effective_message,
                text='Usa /conteggi, /conteggio ID_TELEGRAM oppure /azzera ID_TELEGRAM. Per conoscere il proprio ID il tester può usare /id.')
            return
        tester = int(args[0])
        if not TesterLedger.valid_id(tester):
            raise ValueError('ID out of range')
        ids, complete = await tester_ids(coordinator)
        if tester not in ids:
            await render_admin_panel(coordinator, update.effective_message,
                text=('Tester non presente nella whitelist o nello storico.' if complete else
                      'Whitelist non raggiungibile e tester assente dallo storico: non posso verificarlo.'))
            return
        await show_tester_detail(coordinator, update.effective_message, tester, confirm=name == '/azzera')
    except (sqlite3.Error, ValueError, TypeError):
        await render_admin_panel(coordinator, update.effective_message,
            text='⚠️ ID o registro non disponibile. Nessun azzeramento confermato. Premi Tester per aggiornare.')


async def browser_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the configured viewer only to the administrator in a private chat."""
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    if (not update.effective_user or not update.effective_chat or not update.effective_message
            or update.effective_user.id != coordinator.settings.admin_id
            or update.effective_chat.type != ChatType.PRIVATE):
        return
    url = coordinator.settings.remote_browser_url
    if not url:
        await update.effective_message.reply_text("Collegamento al browser remoto non configurato.")
        return
    await update.effective_message.reply_text(
        "Browser remoto: " + url + "\n\n"
        "Tailscale deve essere collegato. Sul PC usa l'icona Mulino Libero - Browser privato "
        "per aprire Opera privata; sull'iPhone copia il link in una scheda privata di Opera. "
        "Il link Telegram non forza la navigazione privata. "
        "Se non ci sono registrazioni aperte, il desktop puo essere nero.",
        disable_web_page_preview=True,
    )


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user and update.effective_message:
        await update.effective_message.reply_text(
            f"Il tuo Telegram ID è:\n{update.effective_user.id}"
        )


async def group_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sola lettura: restituisce in privato gli ID necessari all'amministratore."""
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    user, chat, message = update.effective_user, update.effective_chat, update.effective_message
    if not user or user.id != coordinator.settings.admin_id or not chat or not message:
        return
    if chat.type not in {"group", "supergroup"}:
        await message.reply_text(
            "Usa /idgruppo@Il_Mugnaio_Bot nel gruppo, rispondendo a un messaggio "
            "di @Apprendista_Mugnaio_bot.")
        return
    text = f"ID gruppo anagrafica: {chat.id}\nTELEGRAM_ANAGRAFICA_GROUP_ID={chat.id}"
    reply = getattr(message, "reply_to_message", None)
    author = getattr(reply, "from_user", None)
    if (author is not None and author.is_bot
            and (author.username or "").lower() == "apprendista_mugnaio_bot"):
        text += f"\nTELEGRAM_ANAGRAFICA_BOT_ID={author.id}"
    else:
        text += ("\nPer ottenere anche l'ID dell'Apprendista, ripeti il comando "
                 "rispondendo a un suo messaggio nel gruppo.")
    await coordinator.bot.send_message(chat_id=coordinator.settings.admin_id, text=text)


def recovery_signature(request: QueueRequest) -> tuple:
    return (request.request_id, request.status, request.destination_spreadsheet,
            request.destination_sheet, request.destination_row, request.email_column,
            request.full_name, request.account_id)


def recovery_token(coordinator: Coordinator, request: QueueRequest, action: str,
                   *, email: str = "", batch: str = "") -> str:
    now = time.monotonic()
    coordinator.recovery_buttons = {
        k: v for k, v in coordinator.recovery_buttons.items() if now - v["created"] < 600
    }
    if len(coordinator.recovery_buttons) >= 200:
        coordinator.recovery_buttons.clear()
    token = secrets.token_hex(8)
    coordinator.recovery_buttons[token] = {
        "created": now, "signature": recovery_signature(request),
        "request_id": request.request_id, "action": action, "email": email,
        "batch": batch,
    }
    return token


def recovery_ignored(coordinator: Coordinator, request: QueueRequest) -> bool:
    row = coordinator.outcomes.db.execute(
        'SELECT signature FROM recovery_ignored WHERE request_id=?', (request.request_id,)).fetchone()
    signature = hashlib.sha256(json.dumps(recovery_signature(request)).encode()).hexdigest()
    if row and row[0] != signature:
        coordinator.outcomes.db.execute('DELETE FROM recovery_ignored WHERE request_id=?', (request.request_id,))
        return False
    return bool(row and row[0] == signature)


def clear_recovery_ignore(coordinator: Coordinator, request_id: str) -> None:
    coordinator.outcomes.db.execute('DELETE FROM recovery_ignored WHERE request_id=?', (request_id,))
    # Un nuovo tentativo invalida anche i pulsanti di vecchi elenchi della stessa richiesta.
    coordinator.recovery_buttons = {k:v for k,v in coordinator.recovery_buttons.items()
                                    if v["request_id"] != request_id}


async def recovery_reply(coordinator: Coordinator, source: Any, text: str, *,
                         batch: str, kind: str = "list", **kwargs: Any) -> Any:
    sent = await source.reply_text(text, **kwargs)
    try:
        if sent.chat.id == coordinator.settings.admin_id:
            coordinator.panel.cleanup.track_recovery(coordinator.bot.id, sent.message_id, batch, kind)
    except (sqlite3.Error, ValueError):
        LOGGER.warning("Messaggio recupero inviato; pulizia non registrata")
    return sent


async def finish_recovery(coordinator: Coordinator, batch: str, *, message: Any = None) -> None:
    if not batch:
        return
    try:
        coordinator.panel.cleanup.finish_recovery(coordinator.bot.id, batch, message=message)
    except (sqlite3.Error, ValueError):
        LOGGER.warning("Operazione recupero completata; pulizia rinviata")
    if message is None:
        coordinator.recovery_buttons = {k:v for k,v in coordinator.recovery_buttons.items()
                                        if v.get("batch") != batch}
    await coordinator.panel.cleanup.drain(coordinator.bot,
                                        lambda: coordinator.panel.message_id(coordinator.bot.id))


async def recovery_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    if (not update.effective_user or not update.effective_chat
            or update.effective_user.id != coordinator.settings.admin_id
            or update.effective_chat.type != ChatType.PRIVATE):
        return
    try:
        ignored_view = bool(context.args and context.args[0].lower() == "ignorate")
        args = context.args[1:] if ignored_view else context.args
        page_number = int(args[0]) if args else 1
        if page_number < 1 or len(args) > 1:
            raise ValueError()
    except ValueError:
        await recovery_reply(coordinator, update.effective_message,
            "Uso: /recupera oppure /recupera 2 per la seconda pagina.\n"
            "Richieste ignorate: /recupera ignorate.", batch=secrets.token_hex(8), kind="usage")
        return
    batch = secrets.token_hex(8)
    try:
        requests = await asyncio.to_thread(coordinator.store._read_requests)
        recorded = coordinator.outcomes.ids() | set(coordinator.created_in_memory)
        pending = set(coordinator.created_in_memory)
        for request_id in coordinator.outcomes.ids():
            outcome = coordinator.outcomes.get(request_id)
            if outcome and not outcome[3]:
                pending.add(request_id)
                if not any(r.request_id == request_id for r in requests):
                    requests.append(outcome[0])
        requests = [r for r in requests if r.status in ({"ERRORE", "ANNULLATA"} | TRANSIENT_STATUSES)
                    or r.request_id in pending]
        def hidden(r):
            return (r.status in {"ERRORE", "ANNULLATA"} and r.request_id not in recorded
                    and not (coordinator.active and coordinator.active.request_id == r.request_id)
                    and recovery_ignored(coordinator, r))
        requests = [r for r in requests if hidden(r) == ignored_view]
        requests.sort(key=lambda r: r.row, reverse=True)
        start = (page_number - 1) * 5
        selected = requests[start:start + 5]
        if not selected:
            await update.effective_message.reply_text("Nessuna richiesta da recuperare in questa pagina.")
            return
        await recovery_reply(coordinator, update.effective_message,
            coordinator.queue_status_text() + "\n"
            + ("Richieste ignorate" if ignored_view else "Recupero richieste")
            + f" — pagina {page_number}/{(len(requests) + 4) // 5}\n"
            "I pulsanti scadono dopo 10 minuti. Per aggiornare usa /recupera.\n"
            "Per rivedere le richieste nascoste: /recupera ignorate.", batch=batch
        )
        for request in selected:
            text = (f"{request.destination_sheet} — riga {request.destination_row}\n"
                    f"{request.full_name}\nID: {request.request_id}\nStato: {request.status}")
            buttons = []
            if ignored_view:
                token = recovery_token(coordinator, request, "restore", batch=batch)
                buttons.append([InlineKeyboardButton("↩️ Rimetti nel recupero", callback_data=f"rec:restore:{token}")])
            elif coordinator.active and coordinator.active.request_id == request.request_id:
                text += "\nRichiesta ancora attiva: se bloccata, usa /annulla e attendi la chiusura, poi /recupera."
            elif request.request_id in recorded:
                text += "\nLa casella risulta gia creata: e disponibile solo il salvataggio su Sheets."
                token = recovery_token(coordinator, request, "sync", batch=batch)
                buttons.append([InlineKeyboardButton("💾 Riprova salvataggio", callback_data=f"rec:sync:{token}")])
            else:
                token = recovery_token(coordinator, request, "retry", batch=batch)
                buttons.append([InlineKeyboardButton("🔄 Riprova registrazione", callback_data=f"rec:retry:{token}")])
                if request.status in {"ERRORE", "ANNULLATA"}:
                    token = recovery_token(coordinator, request, "created", batch=batch)
                    buttons.append([InlineKeyboardButton("✅ Casella gia creata", callback_data=f"rec:created:{token}")])
                    token = recovery_token(coordinator, request, "ignore", batch=batch)
                    buttons.append([InlineKeyboardButton("🙈 Ignora richiesta", callback_data=f"rec:ignore:{token}")])
            await recovery_reply(coordinator, update.effective_message,
                text, batch=batch, reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
            )
        if start + 5 < len(requests):
            command = "/recupera ignorate" if ignored_view else "/recupera"
            await recovery_reply(coordinator, update.effective_message,
                f"Altre richieste: {command} {page_number + 1}", batch=batch)
    except Exception as exc:
        LOGGER.warning("Elenco recupero non disponibile (%s)", type(exc).__name__)
        await update.effective_message.reply_text("Non riesco a leggere la coda. Nessuna modifica: riprova /recupera tra poco.")


async def recovery_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    async with coordinator.recovery_lock:
        await recovery_callback_locked(update, context)


async def recovery_callback_locked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    query = update.callback_query
    if (not query or not query.from_user or not query.message
            or query.from_user.id != coordinator.settings.admin_id
            or query.message.chat.type != ChatType.PRIVATE
            or query.message.chat.id != coordinator.settings.admin_id):
        if query:
            await query.answer("Operazione riservata alla chat privata dell'amministratore.", show_alert=True)
        return
    parts = (query.data or "").split(":")
    item = coordinator.recovery_buttons.get(parts[2]) if len(parts) == 3 else None
    if (not item or time.monotonic() - item["created"] >= 600
            or parts[1] != item["action"]):
        command = "/controlla" if len(parts) == 3 and parts[1] == "audit_sync" else "/recupera"
        await query.answer(f"Pulsante scaduto: usa {command}.", show_alert=True)
        return
    # Un solo uso, anche in caso di errore di rete con esito incerto.
    coordinator.recovery_buttons.pop(parts[2], None)
    await query.answer("Controllo della richiesta…")
    try:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except TelegramError:
            pass
        request = await asyncio.to_thread(coordinator.store.find_request, item["request_id"])
        if not request or recovery_signature(request) != item["signature"]:
            command = "/controlla" if item["action"] == "audit_sync" else "/recupera"
            raise RegistrationError(f"La richiesta e cambiata: aggiorna con {command}.")
        if coordinator.active and coordinator.active.request_id == request.request_id:
            raise RegistrationError("La richiesta e ancora attiva. Usa /annulla, attendi la chiusura e poi /recupera.")
        recorded = request.request_id in coordinator.outcomes.ids() or request.request_id in coordinator.created_in_memory
        action = item["action"]
        if action == "audit_sync":
            if not recorded:
                raise RegistrationError("Esito locale assente: ripristino bloccato.")
            if request.request_id in coordinator.created_in_memory:
                coordinator.record_created(*coordinator.created_in_memory[request.request_id])
            await coordinator.restore_audited_outcome(request)
            await query.message.reply_text("✅ Email e stato riallineati dal registro VPS. Usa /controlla per aggiornare il rapporto.")
            return
        if recorded:
            # Qualunque vecchio pulsante diventa solo recupero del salvataggio.
            if request.request_id in coordinator.created_in_memory:
                coordinator.record_created(*coordinator.created_in_memory[request.request_id])
            synced = await coordinator.sync_outcome(request.request_id)
            await query.message.reply_text("✅ Salvataggio completato." if synced else
                "Casella gia creata. Salvataggio ancora in attesa; verra ritentato automaticamente.")
            return
        if action == "sync":
            raise RegistrationError("Esito locale non trovato: nessuna registrazione avviata. Usa /recupera.")
        hidden = recovery_ignored(coordinator, request)
        if action == "restore":
            if not hidden:
                raise RegistrationError("La richiesta non e piu ignorata. Aggiorna con /recupera.")
            coordinator.outcomes.db.execute('DELETE FROM recovery_ignored WHERE request_id=?', (request.request_id,))
            await finish_recovery(coordinator, item.get("batch", ""), message=query.message.message_id)
            await query.message.reply_text("↩️ Richiesta di nuovo visibile con /recupera. Non e stata riavviata.")
            return
        if hidden:
            raise RegistrationError("Richiesta ignorata: ripristinala con /recupera ignorate.")
        if action == "ignore":
            if request.status not in {"ERRORE", "ANNULLATA"}:
                raise RegistrationError("Puoi ignorare solo richieste fallite o annullate, non quelle in lavorazione.")
            signature = hashlib.sha256(json.dumps(recovery_signature(request)).encode()).hexdigest()
            coordinator.outcomes.db.execute('INSERT OR REPLACE INTO recovery_ignored VALUES (?,?)',
                                           (request.request_id, signature))
            coordinator.recovery_buttons = {k:v for k,v in coordinator.recovery_buttons.items()
                                            if v["request_id"] != request.request_id}
            await finish_recovery(coordinator, item.get("batch", ""), message=query.message.message_id)
            await query.message.reply_text("🙈 Richiesta nascosta dal recupero. Riga e storico conservati. "
                                           "Per ripristinarla usa /recupera ignorate.")
            return
        if request.status not in ({"ERRORE", "ANNULLATA"} | TRANSIENT_STATUSES):
            raise RegistrationError("Richiesta non recuperabile in questo stato. Usa /recupera.")
        if action == "retry":
            batch = item.get("batch", "") or secrets.token_hex(8)
            token = recovery_token(coordinator, request, "retry_yes", batch=batch)
            await recovery_reply(coordinator, query.message,
                f"Riprovare {request.destination_sheet}, riga {request.destination_row}?\n"
                "La registrazione ripartira dall'inizio. Conferma solo se NON hai gia creato la casella "
                "con questo tentativo. In caso di dubbio verifica prima l'accesso alla mail.",
                batch=batch, kind="confirm",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    "Confermo: riprova", callback_data=f"rec:retry_yes:{token}")]]))
        elif action == "retry_yes":
            result = await asyncio.to_thread(coordinator.store.retry, request.request_id)
            if result:
                clear_recovery_ignore(coordinator, request.request_id)
                await finish_recovery(coordinator, item.get("batch", ""))
            await query.message.reply_text(("✅ Richiesta rimessa in coda."
                + (" La coda e in pausa: partira dopo /riprendi." if coordinator.paused else "")) if result else
                "Stato cambiato: richiesta non riavviata. Usa /recupera.")
        elif action in {"created", "created_yes"}:
            current, username, email = await asyncio.to_thread(
                coordinator.store.existing_created_details, request.request_id)
            if recovery_signature(current) != item["signature"]:
                raise RegistrationError("La destinazione e cambiata. Usa /recupera.")
            if action == "created":
                token = recovery_token(coordinator, current, "created_yes", email=email)
                await query.message.reply_text(
                    f"Casella da confermare: {email}\n"
                    f"Destinazione: {current.destination_sheet}, riga {current.destination_row}.\n"
                    "Conferma solo dopo aver verificato personalmente l'accesso a questo indirizzo. "
                    "Il bot registrera l'esito senza creare un altro account.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                        "Ho verificato: salva la casella", callback_data=f"rec:created_yes:{token}")]]))
            else:
                if email != item["email"]:
                    raise RegistrationError("Lo username e cambiato: nessuna conferma. Usa /recupera.")
                coordinator.record_created(current, username, email)
                synced = await coordinator.sync_outcome(request.request_id)
                await query.message.reply_text("✅ Casella confermata e salvata nel foglio." if synced else
                    "✅ Casella confermata. Scrittura sul foglio in attesa; verra ritentata automaticamente.")
    except RegistrationError as exc:
        await query.message.reply_text(f"❌ {exc}")
    except Exception as exc:
        LOGGER.warning("Recupero richiesta non completato (%s)", type(exc).__name__)
        command = "/controlla" if item["action"] == "audit_sync" else "/recupera"
        await query.message.reply_text(
            f"Non posso confermare l'esito dell'operazione. Usa /stato e {command} per rileggere "
            "la situazione prima di riprovare. Il vecchio pulsante e disattivato.")


async def show_consistency_page(coordinator: Coordinator, message: Any, page: int) -> None:
    cached = coordinator.consistency_report
    if not cached or time.monotonic() - cached["created"] > 600:
        await message.reply_text("Rapporto scaduto: usa /controlla per aggiornarlo.")
        return
    report = cached["report"]
    issues = report["issues"]
    counts = {}
    for item in issues:
        counts[item["code"]] = counts.get(item["code"], 0) + 1
    if page == 1:
        text = (f"Controllo completato: {report['requests']} richieste, {report['sheets']} fogli leggibili.\n"
                f"Richieste coerenti o regolarmente in attesa: {report['ok']}.\n"
                "Rilievi: " + (", ".join(f"{k}: {v}" for k, v in counts.items()) or "nessuno") +
                "\nFotografia dei dati: /controlla aggiorna il rapporto. Nessuna registrazione avviata.")
        if report.get("legacy"):
            text += f"\nRichieste senza ID stabile: {report['legacy']} (incluse eventuali destinazioni storiche)."
        if not report["books"]:
            text += "\nNon ho riferimenti ai fogli account nella Coda: non posso cercare righe prive di richiesta."
        await message.reply_text(text)
    selected = issues[(page - 1) * 5:page * 5]
    if not selected and page > 1:
        await message.reply_text("Nessun altro rilievo in questa pagina.")
    for item in selected:
        request = item["request"]
        text = f"{item['code']}\n{item['sheet']} — riga {item['row']}\n{item['message']}"
        if request:
            text += f"\nID: {request.request_id}"
        if item.get("email"):
            text += f"\nEmail nel registro: {item['email']}"
        buttons = None
        if item["restore"] and request:
            token = recovery_token(coordinator, request, "audit_sync")
            text += "\nIl pulsante ripristina solo l'email dal registro VPS e riallinea lo stato."
            buttons = InlineKeyboardMarkup([[InlineKeyboardButton(
                "💾 Ripristina email dal registro", callback_data=f"rec:audit_sync:{token}")]])
        await message.reply_text(text, reply_markup=buttons)
    if page * 5 < len(issues):
        await message.reply_text(f"Altri rilievi: /controlla {page + 1}")


async def run_consistency_check(coordinator: Coordinator, message: Any) -> None:
    try:
        outcomes = {rid: coordinator.outcomes.get(rid) for rid in coordinator.outcomes.ids()}
        for rid, (request, username, email) in coordinator.created_in_memory.items():
            outcomes[rid] = (request, username, email, False)
        active_id = coordinator.active.request_id if coordinator.active else ""
        snapshot = await asyncio.to_thread(coordinator.store.consistency_snapshot)
        report = build_consistency_report(snapshot, outcomes, active_id)
        coordinator.consistency_report = {"created": time.monotonic(), "report": report}
        await show_consistency_page(coordinator, message, 1)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        coordinator.consistency_report = None
        LOGGER.warning("Controllo coerenza non completato (%s)", type(exc).__name__)
        await message.reply_text("Controllo non completato: non posso confermare la coerenza dei dati. Verifica l'accesso a Sheets e riprova /controlla.")


async def consistency_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    if (not update.effective_user or not update.effective_chat
            or update.effective_user.id != coordinator.settings.admin_id
            or update.effective_chat.type != ChatType.PRIVATE):
        return
    try:
        page = int(context.args[0]) if context.args else 1
        if page < 1 or len(context.args) > 1:
            raise ValueError()
    except ValueError:
        await update.effective_message.reply_text("Uso: /controlla oppure /controlla 2 per la seconda pagina.")
        return
    if context.args:
        await show_consistency_page(coordinator, update.effective_message, page)
        return
    if coordinator.consistency_task and not coordinator.consistency_task.done():
        await update.effective_message.reply_text("Un controllo e gia in corso. Attendi il rapporto.")
        return
    await update.effective_message.reply_text(
        "🔎 Confronto Coda, fogli account e registro VPS. Il bot resta disponibile per CAPTCHA e SMS. "
        "Per una fotografia stabile puoi mettere in pausa e lasciare finire la richiesta attiva.")
    coordinator.consistency_report = None
    coordinator.consistency_task = asyncio.create_task(run_consistency_check(coordinator, update.effective_message))


async def reply_queue_summary(coordinator: Coordinator, update: Update, text: str, *, routine: bool) -> None:
    """Track only explicit routine command replies delivered to the owner's private chat."""
    message = update.effective_message
    sent = await message.reply_text(text)
    if not routine:
        return
    user, chat = update.effective_user, update.effective_chat
    words = (getattr(message, 'text', '') or '').split()
    command = words[0].split('@')[0].lower() if words else ''
    date = getattr(sent, 'date', None)
    if not (user and chat and sent and user.id == coordinator.settings.admin_id
            and chat.type == ChatType.PRIVATE and chat.id == user.id
            and getattr(message, 'chat', None) and message.chat.id == chat.id
            and getattr(message, 'from_user', None) and message.from_user.id == user.id
            and not getattr(message, 'forward_origin', None)
            and not getattr(message, 'is_automatic_forward', False)
            and command in ('/pausa', '/stato', '/riprendi')
            and getattr(sent, 'chat', None) and sent.chat.id == chat.id and sent.chat.type == ChatType.PRIVATE
            and getattr(sent, 'from_user', None) and sent.from_user.id == coordinator.bot.id
            and isinstance(date, datetime) and date.tzinfo is not None):
        return
    try:
        coordinator.panel.cleanup.track_response(coordinator.bot.id, getattr(sent, 'message_id', None), int(date.timestamp()))
    except (sqlite3.Error, ValueError, OverflowError):
        # Delivery and any queue-state change already succeeded; never repeat the command.
        LOGGER.warning('Risposta inviata; registrazione della pulizia non disponibile')


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    if (not update.effective_user or not update.effective_chat
            or update.effective_user.id != coordinator.settings.admin_id
            or update.effective_chat.type != ChatType.PRIVATE):
        return
    try:
        coordinator.set_paused(True)
    except RegistrationError as exc:
        await update.effective_message.reply_text(f"⚠️ {exc}")
        return
    text = "⏸ Pausa salvata. Non avviero nuove registrazioni.\n"
    busy = coordinator.registration_busy()
    if busy:
        text += ("La richiesta gia avviata continua, inclusi CAPTCHA e SMS. "
                 "Attendi la sua conclusione prima di aggiornare. "
                 "Se e bloccata puoi usare /annulla, poi verificare /stato.")
    else:
        text += "Nessuna registrazione attiva: puoi aggiornare. La pausa restera attiva dopo il riavvio."
    await reply_queue_summary(coordinator, update, text + "\nPer riattivare la coda: /riprendi.", routine=not busy)


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    if (not update.effective_user or not update.effective_chat
            or update.effective_user.id != coordinator.settings.admin_id
            or update.effective_chat.type != ChatType.PRIVATE):
        return
    try:
        coordinator.set_paused(False)
    except RegistrationError as exc:
        await update.effective_message.reply_text(f"⚠️ {exc}")
        return
    await reply_queue_summary(coordinator, update,
        "▶️ Coda attiva. Le richieste in attesa potranno partire dal prossimo controllo. "
        "Quelle fallite o annullate restano gestibili con /recupera.", routine=not coordinator.registration_busy())


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    if not update.effective_user or update.effective_user.id != coordinator.settings.admin_id:
        return
    request = coordinator.active
    if not request:
        count = coordinator.outcomes.pending_count()
        busy = coordinator.registration_busy()
        await reply_queue_summary(coordinator, update,
            coordinator.queue_status_text() + "\n"
            + ("Richiesta in avvio o chiusura: attendi prima di aggiornare.\n"
               if busy else "Nessuna registrazione attiva.\n")
            + f"Caselle create in attesa di scrittura su Sheets: {count}.",
            routine=not busy and count == 0 and getattr(coordinator, 'pause_persisted', True)
        )
        return
    await coordinator.cleanup_messages(request, "status")
    coordinator.messages.track(request.request_id, "status", update.effective_message)
    await coordinator.reply_temporary(request, "status", update.effective_message,
        coordinator.queue_status_text() + "\n"
        + f"Richiesta attiva: {request.request_id}\nStato: {request.status}\n"
        f"Caselle create in attesa di scrittura su Sheets: {coordinator.outcomes.pending_count()}."
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    if not update.effective_user or update.effective_user.id != coordinator.settings.admin_id:
        return
    if not coordinator.active:
        await update.effective_message.reply_text("Nessuna registrazione attiva.")
        return
    coordinator.cancel_event.set()
    await update.effective_message.reply_text("Richiesta annullata.")


async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    if not update.effective_user or update.effective_user.id != coordinator.settings.admin_id:
        return
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return
    if not context.args:
        await update.effective_message.reply_text("Uso: /riprova ID_RICHIESTA")
        return
    request_id = context.args[0].strip()
    if request_id in coordinator.outcomes.ids() or request_id in coordinator.created_in_memory:
        await update.effective_message.reply_text(
            "La casella risulta già creata. La registrazione non viene ripetuta; "
            "gli eventuali salvataggi pendenti vengono ritentati automaticamente."
        )
        return
    if coordinator.active and coordinator.active.request_id == request_id:
        await update.effective_message.reply_text(
            "La richiesta è ancora attiva. Usa prima /annulla e attendi la chiusura."
        )
        return
    result = await asyncio.to_thread(coordinator.store.retry, request_id)
    if result:
        clear_recovery_ignore(coordinator, request_id)
    await update.effective_message.reply_text(
        ("✅ Richiesta rimessa in coda."
         + (" La coda e in pausa: partira dopo /riprendi." if coordinator.paused else ""))
        if result else "Richiesta non trovata o già chiusa."
    )


async def confirm_created_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    if (not update.effective_user or not update.effective_chat
            or update.effective_user.id != coordinator.settings.admin_id
            or update.effective_chat.type != ChatType.PRIVATE):
        return
    if len(context.args) != 1:
        await update.effective_message.reply_text(
            "Uso: /conferma_creata ID_RICHIESTA\n"
            "Usalo solo dopo avere verificato personalmente l'accesso alla casella."
        )
        return
    request_id = context.args[0].strip()
    if coordinator.active and coordinator.active.request_id == request_id:
        await update.effective_message.reply_text("La richiesta è ancora attiva: nessuna modifica.")
        return
    try:
        request, username, email = await asyncio.to_thread(coordinator.store.existing_created_details, request_id)
        coordinator.record_created(request, username, email)
        synced = await coordinator.sync_outcome(request_id)
    except RegistrationError as exc:
        await update.effective_message.reply_text(f"❌ {exc}")
        return
    if not synced:
        await update.effective_message.reply_text(
            f"✅ Esito confermato e salvato sul VPS: {email}\n"
            "Scrittura su Sheets in attesa; verrà ritentata automaticamente."
        )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    query = update.callback_query
    if not query or not query.from_user:
        return
    data = query.data or ""

    if isinstance(data, str) and data.startswith('panel:'):
        await panel_callback(update, context)
        return

    if data.startswith("rec:"):
        await recovery_callback(update, context)
        return

    if data.startswith(("outcome:", "outcome_yes:")):
        await coordinator.handle_outcome_confirmation(query)
        return

    if data.startswith("resend:"):
        if not query.message or query.message.chat.type != ChatType.PRIVATE:
            await query.answer("Usa il pulsante nella chat privata con il bot.", show_alert=True)
            return
        parts = data.split(":")
        if len(parts) != 3 or not parts[2]:
            await query.answer("Pulsante scaduto: usa l'ultima richiesta.", show_alert=True)
            return
        ok, message = coordinator.queue_sms_resend(parts[1], query.from_user.id, token=parts[2])
        await query.answer(message, show_alert=not ok)
        return

    if data.startswith("claim:"):
        if not query.message or query.message.chat.id != coordinator.settings.group_chat_id:
            await query.answer("Usa il pulsante nel gruppo dedicato.", show_alert=True)
            return
        parts = data.split(":")
        if len(parts) != 3 or not parts[2]:
            await query.answer("Pulsante scaduto: usa l'ultima richiesta.", show_alert=True)
            return
        request_id = parts[1]
        if not coordinator.active or coordinator.active.request_id != request_id:
            await query.answer("Richiesta non più attiva.", show_alert=True)
            return
        ok, message = await coordinator.claim_phone(query.from_user.id, token=parts[2])
        await query.answer(message, show_alert=not ok)
        return

    if data.startswith("tester:"):
        if not query.message or query.message.chat.type != ChatType.PRIVATE:
            await query.answer("Usa il pulsante nella tua chat privata con il bot.", show_alert=True)
            return
        parts = data.split(":")
        if len(parts) != 3:
            await query.answer("Pulsante scaduto.", show_alert=True)
            return
        ok, message = coordinator.queue_tester_change(parts[1], query.from_user.id, parts[2])
        await query.answer(message, show_alert=not ok)
        return

    if query.from_user.id != coordinator.settings.admin_id:
        await query.answer("Operazione riservata all'amministratore.", show_alert=True)
        return

    request_id = data.split(":", 1)[1] if ":" in data else ""
    if not coordinator.active or coordinator.active.request_id != request_id:
        await query.answer("Richiesta non più attiva.", show_alert=True)
        return

    if data.startswith("captcha:") and coordinator.captcha_future:
        if not coordinator.captcha_future.done():
            coordinator.captcha_future.set_result(True)
        await query.answer("Verifica del passaggio in corso.")
    elif data.startswith("final:") and coordinator.final_future:
        if not coordinator.final_future.done():
            coordinator.final_future.set_result(True)
        await query.answer("Creazione autorizzata.")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except BadRequest:
            pass
    elif data.startswith("cancel:"):
        coordinator.cancel_event.set()
        if coordinator.final_future and not coordinator.final_future.done():
            coordinator.final_future.set_result(False)
        await query.answer("Richiesta annullata.")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coordinator: Coordinator = context.application.bot_data["coordinator"]
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat or not message.text:
        return

    request = coordinator.active
    if not request:
        return

    if (request.status == "ATTESA_ANAGRAFICA" and coordinator.personal_future
            and not coordinator.personal_future.done()):
        group_id = getattr(coordinator.settings, "anagrafica_group_id", 0)
        if group_id:
            if (getattr(chat, "id", None) != group_id
                    or chat.type not in {"group", "supergroup"}
                    or not getattr(user, "is_bot", False)
                    or user.id != coordinator.settings.anagrafica_bot_id
                    or getattr(message, "sender_chat", None) is not None
                    or getattr(message, "forward_origin", None) is not None):
                return
            await coordinator.personal_prompt_ready.wait()
            if (coordinator.active is not request or coordinator.personal_future is None
                    or coordinator.personal_future.done()):
                return
            reply = getattr(message, "reply_to_message", None)
            if (coordinator.personal_prompt_id is None or reply is None
                    or reply.message_id != coordinator.personal_prompt_id):
                return
            if message.message_id <= coordinator.personal_last_message_id:
                return
            coordinator.personal_last_message_id = message.message_id
        elif user.id != coordinator.settings.admin_id or chat.type != ChatType.PRIVATE:
            return
        coordinator.messages.track(request.request_id, "personal", message)
        try:
            personal = parse_personal_data(message.text, request.full_name,
                name_parts=getattr(coordinator, "personal_name_parts", None))
        except ValueError as exc:
            if group_id:
                # Nessuna risposta all'altro bot: evita cicli automatici di errori.
                if not coordinator.personal_invalid_notified:
                    coordinator.personal_invalid_notified = True
                    await coordinator.send_temporary(request, "personal",
                        chat_id=coordinator.settings.admin_id,
                        text=f"⚠️ L'Apprendista ha inviato dati non validi: {exc}\n"
                             "Deve correggerli rispondendo alla richiesta originale nel gruppo.")
            else:
                await coordinator.reply_temporary(request, "personal", message, f"❌ {exc}")
            return
        receiver = coordinator.personal_future
        await coordinator.delete_input(request, message)
        if coordinator.active is not request or receiver.done() or coordinator.cancel_event.is_set():
            return
        receiver.set_result(personal)
        if group_id:
            await coordinator.send_temporary(request, "progress",
                chat_id=coordinator.settings.admin_id,
                text="✅ Dati ricevuti dall'Apprendista. Avvio la registrazione.")
        else:
            await coordinator.reply_temporary(request, "progress", message,
                                              "✅ Dati ricevuti. Avvio la registrazione.")
        return

    if (
        request.status in {"ATTESA_CODICE", "ATTESA_CAPTCHA"}
        and request.claimed_by
        and str(user.id) == str(request.claimed_by)
        and coordinator.otp_future
        and not coordinator.otp_future.done()
    ):
        if coordinator.change_tester_event.is_set() or coordinator.tester_sms_expired():
            await coordinator.delete_input(request, message)
            return
        receiver = coordinator.otp_future
        assignment = coordinator.assignment_token
        coordinator.messages.track(request.request_id, "otp", message)
        if chat.type != ChatType.PRIVATE:
            await coordinator.reply_temporary(request, "otp", message,
                                              "Invia il codice nella chat privata con il bot.")
            return
        if coordinator.resend_busy:
            await coordinator.reply_temporary(request, "otp", message,
                                              "Reinvio SMS in corso: attendi e invia soltanto il nuovo codice.")
            return
        # Libero può inviare codici alfabetici: conservarne maiuscole,
        # minuscole e zeri iniziali senza convertire il valore.
        code_match = re.fullmatch(r"\s*([A-Za-z0-9]{4,8})\s*", message.text)
        if not code_match:
            await coordinator.reply_temporary(request, "otp", message,
                "Invia soltanto il codice ricevuto: da 4 a 8 lettere o numeri, "
                "senza spazi interni e rispettando maiuscole e minuscole."
            )
            return
        code = code_match.group(1)
        await coordinator.delete_input(request, message)
        if (coordinator.otp_future is not receiver or receiver.done()
                or coordinator.assignment_token != assignment or coordinator.change_tester_event.is_set()
                or str(request.claimed_by) != str(user.id)):
            return
        receiver.set_result(code)
        await coordinator.send_temporary(request, "progress",
            chat_id=user.id,
            text="✅ Codice ricevuto. Attendo la verifica sul sito.",
        )


async def post_init(application: Application) -> None:
    coordinator: Coordinator = application.bot_data["coordinator"]
    coordinator.application = application
    try:
        recovered = await asyncio.to_thread(coordinator.store.recover_interrupted, coordinator.outcomes.ids())
    except Exception:
        recovered = 0
        coordinator.recovery_pending = True
        LOGGER.warning("Google Sheets non raggiungibile all'avvio; recupero rinviato")
    coordinator.messages.recover()
    await coordinator.messages.drain(application.bot)
    await coordinator.panel.cleanup.drain(application.bot, lambda: coordinator.panel.message_id(application.bot.id))
    if recovered:
        await application.bot.send_message(
            chat_id=coordinator.settings.admin_id,
            text=(
                f"⚠️ Ho trovato {recovered} registrazioni interrotte da un riavvio. "
                "Sono state marcate ERRORE per evitare duplicazioni."
            ),
        )
    application.bot_data["queue_task"] = asyncio.create_task(coordinator.loop())
    await coordinator.health.start(application)
    if coordinator.backups is not None:
        application.bot_data["backup_loop_task"] = asyncio.create_task(coordinator.backup_loop())
    LOGGER.info("Bot avviato; coda %s", "in pausa" if coordinator.paused else "attiva")


async def post_shutdown(application: Application) -> None:
    await application.bot_data['coordinator'].health.stop(application)
    task = application.bot_data.get("queue_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    coordinator: Coordinator = application.bot_data["coordinator"]
    if coordinator.processing_task and not coordinator.processing_task.done():
        coordinator.processing_task.cancel()
        try:
            await coordinator.processing_task
        except asyncio.CancelledError:
            pass
    if coordinator.consistency_task and not coordinator.consistency_task.done():
        coordinator.consistency_task.cancel()
        try:
            await coordinator.consistency_task
        except asyncio.CancelledError:
            pass
    for backup_task in (application.bot_data.get("backup_loop_task"), coordinator.backup_task):
        if backup_task and not backup_task.done():
            backup_task.cancel()
            try:
                await backup_task
            except asyncio.CancelledError:
                pass
    coordinator.messages.close()
    coordinator.outcomes.close()


async def check_telegram(settings: Settings) -> None:
    """Controllo senza inviare messaggi o consumare gli aggiornamenti del bot."""
    async with Bot(settings.telegram_token) as bot:
        me = await bot.get_me()
        if (me.username or "").lower() != "il_mugnaio_bot":
            raise ConfigurationError("Il token appartiene a un bot diverso da @Il_Mugnaio_Bot")
        group = await bot.get_chat(settings.group_chat_id)
        if group.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
            raise ConfigurationError("TELEGRAM_GROUP_ID non indica un gruppo")
        member = await bot.get_chat_member(settings.group_chat_id, me.id)
        if member.status not in {"administrator", "creator"}:
            raise ConfigurationError("Aggiungi @Il_Mugnaio_Bot come amministratore del gruppo dedicato")
        if settings.anagrafica_group_id:
            data_group = await bot.get_chat(settings.anagrafica_group_id)
            if data_group.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
                raise ConfigurationError("TELEGRAM_ANAGRAFICA_GROUP_ID non indica un gruppo")
            for bot_id in (me.id, settings.anagrafica_bot_id):
                data_member = await bot.get_chat_member(settings.anagrafica_group_id, bot_id)
                if data_member.status not in {"administrator", "creator"}:
                    raise ConfigurationError("Aggiungi Mugnaio e Apprendista come amministratori del gruppo anagrafica")
                if bot_id == me.id and not getattr(data_member, "can_delete_messages", False):
                    raise ConfigurationError("Abilita Eliminare i messaggi per il Mugnaio nel gruppo anagrafica")
                if bot_id == settings.anagrafica_bot_id and (
                    not data_member.user.is_bot
                    or (data_member.user.username or "").lower() != "apprendista_mugnaio_bot"
                ):
                    raise ConfigurationError("TELEGRAM_ANAGRAFICA_BOT_ID non corrisponde all'Apprendista")
        try:
            await bot.get_chat(settings.admin_id)
        except (BadRequest, Forbidden):
            raise ConfigurationError("Apri @Il_Mugnaio_Bot in privato e premi Avvia prima di installare") from None
    print("OK: bot Telegram, gruppo e chat privata amministratore raggiungibili.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Non stampare l'Update: può contenere dati anagrafici o un OTP.
    LOGGER.error("Errore Telegram gestito (%s)", type(context.error).__name__)


def main() -> None:
    if sys.argv[1:2] == ["--verify-backup"]:
        if len(sys.argv) != 3:
            raise ConfigurationError("Uso: --verify-backup PERCORSO_ZIP")
        try:
            info = LocalBackups.verify(Path(sys.argv[2]))
        except Exception:
            raise ConfigurationError("Backup non valido o non leggibile: nessun dato ripristinato.") from None
        print(f"OK: backup verificato; {info['files']['created-outcomes.sqlite3']['database']['rows']} esiti. Nessun dato ripristinato.")
        return
    settings = Settings.from_env()
    store = GoogleQueueStore(settings)
    if "--check" in sys.argv:
        whitelist = store.whitelist_map()
        if not whitelist:
            raise ConfigurationError("La whitelist non contiene ancora Telegram ID e numeri utilizzabili")
        print("OK: configurazione, password e intestazioni Google Sheets verificate.")
        print(f"OK: {len(whitelist)} utenti nella whitelist.")
        asyncio.run(check_telegram(settings))
        print("OK: controllo preliminare completato (nessun messaggio inviato o cella modificata).")
        return
    coordinator = Coordinator(settings, store)

    application = (
        Application.builder()
        .token(settings.telegram_token)
        .get_updates_request(HealthRequest(coordinator.health))
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .concurrent_updates(False)
        .build()
    )
    application.bot_data["coordinator"] = coordinator
    application.add_error_handler(error_handler)
    application.add_handler(CommandHandler("start", admin_command(start_command)))
    application.add_handler(CommandHandler(["menu", "pannello"], admin_command(panel_command)))
    application.add_handler(CommandHandler(["conteggio", "conteggi", "azzera"], admin_command(tester_command)))
    application.add_handler(CommandHandler("id", admin_command(id_command)))
    application.add_handler(CommandHandler("idgruppo", admin_command(group_id_command)))
    application.add_handler(CommandHandler("stato", admin_command(status_command)))
    application.add_handler(CommandHandler("recupera", admin_command(recovery_command)))
    application.add_handler(CommandHandler("creamail", admin_command(manual_mail_command)))
    application.add_handler(CommandHandler("controlla", admin_command(consistency_command)))
    application.add_handler(CommandHandler("backup", admin_command(backup_command)))
    application.add_handler(CommandHandler("pausa", admin_command(pause_command)))
    application.add_handler(CommandHandler("browser", admin_command(browser_command)))
    application.add_handler(CommandHandler("riprendi", admin_command(resume_command)))
    application.add_handler(CommandHandler("annulla", admin_command(cancel_command)))
    application.add_handler(CommandHandler("riprova", admin_command(retry_command)))
    application.add_handler(CommandHandler("conferma_creata", admin_command(confirm_created_command)))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except ConfigurationError as error:
        LOGGER.error("Configurazione: %s", error)
        raise SystemExit(1) from None
    except Exception as error:
        LOGGER.error("Avvio non riuscito (%s). Controlla configurazione e accessi.", type(error).__name__)
        raise SystemExit(1) from None
