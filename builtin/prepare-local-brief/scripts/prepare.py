import json,os
from pathlib import Path
inputs=json.loads(Path(os.environ['AIRLOCK_INPUT']).read_text())
template=Path('assets/brief-template.md').read_text()
context='\n\n'.join('### '+x['kind'].title()+'\n'+x['text'] for x in inputs['context']) or 'No matching saved context.'
emails='\n\n'.join('### '+str(x.get('date','Undated'))+'\n'+x['text'] for x in inputs['emails']) or 'No eligible email selected.'
Path(os.environ['AIRLOCK_OUTPUT'],'personal-brief.md').write_text(template.replace('{context}',context).replace('{emails}',emails))
