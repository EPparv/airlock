"""Fresh-user browser setup and a real Codex answer using fictional sources."""
import html,json,os,re,shutil,socket,subprocess,tempfile,time,tomllib
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,urlencode
from urllib.request import urlopen
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT.parent/'outputs/privacy-portable';OUT.mkdir(parents=True,exist_ok=True)
def port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

with tempfile.TemporaryDirectory(prefix='privacy-new-user-test-') as temp:
 root=Path(temp);owner_port=port();mcp_port=port();env=dict(os.environ,PYTHONPATH=str(ROOT))
 service=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'tests/onboarding_fixture.py'),str(root),str(owner_port),str(mcp_port)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 try:
  for _ in range(80):
   try:urlopen(f'http://127.0.0.1:{owner_port}',timeout=.3);break
   except Exception:time.sleep(.1)
  else:raise RuntimeError('Fresh setup fixture did not start')
  checks={}
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
   context=browser.new_context(viewport={'width':1440,'height':1100},permissions=['clipboard-read','clipboard-write']);page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   def google(route):
    params=parse_qs(urlsplit(route.request.url).query)
    assert params['client_id']==['fictional.apps.googleusercontent.com'] and params['code_challenge_method']==['S256']
    callback=params['redirect_uri'][0]+'?'+urlencode({'code':'fictional-code','state':params['state'][0]})
    route.fulfill(status=200,content_type='text/html',body='<h1>Simulated Google consent — test only</h1><a href="'+html.escape(callback,quote=True)+'">Approve read-only Gmail</a>')
   context.route('https://accounts.google.com/o/oauth2/v2/auth**',google)
   page.goto(f'http://127.0.0.1:{owner_port}/#fictional-setup-owner');expect(page.locator('#setupProgress')).to_have_text('0 of 3 steps ready');expect(page.locator('#memoryCount')).to_have_text('0')
   page.screenshot(path=str(OUT/'fresh-setup-desktop.png'),full_page=True);checks['empty_profile_shows_guided_setup']=True
   page.locator('#setupImport').click();page.locator('#copyTransfer').click();expect(page.locator('#transferPrompt')).not_to_be_empty()
   exported={'memories':['I lead design for the fictional Aurora launch. The review is November 17, 2026.','My current priority is the onboarding prototype. API key: sk-fictional_PRIVATE_CANARY_123456789'],'skills':['For Aurora preparation, use three short numbered steps. Separate confirmed facts from suggestions; do not invent completion.'],'scope':'Fictional setup test only.'}
   page.locator('#contextText').fill(json.dumps(exported));page.locator('#previewContext').click();expect(page.locator('#contextCounts')).to_have_text('2 memories · 1 skills');page.locator('#saveContext').click();expect(page.locator('#memoryCount')).to_have_text('2');expect(page.locator('#skillCount')).to_have_text('1');page.locator('#contextDone [data-close]').click();checks['combined_import_saved']=True
   with page.expect_popup() as popped:page.locator('#setupGmail').click()
   popup=popped.value;popup.get_by_role('link',name='Approve read-only Gmail').click();expect(popup.locator('body')).to_contain_text('Google is connected');expect(page.locator('#setupGmailStatus')).to_contain_text('connected',timeout=12000);popup.close();checks['oauth_popup_pkce_callback_and_auto_return']=True
   page.locator('#setupAi').click();page.locator('[data-agent="codex"]').click();expect(page.locator('#newLifetime')).to_have_value('604800');page.locator('#connectAgent').click();expect(page.locator('#setupDialog')).to_be_visible();page.locator('#setupDialog .primary').click();expect(page.locator('#setupProgress')).to_have_text('3 of 3 steps ready');expect(page.locator('#setupAgentStatus')).to_contain_text('Settings saved')
   config=tomllib.loads((root/'home/.codex/config.toml').read_text());entry=config['mcp_servers']['airlock'];assert '--session-file' in entry['args'];checks['native_codex_config_saved_without_key_entry']=True
   page.locator('#setupCopyQuestion').click();assert 'Airlock' in page.evaluate('navigator.clipboard.readText()');page.screenshot(path=str(OUT/'setup-ready-desktop.png'),full_page=True)
   page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.screenshot(path=str(OUT/'fresh-setup-phone.png'),full_page=True);checks['mobile_layout_no_horizontal_overflow']=True
   print('Guided import, simulated Google sign-in and native Codex setup passed.',flush=True)
   real_config=tomllib.loads((Path.home()/'.codex/config.toml').read_text());args=[shutil.which('codex'),'exec','--ephemeral','--ignore-user-config','--skip-git-repo-check','--sandbox','read-only','--json','--color','never','-C',str(root/'home')]
   for key in ('model',):
    if real_config.get(key):args+=['-c',key+'='+json.dumps(real_config[key])]
   for key in ('apps','plugins','remote_plugin','plugin_discovery_prefetch','memories','skill_search','skill_mcp_dependency_install','shell_tool','unified_exec','shell_snapshot','code_mode','multi_agent','computer_use','browser_use','browser_use_external','in_app_browser','image_generation','view_image','hooks','workspace_dependencies'):
    args+=['-c',f'features.{key}=false']
   args+=['-c','features.skip_host_skill_discovery=true','-c','web_search="disabled"']
   for key in ('command','args'):args+=['-c','mcp_servers.airlock.'+key+'='+json.dumps(entry[key])]
   args+=['-c','model_reasoning_effort="medium"']
   args+=['-'];prompt='Use only Airlock. Check privacy_status, retrieve my relevant memories and skills, search Gmail and read a relevant message. What should I prepare for my upcoming project review? Apply my saved answer format, cite actual evidence, distinguish confirmed facts from suggestions, and do not invent completion. Use at most 6 calls. If you see any credential value, report only its category; never repeat it. Do not read files or use other sources.'
   try:result=subprocess.run(args,input=prompt,text=True,capture_output=True,timeout=240,env=env)
   except subprocess.TimeoutExpired as error:
    (OUT/'fresh-codex-timeout.txt').write_bytes((error.stdout or b'')+(error.stderr or b''))
    raise RuntimeError('Native Codex timed out; fictional-only diagnostic saved.') from None
   events=[]
   for line in result.stdout.splitlines():
    try:events.append(json.loads(line))
    except ValueError:pass
   calls=[e['item'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='mcp_tool_call']
   answers=[e['item']['text'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message'];answer=answers[-1] if answers else ''
   released=json.dumps([i.get('result',{}) for i in calls])+answer
   checks.update(native_codex_completed=result.returncode==0 and any(e['type']=='turn.completed' for e in events),all_sources_used={'privacy_status','get_private_context','search_gmail','read_gmail'}<={i['tool'] for i in calls},only_privacy_connection_used=bool(calls) and all(i['server']=='airlock' for i in calls),personalized_fictional_answer='Aurora' in answer and 'November 17' in answer and 'onboarding prototype' in answer,private_canary_filtered='sk-fictional_PRIVATE_CANARY_123456789' not in released and 'QX7654' not in released,three_numbered_steps=all(re.search(r'(?m)^'+str(i)+r'[.)]',answer) for i in range(1,4)))
   page.locator('#setupCheckAgent').click();expect(page.locator('#setupAgentStatus')).to_contain_text('successfully used');checks['panel_confirms_real_context_use']=True
   page.locator('#finishSetup').click();expect(page.locator('#onboarding')).to_be_hidden();page.reload();expect(page.locator('#memoryCount')).to_have_text('2');expect(page.locator('#onboarding')).to_be_hidden();checks['setup_and_import_survive_reload']=True
   checks['no_browser_script_errors']=not errors;browser.close()
  report={'passed':all(checks.values()),'checks':checks,'model':real_config.get('model'),'native_tool_calls':len(calls),'gmail_test':'Simulated Google provider with real PKCE callback, encrypted token storage and Gmail/MCP code paths. No real Google account used.','personal_data_used':False}
  (OUT/'fresh-setup-check.json').write_text(json.dumps(report,indent=2)+'\n');(OUT/'fictional-native-answer.txt').write_text(answer+'\n');print(json.dumps(report),flush=True)
  assert report['passed'],report
 finally:service.terminate();service.wait(timeout=10)
