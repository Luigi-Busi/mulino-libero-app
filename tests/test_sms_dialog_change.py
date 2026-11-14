"""Local HTML reproductions of the SMS/Cellulare screens supplied by the owner."""
import unittest
from unittest.mock import AsyncMock

from test_regressions import worker
import test_tester_timeout as browser_fixtures


class SmsDialogChangeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = browser_fixtures.BrowserFormTests.asyncSetUp
    asyncTearDown = browser_fixtures.BrowserFormTests.asyncTearDown

    async def screen(self, *, close='<button id="close">×</button>', prompt=True,
                     duplicate=False, returns_phone=True):
        await self.page.set_content('''
            <label>Mail o Cellulare<input type="tel" id="recovery"></label>
            <button onclick="window.registered=true">Registrati</button>
            <button onclick="window.back=true">Indietro</button>
            <section id="sms">
              <h2>VERIFICA DEL TUO ACCOUNT</h2>''' +
            ('<p>Inserisci il codice di conferma che abbiamo inviato al numero</p>' if prompt else '') +
            '''<label>Codice di conferma<input id="otp"></label>
              <p>Non hai ricevuto il codice, <a href="#" onclick="window.resent=true">Invia di nuovo</a></p>
              <button onclick="window.sent=true">AVANTI</button>''' + close +
            ('<button>×</button>' if duplicate else '') + '''</section>
            <section id="phoneForm" hidden><h2>VERIFICA DEL TUO ACCOUNT</h2>
              <label>Cellulare<input type="tel" id="phone" value="3330000011"></label>
              <button onclick="window.sent=true">AVANTI</button></section>''')
        await self.page.locator('#close').evaluate('''(el, returnsPhone) => {
            el.onclick = () => {
                window.closedCount = (window.closedCount || 0) + 1;
                if (returnsPhone) {
                    document.querySelector('#sms').remove();
                    document.querySelector('#phoneForm').hidden = false;
                }
            };
        }''', returns_phone)

    async def untouched(self):
        for flag in ('registered', 'back', 'resent', 'sent'):
            self.assertIsNone(await self.page.evaluate('window.' + flag))
        self.assertEqual(await self.page.locator('#recovery').input_value(), '')

    async def test_screenshot_close_returns_to_existing_number_without_any_send(self):
        await self.screen()
        await self.b._return_to_phone_form(object())
        self.assertEqual(await self.page.evaluate('window.closedCount'), 1)
        self.assertEqual(await self.page.locator('#phone').input_value(), '3330000011')
        self.c.wait_for_manual_captcha.assert_not_awaited()
        await self.untouched()

    async def test_close_link_with_accessible_label(self):
        await self.screen(close='<a id="close" aria-label="Chiudi">×</a>')
        await self.b._return_to_phone_form(object())
        self.assertTrue(await self.b._phone_edit_ready())
        await self.untouched()

    async def test_incomplete_dialog_requires_manual_review_without_close(self):
        await self.screen(prompt=False)
        with self.assertRaises(worker.RequestCancelled):
            await self.b._return_to_phone_form(object())
        self.assertIsNone(await self.page.evaluate('window.closedCount'))
        await self.untouched()

    async def test_ambiguous_close_requires_manual_review(self):
        await self.screen(duplicate=True)
        with self.assertRaises(worker.RequestCancelled):
            await self.b._return_to_phone_form(object())
        self.assertIsNone(await self.page.evaluate('window.closedCount'))
        await self.untouched()

    async def test_close_without_transition_is_not_repeated_or_assigned(self):
        await self.screen(returns_phone=False)
        self.page.wait_for_timeout = AsyncMock()
        self.c.revoke_tester = AsyncMock()
        self.b._choose_phone_and_send = AsyncMock()
        with self.assertRaises(worker.RequestCancelled):
            await self.b._replace_phone_tester(object())
        self.assertEqual(await self.page.evaluate('window.closedCount'), 1)
        self.b._choose_phone_and_send.assert_not_awaited()
        await self.untouched()

    async def test_replacement_revokes_before_close_and_only_then_asks_for_tester(self):
        await self.screen()
        events = []
        async def revoke(request):
            events.append('revoke')
            self.assertIsNone(await self.page.evaluate('window.closedCount'))
        async def choose(request):
            events.append('choose')
            self.assertTrue(await self.b._phone_edit_ready())
            await self.b._fill_phone(await self.b._find_phone_input(), '+393330000022')
        self.c.revoke_tester = AsyncMock(side_effect=revoke)
        self.b._choose_phone_and_send = AsyncMock(side_effect=choose)
        await self.b._replace_phone_tester(object())
        self.assertEqual(events, ['revoke', 'choose'])
        self.assertEqual(await self.page.locator('#phone').input_value(), '+393330000022')
        await self.untouched()

    async def test_already_returned_to_empty_cellulare_needs_no_close(self):
        await self.screen()
        await self.page.locator('#close').click()
        await self.page.locator('#phone').fill('')
        await self.b._return_to_phone_form(object())
        self.assertEqual(await self.page.evaluate('window.closedCount'), 1)
        self.c.wait_for_manual_captcha.assert_not_awaited()
        await self.untouched()

    async def test_unrelated_page_close_is_never_selected(self):
        await self.screen(close='<button id="close">Aiuto</button>')
        await self.page.evaluate('''() => {
            const other = document.createElement('button');
            other.textContent = '×'; other.onclick = () => window.wrongClose = true;
            document.body.append(other);
        }''')
        with self.assertRaises(worker.RequestCancelled):
            await self.b._return_to_phone_form(object())
        self.assertIsNone(await self.page.evaluate('window.wrongClose'))
        await self.untouched()

    async def test_disabled_close_is_not_clicked(self):
        await self.screen(close='<button id="close" disabled>×</button>')
        with self.assertRaises(worker.RequestCancelled):
            await self.b._return_to_phone_form(object())
        self.assertIsNone(await self.page.evaluate('window.closedCount'))
        await self.untouched()

    async def test_close_leading_to_reset_does_not_request_another_tester(self):
        await self.screen()
        await self.page.locator('#close').evaluate('''el => el.onclick = () => {
            document.body.innerHTML = '<input id="username"><input id="password" type="password">';
        }''')
        self.c.revoke_tester = AsyncMock()
        self.b._choose_phone_and_send = AsyncMock()
        with self.assertRaises(worker.RegistrationSessionReset):
            await self.b._replace_phone_tester(object())
        self.b._choose_phone_and_send.assert_not_awaited()
