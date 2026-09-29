import copy
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from controller import Config, Failure, Manager, atomic, browser_url_only_change, REMOTE_BROWSER_URLS


class BrowserComposeTests(unittest.TestCase):
    def setUp(self):
        self.before = b'services:\n  libero-mail-bot:\n    environment:\n      REMOTE_BROWSER_URL: ' + REMOTE_BROWSER_URLS[0] + b'\n    ports:\n      - "127.0.0.1:6080:6080"\n'
        self.after = self.before.replace(REMOTE_BROWSER_URLS[0], REMOTE_BROWSER_URLS[1])

    def test_reviewed_transition_and_reverse_are_allowed(self):
        self.assertTrue(browser_url_only_change(self.before, self.after))
        self.assertTrue(browser_url_only_change(self.after, self.before))
        self.assertTrue(browser_url_only_change(self.before, self.before))
        self.assertTrue(browser_url_only_change(self.before.replace(b'\n', b'\r\n'), self.after.replace(b'\n', b'\r\n')))

    def test_unreviewed_urls_credentials_and_public_endpoints_are_rejected(self):
        for url in (b'https://example.com/vnc.html', b'http://80.211.133.89:6080/vnc.html',
                    REMOTE_BROWSER_URLS[1] + b'&password=secret', REMOTE_BROWSER_URLS[1] + b'#secret',
                    REMOTE_BROWSER_URLS[1].replace(b'https://', b'https://user:secret@')):
            with self.subTest(url=url):
                self.assertFalse(browser_url_only_change(self.before, self.after.replace(REMOTE_BROWSER_URLS[1], url)))

    def test_other_compose_changes_remain_blocked(self):
        for extra in (self.after.replace(b'127.0.0.1:6080', b'0.0.0.0:6080'),
                      self.after + b'    privileged: true\n',
                      self.after + b'    volumes: ["../secrets:/data"]\n',
                      self.after.replace(b'\n', b'\r\n'),
                      self.after.replace(b'    ports:', b'    network_mode: host\n    ports:')):
            self.assertFalse(browser_url_only_change(self.before, extra))

    def test_removed_duplicated_or_reindented_url_is_rejected(self):
        for after in (self.after.replace(b'      REMOTE_BROWSER_URL:', b'      OTHER:'),
                      self.after + b'      REMOTE_BROWSER_URL: ' + REMOTE_BROWSER_URLS[1] + b'\n',
                      self.after.replace(b'      REMOTE_BROWSER_URL:', b'        REMOTE_BROWSER_URL:')):
            self.assertFalse(browser_url_only_change(self.before, after))

    def test_preflight_uses_candidate_compose_and_no_production_data_mount(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = Manager(Config(app=root / 'app', state=root))
            candidate = root / 'candidate'
            model = {'services': {manager.c.service: {'environment': {'REMOTE_BROWSER_URL': REMOTE_BROWSER_URLS[1].decode()}}}}
            with patch.object(manager, 'model', return_value=model) as render, patch.object(manager, 'run', return_value=''):
                manager.check_integrations({'image_tag': 'test:image'}, candidate)
            render.assert_called_once_with(compose_file=candidate / 'docker-compose.yml')
            preflight = json.loads((root / 'preflight.json').read_text())['services'][manager.c.service]
            self.assertEqual(preflight['environment']['REMOTE_BROWSER_URL'], REMOTE_BROWSER_URLS[1].decode())
            self.assertNotIn('volumes', preflight)
            self.assertEqual(preflight['environment']['DATA_DIR'], '/tmp/mulino-check')

    def test_runtime_rejects_stale_browser_url(self):
        manager = Manager()
        record = release('v1.1.1', 'a' * 40)
        container = {'Image': record['image'], 'Config': {'Labels': {'com.docker.compose.project': manager.c.project, 'com.docker.compose.service': manager.c.service},
                     'Env': ['REMOTE_BROWSER_URL=' + REMOTE_BROWSER_URLS[0].decode()]},
                     'Mounts': [{'Source': str(manager.c.data), 'Destination': '/data', 'RW': True}]}
        model = {'services': {manager.c.service: {'environment': {'REMOTE_BROWSER_URL': REMOTE_BROWSER_URLS[1].decode()}}}}
        with patch.object(manager, 'model', return_value=model), patch.object(manager, 'inspect', return_value=container):
            with self.assertRaisesRegex(Failure, 'collegamento'):
                manager.runtime_matches(record)
            container['Config']['Env'] = ['REMOTE_BROWSER_URL=' + REMOTE_BROWSER_URLS[1].decode()]
            manager.runtime_matches(record)


def release(tag, sha):
    return dict(tag=tag, sha=sha, image='sha256:' + sha, image_tag='test:' + sha, branch='')


class Simulation(Manager):
    def __init__(self, directory):
        super().__init__(Config(app=Path(directory) / 'app', state=Path(directory) / 'state', minimum_free=0))
        self.c.state.mkdir()
        self.events = []
        self.failures = set()
        self.current = release('v1.0.0', 'a' * 40)
        self.next = release('v1.0.1', 'b' * 40)
        self.state = dict(schema=1, current=self.current, previous=None, pending=None, configuration={})
        self.save(self.state)

    def activate(self, record):
        self.events.append(record['tag'])
        if record['tag'] in self.failures:
            raise Failure('simulated activation failure')
        self.current = record

    def prepare(self, tag):
        if 'prepare' in self.failures:
            raise Failure('tests/build failed')
        return self.next

    def guard(self, state, pending=False):
        if 'dirty' in self.failures:
            raise Failure('dirty')

    def runtime_matches(self, record):
        return {}

    def health(self, record):
        pass

    def ensure_image(self, record):
        pass

    def maintenance(self, record, idle_confirmed):
        if not idle_confirmed:
            raise Failure('idle confirmation absent')


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.m = Simulation(self.tmp.name)

    def test_success_commits_current_and_preserves_previous(self):
        self.m.deploy('v1.0.1', True, True)
        state = self.m.load()
        self.assertEqual(state['current']['tag'], 'v1.0.1')
        self.assertEqual(state['previous']['tag'], 'v1.0.0')
        self.assertIsNone(state['pending'])
        self.assertEqual((self.m.c.state / 'last-known-good').read_text(), 'v1.0.0\n')

    def test_failure_restores_old_without_accepting_failed_release(self):
        self.m.failures.add('v1.0.1')
        with self.assertRaisesRegex(Failure, 'ripristinata'):
            self.m.deploy('v1.0.1', True, True)
        self.assertEqual(self.m.events, ['v1.0.1', 'v1.0.0'])
        self.assertEqual(self.m.load()['current']['tag'], 'v1.0.0')
        self.assertIsNone(self.m.load()['previous'])

    def test_double_failure_keeps_recovery_journal(self):
        self.m.failures.update(('v1.0.0', 'v1.0.1'))
        with self.assertRaisesRegex(Failure, 'ripristino falliti'):
            self.m.deploy('v1.0.1', True, True)
        self.assertEqual(self.m.load()['pending']['phase'], 'recovery-required')
        self.m.failures.clear()
        self.m.rollback(recover=True)
        self.assertIsNone(self.m.load()['pending'])
        self.assertEqual(self.m.current['tag'], 'v1.0.0')

    def test_interrupted_transaction_recovers_saved_from(self):
        state = self.m.load()
        state['pending'] = {'from': self.m.current, 'to': self.m.next, 'phase': 'activating'}
        self.m.save(state)
        with self.assertRaisesRegex(Failure, 'recover'):
            self.m.rollback()
        self.m.rollback(recover=True)
        self.assertEqual(self.m.events, ['v1.0.0'])

    def test_manual_rollback_uses_saved_previous(self):
        self.m.deploy('v1.0.1', True, True)
        self.m.rollback(idle_confirmed=True)
        self.assertEqual(self.m.load()['current']['tag'], 'v1.0.0')
        self.assertEqual(self.m.load()['previous']['tag'], 'v1.0.1')

    def test_failed_prepare_never_activates(self):
        self.m.failures.add('prepare')
        with self.assertRaises(Failure):
            self.m.deploy('v1.0.1', True, True)
        self.assertFalse(self.m.events)
        self.assertIsNone(self.m.load()['pending'])

    def test_missing_idle_blocks_activation(self):
        with self.assertRaises(Failure):
            self.m.deploy('v1.0.1', False, True)
        self.assertFalse(self.m.events)

    def test_missing_data_compatibility_blocks_activation(self):
        with self.assertRaises(Failure):
            self.m.deploy('v1.0.1', True, False)
        self.assertFalse(self.m.events)

    def test_dirty_tree_blocks_activation(self):
        self.m.failures.add('dirty')
        with self.assertRaises(Failure):
            self.m.deploy('v1.0.1', True, True)
        self.assertFalse(self.m.events)

    def test_redeploy_same_commit_is_noop(self):
        self.m.next = self.m.current
        self.m.deploy('v1.0.0')
        self.assertFalse(self.m.events)

    def test_initial_rollback_is_noop(self):
        self.m.rollback()
        self.assertFalse(self.m.events)

    def test_final_state_write_failure_recovers_original_previous(self):
        original_save = self.m.save
        older = release('v0.9.0', 'c' * 40)
        state = self.m.load()
        state['previous'] = older
        original_save(state)
        def fail_new(value):
            if value['current']['tag'] == 'v1.0.1':
                raise OSError('disk full')
            original_save(value)
        with patch.object(self.m, 'save', side_effect=fail_new):
            with self.assertRaisesRegex(Failure, 'ripristinata'):
                self.m.deploy('v1.0.1', True, True)
        self.assertEqual(self.m.load()['previous'], older)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.m = Manager(Config(app=self.path / 'app', state=self.path / 'state'))

    def archive(self, name, link=False):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            entry = tarfile.TarInfo(name)
            if link:
                entry.type = tarfile.SYMTYPE
                entry.linkname = '/opt/mulino-libero/secrets'
            archive.addfile(entry)
        return stream.getvalue()

    def test_unsafe_archives_rejected(self):
        for name in ('../secrets/key', '/etc/passwd', '.env', 'bot_risponditore.env',
                     'secrets/key', 'data/db', '.venv/bin/python', 'created-outcomes.sqlite3'):
            with self.subTest(name=name):
                with patch.object(self.m, 'git', side_effect=['', self.archive(name)]):
                    with self.assertRaises(Failure):
                        self.m.source('a' * 40)

    def test_symlink_archive_rejected(self):
        with patch.object(self.m, 'git', side_effect=['', self.archive('link', True)]):
            with self.assertRaises(Failure):
                self.m.source('a' * 40)

    def test_submodule_rejected(self):
        with patch.object(self.m, 'git', return_value='160000 commit abc\tsubmodule'):
            with self.assertRaises(Failure):
                self.m.source('a' * 40)

    def test_tag_validation(self):
        for tag in ('main', '../v1', 'v1.2', '--help', 'v1.2.3\n'):
            with self.subTest(tag=tag), self.assertRaises(Failure):
                self.m.resolve(tag)

    def test_lock_excludes_concurrent_operation(self):
        second = Manager(self.m.c)
        with self.m.locked():
            with self.assertRaises(Failure):
                with second.locked():
                    self.fail('lock unexpectedly acquired')

    def test_environment_drift_rejected(self):
        with patch.object(self.m, 'clean'), patch.object(self.m, 'git', return_value='abc'), patch.object(self.m, 'fingerprint', return_value={'changed': True}):
            with self.assertRaisesRegex(Failure, 'Configurazione'):
                self.m.guard({'pending': None, 'current': {'sha': 'abc'}, 'configuration': {}})

    def test_pending_journal_blocks_new_deploy(self):
        with patch.object(self.m, 'clean'):
            with self.assertRaisesRegex(Failure, 'interrotto'):
                self.m.guard({'pending': {'phase': 'activating'}})

    def test_last_known_good_prefers_interrupted_source(self):
        self.m.c.state.mkdir()
        old = release('v1.0.0', 'a')
        self.m.save(dict(current=release('v1.0.1', 'b'), previous=release('v0.9.0', 'c'),
                         pending={'from': old}))
        self.assertEqual((self.m.c.state / 'last-known-good').read_text(), 'v1.0.0\n')

    def test_changed_baseline_suite_is_rejected(self):
        corrected = self.path / 'test_regressions.py'
        corrected.write_text('changed')
        with self.assertRaisesRegex(Failure, 'alterata'):
            self.m.unit_tests({'tests_override': {'path': str(corrected), 'sha256': 'bad'}}, self.path)

    def test_corrected_suite_remains_isolated(self):
        from controller import digest
        corrected = self.path / 'test_regressions.py'
        corrected.write_text('verified suite')
        record = {'image': 'sha256:abc', 'tests_override': {'path': str(corrected), 'sha256': digest(corrected)}}
        with patch.object(self.m, 'run', return_value='') as run:
            self.m.unit_tests(record, self.path)
        command = run.call_args_list[0].args[0]
        self.assertIn('none', command)
        self.assertIn('--read-only', command)
        self.assertIn('MULINO_TEST_SOURCE=/suite/libero_mail_bot.py', command)
        self.assertNotIn(str(self.m.c.data), ' '.join(map(str, command)))

    def test_regular_release_uses_its_own_tests(self):
        with patch.object(self.m, 'run', return_value='') as run:
            self.m.unit_tests({'image': 'sha256:abc'}, self.path)
        command = ' '.join(map(str, run.call_args_list[0].args[0]))
        self.assertNotIn('/corrected-tests', command)

    def test_build_with_stale_code_is_rejected(self):
        self.m = Manager(Config(app=self.path / 'app', state=self.path / 'state', image_files=('worker.py',)))
        (self.path / 'worker.py').write_text('new code')
        with patch.object(self.m, 'run', return_value='wrong-hash  /app/worker.py'):
            with self.assertRaisesRegex(Failure, 'codice del tag'):
                self.m.verify_image({'image': 'sha256:abc'}, self.path)

    def test_build_with_matching_code_is_accepted(self):
        from controller import digest
        self.m = Manager(Config(app=self.path / 'app', state=self.path / 'state', image_files=('worker.py',)))
        (self.path / 'worker.py').write_text('correct code')
        with patch.object(self.m, 'run', return_value=digest(self.path / 'worker.py') + '  /app/worker.py'):
            self.m.verify_image({'image': 'sha256:abc'}, self.path)

    def test_monitor_module_must_match_release_when_present(self):
        from controller import digest
        self.m = Manager(Config(app=self.path / 'app', state=self.path / 'state', image_files=('worker.py',)))
        (self.path / 'worker.py').write_text('correct code')
        (self.path / 'runtime_health.py').write_text('current monitor')
        output = digest(self.path / 'worker.py') + '  /app/worker.py\n'
        with patch.object(self.m, 'run', return_value=output + 'stale  /app/runtime_health.py'):
            with self.assertRaisesRegex(Failure, 'codice del tag'):
                self.m.verify_image({'image': 'sha256:abc'}, self.path)
        with patch.object(self.m, 'run', return_value=output + digest(self.path / 'runtime_health.py') + '  /app/runtime_health.py'):
            self.m.verify_image({'image': 'sha256:abc'}, self.path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
