import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

from browser_diagnostics import BrowserDiagnostics, valid_launcher_event
from collector import Collector, decode_line, docker_event, cgroup_resources


class CollectorTests(unittest.TestCase):
    def test_ordinary_logs_and_private_or_malformed_payloads_are_discarded(self):
        observer = BrowserDiagnostics('fixture')
        import logging
        with self.assertLogs('mulino-browser-diagnostics', level='INFO') as captured:
            observer.emit('session_start')
        line = captured.output[0]
        self.assertIsNotNone(decode_line(line))
        private = json.loads(line.split('MULINO_DIAG ', 1)[1])
        private['password'] = 'PRIVATE'
        for raw in ('PRIVATE password=12345', 'MULINO_DIAG []', 'MULINO_DIAG {broken',
                    'MULINO_DIAG ' + json.dumps(private), 'MULINO_DIAG ' + 'x' * 5000):
            self.assertIsNone(decode_line(raw))

    def test_docker_records_omit_names_commands_and_other_attributes(self):
        value = {'Type': 'container', 'Action': 'die', 'Actor': {'ID': 'a' * 64, 'Attributes': {
            'com.docker.compose.project': 'mulino-libero',
            'com.docker.compose.service': 'libero-mail-bot',
            'exitCode': '137', 'name': 'PRIVATE', 'execCommand': 'PASSWORD=PRIVATE'}}, 'timeNano': 123}
        record = docker_event(json.dumps(value))
        self.assertEqual(record['exit_code'], 137)
        self.assertNotIn('PRIVATE', json.dumps(record))
        value['Action'] = 'exec_start'
        self.assertIsNone(docker_event(json.dumps(value)))
        value['Action'] = 'oom'
        self.assertEqual(docker_event(json.dumps(value))['event'], 'oom')
        value['Actor']['Attributes']['com.docker.compose.project'] = 'other'
        self.assertIsNone(docker_event(json.dumps(value)))

    def test_launcher_rejects_unexpected_fields_and_free_text(self):
        value = {'schema': 1, 'source': 'launcher', 'event': 'component_exit',
                 'component': 'vnc', 'exit_code': 23, 'signal': 0, 'expected': False}
        self.assertTrue(valid_launcher_event(value))
        self.assertFalse(valid_launcher_event({**value, 'component': 'PRIVATE'}))
        self.assertFalse(valid_launcher_event({**value, 'stderr': 'PRIVATE'}))

    def test_cgroup_path_escape_is_not_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            group = root / 'group'
            proc = root / 'proc/123'
            group.mkdir()
            proc.mkdir(parents=True)
            (group / 'memory.current').write_text('123')
            (proc / 'cgroup').write_text('0::/../../outside\n')
            self.assertEqual(cgroup_resources(123, group, root / 'proc'), {})

    def test_rotation_bounds_and_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'logs'
            collector = Collector(root)
            self.assertEqual(collector.handler.maxBytes, 2 * 1024**2)
            self.assertEqual(collector.handler.backupCount, 4)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual((root / 'events.jsonl').stat().st_mode & 0o777, 0o600)
            collector.handler.close()
            collector.logger.removeHandler(collector.handler)

    def test_replayed_log_is_deduplicated_but_later_identical_exit_is_retained(self):
        value = {'schema': 1, 'source': 'launcher', 'event': 'component_exit',
                 'component': 'vnc', 'exit_code': 23, 'signal': 0, 'expected': False}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'logs'
            observer = Collector(root)
            try:
                first = '2026-09-30T04:00:00.123456789Z MULINO_DIAG ' + json.dumps(value)
                second = '2026-09-30T04:01:00.123456789Z MULINO_DIAG ' + json.dumps(value)
                seen = set()
                for line in (first, first, second):
                    observer.receive_log('a' * 64, line, seen)
                records = [json.loads(line) for line in (root / 'events.jsonl').read_text().splitlines()]
                self.assertEqual(len(records), 2)
                self.assertNotEqual(records[0]['logged_utc'], records[1]['logged_utc'])
            finally:
                observer.handler.close()
                observer.logger.removeHandler(observer.handler)
