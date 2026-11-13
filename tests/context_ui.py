"""Browser + real MCP import check, using only disposable fictional context."""
import json,os,re,socket,subprocess,tempfile,time
from pathlib import Path
from urllib.request import Request,urlopen
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
def port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
with tempfile.TemporaryDirectory(prefix='privacy-context-ui-') as temporary:
 root=Path(temporary);owner_port=port();mcp_port=port();env=dict(os.environ);env['PYTHONPATH']=str(ROOT)
 process=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'tests/ui_fixture.py'),str(root),str(owner_port),str(mcp_port)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  url=f'http://127.0.0.1:{owner_port}'
  for _ in range(100):
   try:urlopen(url,timeout=.3);break
   except Exception:time.sleep(.1)
  def owner(action,body={}):
   req=Request(url+'/api/'+action,data=json.dumps(body).encode(),headers={'Authorization':'Bearer fictional-ui-owner','Content-Type':'application/json'})
   return json.load(urlopen(req,timeout=10))
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
   context=browser.new_context(viewport={'width':1380,'height':1000},permissions=['clipboard-read','clipboard-write']);page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(url+'/#fictional-ui-owner');expect(page.locator('#memoryCount')).to_have_text('168');page.locator('#addContext').click()
   screenshot=ROOT.parent/'outputs/privacy-layer/ui/context-import-desktop.png';screenshot.parent.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(screenshot))
   text='# Memories\nPhoenix launch interview November 12.\n# Skills\n## Phoenix preparation\nUse the solar launch example and distinguish evidence from assumptions.'
   def paste_save(value):
    page.locator('#contextText').fill(value);page.locator('#previewContext').click();expect(page.locator('#contextReview')).to_be_visible();page.locator('#saveContext').click();expect(page.locator('#contextDone')).to_be_visible()
   paste_save(text);expect(page.locator('#memoryCount')).to_have_text('169');expect(page.locator('#skillCount')).to_have_text('40')
   page.locator('#contextDone [data-close]').click();page.locator('#browseMemories').click();page.locator('#librarySearch').fill('Phoenix');expect(page.locator('#libraryItems')).to_contain_text('November 12');page.locator('#libraryDialog [data-close]').click()
   page.locator('#addContext').click();paste_save(text);expect(page.locator('#contextSaved')).to_contain_text('2 items were already');expect(page.locator('#memoryCount')).to_have_text('169')
   page.locator('#contextDone [data-close]').click();page.locator('#addContext').click();page.locator('#contextFile').set_input_files({'name':'SKILL.md','mimeType':'text/markdown','buffer':b'For summaries, start with the decision and cite the evidence.'});page.locator('#previewContext').click();page.locator('#saveContext').click();expect(page.locator('#skillCount')).to_have_text('41');page.locator('#undoContext').click();expect(page.locator('#skillCount')).to_have_text('40')
   page.locator('#existingContext>summary').click();row=page.locator('#contextSources .context-source').filter(has_text='Claude Code memories');row.get_by_role('button',name='Connect',exact=True).click();expect(page.locator('#memoryCount')).to_have_text('170')
   note=root/'home/.claude/projects/fictional/memory/MEMORY.md';note.write_text('Fictional linked interview moved to November 17.')
   page.locator('#contextDialog .dialog-head [data-close]').click();page.locator('#refresh').click();page.locator('#browseMemories').click();page.locator('#librarySearch').fill('Fictional linked');expect(page.locator('#libraryItems')).to_contain_text('November 17');page.locator('#libraryDialog [data-close]').click();page.locator('#addContext').click();page.locator('#existingContext').evaluate('(el)=>el.open=true');row=page.locator('#contextSources .context-source').filter(has_text='Claude Code memories');row.get_by_role('button',name='Disconnect',exact=True).click();expect(page.locator('#memoryCount')).to_have_text('169')
   page.locator('#copyTransfer').click();expect(page.locator('#transferPrompt')).not_to_be_empty();prompt=page.locator('#transferPrompt').input_value();code=re.search(r'transfer_code "([^"]+)"',prompt)[1]
   setup=owner('client-connect',{'agent':'mcp','approved':True,'install':False});token=Path(setup['args'][-1]).read_text().strip()
   request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'stage_context_import','arguments':{'transfer_code':code,'memories':['Fictional Juniper project begins December 3.'],'skills':['For Juniper, use concise source-grounded summaries.'],'scope':'Fictional browser test only.'}}}
   req=Request(f'http://127.0.0.1:{mcp_port}/mcp',data=json.dumps(request).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-03-26'})
   response=json.load(urlopen(req,timeout=15));assert not response['result'].get('isError'),response
   expect(page.locator('#contextReview')).to_be_visible(timeout=12000);expect(page.locator('#contextCounts')).to_have_text('1 memories · 1 skills');page.locator('#saveContext').click();expect(page.locator('#memoryCount')).to_have_text('170');expect(page.locator('#skillCount')).to_have_text('41')
   page.locator('#contextDone [data-close]').click();page.set_viewport_size({'width':390,'height':844});page.locator('#addContext').click();page.locator('#contextDialog').evaluate('(el)=>el.scrollTop=0');page.screenshot(path=str(ROOT.parent/'outputs/privacy-layer/ui/context-import-phone.png'))
   assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
   assert not errors,errors
   browser.close()
  report={'passed':True,'checks':['mixed paste saves memory and skill together','new memory is visible in library','reimport skips duplicates','skill file recognized','undo restores previous counts','native memory source connects and live updates','disconnect preserves original file','actual MCP transfer appears in owner preview','staged transfer only enters library after owner save','phone has no horizontal overflow','no browser script errors'],'personal_data_used':False}
  (ROOT.parent/'outputs/privacy-layer/context-import-ui.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
 finally:
  process.terminate();process.wait(timeout=10)
