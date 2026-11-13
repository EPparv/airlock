"""Final portable-bundle check with a fresh fictional profile."""
import base64,json,os,signal,subprocess,tempfile,time,tomllib,hashlib
from pathlib import Path
from urllib.request import Request,urlopen
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT.parent/'outputs/privacy-portable';APP=OUT/'airlock-0.5-final/Airlock.app'
with tempfile.TemporaryDirectory(prefix='airlock-final-05-') as temp:
 base=Path(temp)/'data';home=Path(temp)/'home';home.mkdir();launch=None;app_process=None
 def open_app():
  global app_process
  app_process=subprocess.Popen([str(APP/'Contents/MacOS/Airlock'),'--data-dir',str(base),'--profile-home',str(home)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  for _ in range(2400):
   try:
    r=json.loads((base/'app/.private/launch.json').read_text())
    req=Request(r['url'].split('/?')[0]+'/api/dashboard',data=b'{}',headers={'Authorization':'Bearer '+r['owner_token'],'Content-Type':'application/json'})
    with urlopen(req,timeout=.3) as response:return r,json.load(response)
   except Exception:time.sleep(.1)
  raise RuntimeError('Fresh packaged app could not start')
 def api(action,data={}):
  req=Request(launch['url'].split('/?')[0]+'/api/'+action,data=json.dumps(data).encode(),headers={'Authorization':'Bearer '+launch['owner_token'],'Content-Type':'application/json'})
  return json.load(urlopen(req,timeout=30))
 def call(entry,tool,args={}):
  messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'airlock-package-check','version':'1'}}},{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':tool,'arguments':args}}]
  r=subprocess.run([entry['command'],*entry['args']],input='\n'.join(json.dumps(m) for m in messages)+'\n',text=True,capture_output=True,timeout=45)
  parsed=[json.loads(line) for line in r.stdout.splitlines()];result=next(x for x in parsed if x.get('id')==2)
  assert not result.get('error')
  data=json.loads(result['result']['content'][0]['text']);assert 'error' not in data,data;return data
 try:
  launch,d=open_app();assert d['counts']=={'memories':0,'skills':0};print('Fresh portable app started with no personal data.',flush=True)
  checks={'empty_profile':True}
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True);page=browser.new_page(viewport={'width':1440,'height':1050});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(launch['url']);page.locator('#setupImport').click();page.locator('#contextText').fill(json.dumps({'memories':['Fictional Cypress planning review is November 20. Phone: +1 415 555 0123.'],'skills':['For Cypress updates, use two concise bullets and flag missing evidence.']}));page.locator('#previewContext').click();page.locator('#saveContext').click();expect(page.locator('#contextDone')).to_be_visible();page.locator('#contextDone [data-close]').click()
   page.locator('#setupSkipGmail').click();page.locator('#setupAi').click();page.locator('[data-agent=codex]').click();page.locator('#connectAgent').click();expect(page.locator('#setupDialog')).to_be_visible();page.locator('#setupDialog .primary').click()
   entry=tomllib.loads((home/'.codex/config.toml').read_text())['mcp_servers']['airlock'];result=call(entry,'get_private_context',{'query':'Cypress review style'});assert 'November 20' in str(result) and '415 555 0123' not in str(result);checks['packaged_import_native_retrieval_and_filter']=True
   page.locator('[data-page=workbench]').click();page.locator('#addBriefSkill').click();page.locator('#skillExecution').check();page.locator('#installSkill').click();expect(page.locator('#packageList')).to_contain_text('prepare-local-brief');page.locator('#actionPermissions input').first.check();page.locator('#actionPermissions input').nth(1).check()
   skills=call(entry,'list_local_skills',{'query':'brief'});key=skills['skills'][0]['skill_id'];resources=call(entry,'read_local_skill',{'skill_id':key});script=next(x['resource'] for x in resources['resources'] if x['type']=='script')
   r=call(entry,'run_local_skill',{'skill_id':key,'script':script,'topic':'Cypress review style','gmail_query':''});assert r['status']=='completed' and '415 555 0123' not in json.dumps(r);checks['packaged_python_action_and_confinement']=True
   page.locator('#refreshWorkbench').click();expect(page.locator('#localArtifacts')).to_contain_text('personal-brief.md')
   with page.expect_download() as dl:page.locator('#localArtifacts').get_by_role('button',name='personal-brief.md').click()
   download=dl.value;local=Path(download.path()).read_text();assert 'Cypress' in local and '415 555 0123' in local;checks['owner_only_download_keeps_raw_test_detail_local']=True
   added=call(entry,'update_shared_context',{'operation':'add','kind':'skills','text':'Fictional Cypress demo format is two steps.'});assert added['changed']
   reread=call(entry,'get_private_context',{'query':'Cypress demo format'});assert any(x.get('shared_reference')==added['reference'] for x in reread['items']);checks['shared_notes_available_on_next_request']=True
   page.locator('#refreshWorkbench').click();expect(page.locator('#sharedNotes')).to_contain_text('Cypress demo');page.locator('#sharedNotes').get_by_role('button',name='Undo change').click();expect(page.locator('#sharedNotes')).not_to_contain_text('Cypress demo');checks['owner_undo_works']=True
   page.screenshot(path=str(OUT/'workbench-packaged-desktop.png'),full_page=True);assert not errors;checks['no_browser_errors']=True;browser.close()
  # Stop only the two processes created by this test, not any personal app.
  os.kill(launch['pid'],signal.SIGTERM);app_process.terminate();app_process.wait(timeout=10);time.sleep(.5)
  second,d=open_app();assert second['pid']!=launch['pid'] and d['counts']=={'memories':1,'skills':2};launch=second
  assert call(entry,'list_local_skills',{'query':''})['skills'][0]['executable'];checks['restart_preserves_library_packages_and_permissions']=True
  report={'version':'0.5.0','zip_sha256':hashlib.sha256((OUT/'Airlock_Mac_0.5.0.zip').read_bytes()).hexdigest(),'passed':all(checks.values()),'checks':checks,'personal_data_used':False,'runtime':'Apple silicon; launcher includes Intel'}
  (OUT/'workbench-packaged-check.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
 finally:
  if launch:
   try:os.kill(launch['pid'],signal.SIGTERM)
   except ProcessLookupError:pass
  if app_process and app_process.poll() is None:app_process.terminate();app_process.wait(timeout=10)
  # Remove only this disposable profile's Keychain entry, whose service name
  # depends on the exact test app path; preserve all real app keys.
  if (base/'app').exists():
   import sys
   sys.path.insert(0,str(ROOT.parent/'Private_AI'))
   from private_ai.device_access import MacKeychain
   # LocalSources uses the connections.enc path for a fresh portable profile.
   MacKeychain(base/'app/.private/connections.enc').delete()
