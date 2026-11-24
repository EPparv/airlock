from pathlib import Path
import base64
import json
import uuid

import pytest

from macos import distribution, publisher


def test_publisher_credentials_are_optional_only_when_completely_absent():
    assert publisher.configuration({}) is None
    with pytest.raises(ValueError, match='incomplete'):
        publisher.configuration({}, required=True)
    partial = {publisher.KEYS[1]: 'sensitive-fixture'}
    with pytest.raises(ValueError) as err:
        publisher.configuration(partial)
    assert 'sensitive-fixture' not in str(err.value)
    obj = dict.fromkeys(publisher.KEYS, 'opaque')
    obj['AIRLOCK_APPLE_TEAM_ID'] = 'TESTTEAM01'
    assert publisher.configuration(obj) is obj
    with pytest.raises(ValueError):
        distribution.requirement('unquoted team')
    assert 'TESTTEAM01' in distribution.requirement('TESTTEAM01')


def test_submission_requires_accepted_response_before_stapling(tmp_path, monkeypatch):
    submission_id = str(uuid.uuid4())
    status = ['Invalid', 'Accepted']
    calls = []
    def tool(*argv):
        calls.append(argv)
        if 'notarytool' in argv:
            return json.dumps({'id':submission_id, 'status': status.pop(0)})
        return ''
    monkeypatch.setattr(distribution, 'check', tool)
    args = {'identity':'test-identity', 'team':'TESTTEAM01', 'auth':['--keychain-profile', 'local-test']}
    app = tmp_path / 'Airlock.app'
    with pytest.raises(ValueError, match=submission_id):
        distribution.sign_and_staple(app, tmp_path, **args)
    assert not any('stapler' in row for row in calls)
    assert distribution.sign_and_staple(app, tmp_path, **args) == {'submission_id':submission_id,'team_id':'TESTTEAM01'}
    assert 'staple' in calls[-1]
    cmd = calls[0]
    assert '--timestamp' in cmd and 'runtime' in cmd and '--entitlements' in cmd


def test_site_rejects_stale_build_record():
    meta = {'version':'1','build':1,'commit':'a'*40}
    report = {**meta,'sha256':'a'*64,'notarized':False}
    assert not distribution.signing_status(report, report['sha256'], meta)
    with pytest.raises(ValueError):
        distribution.signing_status(report, 'b'*64, meta)
    with pytest.raises(ValueError):
        distribution.signing_status(report, report['sha256'], {**meta,'build':2})
    with pytest.raises((KeyError, ValueError)):
        distribution.signing_status({**report,'notarized':True}, report['sha256'], meta)


def test_ci_keychain_restored_on_rejection(tmp_path, monkeypatch):
    prior = str(tmp_path / 'existing.keychain-db')
    team = 'TESTTEAM01'
    fingerprint = 'A'*40
    values = dict.fromkeys(publisher.KEYS, 'fixture')
    values['AIRLOCK_APPLE_TEAM_ID']=team
    for key in ('AIRLOCK_SIGNING_P12_BASE64','AIRLOCK_NOTARY_KEY_P8_BASE64'):
        values[key]=base64.b64encode(b'fictional test file').decode()
    calls = []
    def tool(*argv):
        calls.append(argv)
        if 'find-identity' in argv:
            return f'  1) {fingerprint} "Developer ID Application: Fictional ({team})"'
        if argv[-1] == 'user':return f'"{prior}"'
        return ''
    monkeypatch.setattr(publisher, 'check', tool)
    with pytest.raises(RuntimeError):
        with publisher.signing_context(values) as params:
            assert params['identity'] == fingerprint
            private_file = Path(params['auth'][1])
            assert private_file.read_bytes()==b'fictional test file' and (private_file.stat().st_mode & 0o777)==0o600
            raise RuntimeError('simulate rejected submission')
    assert calls[-2] == ('/usr/bin/security','list-keychains','-d','user','-s',prior)
    assert calls[-1][1] == 'delete-keychain'
    assert not private_file.exists()
