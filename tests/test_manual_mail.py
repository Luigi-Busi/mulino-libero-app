"""Manual creation through the ordinary queue; fake Sheets/Telegram only."""
import asyncio
import copy
import re
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_regressions as fixtures
from test_regressions import worker


class Sheet:
    def __init__(self, title, values=None):
        self.title, self.values = title, copy.deepcopy(values or [])
        self.raw_options = []
        self.fail_append = False

    def get_all_values(self):
        return copy.deepcopy(self.values)

    def row_values(self, number):
        return copy.deepcopy(self.values[number-1])

    def update(self, *, range_name, values, value_input_option):
        self.raw_options.append(value_input_option)
        self.values = copy.deepcopy(values)

    def append_row(self, row, *, value_input_option):
        self.raw_options.append(value_input_option)
        self.values.append([str(x) for x in row])
        if self.fail_append:
            self.fail_append = False
            raise TimeoutError("synthetic response lost after append")

    def update_cell(self, row, col, value):
        self.values[row-1][col-1] = str(value)

    def batch_update(self, updates, *, value_input_option):
        self.raw_options.append(value_input_option)
        for update in updates:
            col, row = re.fullmatch(r"([A-Z]+)(\d+)", update["range"]).groups()
            number = 0
            for x in col:
                number = number*26 + ord(x)-64
            self.update_cell(int(row), number, update["values"][0][0])


class Book:
    def __init__(self, queue):
        self.sheets = {"Coda": queue}

    def worksheet(self, name):
        if name not in self.sheets:
            raise worker.gspread.WorksheetNotFound(name)
        return self.sheets[name]

    def add_worksheet(self, *, title, rows, cols):
        self.sheets[title] = Sheet(title)
        return self.sheets[title]


def store():
    s = object.__new__(worker.GoogleQueueStore)
    s.settings = SimpleNamespace(spreadsheet_id="queuebook")
    s.queue = Sheet("Coda", [worker.QUEUE_HEADERS + ["ID_ACCOUNT"]])
    s.book = Book(s.queue)
    s.client = SimpleNamespace(open_by_key=Mock(return_value=s.book))
    s._header_index = {h:i+1 for i,h in enumerate(worker.QUEUE_HEADERS)}
    return s


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.s = store()

    def test_add_uses_normal_queue_with_stable_destination_and_no_banco_rows(self):
        r, email, added = self.s.create_manual_request("Giovanni Carlo", "De Luca")
        self.assertTrue(added)
        self.assertEqual(r.status, "DA_COMPLETARE_ANAGRAFICA")
        self.assertEqual(r.account_id, r.request_id)
        self.assertEqual(r.destination_spreadsheet, "queuebook")
        self.assertEqual(r.destination_sheet, worker.MANUAL_SHEET)
        self.assertEqual(self.s.manual_name_parts(r), ("Giovanni Carlo", "De Luca"))
        self.assertEqual(set(self.s.book.sheets), {"Coda", worker.MANUAL_SHEET})
        self.assertEqual(self.s.next_request().request_id, r.request_id)
        self.assertTrue(all(x=="RAW" for x in self.s.queue.raw_options))

    def test_repeated_command_returns_existing_without_new_rows(self):
        original, _, _ = self.s.create_manual_request("Mario", "Rossi")
        again, _, added = self.s.create_manual_request("Mario", "Rossi")
        self.assertFalse(added)
        self.assertEqual(original.request_id, again.request_id)
        self.assertEqual(len(self.s.queue.values), 2)
        self.assertEqual(len(self.s.book.worksheet(worker.MANUAL_SHEET).values), 2)

    def test_lost_queue_append_response_is_inactive_and_reconciled_after_restart(self):
        self.s.queue.fail_append = True
        with self.assertRaises(TimeoutError):
            self.s.create_manual_request("Mario", "Rossi")
        self.assertIsNone(self.s.next_request())
        self.assertEqual(self.s._read_requests()[0].status, worker.MANUAL_PENDING)
        fresh = store()
        fresh.book, fresh.queue, fresh.client = self.s.book, self.s.queue, self.s.client
        r, _, added = fresh.create_manual_request("Mario", "Rossi")
        self.assertTrue(added)
        self.assertEqual(r.status, "DA_COMPLETARE_ANAGRAFICA")
        self.assertEqual(len(self.s.queue.values), 2)

    def test_orphan_destination_is_reused_after_lost_append_response(self):
        manual = self.s.manual_sheet()
        manual.fail_append = True
        with self.assertRaises(TimeoutError):
            self.s.create_manual_request("Mario", "Rossi")
        self.assertEqual(len(self.s.queue.values), 1)
        r, _, added = self.s.create_manual_request("Mario", "Rossi")
        self.assertTrue(added)
        self.assertEqual(len(manual.values), 2)

    def test_completed_or_failed_request_is_not_restarted(self):
        r, _, _ = self.s.create_manual_request("Mario", "Rossi")
        self.s.write_created_email(r, "fixture@libero.it", "fixture")
        again, email, added = self.s.create_manual_request("Mario", "Rossi")
        self.assertEqual(email, "fixture@libero.it")
        self.assertEqual(again.status, "CREATA")
        self.assertFalse(added)
        self.s.update(r, STATO="ERRORE")
        self.assertFalse(self.s.create_manual_request("Mario", "Rossi")[2])

    def test_sorted_destination_is_written_by_stable_id(self):
        a, _, _ = self.s.create_manual_request("Mario", "Rossi")
        b, _, _ = self.s.create_manual_request("Paolo", "Verdi")
        manual = self.s.book.worksheet(worker.MANUAL_SHEET)
        manual.values[1:] = list(reversed(manual.values[1:]))
        self.s.write_created_email(a, "fixture@libero.it", "fixture")
        self.assertEqual(manual.values[2][2], "fixture@libero.it")
        self.assertEqual(manual.values[1][2], "")

    def test_same_name_in_banco_queue_is_reused(self):
        r, _, _ = self.s.create_manual_request("Mario", "Rossi")
        self.s.queue.values[1][5] = "Sisal Sport"
        self.s.queue.values[1][4] = "bancobook"
        same, _, added = self.s.create_manual_request("Mario", "Rossi")
        self.assertEqual(same.destination_sheet, "Sisal Sport")
        self.assertFalse(added)

    def test_duplicate_names_block_without_writes(self):
        self.s.create_manual_request("Mario", "Rossi")
        self.s.queue.values.append(copy.deepcopy(self.s.queue.values[1]))
        before = copy.deepcopy(self.s.queue.values)
        with self.assertRaises(worker.RegistrationError):
            self.s.create_manual_request("Mario", "Rossi")
        self.assertEqual(self.s.queue.values, before)

    def test_missing_stable_queue_column_blocks_before_creating_tab(self):
        self.s.queue.values[0].remove("ID_ACCOUNT")
        with self.assertRaises(worker.RegistrationError):
            self.s.create_manual_request("Mario", "Rossi")
        self.assertNotIn(worker.MANUAL_SHEET, self.s.book.sheets)

    def test_occupied_incompatible_tab_is_never_overwritten(self):
        self.s.book.sheets[worker.MANUAL_SHEET] = Sheet(worker.MANUAL_SHEET, [["Existing content"]])
        with self.assertRaises(worker.ConfigurationError):
            self.s.create_manual_request("Mario", "Rossi")
        self.assertEqual(self.s.book.sheets[worker.MANUAL_SHEET].values, [["Existing content"]])
        self.assertEqual(len(self.s.queue.values), 1)

    def test_blank_grid_returned_as_empty_rows_is_initialized(self):
        self.s.book.sheets[worker.MANUAL_SHEET] = Sheet(worker.MANUAL_SHEET, [[]])
        self.s.manual_sheet()
        self.assertEqual(self.s.book.sheets[worker.MANUAL_SHEET].values, [worker.MANUAL_HEADERS])

    def test_pending_conflicting_name_parts_do_not_activate(self):
        self.s.queue.fail_append = True
        with self.assertRaises(TimeoutError):
            self.s.create_manual_request("Anna Maria", "Bianchi")
        with self.assertRaises(worker.RegistrationError):
            self.s.create_manual_request("Anna", "Maria Bianchi")
        self.assertIsNone(self.s.next_request())


class NamesTests(unittest.TestCase):
    def test_compound_names_and_simple_syntax(self):
        self.assertEqual(worker.parse_manual_name("Giovanni Carlo | De Luca"), ("Giovanni Carlo", "De Luca"))
        self.assertEqual(worker.parse_manual_name("Mario Rossi"), ("Mario", "Rossi"))
        self.assertEqual(worker.parse_manual_name("José | D’Angelo"), ("José", "D’Angelo"))

    def test_malformed_names_are_rejected(self):
        for x in ("", "Mario", "Mario Carlo Rossi", "Mario | ", "=IMPORT | Rossi", "Mario | Rossi | Altro",
                  "Mario | 123", "Mario\nRossi", "Mario | @Rossi", "A"*81 + " | Rossi"):
            with self.subTest(x=x), self.assertRaises(ValueError):
                worker.parse_manual_name(x)

    def test_personal_data_preserves_compound_names_without_changing_old_format(self):
        p = worker.parse_personal_data("01/01/2000 | M | Roma (RM)", "Giovanni Carlo De Luca",
            name_parts=("Giovanni Carlo", "De Luca"))
        self.assertEqual((p.first_name, p.last_name), ("Giovanni Carlo", "De Luca"))
        p = worker.parse_personal_data("01/01/2000 | M | Roma (RM)", "Mario Rossi")
        self.assertEqual((p.first_name, p.last_name), ("Mario", "Rossi"))


class CommandTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.CoordinatorTests.asyncSetUp
    asyncTearDown = fixtures.CoordinatorTests.asyncTearDown

    def update(self, user=99, kind="private", chat=99, text="/creamail Mario | Rossi"):
        message = SimpleNamespace(text=text, reply_text=AsyncMock(), message_id=1)
        return SimpleNamespace(effective_user=SimpleNamespace(id=user),
            effective_chat=SimpleNamespace(id=chat,type=kind), effective_message=message)

    async def test_non_admin_group_and_forwarded_commands_do_nothing(self):
        self.coordinator.store.create_manual_request = Mock()
        for u in (self.update(user=11), self.update(kind="group",chat=-1), self.update(chat=11)):
            await worker.manual_mail_command(u, self.context)
            u.effective_message.reply_text.assert_not_awaited()
        u = self.update()
        u.effective_message.forward_origin = object()
        await worker.manual_mail_command(u, self.context)
        self.coordinator.store.create_manual_request.assert_not_called()

    async def test_paused_queue_remains_paused_and_requests_are_serialized(self):
        c = self.coordinator
        c.paused, c.pause_persisted = True, True
        c.store = store()
        u, v = self.update(), self.update()
        await asyncio.gather(worker.manual_mail_command(u,self.context), worker.manual_mail_command(v,self.context))
        self.assertTrue(c.paused)
        self.assertEqual(len(c.store.queue.values), 2)
        self.assertIn("IN PAUSA", u.effective_message.reply_text.call_args.args[0])
        self.assertIn("già una richiesta", v.effective_message.reply_text.call_args.args[0])

    async def test_manual_job_asks_admin_privately_even_with_apprentice_enabled(self):
        c = self.coordinator
        c.settings.spreadsheet_id = "queuebook"
        c.settings.anagrafica_group_id = -100111
        r = worker.QueueRequest(2,"manual", "ATTESA_ANAGRAFICA", "queuebook", worker.MANUAL_SHEET,2,3,"Giovanni Carlo De Luca")
        c.active = r
        c.personal_name_parts = ("Giovanni Carlo", "De Luca")
        c.personal_future = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(c.request_personal_data(r))
        await c.personal_prompt_ready.wait()
        u = self.update(text="01/01/2000 | M | Roma (RM)")
        u.effective_message.chat = SimpleNamespace(id=99)
        u.effective_message.delete = AsyncMock()
        await worker.text_handler(u,self.context)
        p = await asyncio.wait_for(task, 1)
        self.assertEqual((p.first_name,p.last_name), ("Giovanni Carlo","De Luca"))
        self.assertEqual(self.bot.send_message.call_args_list[0].kwargs["chat_id"],99)

    async def test_full_ordinary_completion_saves_email_notifies_admin_and_credits_once(self):
        c = self.coordinator
        c.paused = False
        c.settings.spreadsheet_id = "queuebook"
        c.store = store()
        r, _, _ = c.store.create_manual_request("Mario", "Rossi")
        c.request_personal_data = AsyncMock(return_value=worker.PersonalData("Mario","Rossi","01/01/2000","M","Roma (RM)"))
        async def complete(request, personal):
            request.claimed_by = "11"
            c.assigned_phone = "+393330000011"
            c.mark_sms_verified(request)
            return "fixture", "fixture@libero.it"
        with patch.object(worker, "RegistrationBrowser") as cls:
            cls.return_value.create_account = AsyncMock(side_effect=complete)
            await c.process_request(r)
            cls.assert_called_once_with(c.settings,c)
        self.assertEqual(c.store.find_request(r.request_id).status,"CREATA")
        self.assertEqual(c.store.book.worksheet(worker.MANUAL_SHEET).values[1][2], "fixture@libero.it")
        self.assertEqual(c.outcomes.testers.stats(11)["count"],1)
        texts = [x.kwargs for x in self.bot.send_message.call_args_list]
        self.assertTrue(any(x['chat_id']==99 and "fixture@libero.it" in x['text'] for x in texts))
        u = self.update()
        await worker.manual_mail_command(u,self.context)
        self.assertIn("fixture@libero.it",u.effective_message.reply_text.call_args.args[0])
        self.assertEqual(len(c.store.queue.values),2)

    async def test_uncertain_append_never_claims_success(self):
        c = self.coordinator
        c.store = store()
        c.store.queue.fail_append = True
        u = self.update()
        await worker.manual_mail_command(u,self.context)
        self.assertIn("Non posso confermare",u.effective_message.reply_text.call_args.args[0])
        self.assertIsNone(c.store.next_request())
