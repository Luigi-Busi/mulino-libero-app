"""Private, ephemeral health signals. Contains no message or account contents."""
import asyncio
import json
import logging
import os
from pathlib import Path
import tempfile
import time

from telegram.request import HTTPXRequest


class HealthRequest(HTTPXRequest):
    def __init__(self, monitor, **kwargs):
        self.monitor = monitor
        super().__init__(**kwargs)

    async def do_request(self, url, method, *args, **kwargs):
        result = await super().do_request(url, method, *args, **kwargs)
        if url.endswith('/getUpdates') and result[0] == 200:
            try:
                good = json.loads(result[1]).get('ok') is True
            except (ValueError, AttributeError):
                good = False
            if good:
                self.monitor.last_poll = time.monotonic()
        return result


class RuntimeHealth:
    def __init__(self, service, path):
        if service not in ('mugnaio', 'risponditore'):
            raise ValueError('Unknown service')
        self.service = service
        self.path = Path(path)
        self.started = time.monotonic()
        self.last_poll = None
        self.task = None
        self.snapshot = None

    def write(self, details):
        allowed = {'paused', 'busy', 'human_wait', 'queue_ok', 'browser_expected', 'browser_ok'}
        if set(details) - allowed or any(type(v) is not bool for v in details.values()):
            raise ValueError('Unexpected health fields')
        value = dict(schema=1, service=self.service, pid=os.getpid(),
                     updated=time.monotonic(), started=self.started,
                     poll=self.last_poll, **details)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise OSError('Unsafe health path')
        fd, name = tempfile.mkstemp(prefix='.health-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as output:
                json.dump(value, output)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    async def loop(self):
        while True:
            try:
                details = await self.snapshot() if self.snapshot else {}
                self.write(details)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Let the independent monitor detect a stale/missing signal.
                logging.getLogger('mulino-health').warning('Segnale di salute non aggiornato')
            await asyncio.sleep(15)

    async def start(self, application):
        self.task = asyncio.create_task(self.loop(), name='mulino-runtime-health')

    async def stop(self, application):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

