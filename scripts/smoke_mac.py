"""Fresh packaged installation and real MCP transport, using disposable data only.

CI calls the same bootstrap as the native window. This does not test Finder,
Gatekeeper or a real AI conversation. No Python/Ollama installation is on PATH.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from urllib.request import Request,build_opener,ProxyHandler


def check(app, cached_runtime=None):
    with tempfile.TemporaryDirectory(prefix='airlock-install-check-') as temp:
        base=Path(temp)/'data';home=Path(temp)/'profile';base.mkdir();home.mkdir()
        if cached_runtime:(base/'runtime').symlink_to(Path(cached_runtime).resolve(),target_is_directory=True)
        resources=Path(app).resolve()/'Contents/Resources'
        env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','OLLAMA','NEAR_'))}
        env.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin',PRIVATE_AI_PROFILE_HOME=str(home),PYTHONDONTWRITEBYTECODE='1')
        launch=None
        opener=build_opener(ProxyHandler({}))
        def start():
            result=subprocess.run(['/bin/bash',str(resources/'bootstrap.sh'),str(resources/'payload'),str(base)],env=env,capture_output=True,text=True,timeout=600)
            if result.returncode:
                # Test-only profile; do not print launch tokens or app identity.
                log=base/'app/.private/service.log'
                raise RuntimeError('Bootstrap failed: '+result.stderr[-2500:]+(log.read_text()[-2500:] if log.exists() else ''))
            return json.loads((base/'app/.private/launch.json').read_text())
        def api(action,data=None,authorized=True):
            headers={'Content-Type':'application/json'}
            if authorized:headers['Authorization']='Bearer '+launch['owner_token']
            req=Request(launch['url'].split('/?')[0]+'/api/'+action,data=json.dumps(data or {}).encode(),headers=headers)
            with opener.open(req,timeout=15) as response:return json.load(response)
        def call(entry,tool,args):
            messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'airlock-install-check','version':'1'}}},
                      {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':tool,'arguments':args}}]
            result=subprocess.run([entry['command'],*entry['args']],input='\n'.join(map(json.dumps,messages))+'\n',text=True,capture_output=True,env=env,timeout=45)
            response=next(json.loads(line) for line in result.stdout.splitlines() if json.loads(line).get('id')==2)
            assert not response.get('error'),response
            assert not response['result'].get('isError'),response
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
            launch=start()
            assert api('dashboard')['counts']=={'memories':0,'skills':0}
            origin=launch['url'].split('/?')[0]
            for path in ('/','/memory','/memory.js','/near.js','/onboarding.js'):
                with opener.open(origin+path) as r:assert r.status==200
            raw=b'# Memories\nFictional Cypress launch is November 20. Phone: +1 415 555 0123.\n# Skills\nUse two concise bullets for Cypress updates.'
            preview=api('context-preview',{'name':'fictional.md','content':base64.b64encode(raw).decode()})
            saved=api('context-commit',{'id':preview['id'],'indices':list(range(len(preview['items'])))})
            assert saved['added']==2
            api('onboarding',{'gmail_skipped':True})
            entry=api('client-connect',{'agent':'codex','approved':True,'lifetime':604800,'max_calls':100})
            assert entry['installed'] and (home/'.codex/config.toml').is_file()
            config=(home/'.codex/config.toml').read_text()
            assert 'pal_' not in config and launch['owner_token'] not in config
            result=call(entry,'get_private_context',{'query':'Cypress launch update style'})
            assert 'November 20' in str(result) and 'two concise bullets' in str(result)
            assert '415 555 0123' not in str(result)
            assert raw not in (base/'app/.private/connections.enc').read_bytes()
            assert isinstance(api('memory-state'),dict)
            first=launch['pid'];stop();launch=start()
            assert launch['pid']!=first
            assert api('dashboard')['counts']=={'memories':1,'skills':1}
            assert 'November 20' in str(call(entry,'get_private_context',{'query':'Cypress launch'}))
            api('revoke',{'id':entry['id']})
            try:call(entry,'get_private_context',{'query':'Cypress'})
            except AssertionError:pass
            else:raise AssertionError('Revoked connection still works')
            print(json.dumps({'passed':True,'version':launch['version'],'fresh_runtime':not bool(cached_runtime),'empty_install':True,'import':True,'native_config':True,'mcp_retrieval':True,'filtering':True,'restart_preserves_data':True,'revocation':True,'finder_ui_tested':False}))
        finally:
            if not launch:
                path=base/'app/.private/launch.json'
                if path.exists():launch=json.loads(path.read_text())
            stop()
            python=base/'runtime/venv/bin/python'
            if python.exists() and (base/'app/vendor').exists():
                subprocess.run([str(python),'-c',"import sys;sys.path.insert(0,'vendor');from private_ai.device_access import MacKeychain;from pathlib import Path;MacKeychain(Path('.private/connections.enc')).delete()"],cwd=base/'app',env=env,check=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('app',type=Path);p.add_argument('--cached-runtime',type=Path);a=p.parse_args();check(a.app,a.cached_runtime)
