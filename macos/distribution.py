"""Sign an Airlock bundle and verify Apple's ticket on the distributed bytes."""
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile
import uuid

from privacy_layer.updater import APP_ID, app_release, extract_archive


def check(*command):
    return subprocess.run([str(v) for v in command], check=True, capture_output=True, text=True).stdout


def requirement(team):
    if not isinstance(team, str) or not re.fullmatch(r'[A-Z0-9]{10}', team):
        raise ValueError('Use your ten-character Apple Developer Team ID.')
    return (f'identifier "{APP_ID}" and anchor apple generic and '
            'certificate 1[field.1.2.840.113635.100.6.2.6] exists and '
            'certificate leaf[field.1.2.840.113635.100.6.1.13] exists and '
            f'certificate leaf[subject.OU] = "{team}"')


def verify_identity(app, team):
    check('/usr/bin/codesign', '--verify', '--strict', '--all-architectures', '-R=' + requirement(team), app)


def sign_and_staple(app, work, *, identity, team, auth, keychain=None):
    requirement(team)
    if not identity or identity == '-' or not auth:
        raise ValueError('Developer ID signing requires a certificate and notarization credentials.')
    entitlements = work / 'developer-id-entitlements.plist'
    entitlements.write_bytes(plistlib.dumps({'com.apple.security.automation.apple-events': True}))
    keychain_args = ['--keychain', keychain] if keychain else []
    check('/usr/bin/codesign', '--force', '--timestamp', '--options', 'runtime', '--entitlements',
          entitlements, *keychain_args, '--sign', identity, app)
    verify_identity(app, team)
    submission = work / 'submission.zip'
    check('/usr/bin/ditto', '-c', '-k', '--keepParent', app, submission)
    answer = json.loads(check('/usr/bin/xcrun', 'notarytool', 'submit', submission,
                              *auth, '--wait', '--timeout', '30m', '--output-format', 'json'))
    submission_id = str(uuid.UUID(str(answer.get('id'))))
    if answer.get('status') != 'Accepted':
        raise ValueError(f'Apple did not accept notarization submission {submission_id}. Check its notarytool log.')
    check('/usr/bin/xcrun', 'stapler', 'staple', app)
    return {'team_id': team, 'submission_id': submission_id}


def verify_archive(archive, team=None):
    """Exercise the same extraction used by the installed updater."""
    archive = Path(archive)
    data = archive.read_bytes()
    manifest = {'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
    with tempfile.TemporaryDirectory(prefix='airlock-archive-verify-') as name:
        app = extract_archive(data, manifest, Path(name))
        release = app_release(app)
        check('/usr/bin/codesign', '--verify', '--deep', '--strict', '--all-architectures', app)
        if team:
            verify_identity(app, team)
            check('/usr/bin/xcrun', 'stapler', 'validate', app)
            check('/usr/sbin/spctl', '--assess', '--type', 'execute', app)
    return {**manifest, 'version':release['version'], 'build':release['build'], 'commit': release['commit']}


def signing_status(report, digest, release):
    if (not isinstance(report, dict) or type(report.get('notarized')) is not bool or
            report.get('sha256') != digest or any(report.get(k) != release[k] for k in ('version','build','commit'))):
        raise ValueError('The verification record does not match this Mac archive.')
    if report['notarized']:
        apple = report['apple']
        requirement(apple['team_id'])
        uuid.UUID(apple['submission_id'])
    return report['notarized']


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    team = report.get('apple', {}).get('team_id') if report.get('notarized') else None
    verified = verify_archive(args.archive, team)
    signed = signing_status(report, verified['sha256'], verified)
    print('Developer ID signature and Apple ticket verified.' if signed else 'Ad-hoc Mac test archive verified.')
