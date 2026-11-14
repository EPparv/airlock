"""A real signed update through the helper, native restart and failed-start recovery.

All app paths, runtime, profile, encrypted fixtures and AI settings are disposable.
Only the network transport is replaced with the exact CI-published signed files.
No alternate-feed option is shipped in the app.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from privacy_layer import updater as u


def stop_service(base):
    record=u.live_session(base)
    if record:
        os.kill(record['pid'],signal.SIGTERM)
        for _ in range(80):
            if not u.live_session(base):
                return
            time.sleep(.25)
        raise RuntimeError('Disposable service did not close')


def smoke(directory):
    directory=Path(directory).resolve()
    metadata=u.verify_manifest((directory/'updates.json').read_bytes(),(directory/'updates.sigstore.json').read_bytes())
    data=(directory/u.ARCHIVE).read_bytes()
    with tempfile.TemporaryDirectory(prefix='airlock-update-smoke-') as temp:
        root=Path(temp);base=root/'support';home=root/'profile';home.mkdir();base.mkdir()
        staging=root/'download';staging.mkdir()
        current=u.extract_archive(data,metadata,staging)
        u.validate_app(current,metadata)
        installed=root/'Airlock.app';shutil.copytree(current,installed)
        old_build=metadata['build']-1;old_version='0.0.0-alpha.1'
        payload=installed/'Contents/Resources/payload'
        old=json.loads((payload/'release.json').read_bytes());old.update(version=old_version,build=old_build)
        (payload/'release.json').write_text(json.dumps(old))
        (payload/'privacy_layer/version.py').write_text(f'VERSION = {old_version!r}\nBUILD = {old_build}\n')
        info=plistlib.loads((installed/'Contents/Info.plist').read_bytes());info['CFBundleVersion']=str(old_build)
        (installed/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
        subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(installed)],check=True,capture_output=True)
        env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','OLLAMA','NEAR_'))}
        env.update(PRIVATE_AI_PROFILE_HOME=str(home),PYTHONDONTWRITEBYTECODE='1',PATH='/usr/bin:/bin:/usr/sbin:/sbin')
        subprocess.run(['/bin/bash',str(installed/'Contents/Resources/bootstrap.sh'),str(payload),str(base)],
                       env=env,check=True,timeout=600)
        config=home/'.codex/config.toml';config.parent.mkdir();config.write_bytes(b'# EXISTING_FICTIONAL_AI_SETTINGS\n')
        canary=base/'app/.private/retained.enc';canary.write_bytes(b'ENCRYPTED_UPDATE_TEST_CANARY')
        fixture_key=base/'app/.private/safe-test/fictional.key'
        key=fixture_key.read_bytes()
        status=base/'smoke-status.json'
        processes=[]
        # This process models the native owner's quit handshake. Its child is
        # the real updater from the OLD installed program, not the source tree.
        helper=r'''
import json,os,signal,subprocess,sys,time
from pathlib import Path
app,base,published,status,home=map(Path,sys.argv[1:])
code="""
import os,sys
from pathlib import Path
app,base,published,status,home,parent=sys.argv[1:]
sys.path.insert(0,str(Path(base)/'app'))
from privacy_layer import updater as u
u.fetch=lambda name,limit: (Path(published)/name).read_bytes()
try:
    manifest=u.latest()
    u.install(Path(app),Path(base),manifest['build'],int(parent),Path(status),Path(home))
except Exception as e:
    u.atomic_json(Path(status),{'phase':'error','message':str(e)})
    raise
"""
child=subprocess.Popen([str(base/'runtime/venv/bin/python'),'-c',code,str(app),str(base),str(published),str(status),str(home),str(os.getpid())],start_new_session=True)
sys.path.insert(0,str(base/'app'))
from privacy_layer import updater as u
for _ in range(600):
    state=json.loads(status.read_text()) if status.exists() else {}
    if state.get('phase')=='ready':
        live=u.live_session(base)
        if live:os.kill(live['pid'],signal.SIGTERM)
        sys.exit(0)
    if child.poll() is not None:raise RuntimeError(state)
    time.sleep(.2)
child.terminate()
raise RuntimeError('Update did not finish staging')
'''
        try:
            subprocess.run([sys.executable,'-c',helper,str(installed),str(base),str(directory),str(status),str(home)],
                           env=env,check=True,timeout=150)
            deadline=time.monotonic()+660
            while time.monotonic()<deadline:
                state=json.loads(status.read_text())
                if state['phase'] in ('error','installed'):
                    break
                time.sleep(.5)
            assert state['phase']=='installed',state
            new_pid=state['app_pid'];processes.append(new_pid)
            assert u.app_release(installed)['build']==metadata['build']
            assert u.live_session(base)['version']==metadata['version']
            assert fixture_key.read_bytes()==key
            assert canary.read_bytes()==b'ENCRYPTED_UPDATE_TEST_CANARY'
            assert config.read_bytes()==b'# EXISTING_FICTIONAL_AI_SETTINGS\n'
            backup=Path(json.loads((base/'previous-app.json').read_text())['path'])
            assert u.app_release(backup)['version']==old_version
            print('Verified signed helper update, native relaunch, prior app backup, encrypted-key and config preservation.',flush=True)
            os.kill(new_pid,signal.SIGTERM);stop_service(base);time.sleep(1)
            # A broken candidate must restore the working bundle and launch it.
            broken=root/'broken.app';shutil.copytree(installed,broken)
            binary=broken/'Contents/MacOS/Airlock';binary.write_text('#!/bin/sh\nexit 1\n');binary.chmod(0o755)
            launch=u.launch_app
            def tracked(*args,**kwargs):
                process=launch(*args,**kwargs);processes.append(process.pid);return process
            u.launch_app=tracked
            try:
                u.replace_and_restart(installed,broken,base,metadata,home)
            except u.UpdateError as error:
                assert 'previous app was restored' in str(error),error
            else:
                raise AssertionError('Failed update was not rolled back')
            deadline=time.monotonic()+90
            while time.monotonic()<deadline and not u.live_session(base):
                time.sleep(.5)
            assert u.live_session(base)['version']==metadata['version']
            assert u.app_release(installed)['build']==metadata['build']
            assert fixture_key.read_bytes()==key and canary.read_bytes()==b'ENCRYPTED_UPDATE_TEST_CANARY'
            assert config.read_bytes()==b'# EXISTING_FICTIONAL_AI_SETTINGS\n'
            print('Verified failed native start restores and reopens the previous app without resetting state.',flush=True)
        finally:
            for pid in processes:
                try:os.kill(pid,signal.SIGTERM)
                except ProcessLookupError:pass
            stop_service(base)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path)
    smoke(parser.parse_args().directory)
