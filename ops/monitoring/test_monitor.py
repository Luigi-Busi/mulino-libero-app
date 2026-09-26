import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import monitor


class MonitorTests(unittest.TestCase):
    def healthy(self, **changes):
        data = dict(schema=1, service='mugnaio', pid=12, started=100, updated=995,
                    poll=980, queue_ok=True, paused=True, busy=False, human_wait=False)
        data.update(changes)
        return data

    def test_paused_and_human_wait_are_normal(self):
        for flags in [dict(paused=True), dict(paused=False, busy=True, human_wait=True)]:
            self.assertEqual(monitor.runtime_problem(self.healthy(**flags), 'mugnaio', True, 1000), 'OK')

    def test_running_process_does_not_hide_a_frozen_loop(self):
        self.assertEqual(monitor.runtime_problem(self.healthy(updated=700), 'mugnaio', True, 1000), 'CICLO_BLOCCATO')

    def test_polling_and_queue_failures_are_distinct(self):
        self.assertEqual(monitor.runtime_problem(self.healthy(poll=700), 'mugnaio', True, 1000), 'TELEGRAM_NON_RAGGIUNTO')
        self.assertEqual(monitor.runtime_problem(self.healthy(queue_ok=False), 'mugnaio', True, 1000), 'CODA_NON_AGGIORNATA')

    def test_startup_grace_expires_and_does_not_cover_missing_file(self):
        self.assertEqual(monitor.runtime_problem(self.healthy(started=950, poll=None, queue_ok=False), 'mugnaio', True, 1000), 'OK')
        self.assertNotEqual(monitor.runtime_problem(self.healthy(started=800, poll=None), 'mugnaio', True, 1000), 'OK')
        self.assertNotEqual(monitor.runtime_problem(None, 'mugnaio', True, 1000), 'OK')

    def test_stopped_process_and_wrong_service_are_rejected(self):
        self.assertNotEqual(monitor.runtime_problem(self.healthy(), 'mugnaio', False, 1000), 'OK')
        self.assertNotEqual(monitor.runtime_problem(self.healthy(service='other'), 'mugnaio', True, 1000), 'OK')

    def test_invalid_clock_values_cannot_be_healthy(self):
        for stamp in [float('nan'), float('inf'), True, '999', 1001, -1, None]:
            self.assertFalse(monitor.age_good(stamp, 1000, 100))

    def test_failure_and_recovery_require_two_samples(self):
        first = monitor.stabilize({'disk': 'FULL'}, {}, 1000)
        self.assertFalse(first['components']['disk']['alarm'])
        second = monitor.stabilize({'disk': 'FULL'}, first, 1120)
        self.assertTrue(second['components']['disk']['alarm'])
        recovering = monitor.stabilize({'disk': 'OK'}, second, 1240)
        self.assertTrue(recovering['components']['disk']['alarm'])
        self.assertEqual(recovering['components']['disk']['code'], 'RIENTRO_IN_VERIFICA')
        healthy = monitor.stabilize({'disk': 'OK'}, recovering, 1360)
        self.assertFalse(healthy['components']['disk']['alarm'])

    def test_old_samples_do_not_confirm_new_fault(self):
        first = monitor.stabilize({'disk': 'FULL'}, {}, 1000)
        second = monitor.stabilize({'disk': 'FULL'}, first, 2000)
        self.assertFalse(second['components']['disk']['alarm'])

    def test_digest_cache_detects_replaced_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'copy.gpg'
            path.write_bytes(b'abc')
            cache = {}
            expected = monitor.hashlib.sha256(b'abc').hexdigest()
            self.assertTrue(monitor.file_matches(path, expected, cache))
            self.assertTrue(monitor.file_matches(path, expected, cache))
            path.write_bytes(b'bad')
            self.assertFalse(monitor.file_matches(path, expected, cache))

    def test_receipt_cannot_choose_an_unrelated_file(self):
        for name in ['../config.json', 'system-bad.json', '/etc/passwd', None]:
            with self.assertRaises(ValueError):
                monitor.checked_index(name)

    def test_receipt_hash_must_match_published_backup(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(monitor, 'EXPORT', Path(temp)):
            name = 'system-20260926T170250Z.json'
            data = dict(format='mulino-system-index-v1', file=name[:-5]+'.tar.gpg', sha256='a'*64)
            (Path(temp) / name).write_text(json.dumps(data))
            self.assertEqual(monitor.checked_index(name, 'a'*64), data)
            with self.assertRaises(ValueError):
                monitor.checked_index(name, 'b'*64)

    def test_receipt_freshness_uses_original_backup_date(self):
        stamp = monitor.source_time({'created_utc': '20260926T170250Z'})
        self.assertTrue(monitor.age_good(stamp, stamp+29*3600, 30*3600))
        self.assertFalse(monitor.age_good(stamp, stamp+31*3600, 30*3600))

    def test_no_signal_can_go_to_other_destinations(self):
        for url in ['http://hc-ping.com/test', 'https://example.com', 'https://hc-ping.com@evil.test/x',
                    'https://hc-ping.com/00000000-0000-0000-0000-000000000000?token=x']:
            with self.assertRaises(ValueError):
                monitor.ping(url, False, 'OK')


if __name__ == '__main__':
    unittest.main()
