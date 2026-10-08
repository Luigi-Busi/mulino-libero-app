import unittest
from unittest.mock import AsyncMock
from test_regressions import worker
import test_tester_timeout as browser_fixtures

class NameNormalizationTests(unittest.TestCase):
    def test_accents_and_combining_forms(self):
        for value, expected in [("Nicolò", "Nicolo"), ("Jose\u0301", "Jose"),
                                ("Álvaro Muñoz", "Alvaro Munoz")]:
            self.assertEqual(worker.libero_personal_name(value), expected)

    def test_apostrophes_hyphens_and_whitespace(self):
        for value in ["D’Angelo", "D‘Angelo", "DʼAngelo", "D'Angelo"]:
            self.assertEqual(worker.libero_personal_name(value), "D'Angelo")
        self.assertEqual(worker.libero_personal_name("  Anne‑Marie  De   Rosa "), "Anne-Marie De Rosa")

    def test_unsupported_names_are_not_silently_truncated(self):
        for value in ["", "---", "Mario123", "李", "Søren", "Name<script>"]:
            with self.assertRaises(worker.RegistrationError):
                worker.libero_personal_name(value)

class PersonalValidationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = browser_fixtures.BrowserFormTests.asyncSetUp
    asyncTearDown = browser_fixtures.BrowserFormTests.asyncTearDown

    async def form(self):
        html = """<input id=firstname><input id=lastname><input id=dateofbirth>
        <input id=comune_provincia><input id=male type=radio name=gender>
        <div class=mdb-autocomplete-wrap><li>Fixture City</li></div>
        <button id=button_submit>Avanti</button>
        <div id=feedback hidden>Presenza di caratteri non validi</div>"""
        await self.page.route('https://registrazione.libero.it/**',lambda r:r.fulfill(body=html,content_type='text/html; charset=utf-8'))
        await self.page.goto('https://registrazione.libero.it/join2.phtml')
        self.b._handle_captcha_if_needed = AsyncMock()
        self.b._click_and_wait_for_change = AsyncMock()

    async def test_fill_normalizes_only_browser_fields_and_keeps_originals(self):
        await self.form()
        p = worker.PersonalData("Nicolò", "D’Angelo", "01/02/1990", "M", "Fixture City")
        await self.b._fill_personal_data(object(), p)
        self.assertEqual(await self.page.locator('#firstname').input_value(), 'Nicolo')
        self.assertEqual(await self.page.locator('#lastname').input_value(), "D'Angelo")
        self.assertEqual((p.first_name,p.last_name),("Nicolò","D’Angelo"))
        self.b._click_and_wait_for_change.assert_awaited_once_with('#button_submit')

    async def test_invalid_field_blocks_before_submit_without_leaking_value(self):
        await self.form()
        await self.page.locator('#lastname').evaluate("el=>el.setAttribute('aria-invalid','true')")
        p = worker.PersonalData('Fixture', 'PrivateName', '01/02/1990', 'M', 'Fixture City')
        with self.assertRaisesRegex(worker.RegistrationError,'campo cognome') as error:
            await self.b._fill_personal_data(object(),p)
        self.assertNotIn('PrivateName',str(error.exception))
        self.b._click_and_wait_for_change.assert_not_awaited()

    async def test_rejection_after_submit_is_detected_without_second_click(self):
        await self.form()
        async def reject(selector):
            await self.page.locator('#feedback').evaluate('el=>el.hidden=false')
        self.b._click_and_wait_for_change.side_effect = reject
        p=worker.PersonalData('Fixture','Surname','01/02/1990','M','Fixture City')
        with self.assertRaisesRegex(worker.RegistrationError,'caratteri non validi'):
            await self.b._fill_personal_data(object(),p)
        self.b._click_and_wait_for_change.assert_awaited_once()

    async def test_hidden_error_or_next_page_does_not_fail(self):
        await self.form()
        await self.b._raise_if_personal_data_invalid()
        await self.page.evaluate("document.body.innerHTML='<h1>Protezione Account</h1>'")
        await self.b._raise_if_personal_data_invalid()

    async def test_html_native_validity_and_invalid_class(self):
        for attr in ['pattern','class']:
            await self.form()
            await self.page.locator('#firstname').fill('Fixture')
            await self.page.locator('#firstname').evaluate("(el,attr)=>el.setAttribute(attr,attr==='pattern'?'[0-9]+':'is-invalid')",attr)
            with self.assertRaisesRegex(worker.RegistrationError,'campo nome'):
                await self.b._raise_if_personal_data_invalid()
