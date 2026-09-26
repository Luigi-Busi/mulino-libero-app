import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from runtime_health import RuntimeHealth, HealthRequest, HTTPXRequest
from test_regressions import worker


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_successful_get_updates_marks_polling(self):
        monitor = RuntimeHealth('risponditore', '/unused/test')
        request = HealthRequest(monitor)
        try:
            with patch.object(HTTPXRequest, 'do_request', new=AsyncMock(return_value=(200, b'{"ok":true,"result":[]}'))):
                await request.do_request('https://api.telegram.org/botTEST/getMe', 'POST')
                self.assertIsNone(monitor.last_poll)
                await request.do_request('https://api.telegram.org/botTEST/getUpdates', 'POST')
                self.assertIsNotNone(monitor.last_poll)
            stamp = monitor.last_poll
            for result in [(401, b'{"ok":false}'), (200, b'bad-json'), (200, b'{"ok":false}')]:
                with patch.object(HTTPXRequest, 'do_request', new=AsyncMock(return_value=result)):
                    await request.do_request('https://api.telegram.org/botTEST/getUpdates', 'POST')
                    self.assertEqual(monitor.last_poll, stamp)
        finally:
            await request.shutdown()

    async def test_writer_rejects_private_or_unexpected_content(self):
        with tempfile.TemporaryDirectory() as temp:
            monitor = RuntimeHealth('mugnaio', Path(temp) / 'health.json')
            for fields in [{'email': 'private@example.test'}, {'paused': 'private data'}]:
                with self.assertRaises(ValueError):
                    monitor.write(fields)
            monitor.write({'paused': True, 'busy': False})
            data = json.loads(monitor.path.read_text())
            self.assertTrue(data['paused'])
            self.assertFalse(data['busy'])
            self.assertEqual(data['service'], 'mugnaio')

    async def test_actual_queue_loop_updates_during_pause_and_stops_when_blocked(self):
        coordinator = worker.Coordinator(SimpleNamespace(poll_seconds=.01), SimpleNamespace())
        coordinator.paused = True
        coordinator.sync_pending_outcomes = AsyncMock()
        coordinator.messages.drain = AsyncMock()
        coordinator.application = SimpleNamespace(bot=object(), bot_data={})
        task = asyncio.create_task(coordinator.loop())
        coordinator.application.bot_data['queue_task'] = task
        try:
            await asyncio.sleep(.05)
            snapshot = await coordinator.health_snapshot()
            self.assertTrue(snapshot['queue_ok'])
            self.assertTrue(snapshot['paused'])
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.assertFalse((await coordinator.health_snapshot())['queue_ok'])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            coordinator.messages.close()
            coordinator.outcomes.close()

    async def test_human_wait_is_observed_without_losing_browser_check(self):
        coordinator = worker.Coordinator(SimpleNamespace(), SimpleNamespace())
        coordinator.phone_future = asyncio.get_running_loop().create_future()
        coordinator.monitor_browser = SimpleNamespace(
            browser=SimpleNamespace(is_connected=lambda: True),
            page=SimpleNamespace(is_closed=lambda: False, title=AsyncMock(return_value='ignored')))
        try:
            snapshot = await coordinator.health_snapshot()
            self.assertTrue(snapshot['human_wait'])
            self.assertTrue(snapshot['browser_expected'])
            self.assertTrue(snapshot['browser_ok'])
            coordinator.monitor_browser.page.title.side_effect = RuntimeError('closed')
            self.assertFalse((await coordinator.health_snapshot())['browser_ok'])
        finally:
            coordinator.phone_future.cancel()
            coordinator.messages.close()
            coordinator.outcomes.close()


if __name__ == '__main__':
    unittest.main()
