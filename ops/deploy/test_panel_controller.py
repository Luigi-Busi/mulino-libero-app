import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from controller import Config, Failure, Manager, PANEL_BIND, reviewed_compose_change


class PanelControllerTests(unittest.TestCase):
    def setUp(self):
        self.manager = Manager()
        self.before = Path(__file__).resolve().parents[2].joinpath('docker-compose.yml').read_bytes().replace(PANEL_BIND, b'')
        self.after = self.before.replace(b'      - ../data:/data\n', b'      - ../data:/data\n' + PANEL_BIND)
        self.model = {'services': {self.manager.c.service: {'volumes': [
            {'type': 'bind', 'source': str(self.manager.c.data), 'target': '/data'},
            {'type': 'bind', 'source': '/var/lib/mulino-monitor/panel', 'target': '/run/mulino-panel',
             'read_only': True, 'bind': {'create_host_path': False}},
        ]}}}

    def test_only_exact_read_only_addition_and_reverse_are_allowed(self):
        self.assertTrue(reviewed_compose_change(self.before, self.after))
        self.assertTrue(reviewed_compose_change(self.after, self.before))
        self.assertTrue(reviewed_compose_change(self.before, self.before))
        self.assertTrue(reviewed_compose_change(self.after, self.after))

    def test_sensitive_paths_writes_extra_mounts_ports_and_duplicate_bind_rejected(self):
        for bad in (self.after.replace(b'read_only: true', b'read_only: false'),
                    self.after.replace(b'create_host_path: false', b'create_host_path: true'),
                    self.after.replace(b'/var/lib/mulino-monitor/panel', b'/etc/mulino-monitor'),
                    self.after.replace(b'/run/mulino-panel', b'/run/secrets'),
                    self.after.replace(b'127.0.0.1:6080', b'0.0.0.0:6080'),
                    self.after.replace(PANEL_BIND, PANEL_BIND * 2),
                    self.after + b'    privileged: true\n',
                    self.after.replace(b'      - ../data:/data', b'      - ../data:/data:ro')):
            self.assertFalse(reviewed_compose_change(self.before, bad))

    def test_model_accepts_old_and_reviewed_panel_configurations(self):
        with patch.object(self.manager, 'compose', return_value=json.dumps(self.model)):
            self.manager.model()
        self.model['services'][self.manager.c.service]['volumes'].pop()
        with patch.object(self.manager, 'compose', return_value=json.dumps(self.model)):
            self.manager.model()

    def test_model_rejects_unexpected_or_writable_mounts(self):
        for change in ('source', 'write', 'create', 'extra', 'data_read_only', 'missing_data'):
            model = copy.deepcopy(self.model)
            volumes = model['services'][self.manager.c.service]['volumes']
            if change == 'source': volumes[1]['source'] = '/etc/mulino-monitor'
            if change == 'write': volumes[1]['read_only'] = False
            if change == 'create': volumes[1]['bind']['create_host_path'] = True
            if change == 'extra': volumes.append(dict(type='bind', source='/etc', target='/etc'))
            if change == 'data_read_only': volumes[0]['read_only'] = True
            if change == 'missing_data': volumes.pop(0)
            with patch.object(self.manager, 'compose', return_value=json.dumps(model)):
                with self.assertRaises(Failure):
                    self.manager.model()

    def test_runtime_rejects_writable_panel_even_if_image_matches(self):
        record = {'image': 'sha256:fixture'}
        container = {'Image': record['image'], 'Config': {'Labels': {
            'com.docker.compose.project': self.manager.c.project,
            'com.docker.compose.service': self.manager.c.service}}, 'Mounts': [
            {'Source': str(self.manager.c.data), 'Destination': '/data', 'RW': True},
            {'Source': '/var/lib/mulino-monitor/panel', 'Destination': '/run/mulino-panel', 'RW': True}]}
        with patch.object(self.manager, 'model', return_value=self.model), patch.object(self.manager, 'inspect', return_value=container):
            with self.assertRaises(Failure): self.manager.runtime_matches(record)
            container['Mounts'][1]['RW'] = False
            self.manager.runtime_matches(record)

    def test_preflight_does_not_mount_panel_or_production_data(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = Manager(Config(app=Path(temp) / 'app', state=Path(temp)))
            with patch.object(manager, 'model', return_value=self.model), patch.object(manager, 'run', return_value=''):
                manager.check_integrations({'image_tag': 'fixture'}, Path(temp))
            safe = json.loads((Path(temp) / 'preflight.json').read_text())['services'][manager.c.service]
            self.assertNotIn('volumes', safe)

    def test_panel_image_also_verifies_displayed_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertNotIn('VERSION', self.manager.image_files(root))
            (root / 'telegram_panel.py').touch()
            self.assertIn('telegram_panel.py', self.manager.image_files(root))
            self.assertIn('VERSION', self.manager.image_files(root))
