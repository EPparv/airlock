"""Print only a disposable action's startup log to diagnose CI interpreter layouts."""
import base64
import io
from pathlib import Path
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from privacy_layer.skills import parse_package
from privacy_layer.runner import execute

archive=io.BytesIO()
with zipfile.ZipFile(archive,'w') as z:
    z.writestr('SKILL.md','---\nname: installation-check\ndescription: Fictional installation check\n---\nRun the test script.')
    z.writestr('scripts/main.py','print("synthetic action started")')
result=execute(parse_package(archive.getvalue()),'scripts/main.py',{})
print('Interpreter:',sys.executable,'base:',sys.base_prefix,'status:',result['status'])
for file in result['files']:
    if file['name']=='execution-log.txt':print(base64.b64decode(file['content']).decode(errors='replace'))
