#!/usr/bin/env python3
"""Read-only Docker observer. Persist only validated technical records."""
import contextlib
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time

from browser_diagnostics import resources, valid_event, valid_launcher_event


ROOT = Path('/var/log/mulino-browser-diagnostics')
PROJECT = 'mulino-libero'
SERVICE = CONTAINER = 'libero-mail-bot'
DOCKER_EVENTS = {'oom', 'kill', 'die', 'start', 'stop', 'restart', 'destroy', 'create'}
ID = re.compile(r'[a-f0-9]{64}\Z')
STAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z\Z')


def decode_line(line):
    if len(line) > 4096 or 'MULINO_DIAG ' not in line:
        return None
    try:
        value = json.loads(line.split('MULINO_DIAG ', 1)[1])
        return value if valid_event(value) or valid_launcher_event(value) else None
    except (ValueError, TypeError, KeyError):
        return None


def docker_event(raw):
    try:
        value = json.loads(raw)
        action, actor = value['Action'], value['Actor']
        attributes = actor.get('Attributes', {})
        if (value.get('Type') != 'container' or action not in DOCKER_EVENTS
                or not ID.fullmatch(actor['ID'])
                or attributes.get('com.docker.compose.project') != PROJECT
                or attributes.get('com.docker.compose.service') != SERVICE):
            return None
        record = {'container': actor['ID'], 'event': action}
        for attr, key in (('exitCode', 'exit_code'), ('signal', 'signal')):
            if attr in attributes:
                number = int(attributes[attr])
                if 0 <= number <= 255:
                    record[key] = number
        stamp = value.get('timeNano')
        if type(stamp) is int and 0 <= stamp < 2**63:
            record['event_ns'] = stamp
        return record
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def cgroup_resources(pid, root=Path('/sys/fs/cgroup'), proc=Path('/proc')):
    try:
        for line in (proc / str(pid) / 'cgroup').read_text().splitlines():
            hierarchy, controllers, relative = line.split(':', 2)
            if hierarchy == '0' and not controllers:
                path = (root / relative.lstrip('/')).resolve()
                if path.is_relative_to(root.resolve()):
                    return resources(path)
    except (OSError, ValueError):
        pass
    return {}


class Collector:
    def __init__(self, root=ROOT, docker='/usr/bin/docker'):
        self.docker = docker
        self.stop = threading.Event()
        self.children = set()
        self.children_lock = threading.Lock()
        if root.is_symlink():
            raise OSError('Unsafe diagnostics path')
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        self.logger = logging.getLogger('collector-' + str(root))
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        logfile = root / 'events.jsonl'
        if logfile.is_symlink():
            raise OSError('Unsafe diagnostics file')
        self.handler = RotatingFileHandler(logfile, maxBytes=2 * 1024**2, backupCount=4)
        os.chmod(logfile, 0o600)
        self.handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(self.handler)

    def write(self, kind, record):
        # Caller passes only records produced by the validators in this module.
        self.logger.info(json.dumps(dict(observed_utc=datetime.now(timezone.utc).isoformat(),
                                        kind=kind, **record), separators=(',', ':')))

    def run(self, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith(('DOCKER_', 'COMPOSE_'))}
        env['DOCKER_HOST'] = 'unix:///var/run/docker.sock'
        try:
            output = subprocess.run([self.docker, *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    text=True, timeout=10, env=env)
            return output.stdout if output.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def inspect(self):
        raw = self.run('inspect', '--format',
                       '{"id":{{json .Id}},"state":{{json .State}},"labels":{{json .Config.Labels}}}', CONTAINER)
        try:
            value = json.loads(raw)
            if (ID.fullmatch(value['id']) and value['labels'].get('com.docker.compose.project') == PROJECT
                    and value['labels'].get('com.docker.compose.service') == SERVICE):
                return value
        except (ValueError, TypeError, KeyError, AttributeError):
            pass
        return None

    def stream(self, args, receive):
        env = {key: value for key, value in os.environ.items() if not key.startswith(('DOCKER_', 'COMPOSE_'))}
        env['DOCKER_HOST'] = 'unix:///var/run/docker.sock'
        try:
            # docker logs forwards the container's stderr to its own stderr.
            # Merge both streams, then persist only fully validated events.
            process = subprocess.Popen([self.docker, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, errors='replace', env=env)
        except OSError:
            return
        with self.children_lock:
            self.children.add(process)
            if self.stop.is_set():
                process.terminate()
        try:
            while not self.stop.is_set():
                line = process.stdout.readline(8192)
                if not line:
                    break
                receive(line)
        finally:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdout.close()
            with self.children_lock:
                self.children.discard(process)

    def follow_events(self):
        while not self.stop.is_set():
            since = str(int(time.time()) - 300)
            args = ['events', '--since', since, '--format', '{{json .}}',
                    '--filter', 'label=com.docker.compose.project=' + PROJECT,
                    '--filter', 'label=com.docker.compose.service=' + SERVICE]
            def receive(line):
                record = docker_event(line)
                if record:
                    self.write('docker', record)
            self.stream(args, receive)
            self.stop.wait(3)

    def follow_logs(self):
        while not self.stop.is_set():
            container = self.inspect()
            if container:
                identity = container['id']
                seen = set()
                def receive(line):
                    self.receive_log(identity, line, seen)
                self.stream(['logs', '--follow', '--since', '5m', '--timestamps', identity], receive)
            self.stop.wait(3)

    def receive_log(self, identity, line, seen):
        event = decode_line(line)
        if event is None:
            return
        record = {'container': identity, 'detail': event}
        stamp = line.split(' ', 1)[0]
        if STAMP.fullmatch(stamp):
            try:
                datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                record['logged_utc'] = stamp
            except ValueError:
                pass
        # Repeated launcher events after a restart can have identical payloads.
        # Deduplicate only the same Docker timestamp and payload, not later exits.
        key = json.dumps(record, sort_keys=True)
        if key not in seen:
            if len(seen) >= 1024:
                seen.clear()
            seen.add(key)
            self.write(event['source'], record)

    def sample(self, container):
        state = container['state']
        record = {'container': container['id'], 'running': state.get('Running') is True,
                  'oom_killed': state.get('OOMKilled') is True}
        code = state.get('ExitCode')
        if type(code) is int and 0 <= code <= 255:
            record['exit_code'] = code
        pid = state.get('Pid')
        if type(pid) is int and pid > 0:
            record['resources'] = cgroup_resources(pid)
        self.write('sample', record)

    def shutdown(self, *_):
        self.stop.set()
        with self.children_lock:
            for process in self.children:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()

    def serve(self):
        threads = [threading.Thread(target=target, daemon=True)
                   for target in (self.follow_events, self.follow_logs)]
        for thread in threads:
            thread.start()
        self.write('collector', {'event': 'started'})
        try:
            while not self.stop.is_set():
                container = self.inspect()
                if container:
                    self.sample(container)
                else:
                    self.write('collector', {'event': 'container_unavailable'})
                if not all(thread.is_alive() for thread in threads):
                    raise RuntimeError('Observer thread stopped')
                self.stop.wait(60)
        finally:
            self.shutdown()
            for thread in threads:
                thread.join(timeout=8)
            self.write('collector', {'event': 'stopped'})
            self.logger.removeHandler(self.handler)
            self.handler.close()


if __name__ == '__main__':
    os.umask(0o077)
    observer = Collector()
    signal.signal(signal.SIGTERM, observer.shutdown)
    signal.signal(signal.SIGINT, observer.shutdown)
    observer.serve()
