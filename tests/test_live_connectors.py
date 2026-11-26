"""Real connector I/O with disposable databases/files and loopback-only HTTP."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sqlite3
from threading import Event, Thread

import pytest

from privacy_layer.agent_memory import AgentMemory
from privacy_layer.core import Denied
from privacy_layer.data_view import write_payload
from privacy_layer.workspace import Workspace


@pytest.fixture
def setup(bundle):
    gateway = bundle[0]
    gateway.device_apps = object()
    agents = []
    for name in ('codex','cursor'):
        grant = gateway.create(agent=name, purpose='Connector test', views=[], approved=True, mode='automatic')
        AgentMemory(gateway).configure(grant['id'], records=[])
        agents.append(grant)
    return gateway, Workspace(gateway), *agents


def prepare(workspace, agent, kind, values):
    key = workspace.owner('workspace-create', dict(kind=kind, label='Project update', audience=[agent['id']], values=values))['id']
    return next(row for row in workspace.state()['actions'] if row['id'] == key)


def call(g, agent, tool, row, **kw):
    return g.call(agent['token'], tool, {'reference': row['handles'].get(agent['id'], next(iter(row['handles'].values()))), **kw})


def discover(w, path, table='', identity=None):
    return w.owner('workspace-live-fields', dict(path=str(path), table=table, identity=identity))


@pytest.fixture
def endpoint():
    requests = []
    entered, release = Event(), Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_PATCH(self):
            payload = self.rfile.read(int(self.headers['Content-Length']))
            requests.append((self.path, payload, self.headers.get('Authorization')))
            if self.path == '/pending':
                entered.set()
                release.wait(4)
            if self.path == '/redirect':
                self.send_response(307)
                self.send_header('Location', '/leaked')
            else:
                self.send_response(201)
            self.end_headers()
            self.wfile.write(b'{"private":"RAW_SERVICE_VALUE"}')
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}', requests, entered, release
        finally:
            release.set()
            server.shutdown()
            thread.join()


def test_fixed_write_exactly_once_through_gateway(setup, endpoint):
    g, w, agent, other = setup
    base, writes, entered, release = endpoint
    original = '{ "title": "OWNER_ONLY", "cost": 1.2300 }'
    row = prepare(w, agent, 'api_write', dict(method='PATCH', url=base + '/pending', credential='LOCAL_SECRET', body=original))
    assert writes == [] and 'LOCAL_SECRET' not in str(row)
    with pytest.raises(Denied):
        call(g, other, 'request_private_action', row)
    with pytest.raises(Denied):
        call(g, agent, 'request_private_action', row, body='changed')
    pending = call(g, agent, 'request_private_action', row)
    assert pending['status'] == 'pending' and writes == []
    with ThreadPoolExecutor() as pool:
        first = pool.submit(w.decide, row['id'], row['fingerprint'], True)
        assert entered.wait(4)
        with pytest.raises(Denied):
            w.decide(row['id'], row['fingerprint'], True)
        release.set()
        assert first.result() == {'status': 'submitted'}
    result = call(g, agent, 'private_action_status', row)
    assert set(result) <= {'status', 'label', 'reference', 'kind', 'execution'}
    assert result['status'] == 'submitted'
    assert writes == [('/pending', original.encode(), 'Bearer LOCAL_SECRET')]
    receipt = json.dumps(w.state()['receipts'])
    assert all(secret not in receipt for secret in ('OWNER_ONLY', 'LOCAL_SECRET', 'RAW_SERVICE_VALUE', '/pending'))


def test_redirect_and_revocation_prevent_submission(setup, endpoint):
    g, w, agent, _ = setup
    base, writes, _, _ = endpoint
    values = dict(method='PATCH', url=base+'/redirect', credential='pinned', body='{}')
    row = prepare(w, agent, 'api_write', values)
    call(g, agent, 'request_private_action', row)
    assert w.decide(row['id'], row['fingerprint'], True)['status'] == 'unconfirmed'
    with pytest.raises(Denied):
        w.decide(row['id'], row['fingerprint'], True)
    row = prepare(w, agent, 'api_write', values)
    call(g, agent, 'request_private_action', row)
    g.revoke(agent['id'])
    with pytest.raises(Denied):
        w.decide(row['id'], row['fingerprint'], True)
    assert [r[0] for r in writes] == ['/redirect']


@pytest.mark.parametrize('body', ['[]', '{"a":1, "a":2}', '{"x": NaN}', 'bad', '{"x":"'+'x'*32768+'"}'])
def test_json_body_validation(body):
    with pytest.raises(Denied):
        write_payload(dict(method='POST', url='https://owner.example', credential='', body=body))


@pytest.mark.parametrize('journal', ['wal','delete','persist'])
def test_live_sqlite_empty_table_projection_and_commit(setup, tmp_path, journal):
    g, w, agent, other = setup
    path = tmp_path/'db.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA journal_mode='+journal)
        db.execute('CREATE TABLE "t""1"(stage TEXT, email TEXT, concealed TEXT)')
        db.execute('CREATE VIEW excluded AS SELECT * FROM "t""1"')
        db.commit()
        discovery = discover(w, path)
        assert discovery['tables'] == ['t"1']
        ticket = discover(w, path, 't"1', discovery['identity'])
        assert set(ticket['fields']) == {'stage', 'email', 'concealed'}
        row = prepare(w, agent, 'live_data', dict(path=str(path), table='t"1', identity=ticket['identity'], fields=['stage','email']))
        db.execute('INSERT INTO "t""1" VALUES (?,?,?)', ('Pilot','raw@example.org','PRIVATE_CANARY'))
        db.commit()
        first = call(g, agent, 'read_private_fields', row)
        assert first['rows'][0][0] == 'Pilot' and first['rows'][0][1].startswith('[email-')
        db.execute('UPDATE "t""1" SET stage=?', ('Private draft',))
        if journal == 'wal':
            assert call(g, agent, 'read_private_fields', row) == first
        else:
            with pytest.raises(Denied):
                call(g, agent, 'read_private_fields', row)
        db.commit()
        assert call(g, agent, 'read_private_fields', row)['rows'][0][0] == 'Private draft'
        with pytest.raises(Denied):
            call(g, other, 'read_private_fields', row)
        with pytest.raises(Denied):
            call(g, agent, 'read_private_fields', row, table='excluded')
        assert all(t not in json.dumps(w.state()['receipts']) for t in ('concealed','PRIVATE_CANARY','raw@example.org',str(path)))
        w.remove(row['id'])
        with pytest.raises(Denied):
            call(g, agent, 'read_private_fields', row)


def test_live_csv_rechecks_identity_between_forms_and_reads(setup, tmp_path):
    g, w, agent, _ = setup
    path = tmp_path/'feed.csv'
    path.write_text('stage,hidden\nOpen,SECRET\n')
    ticket = discover(w, path)['identity']
    values = dict(path=str(path), identity=ticket, table='',fields=['stage'])
    row = prepare(w, agent, 'live_data', values)
    assert call(g, agent, 'read_private_fields', row)['rows'] == [['Open']]
    path.write_text('stage,hidden\nDone,PRIVATE\n')
    assert call(g, agent, 'read_private_fields', row)['rows'] == [['Done']]
    replacement = tmp_path/'replacement'
    replacement.write_text('stage\nSWAPPED\n')
    os.replace(replacement, path)
    with pytest.raises(Denied):
        prepare(w, agent, 'live_data', values)
    with pytest.raises(Denied):
        call(g, agent, 'read_private_fields', row)
    link = tmp_path/'alias'
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(Denied):
        discover(w, link/'feed.csv')


def test_append_review_replacement_and_private_receipt(setup, tmp_path):
    g, w, agent, _ = setup
    path = tmp_path/'notes.txt'
    path.write_text('old\n')
    values = dict(path=str(path), text='PRIVATE_APPEND\n')
    row = prepare(w, agent, 'file_append', values)
    call(g, agent, 'request_private_action', row)
    assert path.read_text() == 'old\n'
    assert w.decide(row['id'], row['fingerprint'], True)['status'] == 'appended'
    assert path.read_text() == 'old\nPRIVATE_APPEND\n'
    with pytest.raises(Denied):
        w.decide(row['id'], row['fingerprint'], True)
    assert call(g, agent, 'private_action_status', row)['status'] == 'appended'
    assert all(t not in str(w.state()['receipts']) for t in ('PRIVATE_APPEND', str(path)))
    row = prepare(w, agent, 'file_append', values)
    call(g, agent, 'request_private_action', row)
    other = tmp_path/'new.txt'
    other.write_text('another file')
    os.replace(other, path)
    assert w.decide(row['id'], row['fingerprint'], True)['status'] == 'unconfirmed'
    assert path.read_text() == 'another file'
    os.link(path, other)
    with pytest.raises(Denied):
        prepare(w, agent, 'file_append', values)


def test_revoked_during_live_read_withholds_result(setup, tmp_path, monkeypatch):
    import privacy_layer.workspace as workspace
    g, w, agent, _ = setup
    path = tmp_path/'projects.json'
    path.write_text('[{"stage":"Open","other":"Private"}]')
    row = prepare(w, agent, 'live_data', dict(path=str(path), table='', identity=discover(w,path)['identity'],fields=['stage']))
    entered, release = Event(), Event()
    original = workspace.inspect_live
    def paused(*args):
        result = original(*args)
        entered.set()
        assert release.wait(4)
        return result
    monkeypatch.setattr(workspace, 'inspect_live', paused)
    with ThreadPoolExecutor() as pool:
        read = pool.submit(call, g, agent, 'read_private_fields', row)
        assert entered.wait(4)
        g.revoke(agent['id'])
        release.set()
        with pytest.raises(Denied):
            read.result()
    assert 'Open' not in str(w.state()['receipts'])
