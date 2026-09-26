"""Verify an authenticated, decrypted system TAR before extracting anything."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


def checked_name(raw):
    name = raw[2:] if raw.startswith('./') else raw
    p = PurePosixPath(name)
    if not name or '\\' in name or ':' in name or p.is_absolute() or '..' in p.parts:
        raise ValueError('Unsafe archive path')
    return p.as_posix()


def verify(archive, destination=None):
    with tarfile.open(archive, 'r:') as tar:
        files = {}
        total = 0
        for member in tar:
            if member.isdir():
                if member.name not in ('.', './'):
                    checked_name(member.name)
                continue
            name = checked_name(member.name)
            if not member.isfile() or name in files:
                raise ValueError('Duplicate file or unsupported archive entry')
            total += member.size
            if member.size > 512 * 1024**2 or total > 1024**3:
                raise ValueError('System payload size limit exceeded')
            files[name] = member
        item = files.pop('manifest.json')
        if item.size > 8 * 1024**2:
            raise ValueError('Manifest too large')
        manifest = json.load(tar.extractfile(item))
        if manifest.get('format') != 'mulino-system-v1' or set(files) != set(manifest['files']):
            raise ValueError('Manifest file list mismatch')
        for name, member in files.items():
            record = manifest['files'][name]
            if member.size != record['bytes']:
                raise ValueError('Size mismatch')
            if hashlib.file_digest(tar.extractfile(member), 'sha256').hexdigest() != record['sha256']:
                raise ValueError('Checksum mismatch')
        if destination is not None:
            destination = Path(destination)
            if destination.exists():
                raise ValueError('Extraction destination must not exist')
            destination.mkdir(mode=0o700, parents=True)
            # Explicit file creation; never tar.extractall or inherited ownership.
            for name, member in files.items():
                target = destination.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with target.open('xb') as output:
                    import shutil
                    shutil.copyfileobj(tar.extractfile(member), output)
                target.chmod(manifest['files'][name]['mode'] & 0o777)
            (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        return {'files_verified': len(files), 'payload_bytes': total,
                'created_utc': manifest['created_utc'], 'current': manifest['current']['tag'],
                'previous': manifest['previous']['tag'], 'image_asset': manifest['image_asset']}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('archive', type=Path)
    p.add_argument('--extract-to', type=Path)
    args = p.parse_args()
    print(json.dumps(verify(args.archive, args.extract_to), indent=2))
