"""Build the personal Mac launcher. No credentials or private library bundled."""
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'dist/Airlock.app'
contents=APP/'Contents'
for name in ('MacOS','Resources'):(contents/name).mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='private-ai-icon-') as temp:
    iconset=Path(temp)/'Airlock.iconset'
    iconbin=Path(temp)/'render-icon'
    subprocess.run(['/usr/bin/swiftc','-module-cache-path',str(ROOT/'dist/.module-cache'),str(ROOT/'macos/icon.swift'),'-o',str(iconbin)],check=True)
    subprocess.run([str(iconbin),str(iconset)],check=True)
    subprocess.run(['/usr/bin/iconutil','-c','icns',str(iconset),'-o',str(contents/'Resources/Airlock.icns')],check=True)
subprocess.run(['/usr/bin/swiftc','-module-cache-path',str(ROOT/'dist/.module-cache'),str(ROOT/'macos/main.swift'),'-o',str(contents/'MacOS/Airlock')],check=True)
info={'CFBundleName':'Airlock','CFBundleDisplayName':'Airlock','CFBundleIdentifier':'local.privateai.privacy-control','CFBundleExecutable':'Airlock','CFBundleIconFile':'Airlock','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.4.0','CFBundleVersion':'4','NSHighResolutionCapable':True,'LSMinimumSystemVersion':'13.0'}
(contents/'Info.plist').write_bytes(plistlib.dumps(info))
(contents/'Resources/workspace.json').write_text(json.dumps({'path':str(ROOT)}))
subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-',str(APP)],check=True)
print('Built Airlock.app')
