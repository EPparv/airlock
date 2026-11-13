import copy
import pytest
from privacy_layer.core import Denied
from privacy_layer import setup


def prepare(bundle,monkeypatch,tmp_path):
    gateway,_,_,views,_=bundle
    grant=gateway.create(agent='dot',purpose='Reviewed context',views=views,approved=True,lifetime=60,max_calls=3)
    monkeypatch.setattr(setup,'ROOT',tmp_path)
    setup.private_write(tmp_path/'.private/dot.token',grant['token'])
    with gateway.store.transaction() as data:
        data['dot_tunnel']={'id':'tunnel_test','runtime_key':'sk-local-test-only'}
    return gateway,grant


def test_saved_reconnect_preserves_grant_and_credentials(bundle,monkeypatch,tmp_path):
    gateway,grant=prepare(bundle,monkeypatch,tmp_path)
    with gateway.store.transaction() as data:before=copy.deepcopy(data['grants'])
    calls=[]
    monkeypatch.setattr(setup,'dot_status',lambda:dict(process_running=False,healthy=False,ready=False))
    monkeypatch.setattr(setup,'configure_dot',lambda *args: calls.append(args) or {'running':True,'healthy':True,'ready':True})
    assert setup.restore_dot(gateway)['ready']
    assert calls==[(gateway,grant['token'],'tunnel_test','sk-local-test-only')]
    with gateway.store.transaction() as data:assert data['grants']==before


@pytest.mark.parametrize('blocked',['expired','revoked','exhausted','wrong-agent'])
def test_saved_reconnect_never_reopens_closed_access(bundle,monkeypatch,tmp_path,blocked):
    gateway,grant=prepare(bundle,monkeypatch,tmp_path)
    if blocked=='expired':bundle[2][0]+=61
    elif blocked=='revoked':gateway.revoke(grant['id'])
    else:
        with gateway.store.transaction() as data:
            data['grants'][grant['id']]['remaining' if blocked=='exhausted' else 'agent']=0 if blocked=='exhausted' else 'claude-code'
    def unexpected(*args):pytest.fail('Closed access must not start or reconfigure a tunnel')
    monkeypatch.setattr(setup,'configure_dot',unexpected)
    monkeypatch.setattr(setup,'dot_status',unexpected)
    with pytest.raises(Denied):setup.restore_dot(gateway)


def test_new_approved_grant_rebinds_existing_setup(bundle,monkeypatch,tmp_path):
    gateway,_=prepare(bundle,monkeypatch,tmp_path)
    newer=gateway.create(agent='dot',purpose='Fresh reviewed context',views=bundle[3],approved=True,lifetime=60,max_calls=3)
    calls=[]
    monkeypatch.setattr(setup,'dot_status',lambda:dict(process_running=True,healthy=True,ready=True))
    monkeypatch.setattr(setup,'configure_dot',lambda *args:calls.append(args) or {'running':True,'healthy':True,'ready':True})
    assert setup.restore_dot(gateway,newer['token'])['ready']
    assert calls[0][1]==newer['token']


def test_ready_reopen_does_not_reconfigure(bundle,monkeypatch,tmp_path):
    gateway,_=prepare(bundle,monkeypatch,tmp_path)
    monkeypatch.setattr(setup,'dot_status',lambda:dict(process_running=True,healthy=True,ready=True))
    monkeypatch.setattr(setup,'configure_dot',lambda *args:pytest.fail('Already ready'))
    assert setup.restore_dot(gateway)['ready']


def test_reconnect_does_not_report_incomplete_startup_as_success(bundle,monkeypatch,tmp_path):
    gateway,grant=prepare(bundle,monkeypatch,tmp_path)
    monkeypatch.setattr(setup,'configure_dot',lambda *args:{'running':True,'healthy':False,'ready':False})
    with pytest.raises(Denied,match='not become ready'):setup.restore_dot(gateway,grant['token'])
