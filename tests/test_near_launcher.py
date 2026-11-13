"""ASGI isolation and mocked listener lifecycle; no live browser/network claim."""
import asyncio
import json
from unittest.mock import Mock

import pytest
from starlette.testclient import TestClient
import uvicorn

from privacy_layer.demo_server import DemoServer, make_app, main


def test_demo_dashboard_keeps_personal_actions_blocked(tmp_path):
    app=make_app(tmp_path,'fixture-token',9876)
    with TestClient(app,base_url='http://127.0.0.1:9876') as client:
        assert client.post('/api/dashboard',json={}).status_code==401
        headers={'Authorization':'Bearer fixture-token','Origin':'http://127.0.0.1:9876'}
        assert client.post('/api/dashboard',json={},headers=headers).json()['demo_only'] is True
        assert client.post('/api/private-phrases',json={},headers=headers).status_code==403
        assert client.post('/api/near-state',json={},headers=headers).status_code==200
        assert client.post('/api/near-state',json={},headers={**headers,'Origin':'http://127.0.0.1:8795'}).status_code==403


@pytest.mark.parametrize('started',[True,False])
def test_private_link_and_browser_wait_for_successful_startup(tmp_path,monkeypatch,started):
    opened=Mock(return_value=True)
    monkeypatch.setattr('privacy_layer.demo_server.webbrowser.open',opened)
    async def startup(server,sockets=None):
        assert not (tmp_path/'launch.json').exists()
        opened.assert_not_called()
        server.started=started
    monkeypatch.setattr(uvicorn.Server,'startup',startup)
    server=DemoServer(uvicorn.Config(make_app(tmp_path,'fixture',9876)),tmp_path,'fixture',9876)
    asyncio.run(server.startup())
    if started:
        url=json.loads((tmp_path/'launch.json').read_text())['url']
        assert url=='http://127.0.0.1:9876/#fixture'
        assert (tmp_path/'launch.json').stat().st_mode&0o777==0o600
        opened.assert_called_once_with(url)
    else:
        assert not (tmp_path/'launch.json').exists()
        opened.assert_not_called()


def test_failed_bind_preserves_working_launch_link(tmp_path,monkeypatch,capsys):
    saved=tmp_path/'launch.json';saved.write_text('{"url":"existing-private-link"}')
    class UnavailableSocket:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def bind(self,address):raise OSError('occupied')
    monkeypatch.setattr('privacy_layer.demo_server.socket.socket',lambda *args:UnavailableSocket())
    monkeypatch.setattr('sys.argv',['demo_server','--state',str(tmp_path)])
    with pytest.raises(SystemExit) as error:main()
    assert error.value.code==2
    assert 'Try --port 0' in capsys.readouterr().err
    assert saved.read_text()=='{"url":"existing-private-link"}'
    assert not (tmp_path/'demo.key').exists()
