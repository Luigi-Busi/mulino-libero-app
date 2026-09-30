import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import monitor


class ExportTests(unittest.TestCase):
    def report(self):
        return dict(checked_utc='2026-09-30T16:00:00+00:00', codes={c: 'OK' for c in (
            'mugnaio', 'browser', 'risponditore', 'disco', 'backup_creazione', 'backup_esportazione', 'backup_pc')},
            states={'paused': False}, private='TEST-SECRET', ping_url='TEST-SECRET')

    def test_export_drops_configuration_states_and_private_fields(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(monitor, 'ROOT', Path(temp)):
            monitor.publish_panel(self.report())
            path = Path(temp) / 'panel' / 'status.json'
            raw = path.read_text()
            self.assertNotIn('TEST-SECRET', raw)
            self.assertEqual(set(json.loads(raw)), {'schema', 'checked_utc', 'codes'})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_symlink_export_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(monitor, 'ROOT', Path(temp)):
            (Path(temp) / 'panel').symlink_to(Path(temp), target_is_directory=True)
            with self.assertRaises(ValueError): monitor.publish_panel(self.report())

    def test_bad_component_set_or_arbitrary_codes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(monitor, 'ROOT', Path(temp)):
            report = self.report()
            report['codes']['mugnaio'] = 'TEST-SECRET'
            with self.assertRaises(ValueError): monitor.publish_panel(report)
            report = self.report()
            report['codes']['extra'] = 'OK'
            with self.assertRaises(ValueError): monitor.publish_panel(report)

    def test_atomic_replacement_advances_timestamp(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(monitor, 'ROOT', Path(temp)):
            report = self.report()
            monitor.publish_panel(report)
            report['checked_utc'] = '2026-09-30T16:02:00+00:00'
            monitor.publish_panel(report)
            self.assertEqual(json.loads((Path(temp) / 'panel' / 'status.json').read_text())['checked_utc'], report['checked_utc'])
