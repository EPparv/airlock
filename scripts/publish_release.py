"""Publish tested versioned assets. Never overwrite an existing release."""
import argparse
import json
from pathlib import Path
import subprocess


def publish(directory):
    directory=Path(directory)
    release=json.loads((directory/'release.json').read_text())
    if release['dirty']:
        raise ValueError('Only a clean revision can be released')
    tag='v'+release['version']
    found=subprocess.run(['gh','api','repos/EPparv/airlock/releases/tags/'+tag],capture_output=True,text=True)
    if found.returncode==0:
        existing=json.loads(found.stdout)
        if existing['target_commitish'] != release['commit']:
            raise ValueError('This version already belongs to a different commit. Increase VERSION and BUILD.')
        # A workflow retry keeps the first numbered artifact intact. Pages must
        # also use its exact bytes, not a potentially different rebuild.
        raise ValueError('This version is already published. Increase VERSION and BUILD to publish another build.')
    if '404' not in found.stderr:
        raise RuntimeError('Could not verify that this release tag is unused')
    assets=[directory/n for n in ('Airlock_Mac_Latest.zip','Airlock_Source_Latest.zip','release.json',
                                  'updates.json','updates.sigstore.json','SHA256SUMS')]
    command=['gh','release','create',tag,'--repo','EPparv/airlock','--target',release['commit'],
             '--title','Airlock '+release['version'],'--notes-file','docs/RELEASE_NOTES.md']
    if '-alpha.' in release['version']:
        command.append('--prerelease')
    subprocess.run(command+list(map(str,assets)),check=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path)
    publish(parser.parse_args().directory)
