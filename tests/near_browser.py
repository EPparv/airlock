"""Real browser rehearsal, screenshots and backup video on a normal local runtime.

Uses only the isolated demo service. Defaults to real Ollama generation;
--mode rehearsal explicitly selects the scripted backup. Neither verifies NEAR.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Record the real local demo or the explicitly scripted backup.')
parser.add_argument('--mode',choices=['local','rehearsal'],default='local')
args=parser.parse_args()
OUT=ROOT/'artifacts'/('browser-'+args.mode);OUT.mkdir(parents=True,exist_ok=True)

with tempfile.TemporaryDirectory(prefix='airlock-near-browser-') as temp:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    service=subprocess.Popen([sys.executable,'-m','privacy_layer.demo_server','--state',temp,'--port',str(port),'--no-open'],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        for _ in range(80):
            try:
                with urlopen(f'http://127.0.0.1:{port}/',timeout=1):break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('Demo listener did not start; check runtime permissions.')
        launch=json.loads((Path(temp)/'launch.json').read_text())['url']
        with sync_playwright() as p:
            options={'headless':True,'chromium_sandbox':True}
            chrome=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            if chrome.exists():options['executable_path']=str(chrome)
            browser=p.chromium.launch(**options)
            context=browser.new_context(viewport={'width':1440,'height':1100},record_video_dir=str(OUT/'video'),record_video_size={'width':1440,'height':1100})
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(launch)
            expect(page.locator('#page-near')).to_be_visible()
            expect(page.locator('#notice')).to_be_hidden()
            expect(page.locator('#onboarding')).to_be_hidden()
            expect(page.locator('#nearMode')).to_have_value('local')
            page.locator('#nearReset').click();page.locator('#nearGrant').click()
            page.locator('#nearMode').select_option(args.mode)
            page.locator('#nearPrepare').click()
            expect(page.locator('#nearReview')).to_be_visible()
            assert 'ORCHID-NEVER-SHARE-83Q' not in page.locator('#nearPayload').inner_text()
            assert page.locator('#nearSend').is_disabled()
            page.screenshot(path=str(OUT/'01-review.png'),full_page=True)
            page.locator('#nearConsent').check();page.locator('#nearSend').click()
            expect(page.locator('#nearResult')).to_be_visible(timeout=130000)
            draft=page.locator('#nearDraft').inner_text()
            assert len(draft)>80 and 'ORCHID-NEVER-SHARE-83Q' not in draft
            expect(page.locator('#nearResultMode')).to_contain_text('LOCAL AI' if args.mode=='local' else 'SCRIPTED')
            page.locator('#nearResult').scroll_into_view_if_needed()
            page.screenshot(path=str(OUT/'02-draft.png'),full_page=True)
            page.locator('#nearRestricted').click()
            expect(page.locator('#nearBlocked')).to_contain_text('never share')
            page.screenshot(path=str(OUT/'03-blocked.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(OUT/'04-mobile.png'),full_page=True)
            assert not errors,errors
            context.close();browser.close()
            print(f'Browser {args.mode} run passed. Screenshots and video: {OUT}')
    finally:
        service.terminate();service.wait(timeout=10)
