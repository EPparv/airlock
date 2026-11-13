"""Real browser import/permission/output test, fictional data only."""
import base64,json,os,socket,subprocess,tempfile,time
from pathlib import Path
from urllib.request import Request,urlopen
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT.parent/'outputs/privacy-layer/ui';OUT.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='airlock-workbench-ui-') as temp:
 with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
 service=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'tests/ui_fixture.py'),temp,str(port)],env=dict(os.environ,PYTHONPATH=str(ROOT)),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 try:
  for _ in range(80):
   try:urlopen(f'http://127.0.0.1:{port}',timeout=.3);break
   except Exception:time.sleep(.1)
  def api(action,data={}):
   return json.load(urlopen(Request(f'http://127.0.0.1:{port}/api/'+action,data=json.dumps(data).encode(),headers={'Authorization':'Bearer fictional-ui-owner','Content-Type':'application/json'})))
  with sync_playwright() as p:
   b=p.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');page=b.new_page(viewport={'width':1440,'height':1050});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{port}/#fictional-ui-owner');expect(page.locator('#memoryCount')).to_have_text('168')
   page.locator('[data-page=workbench]').click();expect(page.locator('#page-workbench')).to_be_visible()
   page.locator('#addBriefSkill').click();expect(page.locator('#skillTitle')).to_have_text('prepare-local-brief');expect(page.locator('#skillExecution')).not_to_be_checked();page.locator('#skillExecution').check();page.locator('#installSkill').click();expect(page.locator('#packageList')).to_contain_text('prepare-local-brief');expect(page.locator('#skillCount')).to_have_text('40')
   assert len(api('workbench')['packages'])==1
   page.locator('#actionPermissions input').first.check();assert any(c.get('capabilities',{}).get('skill_execution') for c in api('state')['connections'])
   page.locator('#actionPermissions input').nth(1).check();assert any(c.get('capabilities',{}).get('context_updates') for c in api('state')['connections'])
   page.screenshot(path=str(OUT/'workbench-desktop.png'),full_page=True)
   page.reload();page.locator('[data-page=workbench]').click();expect(page.locator('#packageList')).to_contain_text('prepare-local-brief');expect(page.locator('#actionPermissions input').first).to_be_checked()
   page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(OUT/'workbench-phone.png'),full_page=True);assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),page.evaluate('[...document.querySelectorAll("body *")].filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,id:e.id,cls:e.className,w:e.getBoundingClientRect().width})).slice(0,20)')
   page.locator('#packageList').get_by_role('button',name='Pause execution').click();expect(page.locator('#packageList')).to_contain_text('Enable execution')
   assert not api('workbench')['packages'][0]['enabled'];assert not errors,errors;b.close()
  print(json.dumps({'skill_import':True,'execution_opt_in':True,'permissions_persist':True,'pause':True,'desktop_mobile':True,'browser_errors':errors,'fictional_data_only':True}))
 finally:service.terminate();service.wait(timeout=10)
