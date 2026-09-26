"""Test offline delle definizioni originali; nessuna credenziale o rete richiesta.

Le definizioni vengono estratte con AST dal worker, senza riscriverne la logica.
Telegram e Sheets sono simulati; questi test non verificano le librerie esterne
né i selettori del sito. Esecuzione: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import ast
import asyncio
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


class BadRequest(Exception):
    pass


class Forbidden(Exception):
    pass


SOURCE = Path(__file__).resolve().parents[1] / "libero_mail_bot.py"
NAMES = {
    "ConfigurationError", "RegistrationError", "RequestCancelled",
    "redact_secrets", "SecretFormatter", "env_required", "env_int",
    "secret_required", "validate_libero_password", "Settings", "QueueRequest",
    "mask_phone", "Coordinator", "text_handler", "callback_handler",
}
tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
selected = [node for node in tree.body if getattr(node, "name", None) in NAMES]
assert {node.name for node in selected} == NAMES, "Definizioni attese non trovate"
extracted = ast.Module(
    body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *selected],
    type_ignores=[],
)
ast.fix_missing_locations(extracted)
worker = ModuleType("mulino_test_worker")
sys.modules[worker.__name__] = worker
worker.__dict__.update(
    asyncio=asyncio, logging=logging, os=os, Path=Path, re=re,
    dataclass=dataclass, field=field, _SECRET_VALUES=set(),
    LOGGER=logging.getLogger("mulino-test"), BadRequest=BadRequest,
    Forbidden=Forbidden, ChatType=SimpleNamespace(PRIVATE="private"),
)
exec(compile(extracted, str(SOURCE), "exec"), worker.__dict__)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        worker._SECRET_VALUES.clear()

    def test_server_files_and_existing_env_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "token").write_text("123456:example_token\n")
            (root / "password").write_text("Abcdef1!\n")
            (root / "google.json").write_text("{}")
            environment = {
                "TELEGRAM_BOT_TOKEN_FILE": str(root / "token"),
                "TELEGRAM_BOT_TOKEN": "old-placeholder",
                "LIBERO_PASSWORD_FILE": str(root / "password"),
                "TELEGRAM_ADMIN_ID": "123",
                "TELEGRAM_GROUP_ID": "-100987",
                "GOOGLE_SPREADSHEET_ID": "sheet-id",
                "GOOGLE_SERVICE_ACCOUNT_FILE": str(root / "google.json"),
                "GOOGLE_QUEUE_SHEET": "Coda",
                "GOOGLE_WHITELIST_SHEET": "Whitelist",
                "DATA_DIR": str(root / "data"),
            }
            with patch.dict(os.environ, environment, clear=True):
                settings = worker.Settings.from_env()
            self.assertEqual(settings.telegram_token, "123456:example_token")
            self.assertEqual(settings.libero_password, "Abcdef1!")
            self.assertEqual((settings.admin_id, settings.group_chat_id), (123, -100987))
            self.assertEqual((settings.queue_sheet, settings.whitelist_sheet), ("Coda", "Whitelist"))
            self.assertNotIn(settings.telegram_token, repr(settings))
            self.assertNotIn(settings.libero_password, repr(settings))

    def test_missing_secret_file_does_not_use_old_environment_value(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {
                "LIBERO_PASSWORD_FILE": str(Path(directory) / "missing"),
                "LIBERO_PASSWORD": "Abcdef1!",
            }, clear=True):
                with self.assertRaises(worker.ConfigurationError):
                    worker.secret_required("LIBERO_PASSWORD")

    def test_old_alias_and_current_name_priority(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_ID": "123"}, clear=True):
            self.assertEqual(worker.env_int("TELEGRAM_ADMIN_ID", "ADMIN_TELEGRAM_ID"), 123)
            os.environ["TELEGRAM_ADMIN_ID"] = "456"
            self.assertEqual(worker.env_int("TELEGRAM_ADMIN_ID", "ADMIN_TELEGRAM_ID"), 456)

    def test_password_rules_and_redaction(self):
        worker.validate_libero_password("Abcdef1!")
        for password in ("abcdef1!", "Abcdefg!", "Abcdef12", "Ab1!", "Abcdef1!" * 3, "Abc\ndef1!"):
            with self.subTest(password=password):
                with self.assertRaises(worker.ConfigurationError):
                    worker.validate_libero_password(password)
        worker._SECRET_VALUES.add("Abcdef1!")
        record = logging.LogRecord("test", logging.ERROR, "", 0,
                                   "https://api.telegram.org/bot123:example/getMe Abcdef1!", (), None)
        output = worker.SecretFormatter("%(message)s").format(record)
        self.assertNotIn("123:example", output)
        self.assertNotIn("Abcdef1!", output)


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.request = worker.QueueRequest(2, "test-request", "ATTESA_UTENTE", "sheet", "tab", 4, 3, "Test Persona")
        self.store = SimpleNamespace(whitelist_map=Mock(return_value={11: "+393330000011", 22: "+393330000022"}))
        self.writes = []

        def update(request, **fields):
            self.writes.append(fields)
            if "STATO" in fields:
                request.status = fields["STATO"]
            if "TELEGRAM_ASSEGNATO" in fields:
                request.claimed_by = fields["TELEGRAM_ASSEGNATO"]

        self.store.update = update
        self.bot = SimpleNamespace(send_message=AsyncMock())
        self.coordinator = worker.Coordinator(SimpleNamespace(admin_id=99, group_chat_id=-100987), self.store)
        self.coordinator.application = SimpleNamespace(bot=self.bot)
        self.coordinator.active = self.request
        self.coordinator.phone_future = asyncio.get_running_loop().create_future()
        self.context = SimpleNamespace(application=SimpleNamespace(bot_data={"coordinator": self.coordinator}), bot=self.bot)

    async def test_only_one_concurrent_claim_wins(self):
        results = await asyncio.gather(self.coordinator.claim_phone(11), self.coordinator.claim_phone(22))
        self.assertEqual(sum(result[0] for result in results), 1)
        phone, person = self.coordinator.phone_future.result()
        self.assertEqual(str(person), self.request.claimed_by)
        self.assertEqual(phone, self.store.whitelist_map()[person])
        self.assertNotIn(phone, str(self.writes))

    async def test_unknown_user_and_blocked_dm_cannot_claim(self):
        self.assertFalse((await self.coordinator.claim_phone(33))[0])
        self.bot.send_message.assert_not_awaited()
        self.bot.send_message.side_effect = Forbidden("blocked")
        self.assertFalse((await self.coordinator.claim_phone(11))[0])
        self.assertFalse(self.coordinator.phone_future.done())
        self.assertEqual(self.request.claimed_by, "")

    async def test_fast_otp_is_preserved(self):
        self.coordinator.otp_future = asyncio.get_running_loop().create_future()
        original = self.coordinator.otp_future
        original.set_result("123456")
        await self.coordinator.notify_otp_sent(self.request, 11, "+393330000011")
        result = await asyncio.wait_for(self.coordinator.request_otp(self.request), timeout=0.5)
        self.assertIs(self.coordinator.otp_future, original)
        self.assertEqual(result, "123456")

    def make_update(self, person, chat_type):
        message = SimpleNamespace(text="123456", reply_text=AsyncMock(), delete=AsyncMock())
        return SimpleNamespace(effective_user=SimpleNamespace(id=person),
                               effective_chat=SimpleNamespace(type=chat_type), effective_message=message)

    async def test_otp_only_from_assigned_user_in_private(self):
        self.request.status = "ATTESA_CODICE"
        self.request.claimed_by = "11"
        self.coordinator.otp_future = asyncio.get_running_loop().create_future()
        await worker.text_handler(self.make_update(22, "private"), self.context)
        self.assertFalse(self.coordinator.otp_future.done())
        await worker.text_handler(self.make_update(11, "supergroup"), self.context)
        self.assertFalse(self.coordinator.otp_future.done())
        valid = self.make_update(11, "private")
        await worker.text_handler(valid, self.context)
        self.assertEqual(self.coordinator.otp_future.result(), "123456")
        valid.effective_message.delete.assert_awaited_once()

    async def test_claim_button_in_wrong_group_is_ignored(self):
        query = SimpleNamespace(data="claim:test-request", from_user=SimpleNamespace(id=11),
                                message=SimpleNamespace(chat=SimpleNamespace(id=-100111)), answer=AsyncMock())
        await worker.callback_handler(SimpleNamespace(callback_query=query), self.context)
        self.assertFalse(self.coordinator.phone_future.done())
        self.bot.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
