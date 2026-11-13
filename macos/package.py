"""Portable Mac release: allowlisted code + public Desktop OAuth identity only."""
import argparse,hashlib,json,plistlib,shutil,struct,subprocess,sys,tempfile,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION='0.6.0-alpha.3'
MODULES=('__init__.py','automatic.py','core.py','sources.py','context.py','clients.py','setup.py','server.py','stdio.py','launcher.py','skills.py','runner.py','shared.py','actions.py','agent_memory.py','local_provider.py','near_provider.py','ironclaw_adapter.py','founder_demo.py','continuity.py')
ADAPTERS=('__init__.py','device_access.py','vault.py','model_defaults.py','google_connection.py','google_app.py','network.py')
UI=('index.html','ui.js','context.js','onboarding.js','workbench.js','ui.css','icon.svg','memory.html','memory.js','memory.css','near.js','near.css')

GUIDE='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Start with Airlock</title><style>body{font:17px/1.65 -apple-system,BlinkMacSystemFont,sans-serif;background:#0c1017;color:#edf2fa;max-width:740px;margin:60px auto;padding:24px}h1{font-size:42px;line-height:1.1}a{color:#a9ceff}li{margin:16px 0}small{color:#a2b0c3}</style><h1>Airlock.<br>Your context, connected.</h1><p>Open <b>Airlock.app</b>. You can move it to Applications first.</p><ol><li><b>Import memories & skills.</b> Paste an export, choose a file, or copy the transfer prompt into the AI that knows you.</li><li><b>Gmail is optional.</b> New Gmail sign-in is not configured in this public build. Continue with imported context; existing configured installations retain Gmail.</li><li><b>Connect your AI.</b> Choose Codex, Claude or Cursor. Restart that AI, then paste the test prompt from the setup screen.</li></ol><p>No Terminal, separate Python installation, Ollama or API key entry for the context flow. First open downloads the app runtime; keep an internet connection. Your AI account may require its own subscription.</p><h2>If macOS blocks the first open</h2><p>This beta is not Apple-notarized. Try opening it, then use <b>System Settings → Privacy & Security → Open Anyway</b> for this app. Only do this if you trust the sender. <a href="https://support.apple.com/102445">Apple’s instructions</a>.</p><h2>Shared memory</h2><p>Open Shared memory in the sidebar. Choose the sources each agent may read, review proposed memories and approve or reject them. Your existing AI generates the answers. Private task inference through Ollama or NEAR is optional and needs separate provider setup.</p><h2>Try local skills</h2><p>Open Skills &amp; actions. Add the personal briefing skill, allow its Python script to run, then enable local actions for your AI. Generated files stay in this panel. You can also enable shared notes so preferences carry between connected agents.</p><h2>What stays yours</h2><p>This download starts empty. Your memories, skills and Google tokens stay encrypted on your Mac. Relevant filtered facts go to your AI provider. Filtering can miss details; it is not guaranteed anonymity. You can inspect what was shared or disconnect an AI in the panel.</p><p>Keep the app open and your Mac awake while using it. Quitting stops its local service. Gmail is read-only; attachments are not read. New Gmail sign-in is not configured in this public build. Dot needs a separately configured private connection and is not part of the quick setup.</p><small>Airlock 0.6.0 alpha 3 · macOS 12 or later · Apple silicon and Intel launcher</small></html>'''

def entries(google_client=None):
    sys.path.insert(0,str(ROOT/'vendor'))
    from private_ai.google_app import read_client
    result={f'privacy_layer/{n}':(ROOT/'privacy_layer'/n).read_bytes() for n in MODULES}
    result.update({f'ui/{n}':(ROOT/'ui'/n).read_bytes() for n in UI})
    result.update({f'vendor/private_ai/{n}':(ROOT/'vendor/private_ai'/n).read_bytes() for n in ADAPTERS})
    if google_client:
        result['vendor/private_ai/google_client.json']=json.dumps({'installed':read_client(google_client)},indent=2).encode()
    result.update({f'builtin/prepare-local-brief/{p.relative_to(ROOT/"builtin/prepare-local-brief").as_posix()}':p.read_bytes() for p in (ROOT/'builtin/prepare-local-brief').rglob('*') if p.is_file()})
    result['requirements.lock']=(ROOT/'macos/requirements.lock').read_bytes()
    result['release.json']=json.dumps({'name':'Airlock','version':VERSION,'portable':True}).encode()
    return result

def build(destination,google_client=None,app_destination=None):
    files=entries(google_client)
    with tempfile.TemporaryDirectory(prefix='private-ai-portable-') as temp:
        root=Path(temp);app=root/'Airlock.app';contents=app/'Contents';resources=contents/'Resources'
        (contents/'MacOS').mkdir(parents=True);resources.mkdir()
        for name,value in files.items():
            target=resources/'payload'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
        shutil.copyfile(ROOT/'macos/bootstrap.sh',resources/'bootstrap.sh');(resources/'bootstrap.sh').chmod(0o755)
        iconset=root/'Airlock.iconset';iconbin=root/'render-icon'
        subprocess.run(['/usr/bin/swiftc','-module-cache-path',str(root/'module-cache'),str(ROOT/'macos/icon.swift'),'-o',str(iconbin)],check=True)
        subprocess.run([str(iconbin),str(iconset)],check=True)
        # PNG-backed ICNS avoids iconutil's WindowServer dependency on headless builders.
        chunks=[]
        for kind,name in ((b'ic07','icon_128x128'),(b'ic08','icon_256x256'),(b'ic09','icon_512x512'),(b'ic10','icon_512x512@2x')):
            png=(iconset/(name+'.png')).read_bytes()
            if not png.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Invalid rendered icon')
            chunks.append(kind+struct.pack('>I',len(png)+8)+png)
        data=b''.join(chunks);(resources/'Airlock.icns').write_bytes(b'icns'+struct.pack('>I',len(data)+8)+data)
        binary=contents/'MacOS/Airlock'
        subprocess.run(['/usr/bin/xcrun','clang','-fobjc-arc','-arch','arm64','-arch','x86_64','-mmacosx-version-min=12.0','-framework','Cocoa',str(ROOT/'macos/Portable.m'),'-o',str(binary)],check=True)
        info={'CFBundleIdentifier':'local.privateai.privacy-portable','CFBundleName':'Airlock','CFBundleDisplayName':'Airlock','CFBundleExecutable':'Airlock','CFBundleIconFile':'Airlock','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.6.0','CFBundleVersion':'63','NSHighResolutionCapable':True,'LSMinimumSystemVersion':'12.0','NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}
        (contents/'Info.plist').write_bytes(plistlib.dumps(info))
        subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(app)],check=True,capture_output=True)
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True)
        output=Path(destination);output.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            for f in sorted(app.rglob('*')):
                if f.is_file():
                    name='Airlock/'+f.relative_to(root).as_posix();item=zipfile.ZipInfo(name,(2026,11,10,0,0,0));item.create_system=3
                    executable=f==binary or f.name=='bootstrap.sh';item.external_attr=(0o100755 if executable else 0o100644)<<16
                    z.writestr(item,f.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
            z.writestr('Airlock/Read me.html',GUIDE)
        if app_destination:
            if Path(app_destination).exists():raise ValueError('Use a new app destination.')
            shutil.copytree(app,app_destination)
        report={'version':VERSION,'zip':str(output.resolve()),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'bytes':output.stat().st_size,'payload_files':len(files),'architectures':['arm64','x86_64'],'notarized':False,'personal_data_bundled':False}
        print(json.dumps(report))
        return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('destination',type=Path);p.add_argument('--google-client',type=Path);p.add_argument('--app-destination',type=Path);a=p.parse_args();build(a.destination,a.google_client,a.app_destination)
