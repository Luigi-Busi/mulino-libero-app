"""Native multi-image archives. Caller holds the existing deploy lock.

Historical image names are hard links, not copies. Each generation contains
every previously recorded immutable image. The encrypted external copy is
published before committing the new local index. No app services are restarted.
"""
import contextlib
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid


IMAGE = re.compile(r'sha256:[a-f0-9]{64}\Z')
HASH = re.compile(r'[a-f0-9]{64}\Z')
FORMAT = 'mulino-shared-images-v1'


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def sync_directory(path):
    descriptor = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.partial')
    try:
        with temporary.open('x', encoding='utf-8') as f:
            os.chmod(temporary, 0o600)
            json.dump(value, f, indent=2, sort_keys=True)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def validate_bundle(path, expected):
    """Verify configs and uncompressed layer hashes without extracting files."""
    checksums, small = {}, {}
    small_bytes = 0
    with gzip.open(path, 'rb') as compressed:
        with tarfile.open(fileobj=compressed, mode='r|') as archive:
            for member in archive:
                name = member.name
                part = PurePosixPath(name)
                if part.is_absolute() or '..' in part.parts or name in checksums:
                    raise ValueError('Unsafe or duplicate Docker archive entry')
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError('Non-regular Docker archive entry')
                with archive.extractfile(member) as f:
                    if member.size <= 1024 * 1024:
                        value = f.read()
                        small_bytes += len(value)
                        if small_bytes > 32 * 1024 * 1024:
                            raise ValueError('Unexpected Docker metadata volume')
                        small[name] = value
                        checksums[name] = hashlib.sha256(value).hexdigest()
                    else:
                        checksums[name] = hashlib.file_digest(f, 'sha256').hexdigest()
                if name.startswith('blobs/sha256/') and checksums[name] != part.name:
                    raise ValueError('Docker content digest mismatch')
        # Read through gzip EOF to check its CRC, not just the tar end markers.
        while compressed.read(4 * 1024 * 1024):
            pass
    manifest = json.loads(small['manifest.json'])
    actual = []
    for entry in manifest:
        config = entry['Config']
        actual.append('sha256:' + checksums[config])
        config_data = json.loads(small[config])
        layers = ['sha256:' + checksums[name] for name in entry['Layers']]
        if config_data['rootfs']['diff_ids'] != layers:
            raise ValueError('Image layers differ from immutable config')
    if sorted(actual) != sorted(set(expected)):
        raise ValueError('Archive does not contain exactly the requested images')
    return {'images_verified':len(actual), 'layers_verified':len(set(
        layer for entry in manifest for layer in entry['Layers']))}


class Store:
    def __init__(self, state, run, minimum_free=4 * 1024**3,
                 export=Path('/srv/mulino-backups-export/history'),
                 recovery=Path('/etc/mulino-recovery'), docker_host='unix:///var/run/docker.sock'):
        self.state = Path(state)
        self.index = self.state / 'releases' / 'shared-images.json'
        self.directory = self.state / 'images' / 'shared'
        self.run = run
        self.minimum_free = minimum_free
        self.export = Path(export) if export is not None else None
        self.recovery = Path(recovery)
        self.environment = {k:v for k,v in os.environ.items()
                            if not k.startswith(('DOCKER_', 'COMPOSE_', 'GIT_'))}
        self.environment['DOCKER_HOST'] = docker_host

    def read(self, verify=True):
        if self.index.is_symlink():
            raise ValueError('Unexpected shared index symlink')
        value = json.loads(self.index.read_text())
        if value.get('format') != FORMAT or not HASH.fullmatch(value.get('sha256', '')):
            raise ValueError('Invalid shared image index')
        if value.get('archive') != value['sha256'] + '.tar.gz':
            raise ValueError('Invalid archive name')
        images = value['images']
        if not images or sorted(set(images)) != images or any(not IMAGE.fullmatch(x) for x in images):
            raise ValueError('Invalid immutable image identities')
        path = self.directory / value['archive']
        if path.is_symlink() or not path.is_file() or path.stat().st_size != value['bytes']:
            raise ValueError('Shared image archive missing or altered')
        if verify and digest(path) != value['sha256']:
            raise ValueError('Shared image archive checksum mismatch')
        return value

    def load_missing(self, value):
        missing = False
        for image in value['images']:
            try:
                self.run(['docker', 'image', 'inspect', image])
            except RuntimeError:
                missing = True
        if missing:
            self.run(['docker', 'image', 'load', '-i', self.directory / value['archive']], timeout=1200)
        for image in value['images']:
            result = json.loads(self.run(['docker', 'image', 'inspect', image]))
            if result[0]['Id'] != image:
                raise ValueError('Unexpected restored image identity')

    def create(self, images):
        images = sorted(set(images))
        if not images or any(not IMAGE.fullmatch(x) for x in images):
            raise ValueError('Invalid images requested')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if shutil.disk_usage(self.directory).free < self.minimum_free:
            raise ValueError('Insufficient free disk space for image archive')
        temporary = self.directory / (uuid.uuid4().hex + '.partial')
        producer = consumer = None
        try:
            with temporary.open('xb') as output, tempfile.TemporaryFile() as errors:
                os.chmod(temporary, 0o600)
                producer = subprocess.Popen(['docker', 'image', 'save', *images],
                    stdout=subprocess.PIPE, stderr=errors, env=self.environment)
                consumer = subprocess.Popen(['gzip', '-3', '-n'], stdin=producer.stdout,
                    stdout=output, stderr=errors)
                producer.stdout.close()
                consumer_code = consumer.wait(timeout=1200)
                producer_code = producer.wait(timeout=30)
                if consumer_code or producer_code:
                    raise RuntimeError('Image export or compression failed')
                output.flush()
                os.fsync(output.fileno())
            verification = validate_bundle(temporary, images)
            checksum = digest(temporary)
            destination = self.directory / (checksum + '.tar.gz')
            if destination.exists():
                if destination.is_symlink() or digest(destination) != checksum:
                    raise ValueError('Existing bundle altered')
                temporary.unlink()
            else:
                os.replace(temporary, destination)
                sync_directory(self.directory)
            return {'format':FORMAT, 'archive':destination.name, 'sha256':checksum,
                    'bytes':destination.stat().st_size, 'images':images, 'verification':verification}
        finally:
            for process in (consumer, producer):
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=30)
            temporary.unlink(missing_ok=True)

    def publish(self, value):
        if self.export is None:
            return
        import grp
        self.export.mkdir(parents=True, exist_ok=True, mode=0o750)
        group = grp.getgrnam('backupmulino').gr_gid
        os.chown(self.export, 0, group)
        os.chmod(self.export, 0o750)
        recipient = (self.recovery / 'recipient.txt').read_text().strip()
        if not re.fullmatch('[A-F0-9]{40}', recipient):
            raise ValueError('Invalid backup recipient')
        destination = self.export / 'history-images.tar.gpg'
        temporary = self.export / ('history-images.' + uuid.uuid4().hex + '.partial')
        try:
            with temporary.open('xb') as output:
                os.chmod(temporary, 0o600)
                with tempfile.TemporaryFile() as errors:
                    result = subprocess.run(['gpg', '--homedir', str(self.recovery / 'gnupg'),
                        '--batch', '--trust-model', 'always', '--cipher-algo', 'AES256',
                        '--compress-algo', 'none', '--recipient', recipient, '--output', '-', '--encrypt',
                        str(self.directory / value['archive'])], stdout=output, stderr=errors, timeout=600)
                if result.returncode:
                    raise RuntimeError('External archive encryption failed')
                if output.tell() < value['bytes']:
                    raise RuntimeError('Encrypted stream unexpectedly incomplete')
                output.flush()
                os.fsync(output.fileno())
            checksum = digest(temporary)
            os.chown(temporary, 0, group)
            os.chmod(temporary, 0o640)
            os.replace(temporary, destination)
            external = dict(value, file=destination.name, ciphertext_sha256=checksum,
                            ciphertext_bytes=destination.stat().st_size,
                            recovery='Decrypt with the existing separate recovery key; result is native Docker gzip.')
            atomic_json(self.export / 'history-index.json', external)
            os.chown(self.export / 'history-index.json', 0, group)
            os.chmod(self.export / 'history-index.json', 0o640)
            sync_directory(self.export)
        finally:
            temporary.unlink(missing_ok=True)

    def commit(self, value):
        # New index first: interrupted link replacement is completed on next retain.
        # Every old link is independently loadable and new bundles are supersets.
        atomic_json(self.index, value)
        self.link_images(value)
        self.collect(value)

    def link_images(self, value):
        source = self.directory / value['archive']
        for image in value['images']:
            destination = self.state / 'images' / (image.split(':')[1] + '.tar')
            if destination.exists() and not destination.is_symlink() and os.path.samefile(source, destination):
                continue
            temporary = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.partial')
            try:
                os.link(source, temporary)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        sync_directory(self.state / 'images')

    def collect(self, value):
        # Only content-addressed, unreferenced store files, never unrelated archives.
        for path in self.directory.glob('*.tar.gz'):
            if path.name != value['archive'] and re.fullmatch(r'[a-f0-9]{64}\.tar\.gz', path.name):
                if not path.is_symlink() and path.stat().st_nlink == 1:
                    path.unlink()
        sync_directory(self.directory)

    def retain(self, record):
        old = self.read()
        if not IMAGE.fullmatch(record['image']):
            raise ValueError('Invalid requested image identity')
        if record['image'] in old['images']:
            self.link_images(old)
            self.collect(old)
            return old
        self.load_missing(old)
        value = self.create(old['images'] + [record['image']])
        self.publish(value)
        self.commit(value)
        return value

    def archive_for(self, image):
        value = self.read()
        if image not in value['images']:
            raise ValueError('Image is absent from shared archive')
        return self.directory / value['archive']
