import asyncio
import json
import logging
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import browser_diagnostics as diag
from test_regressions import worker


class PrivacyTests(unittest.TestCase):
    def test_untrusted_values_and_exception_messages_never_enter_records(self):
        observer = diag.BrowserDiagnostics('secret.person@example.test')
        with self.assertLogs('mulino-browser-diagnostics', level='INFO') as captured:
            observer.emit('session_start')
            observer.set_phase('https://example.test/?password=PRIVATE')
            observer.failure(RuntimeError('PRIVATE password=123456 secret.person@example.test'))
        text = '\n'.join(captured.output)
        for private in ('PRIVATE', 'secret.person@', 'example.test', '123456', 'password='):
            self.assertNotIn(private, text)
        values = [json.loads(line.split('MULINO_DIAG ', 1)[1]) for line in captured.output]
        self.assertTrue(all(diag.valid_event(value) for value in values))
        for malformed in ({**values[0], 'url': 'PRIVATE'}, {**values[0], 'event': []},
                          {**values[0], 'reason': {}}, {**values[0], 'schema': True},
                          {**values[0], 'resources': {'cookie': 'PRIVATE'}}):
            self.assertFalse(diag.valid_event(malformed))

    def test_resources_allow_only_numeric_cgroup_counters(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'memory.current').write_text('1234')
            (root / 'memory.max').write_text('max')
            (root / 'memory.events').write_text('oom 2\noom_kill 1\nprivate 123456\n')
            self.assertEqual(diag.resources(root), {'memory_bytes': 1234, 'oom': 2, 'oom_kill': 1})


class Emitter:
    def __init__(self):
        self.handlers = {}

    def on(self, event, callback):
        self.handlers.setdefault(event, []).append(callback)

    def emit(self, event):
        for callback in self.handlers.get(event, []):
            callback(self)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setup_browser(self):
        page, context, browser = Emitter(), Emitter(), Emitter()
        page.goto = AsyncMock()
        context.new_page = AsyncMock(return_value=page)
        context.clear_cookies = AsyncMock()
        context.close = AsyncMock(side_effect=lambda: (page.emit('close'), context.emit('close')))
        browser.new_context = AsyncMock(return_value=context)
        browser.close = AsyncMock(side_effect=lambda: browser.emit('disconnected'))
        manager = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))
        factory = Mock()
        factory.return_value.__aenter__ = AsyncMock(return_value=manager)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        coordinator = SimpleNamespace(monitor_browser=None, record_created=Mock())
        registration = worker.RegistrationBrowser(SimpleNamespace(headless=True, registration_url='https://private.example.test'), coordinator)
        registration._dismiss_cookie_banner = AsyncMock()
        registration._fill_credentials = AsyncMock(return_value='fixture')
        registration._fill_personal_data = AsyncMock()
        registration._complete_remaining_steps = AsyncMock()
        return registration, coordinator, page, context, browser, factory

    async def run_registration(self, registration):
        return await registration.create_account(SimpleNamespace(request_id='fixture-request'), SimpleNamespace())

    def records(self, captured):
        return [json.loads(line.split('MULINO_DIAG ', 1)[1]) for line in captured.output]

    async def test_success_cleanup_is_expected_and_result_is_saved_first(self):
        registration, coordinator, page, context, browser, factory = self.setup_browser()
        with patch.object(worker, 'async_playwright', factory), self.assertLogs('mulino-browser-diagnostics', level='INFO') as captured:
            result = await self.run_registration(registration)
        self.assertEqual(result, ('fixture', 'fixture@libero.it'))
        coordinator.record_created.assert_called_once()
        self.assertIsNone(coordinator.monitor_browser)
        events = self.records(captured)
        self.assertFalse(any(event['event'] == 'operation_error' for event in events))
        closed = [event for event in events if event['event'] in ('page_close', 'context_close', 'browser_disconnected')]
        self.assertEqual(len(closed), 3)
        self.assertTrue(all(event['expected'] and event['reason'] == 'completed' for event in closed))

    async def test_original_error_survives_cleanup_failure_and_no_retry_occurs(self):
        registration, coordinator, page, context, browser, factory = self.setup_browser()
        class TargetClosedError(RuntimeError):
            pass
        original = TargetClosedError('PRIVATE password email@example.test')
        async def fail(*args):
            page.emit('close')
            raise original
        registration._fill_credentials.side_effect = fail
        context.clear_cookies.side_effect = RuntimeError('PRIVATE secondary error')
        context.close.side_effect = TargetClosedError('PRIVATE secondary target')
        with patch.object(worker, 'async_playwright', factory), self.assertLogs('mulino-browser-diagnostics', level='INFO') as captured:
            with self.assertRaises(TargetClosedError) as raised:
                await self.run_registration(registration)
        self.assertIs(raised.exception, original)
        self.assertNotIn('PRIVATE', '\n'.join(captured.output))
        coordinator.record_created.assert_not_called()
        registration._fill_credentials.assert_awaited_once()
        browser.close.assert_awaited_once()
        events = self.records(captured)
        closed = next(event for event in events if event['event'] == 'page_close')
        self.assertFalse(closed['expected'])
        primary = next(event for event in events if event['event'] == 'operation_error')
        self.assertEqual(primary['error'], 'target_closed')
        self.assertLess(primary['seq'], next(event for event in events if event['event'] == 'cleanup_error')['seq'])

    async def test_launch_failure_is_recorded_without_a_page(self):
        registration, coordinator, page, context, browser, factory = self.setup_browser()
        factory.return_value.__aenter__.return_value.chromium.launch.side_effect = RuntimeError('PRIVATE launch')
        with patch.object(worker, 'async_playwright', factory), self.assertLogs('mulino-browser-diagnostics', level='INFO') as captured:
            with self.assertRaises(RuntimeError):
                await self.run_registration(registration)
        self.assertNotIn('PRIVATE', '\n'.join(captured.output))
        self.assertTrue(any(event['event'] == 'operation_error' for event in self.records(captured)))
        coordinator.record_created.assert_not_called()

    async def test_cancellation_is_recorded_and_propagated(self):
        registration, coordinator, page, context, browser, factory = self.setup_browser()
        registration._fill_credentials.side_effect = asyncio.CancelledError()
        with patch.object(worker, 'async_playwright', factory), self.assertLogs('mulino-browser-diagnostics', level='INFO') as captured:
            with self.assertRaises(asyncio.CancelledError):
                await self.run_registration(registration)
        events = self.records(captured)
        self.assertEqual(events[-1]['reason'], 'cancelled')
        coordinator.record_created.assert_not_called()

    async def test_logging_failure_cannot_fail_a_successful_registration(self):
        registration, coordinator, page, context, browser, factory = self.setup_browser()
        with patch.object(worker, 'async_playwright', factory), patch.object(logging.getLogger('mulino-browser-diagnostics'), 'info', side_effect=OSError('disk full')):
            self.assertEqual(await self.run_registration(registration), ('fixture', 'fixture@libero.it'))


class RealBrowserEventsTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_page_close_and_browser_disconnect_are_separate(self):
        async with worker.async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, args=['--no-sandbox'])
            context = await browser.new_context()
            page = await context.new_page()
            observer = diag.BrowserDiagnostics('fixture')
            with self.assertLogs('mulino-browser-diagnostics', level='INFO') as captured:
                observer.attach_browser(browser)
                observer.attach_context(context)
                observer.attach_page(page)
                await page.close()
                observer.begin_cleanup('cancelled')
                await context.close()
                await browser.close()
            events = [json.loads(line.split('MULINO_DIAG ', 1)[1]) for line in captured.output]
            self.assertFalse(next(event for event in events if event['event'] == 'page_close')['expected'])
            self.assertTrue(next(event for event in events if event['event'] == 'browser_disconnected')['expected'])

    async def test_real_renderer_crash_is_recorded_without_page_contents(self):
        async with worker.async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, args=['--no-sandbox'])
            context = await browser.new_context()
            page = await context.new_page()
            observer = diag.BrowserDiagnostics('fixture-crash')
            crashed = asyncio.Event()
            page.on('crash', lambda *_: crashed.set())
            try:
                with self.assertLogs('mulino-browser-diagnostics', level='INFO') as captured:
                    observer.attach_page(page)
                    session = await context.new_cdp_session(page)
                    crash = asyncio.create_task(session.send('Page.crash'))
                    try:
                        await asyncio.wait_for(crashed.wait(), 10)
                    finally:
                        crash.cancel()
                        await asyncio.gather(crash, return_exceptions=True)
                events = [json.loads(line.split('MULINO_DIAG ', 1)[1]) for line in captured.output]
                self.assertTrue(any(event['event'] == 'page_crash' and not event['expected'] for event in events))
            finally:
                await context.close()
                await browser.close()
