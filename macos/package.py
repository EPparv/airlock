"""Portable Mac release: allowlisted code + public Desktop OAuth identity only."""
import argparse,json,plistlib,shutil,struct,subprocess,sys,tempfile,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from privacy_layer.version import VERSION, BUILD
from macos.distribution import sign_and_staple, verify_archive
MODULES=('__init__.py','automatic.py','privacy_engine.py','core.py','sources.py','context.py','clients.py','agent_launch.py','setup.py','server.py','stdio.py','launcher.py','skills.py','runner.py','shared.py','actions.py','workspace.py','device_apps.py','device_apps.js','data_view.py','agent_memory.py','local_provider.py','near_provider.py','near_setup.py','demo_server.py','ironclaw_adapter.py','founder_demo.py','continuity.py','safe_test.py','updater.py','version.py','semantic.py','semantic.js','prompt_gateway.py','agent_handoffs.py','remote_clients.py','remote_tunnel.py','live_data.py','phone_companion.py','quick_tunnel.py','quick_connect.py','provider_checks.py')
ADAPTERS=('__init__.py','device_access.py','vault.py','model_defaults.py','google_connection.py','google_app.py','network.py')
UI=('index.html','ui.js','context.js','onboarding.js','workbench.js','ui.css','icon.svg','memory.html','memory.js','memory.css','near.js','near.css','near-setup.html','near-setup.js','safe-test.html','safe-test.js','safe-test.css','workspace.html','workspace.css','workspace-transport.js','workspace.js','workspace-agents.js','workspace-context.js','workspace-privacy.js','workspace-actions.js','workspace-prompt.js','workspace-handoffs.js','workspace-remote.js','workspace-phone.js','workspace-provider-checks.js','phone.html','phone.css','phone.js')

GUIDE='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Airlock for Mac</title><style>body{font:16px/1.6 -apple-system,BlinkMacSystemFont,sans-serif;color:#232520;background:#fafaf8;max-width:580px;margin:9vh auto;padding:24px}h1{letter-spacing:-.05em}li{margin:14px 0}a{color:inherit}</style><h1>Airlock</h1><p>Move Airlock.app to Applications and open it. The first launch needs an internet connection to install the runtime.</p><ul><li><b>Connect agent</b> opens the selected agent or its setup page. Supported clients open with a privacy check ready. New connections share no memories.</li><li><b>Context &amp; memory</b> contains your memories, skills, imports and proposed changes.</li><li><b>Privacy &amp; connections</b> contains app permissions, redaction settings, approvals, receipts and private inference.</li></ul><p>Your personal vault starts locked. Airlock asks before opening it or resuming agent access. For a fictional test, open Privacy &amp; connections → Privacy checks.</p><p>If macOS asks for approval on first open, use System Settings → Privacy &amp; Security → Open Anyway for this app if you trust the download. <a href="https://support.apple.com/102445">Apple’s instructions</a>.</p><p>Updates are available in App settings and in the Airlock menu.</p><small>Airlock 0.11.7 · macOS 12 or later</small></html>'''


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
    result['requirements-near.txt']=(ROOT/'requirements-near.txt').read_bytes()
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    result['release.json']=json.dumps({'name':'Airlock','version':VERSION,'build':BUILD,'commit':commit,'portable':True}).encode()
    return result

def build(destination,google_client=None,app_destination=None,*,signing=None,report_path=None):
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
        subprocess.run(['/usr/bin/xcrun','clang','-fobjc-arc','-arch','arm64','-arch','x86_64','-mmacosx-version-min=12.0','-framework','Cocoa','-framework','WebKit','-framework','CoreImage',str(ROOT/'macos/Portable.m'),'-o',str(binary)],check=True)
        info={'CFBundleIdentifier':'local.privateai.privacy-portable','CFBundleName':'Airlock','CFBundleDisplayName':'Airlock','CFBundleExecutable':'Airlock','CFBundleIconFile':'Airlock','CFBundlePackageType':'APPL','CFBundleShortVersionString':VERSION.split('-')[0],'CFBundleVersion':str(BUILD),'NSAppleEventsUsageDescription':'Airlock accesses Mail or Calendar when you select a source or approve a prepared action.','NSHighResolutionCapable':True,'LSMinimumSystemVersion':'12.0','NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}
        (contents/'Info.plist').write_bytes(plistlib.dumps(info))
        apple = None
        if signing:
            apple = sign_and_staple(app,root,**signing)
        else:
            subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(app)],check=True,capture_output=True)
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True)
        output=Path(destination);output.parent.mkdir(parents=True,exist_ok=True)
        staged=root/'distribution.zip'
        with zipfile.ZipFile(staged,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            for f in sorted(app.rglob('*')):
                if f.is_file():
                    name='Airlock/'+f.relative_to(root).as_posix();item=zipfile.ZipInfo(name,(2026,11,10,0,0,0));item.create_system=3
                    executable=f==binary or f.name=='bootstrap.sh';item.external_attr=(0o100755 if executable else 0o100644)<<16
                    z.writestr(item,f.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
            guide = GUIDE
            if apple:
                start = guide.index('<p>If macOS asks for approval')
                end = guide.index('</p>', start) + 4
                guide = guide[:start] + '<p>This download is Developer ID signed and Apple-notarized.</p>' + guide[end:]
            z.writestr('Airlock/Read me.html',guide)
        verified = verify_archive(staged, apple['team_id'] if apple else None)
        # Expose the distributable only after testing the repacked, extracted app.
        with tempfile.NamedTemporaryFile(dir=output.parent,prefix='.airlock-zip-',delete=False) as temp_output:
            try:
                with staged.open('rb') as src: shutil.copyfileobj(src, temp_output)
                temp_output.close()
                Path(temp_output.name).replace(output)
            finally:
                Path(temp_output.name).unlink(missing_ok=True)
        if app_destination:
            if Path(app_destination).exists():raise ValueError('Use a new app destination.')
            shutil.copytree(app,app_destination)
        report={**verified,'zip':str(output.resolve()),'bytes':output.stat().st_size,'payload_files':len(files),'architectures':['arm64','x86_64'],'notarized':bool(apple),'personal_data_bundled':False}
        if apple: report['apple'] = apple
        if report_path:
            Path(report_path).write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))
        return report

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('destination',type=Path)
    p.add_argument('--google-client',type=Path)
    p.add_argument('--app-destination',type=Path)
    p.add_argument('--report',type=Path)
    p.add_argument('--developer-id',help='Developer ID Application signing identity')
    p.add_argument('--apple-team',help='Apple Developer team identifier')
    p.add_argument('--notary-profile',help='notarytool credentials stored in the login keychain')
    a=p.parse_args()
    values=(a.developer_id,a.apple_team,a.notary_profile)
    if any(values) and not all(values): p.error('Provide developer-id, apple-team and notary-profile together.')
    signing={'identity':a.developer_id,'team':a.apple_team,'auth':['--keychain-profile',a.notary_profile]} if all(values) else None
    build(a.destination,a.google_client,a.app_destination,signing=signing,report_path=a.report)
