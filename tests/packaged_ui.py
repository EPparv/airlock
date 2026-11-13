"""Exercise the actual final Mac app, its encrypted profile and installed bridge."""
import json,os,subprocess,time,tomllib
from pathlib import Path
from urllib.request import Request,urlopen
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT.parent/'outputs/privacy-portable'
profile=json.loads((OUT/'fresh-launch-local.json').read_text());base=Path(profile['data_dir']);home=Path(profile['profile_home']);app=OUT/'airlock-verified/Airlock.app'
def open_app():
 subprocess.run(['/usr/bin/open','-n','-a',str(app),'--args','--data-dir',str(base),'--profile-home',str(home)],check=True)
 for _ in range(160):
  try:
   launch=json.loads((base/'app/.private/launch.json').read_text());url=launch['url'].split('/?')[0]
   req=Request(url+'/api/dashboard',data=b'{}',headers={'Authorization':'Bearer '+launch['owner_token'],'Content-Type':'application/json'})
   with urlopen(req,timeout=.3) as response:return launch,json.load(response)
  except Exception:time.sleep(.15)
 raise RuntimeError('Packaged app did not become ready')
def call(entry,query):
 messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'release-check','version':'1'}}},{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'get_private_context','arguments':{'query':query}}}]
 r=subprocess.run([entry['command'],*entry['args']],input='\n'.join(json.dumps(m) for m in messages)+'\n',text=True,capture_output=True,timeout=30);assert r.returncode==0
 result=next(json.loads(line) for line in r.stdout.splitlines() if json.loads(line).get('id')==2)
 assert not result.get('error') and not result['result'].get('isError')
 return json.loads(result['result']['content'][0]['text'])

checks={}
try:
 launch,d=open_app();assert d['counts']=={'memories':0,'skills':0} and not d['connections'];checks['empty_packaged_profile']=True
 print('Final packaged app opened with an empty encrypted profile.',flush=True)
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True);page=browser.new_page(viewport={'width':1440,'height':1100});errors=[];page.on('pageerror',lambda e:errors.append(True))
  page.goto(launch['url']);expect(page.locator('#onboarding')).to_be_visible();expect(page.locator('#overviewContent')).to_be_hidden();page.screenshot(path=str(OUT/'packaged-setup-desktop.png'),full_page=True)
  page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.screenshot(path=str(OUT/'packaged-setup-phone.png'),full_page=True);page.set_viewport_size({'width':1440,'height':1100})
  page.locator('#setupImport').click();page.locator('#contextText').fill(json.dumps({'memories':['Fictional Cypress planning review is November 20. Phone: +1 415 555 0123.'],'skills':['For Cypress updates, lead with the next action and use two bullets.']}));page.locator('#previewContext').click();page.locator('#saveContext').click();expect(page.locator('#contextDone')).to_be_visible();page.locator('#contextDone [data-close]').click();expect(page.locator('#setupContextStatus')).to_contain_text('1 memories · 1 skills');checks['packaged_import_works']=True
  page.locator('#setupSkipGmail').click();page.locator('#setupAi').click();page.locator('[data-agent="codex"]').click();page.locator('#connectAgent').click();expect(page.locator('#setupDialog')).to_be_visible();page.locator('#setupDialog .primary').click();expect(page.locator('#setupProgress')).to_have_text('3 of 3 steps ready')
  entry=tomllib.loads((home/'.codex/config.toml').read_text())['mcp_servers']['airlock'];assert str(base) in entry['command'] and '--session-file' in entry['args'];checks['config_uses_installed_location']=True
  result=call(entry,'Cypress planning review updates');visible=json.dumps(result);assert 'November 20' in visible and 'two bullets' in visible and '415 555 0123' not in visible;checks['actual_packaged_mcp_filters_imported_context']=True
  page.locator('#setupCheckAgent').click();expect(page.locator('#setupAgentStatus')).to_contain_text('successfully used');page.locator('#finishSetup').click();expect(page.locator('#onboarding')).to_be_hidden();assert not errors;checks['packaged_ui_no_script_errors']=True;browser.close()
 subprocess.run(['/usr/bin/osascript','-e','tell application id "local.privateai.privacy-portable" to quit'],check=True)
 for _ in range(50):
  try:os.kill(launch['pid'],0)
  except ProcessLookupError:break
  time.sleep(.1)
 else:raise RuntimeError('App quit did not stop its server')
 checks['quitting_stops_local_service']=True
 second,d=open_app();assert second['pid']!=launch['pid'];assert d['counts']=={'memories':1,'skills':1};assert d['onboarding']['dismissed'];checks['encrypted_library_survives_quit_and_reopen']=True
 result=call(entry,'Cypress planning review updates');assert result['library_counts']=={'memories':1,'skills':1};checks['saved_agent_connection_survives_restart']=True
 report={'zip_sha256':__import__('hashlib').sha256((OUT/'Airlock_Mac_0.4.0.zip').read_bytes()).hexdigest(),'passed':all(checks.values()),'checks':checks,'architecture':'Apple silicon runtime; universal launcher inspected separately','gmail':'Skipped in this production-bundle test; OAuth is tested separately.','personal_data_used':False}
 (OUT/'packaged-app-check.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
finally:subprocess.run(['/usr/bin/osascript','-e','tell application id "local.privateai.privacy-portable" to quit'],capture_output=True)
