"""Real browser smoke test against an isolated fixture, never personal data."""
import json,os,socket,subprocess,tempfile,time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT.parent/'outputs/privacy-layer/ui';OUT.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='privacy-layer-ui-') as temp:
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    env=dict(os.environ,PYTHONPATH=str(ROOT))
    service=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'tests/ui_fixture.py'),temp,str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        for _ in range(80):
            try:
                with urlopen(f'http://127.0.0.1:{port}/',timeout=1) as r:break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('Fixture did not start')
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",chromium_sandbox=True)
            page=browser.new_page(viewport={'width':1440,'height':1050},device_scale_factor=1)
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{port}/#fictional-ui-owner')
            expect(page.locator('#memoryCount')).to_have_text('168')
            assert page.locator('#skillCount').inner_text()=='39'
            assert 'fictional-ui-owner' not in page.url
            page.screenshot(path=str(OUT/'overview-desktop.png'),full_page=True)
            page.locator('#browseSkills').click();page.locator('#libraryDialog').wait_for(state='visible')
            assert page.locator('.library-item').count()==39
            page.locator('#librarySearch').fill('skill 12');assert page.locator('.library-item').count()==1
            page.locator('[data-close="libraryDialog"]').click()
            page.locator('[data-page="privacy"]').click()
            page.locator('#privatePhrases').fill('Fictional protected phrase')
            page.locator('#savePrivatePhrases').click();expect(page.locator('#notice')).to_contain_text('Saved.')
            page.locator('#showDisclosures').click();page.locator('.receipt').first.wait_for()
            page.locator('.receipt summary').first.click()
            assert 'Hyderabad' in page.locator('.receipt pre').first.inner_text()
            page.locator('[data-page="agents"]').click()
            page.locator('#page-agents [data-add]').click();page.locator('[data-agent="codex"]').click()
            page.locator('#connectAgent').click();page.locator('#setupDialog').wait_for(state='visible')
            assert page.locator('#setupTitle').inner_text()=='Settings saved'
            config=page.locator('#exportConfig').inner_text();assert 'pal_' not in config
            saved=Path(temp)/'home/.codex/config.toml';assert saved.exists()
            page.locator('#setupDialog .primary').click()
            row=page.locator('#connections .connection').filter(has_text='Codex');row.get_by_role('button',name='Disconnect',exact=True).click()
            expect(page.locator('#connections .connection').filter(has_text='Codex')).to_have_count(0)
            page.locator('#page-agents [data-add]').click();page.locator('[data-agent="mcp"]').click();page.locator('#connectAgent').click();page.locator('#setupDialog').wait_for(state='visible')
            assert page.locator('#setupTitle').inner_text()=='Connection created'
            assert page.locator('#configDetails').get_attribute('open') is not None
            page.locator('#setupDialog .primary').click()
            page.screenshot(path=str(OUT/'agents-desktop.png'),full_page=True)
            page.locator('[data-page="privacy"]').click();page.locator('#exactReview summary').click();page.locator('#search').fill('interview');page.locator('#sources button').first.wait_for();page.locator('#sources button').first.click()
            page.locator('#purpose').fill('Fictional interview review');page.locator('#consent').check();page.locator('#create').click();page.locator('#created').wait_for(state='visible')
            assert page.locator('#create').is_disabled()
            page.locator('[data-page="overview"]').click();page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(OUT/'overview-phone.png'),full_page=True)
            page.locator('#page-overview [data-add]').click();page.locator('#connectDialog').wait_for(state='visible')
            assert page.locator('#connectDialog').bounding_box()['width']<=390
            page.screenshot(path=str(OUT/'connect-phone.png'),full_page=True)
            assert not errors,errors
            browser.close()
        print(json.dumps({'ui_checks':'passed','desktop':'1440px','mobile':'390px','browser_errors':errors,'isolated_data':True,'native_config_created':True,'disconnect_verified':True}))
    finally:
        service.terminate();service.wait(timeout=10)
