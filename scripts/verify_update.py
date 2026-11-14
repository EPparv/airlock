"""Verify a real CI signature, including negative identity and tamper checks."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from privacy_layer import updater


def verify(directory):
    directory = Path(directory)
    data = (directory / 'updates.json').read_bytes()
    signature = (directory / 'updates.sigstore.json').read_bytes()
    manifest = updater.verify_manifest(data, signature)
    archive = (directory / manifest['archive']).read_bytes()
    assert len(archive) == manifest['size']
    assert hashlib.sha256(archive).hexdigest() == manifest['sha256']
    for changed in (data + b' ', data.replace(manifest['commit'].encode(), b'0' * 40)):
        try:
            updater.verify_manifest(changed, signature)
        except Exception:
            pass
        else:
            raise AssertionError('Tampered update metadata was accepted')
    identity = updater.IDENTITY
    try:
        updater.IDENTITY = identity.replace('EPparv/airlock', 'untrusted/airlock')
        try:
            updater.verify_manifest(data, signature)
        except Exception:
            pass
        else:
            raise AssertionError('Wrong publisher was accepted')
    finally:
        updater.IDENTITY = identity
    print(json.dumps({'verified': manifest['version'], 'build': manifest['build'], 'commit': manifest['commit'],
                      'signature': 'GitHub main workflow, exact commit', 'tamper_and_wrong_publisher': 'rejected'}))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    verify(parser.parse_args().directory)
