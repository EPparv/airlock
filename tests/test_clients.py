import copy
import json
from pathlib import Path
import stat
import tomllib
import pytest
from starlette.testclient import TestClient
from privacy_layer import clients
from privacy_layer.core import Denied
from privacy_layer.server import owner_app

@pytest.mark.parametrize('agent',['codex','claude-desktop','claude-code','cursor','mcp'])
def test_independent_automatic_clients(bundle,tmp_path,monkeypatch,agent):
    g=bundle[0];monkeypatch.setattr(clients,'ROOT',tmp_path)
    result=clients.connect(g,agent=agent,approved=True,install=False)
    token_path=Path(result['args'][-1]);token=token_path.read_text()
    assert stat.S_IMODE(token_path.stat().st_mode)==0o600
    assert token not in result['config'] and 'owner' not in result['config']
    assert g.authenticate(token)['agent']==agent
    assert g.call(token,'privacy_status',{})['mode']=='automatic'
    output=g.call(token,'get_private_context',{'query':'interview'})
    assert {x['kind'] for x in output['items']}=={'memories','skills'}
    assert 'PRIVATE_CREDENTIAL_CANARY' not in json.dumps(output)
    g.revoke(result['id'])
    with pytest.raises(Denied):g.call(token,'privacy_status',{})

@pytest.mark.parametrize('agent',['claude-desktop','claude-code','cursor'])
def test_json_install_preserves_other_settings_and_no_keys(bundle,tmp_path,monkeypatch,agent):
    monkeypatch.setattr(clients,'ROOT',tmp_path/'root');home=tmp_path/'home';p=home/clients.RELATIVE_CONFIGS[agent];p.parent.mkdir(parents=True)
    previous={'theme':'dark','mcpServers':{'existing':{'command':'existing-tool','env':{'USER_SETTING':'keep-me'}}},'projects':{'keep':'everything'}}
    p.write_text(json.dumps(previous));result=clients.connect(bundle[0],agent=agent,approved=True,home=home)
    assert result['installed']
    updated=json.loads(p.read_text());new=updated['mcpServers'].pop(clients.SERVER)
    assert updated==previous and 'pal_' not in p.read_text()
    assert stat.S_IMODE(Path(new['args'][-1]).stat().st_mode)==0o600
    assert stat.S_IMODE(p.stat().st_mode)==0o600
    assert any((tmp_path/'root/.private/clients/backups').glob('*'))

def test_codex_install_reinstall_preserves_everything(bundle,tmp_path,monkeypatch):
    monkeypatch.setattr(clients,'ROOT',tmp_path/'root');home=tmp_path/'home';p=home/'.codex/config.toml';p.parent.mkdir(parents=True)
    original='# Keep comment\nmodel = "example-model"\n[features]\nshell_tool = true\n[mcp_servers.existing]\ncommand = "/bin/existing"\nargs = ["a", "b"]\n[projects."/with spaces"]\ntrust_level = "trusted"\n';p.write_text(original)
    for _ in range(2):
        clients.connect(bundle[0],agent='codex',approved=True,home=home)
        current=tomllib.loads(p.read_text());entry=current['mcp_servers'].pop(clients.SERVER)
        assert current==tomllib.loads(original) and '# Keep comment' in p.read_text()
        assert 'pal_' not in p.read_text() and Path(entry['args'][-1]).exists()
        assert p.read_text().count('[mcp_servers.airlock]')==1

@pytest.mark.parametrize('content',['{invalid',json.dumps({'mcpServers':{'airlock':{'command':'unrelated'}}})])
def test_failed_install_revokes_access_without_changing_existing(bundle,tmp_path,monkeypatch,content):
    monkeypatch.setattr(clients,'ROOT',tmp_path/'root');home=tmp_path/'home';p=home/'.cursor/mcp.json';p.parent.mkdir(parents=True);p.write_text(content)
    with pytest.raises(Denied):clients.connect(bundle[0],agent='cursor',approved=True,home=home)
    assert p.read_text()==content and all(x['revoked'] for x in bundle[0].list_grants())
    assert not list((tmp_path/'root/.private/clients').glob('*.token'))

def test_symlinked_config_is_not_followed(bundle,tmp_path,monkeypatch):
    monkeypatch.setattr(clients,'ROOT',tmp_path/'root');home=tmp_path/'home';p=home/'.cursor/mcp.json';p.parent.mkdir(parents=True)
    elsewhere=tmp_path/'protected.json';elsewhere.write_text('{}');p.symlink_to(elsewhere)
    with pytest.raises(Denied):clients.connect(bundle[0],agent='cursor',approved=True,home=home)
    assert elsewhere.read_text()=='{}'

def test_policy_approval_and_limits(bundle):
    g=bundle[0]
    for args in [{'approved':False},{'lifetime':True},{'max_calls':False},{'max_calls':1001},{'mode':'unknown'}]:
        values={'agent':'cursor','purpose':'Personal context','views':[],'mode':'automatic','approved':True};values.update(args)
        with pytest.raises(Denied):g.create(**values)
    assert not g.list_grants()

def test_existing_grant_unchanged(bundle,tmp_path,monkeypatch):
    monkeypatch.setattr(clients,'ROOT',tmp_path);g=bundle[0];original=bundle[4](max_calls=9)
    with g.store.transaction() as data:before=copy.deepcopy(data['grants'][original['id']])
    clients.connect(g,agent='mcp',approved=True,install=False)
    with g.store.transaction() as data:assert data['grants'][original['id']]==before

def test_dashboard_and_owner_only_setup(bundle,tmp_path,monkeypatch):
    g,s,_,_,_=bundle;monkeypatch.setattr(clients,'ROOT',tmp_path);s.gmail_state=lambda:{'configured':False,'sign_in':'not_checked','account':''}
    headers={'Authorization':'Bearer owner-secret'}
    with TestClient(owner_app(g,'owner-secret'),base_url='http://127.0.0.1:8791') as c:
        response=c.post('/api/dashboard',json={},headers=headers)
        assert response.status_code==200 and response.json()['counts']=={'memories':2,'skills':1}
        assert 'HIDDEN_FINANCE_CANARY' not in response.text
        assert c.post('/api/client-connect',json={'agent':'mcp','approved':True}).status_code==401
        assert c.post('/api/client-connect',json={'agent':'mcp','approved':True,'home':'/tmp/no'},headers=headers).status_code==400
        response=c.post('/api/client-connect',json={'agent':'mcp','approved':True,'install':False},headers=headers)
        assert response.status_code==200 and 'pal_' not in response.text and response.json()['installed'] is False
        assert c.get('/icon.svg').status_code==200

def test_other_agent_receipts_visible(bundle,tmp_path,monkeypatch):
    monkeypatch.setattr(clients,'ROOT',tmp_path);g=bundle[0];r=clients.connect(g,agent='cursor',approved=True,install=False)
    g.call(Path(r['args'][-1]).read_text(),'get_private_context',{'query':'interview'})
    with TestClient(owner_app(g,'owner-secret'),base_url='http://127.0.0.1:8791') as c:
        data=c.post('/api/disclosures',json={},headers={'Authorization':'Bearer owner-secret'}).json()
        assert data['events'][0]['agent_name']=='cursor' and data['events'][0]['items']

def test_scoped_connection_tokens_are_never_shareable():
    from privacy_layer.core import check_text,suggest_redaction
    token='pal_'+'a'*43
    with pytest.raises(Denied):check_text('Shared note '+token)
    assert token not in suggest_redaction('Shared note '+token)


def test_airlock_migrates_owned_legacy_entries_without_changing_token(tmp_path,monkeypatch):
    monkeypatch.setattr(clients,'ROOT',tmp_path)
    entry=clients.server_entry(tmp_path/'.private/existing.token')
    old='# Keep my settings\nmodel = "example"\n# Private AI managed connection — begin\n[mcp_servers.private-ai-privacy-layer]\ncommand = '+json.dumps(entry['command'])+'\nargs = '+json.dumps(entry['args'])+'\n# Private AI managed connection — end\n'
    updated=clients.codex_config(old,entry)
    data=tomllib.loads(updated)
    assert data['mcp_servers']=={'airlock':entry} and data['model']=='example'
    assert '# Keep my settings' in updated
    assert clients.codex_config(updated,entry)==updated
    js=json.dumps({'theme':'dark','mcpServers':{clients.LEGACY_SERVER:entry,'other':{'command':'other'}}})
    assert json.loads(clients.json_config(js,entry))=={'theme':'dark','mcpServers':{'airlock':entry,'other':{'command':'other'}}}

def test_airlock_does_not_take_over_unrelated_legacy_connection(tmp_path,monkeypatch):
    monkeypatch.setattr(clients,'ROOT',tmp_path)
    entry=clients.server_entry(tmp_path/'.private/existing.token')
    old='[mcp_servers.private-ai-privacy-layer]\ncommand = "unrelated"\n'
    assert tomllib.loads(clients.codex_config(old,entry))['mcp_servers']=={clients.LEGACY_SERVER:{'command':'unrelated'},'airlock':entry}
    js=json.dumps({'mcpServers':{clients.LEGACY_SERVER:{'command':'unrelated'}}})
    assert json.loads(clients.json_config(js,entry))['mcpServers'][clients.LEGACY_SERVER]=={'command':'unrelated'}
