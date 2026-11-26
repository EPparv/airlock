"""Fresh packaged installation and real MCP with disposable fictional data only.

The native window check launches the archived executable with a disposable profile.
No separately installed Python or Ollama is on PATH.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import plistlib
import signal
import shutil
import subprocess
import tempfile
import time
import tomllib
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,ProxyHandler


def check(app, cached_runtime=None, window_probe=None):
    with tempfile.TemporaryDirectory(prefix='airlock-install-check-') as temp:
        base=Path(temp)/'data';home=Path(temp)/'profile';base.mkdir();home.mkdir()
        canary=home/'.private-ai/vault.enc';canary.parent.mkdir();canary.write_bytes(b'EXISTING_PERSONAL_VAULT_CANARY')
        if cached_runtime:(base/'runtime').symlink_to(Path(cached_runtime).resolve(),target_is_directory=True)
        resources=Path(app).resolve()/'Contents/Resources'
        env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','OLLAMA','NEAR_'))}
        env.pop('XDG_CONFIG_HOME',None)
        env.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin',PRIVATE_AI_PROFILE_HOME=str(home),PYTHONDONTWRITEBYTECODE='1')
        native_process=None
        launch=None;personal_owner=None;personal_initialized=False
        opener=build_opener(ProxyHandler({}))
        def start():
            result=subprocess.run(['/bin/bash',str(resources/'bootstrap.sh'),str(resources/'payload'),str(base)],env=env,capture_output=True,text=True,timeout=600)
            if result.returncode:
                log=base/'app/.private/service.log'
                raise RuntimeError('Bootstrap failed: '+result.stderr[-2500:]+(log.read_text()[-2500:] if log.exists() else ''))
            return json.loads((base/'app/.private/launch.json').read_text())
        def start_native():
            nonlocal native_process
            binary=resources.parent/'MacOS/Airlock'
            native_process=subprocess.Popen([str(binary),'--data-dir',str(base),'--profile-home',str(home),'--no-update-check'],
                                            env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            session=base/'app/.private/launch.json'
            deadline=time.monotonic()+600
            while time.monotonic()<deadline:
                if native_process.poll() is not None:
                    raise RuntimeError('The archived Airlock executable exited before opening its workspace.')
                if session.is_file():
                    try:
                        record=json.loads(session.read_text())
                        url=urlsplit(record['url'])
                        with opener.open(f'{url.scheme}://{url.netloc}/workspace',timeout=2) as response:
                            if response.status==200:
                                return record
                    except (OSError,ValueError,KeyError):
                        pass
                time.sleep(.25)
            raise RuntimeError('The archived Airlock executable did not finish first setup.')
        def api(action,data=None,personal=False):
            token=personal_owner if personal else launch['owner_token']
            u=urlsplit(launch['url']);origin=f'{u.scheme}://{u.netloc}'
            req=Request(origin+'/api/'+action,data=json.dumps(data or {}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
            with opener.open(req,timeout=15) as response:return json.load(response)
        def call(entry,tool,args,denied=False):
            messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'airlock-install-check','version':'1'}}},
                      {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':tool,'arguments':args}}]
            result=subprocess.run([entry['command'],*entry['args']],input='\n'.join(map(json.dumps,messages))+'\n',text=True,capture_output=True,env=env,timeout=45)
            response=next(json.loads(line) for line in result.stdout.splitlines() if json.loads(line).get('id')==2)
            if response.get('error'):
                assert denied,response
                # A revoked/closed credential fails before MCP dispatch. Confirm
                # an actual 401 from the live service, not an unavailable server.
                api('test-state')
                args=entry['args'];token=Path(args[args.index('--token-file')+1]).read_text().strip()
                req=Request(launch['mcp_url'],data=json.dumps(messages[0]).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json, text/event-stream'})
                try:opener.open(req,timeout=10)
                except HTTPError as error:assert error.code==401,error.code
                else:raise AssertionError('Expected an authentication denial')
                return {'denied_at_http_boundary':True}
            assert bool(response['result'].get('isError'))==denied,response
            return json.loads(response['result']['content'][0]['text'])
        def stop():
            if launch:
                try:os.kill(launch['pid'],signal.SIGTERM)
                except ProcessLookupError:pass
                for _ in range(100):
                    try:api('state')
                    except Exception:return
                    time.sleep(.1)
                raise RuntimeError('Disposable test server did not stop')
        try:
            launch=start_native() if window_probe else start()
            assert launch['mode']=='safe-test'
            if window_probe:
                # Run the native UI probe against this archive's resources, executable layout and live service.
                contents=Path(temp)/'window/Airlock.app/Contents'
                (contents/'MacOS').mkdir(parents=True)
                shutil.copy2(resources.parent/'Info.plist',contents/'Info.plist')
                (contents/'Resources').symlink_to(resources,target_is_directory=True)
                binary=contents/'MacOS/Airlock'
                shutil.copy2(window_probe,binary)
                subprocess.run([str(binary),'--data-dir',str(base),'--profile-home',str(home),'--no-update-check'],env=env,check=True,timeout=110)
            state=api('test-state');assert state['isolated'] and not state['personal_open']
            assert not (base/'app/.private/connections.enc').exists()
            assert not (base/'app/.private/key.lock').exists()
            assert canary.read_bytes()==b'EXISTING_PERSONAL_VAULT_CANARY'
            parsed=urlsplit(launch['url']);origin=f'{parsed.scheme}://{parsed.netloc}'
            for path in ('/','/safe-test.js','/safe-test.css','/workspace','/workspace.js','/workspace.css','/workspace-remote.js','/workspace-prompt.js','/workspace-handoffs.js'):
                with opener.open(origin+path) as r:assert r.status==200
            for step in ('recall','privacy','correction','propose','approve','persistence','revoke'):
                assert api('test-check',{'step':step})['passed'],step
            api('test-connect',{'agent':'codex','approved':True})
            config=home/'.codex/config.toml';test_entry=tomllib.loads(config.read_text())['mcp_servers']['airlock-test']
            r=call(test_entry,'get_private_context',{'query':'Cypress'})
            assert 'November 27' in str(r) and 'two concise bullets' in str(r)
            assert 'FICTIONAL-ORCHID-7429' not in str(r)
            call(test_entry,'search_gmail',{'query':'anything'},denied=True)
            first=launch['pid'];stop();launch=start();assert first!=launch['pid']
            assert len(api('test-state')['checks'])==7 and not api('test-state')['personal_open']
            assert 'November 27' in str(call(test_entry,'get_private_context',{'query':'Cypress'}))
            api('test-disconnect');call(test_entry,'get_private_context',{'query':'Cypress'},denied=True)
            # Now explicitly opt into a fresh personal workspace, using fictional data.
            canary.unlink()
            personal_owner=api('open-personal',{'approved':True})['url'].split('#')[1];personal_initialized=True
            assert personal_owner!=launch['owner_token']
            assert api('dashboard',personal=True)['counts']=={'memories':0,'skills':0}
            raw=b'# Memories\nFictional Cypress launch is November 20. Phone: +1 415 555 0123.\n# Skills\nUse two concise bullets for Cypress updates.'
            preview=api('context-preview',{'name':'fictional.md','content':base64.b64encode(raw).decode()},personal=True)
            saved=api('context-commit',{'id':preview['id'],'indices':list(range(len(preview['items'])))},personal=True)
            assert saved['added']==2
            # An existing developer copy must migrate without touching other entries.
            old=base/'old-source';old_entry={'command':str(old/'.venv/bin/python'),'args':[str(old/'privacy_layer/stdio.py'),'--token-file',str(old/'.private/clients/old.token')]}
            with config.open('a') as f:f.write('\n# Airlock managed connection — begin\n[mcp_servers.airlock]\ncommand = '+json.dumps(old_entry['command'])+'\nargs = '+json.dumps(old_entry['args'])+'\n# Airlock managed connection — end\n')
            entry=api('client-connect',{'agent':'codex','approved':True,'lifetime':604800,'max_calls':100},personal=True)
            assert entry['installed']
            servers=tomllib.loads(config.read_text())['mcp_servers']
            assert servers['airlock-test']==test_entry and 'airlock' in servers
            assert 'pal_' not in config.read_text() and personal_owner not in config.read_text()
            call(entry,'get_private_context',{'query':'Cypress'},denied=True)
            selectable=api('client-context',personal=True)['records']
            entry=api('client-connect',{'agent':'codex','approved':True,'lifetime':604800,'max_calls':100,'selection':{r['ref']:r['text_hash'] for r in selectable}},personal=True)
            assert api('client-status',{'id':entry['id']},personal=True)['status']=='waiting'
            result=call(entry,'get_private_context',{'query':'Cypress launch update style'})
            assert 'November 20' in str(result) and 'two concise bullets' in str(result)
            assert '415 555 0123' not in str(result)
            assert api('client-status',{'id':entry['id']},personal=True)['status']=='verified'
            assert raw not in (base/'app/.private/connections.enc').read_bytes()
            # Two independently configured agents can share a record and pass one approved result.
            muse=api('client-connect', {'agent':'muse-code','approved':True,'lifetime':3600,
                     'max_calls':30,'selection':{r['ref']:r['text_hash'] for r in selectable}}, personal=True)
            muse_config=json.loads((home/'.config/muse/settings.json').read_text())['mcp_servers']['airlock']
            assert muse_config['transport']=='stdio' and muse_config['mode']=='optional'
            assert all(muse_config[k]==muse[k] for k in ('command','args'))
            assert muse['installed'] and 'November 20' in str(call(muse,'get_private_context',{'query':'Cypress'}))
            assignment='Prepare the fictional release checklist.'
            routing={'worker':entry['id'],'recipient':muse['id']}
            reviewed=api('handoff-check-assignment',{**routing,'instruction':assignment},personal=True)
            api('handoff-assign',{**routing,'instruction':reviewed['text'],
                                  'approval':reviewed['approval'],'approved':True},personal=True)
            handle=call(entry,'list_agent_handoffs',{})['handoffs'][0]['reference']
            assert call(entry,'claim_agent_handoff',{'reference':handle})['instruction']==assignment
            report='The release checklist is ready.'
            call(entry,'submit_agent_handoff',{'reference':handle,'result':report,'memory_proposal_id':''})
            assert call(muse,'list_agent_handoffs',{})['handoffs']==[]
            job=api('handoff-state',personal=True)['handoffs'][0]
            api('handoff-release',{'id':job['id'],'revision':job['revision'],'text':report,'approved':True},personal=True)
            recipient_handle=call(muse,'list_agent_handoffs',{})['handoffs'][0]['reference']
            assert recipient_handle!=handle and call(muse,'read_agent_handoff',{'reference':recipient_handle})['result']==report
            model=api('prompt-create',{'name':'Local smoke','provider':'ollama','model':'fictional','approved':True},personal=True)
            catalog_request=Request(model['base_url'].rstrip('/')+'/models',headers={'Authorization':'Bearer '+model['token']})
            with opener.open(catalog_request,timeout=5) as response:
                assert json.load(response)['data'][0]['id']=='airlock'
            api('close-personal');call(entry,'get_private_context',{'query':'Cypress'},denied=True)
            try:opener.open(catalog_request,timeout=5)
            except HTTPError as error:assert error.code in (401,403,404)
            else:raise AssertionError('Model credential survived workspace lock')
            first=launch['pid'];stop();launch=start();assert launch['pid']!=first
            assert not api('test-state')['personal_open']
            call(entry,'get_private_context',{'query':'Cypress'},denied=True)
            personal_owner=api('open-personal',{'approved':True})['url'].split('#')[1]
            assert api('dashboard',personal=True)['counts']=={'memories':1,'skills':1}
            assert 'November 20' in str(call(entry,'get_private_context',{'query':'Cypress launch'}))
            api('revoke',{'id':entry['id']},personal=True)
            call(entry,'get_private_context',{'query':'Cypress'},denied=True)
            # Register test bundles with vendor IDs only on disposable hosted Macs
            # that have no matching installed app. No machine-level changes on user Macs.
            if window_probe and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted':
                register='/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
                for name,identifier in [('Cursor','com.todesktop.230313mzl4w4u92'),('Codex','com.openai.codex')]:
                    def resolved():
                        return subprocess.check_output([binary,'--find-installed-bundle',identifier],env=env,text=True).strip()
                    assert not resolved(), 'Refusing to register a disposable bundle over an installed agent.'
                    fixture=Path(temp)/name/'Fixture.app'
                    executable=fixture/'Contents/MacOS/Fixture'
                    executable.parent.mkdir(parents=True)
                    shutil.copy2(window_probe,executable)
                    (fixture/'Contents/Info.plist').write_bytes(plistlib.dumps({
                        'CFBundleName':'Airlock test client','CFBundleExecutable':'Fixture',
                        'CFBundleIdentifier':identifier,'AirlockDisposableLaunchFixture':True,
                        'CFBundlePackageType':'APPL','CFBundleVersion':'1','NSPrincipalClass':'NSApplication',
                        'CFBundleURLTypes':[{'CFBundleURLName':'Airlock disposable test', 'CFBundleTypeRole':'Viewer',
                                             'LSHandlerRank':'None','CFBundleURLSchemes':[name.lower()]}],
                    }))
                    subprocess.run(['/usr/bin/codesign','--force','--sign','-',fixture],check=True)
                    subprocess.run([register,'-f',fixture],check=True)
                    try:
                        assert Path(resolved()).resolve()==fixture.resolve(), 'Launch Services did not register the test bundle.'
                        api('close-personal')
                        subprocess.run([binary,'--data-dir',base,'--profile-home',home,'--no-update-check',
                                        '--test-client',fixture,name],env=env,check=True,timeout=120)
                        assert api('test-state')['personal_open']
                        personal_owner=api('open-personal',{'approved':True})['url'].split('#')[1]
                        agents=api('workspace-state',personal=True)['agents']
                        active=[a for a in agents if a['name']==name.lower() and a['status'] not in ('expired','revoked')]
                        assert len(active)==1 and active[0]['installed'] and active[0]['scope']['records']==[]
                        assert not active[0]['proposals'] and not any(active[0]['device'].values())
                        assert active[0]['last_call'] is None and active[0]['last_discovery'] is None
                    finally:
                        subprocess.run([register,'-u',fixture],check=False)
            print(json.dumps({'passed':True,'version':launch['version'],'fresh_runtime':not bool(cached_runtime),'safe_start':True,'existing_vault_untouched':True,'guided_checks':7,'separate_client_names':True,'personal_opt_in':True,'zero_access_default':True,'old_install_migration':True,'inline_selection':True,'connection_verification':True,'mcp_retrieval':True,'approved_cross_agent_handoff':True,'personal_model_key_revoked_on_lock':True,'filtering':True,'restart_preserves_data_and_closes_personal':True,'revocation':True,'archived_executable':bool(window_probe),'native_window':bool(window_probe),'finder_ui_tested':False}))
        finally:
            if native_process and native_process.poll() is None:
                native_process.terminate()
                try:native_process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    native_process.kill()
                    native_process.wait()
            if not launch:
                path=base/'app/.private/launch.json'
                if path.exists():launch=json.loads(path.read_text())
            stop()
            python=base/'runtime/venv/bin/python'
            if personal_initialized and python.exists():
                subprocess.run([str(python),'-c',"import sys;sys.path.insert(0,'vendor');from private_ai.device_access import MacKeychain;from pathlib import Path;MacKeychain(Path('.private/connections.enc')).delete()"],cwd=base/'app',env=env,check=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('app',type=Path);p.add_argument('--cached-runtime',type=Path);p.add_argument('--window-probe',type=Path);a=p.parse_args();check(a.app,a.cached_runtime,a.window_probe)
