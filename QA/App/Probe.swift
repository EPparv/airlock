import UIKit
import WebKit

@main
final class Probe: UIResponder, UIApplicationDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    var window: UIWindow?
    var web: WKWebView!
    var ready = UILabel()
    func application(_ app: UIApplication, didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey:Any]?) -> Bool {
        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name:"fixtureState")
        web = WKWebView(frame:.zero,configuration:config)
        web.navigationDelegate = self
        let vc = UIViewController()
        vc.view.backgroundColor = .white
        window = UIWindow(frame:UIScreen.main.bounds)
        window?.rootViewController = vc
        window?.makeKeyAndVisible()
        web.frame = vc.view.bounds.inset(by:UIEdgeInsets(top:65,left:0,bottom:25,right:0))
        web.autoresizingMask = [.flexibleWidth,.flexibleHeight]
        vc.view.addSubview(web)
        ready.frame = CGRect(x:3,y:45,width:380,height:18)
        ready.isAccessibilityElement = true
        ready.accessibilityIdentifier = "fixture-state"
        ready.font = UIFont.systemFont(ofSize:9)
        ready.text = "Loading local Airlock page"
        vc.view.addSubview(ready)
        web.load(URLRequest(url:URL(string:"https://127.0.0.1:8742/iphone/#connect")!))
        return true
    }
    func userContentController(_ userContentController: WKUserContentController, didReceive message:WKScriptMessage) {
        if let status = message.body as? String { ready.text = status; ready.accessibilityLabel = status }
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation:WKNavigation!, withError error:Error) {
        ready.text="Loading failed: "+error.localizedDescription
    }
    func webView(_ webView: WKWebView, didFinish navigation:WKNavigation!) {
        // Exercise the shipping UI to prepare fictional text. The share button has no automated JS click or mock.
        let setup = #"""
        (async () => {
          const state = x => window.webkit.messageHandlers.fixtureState.postMessage(x);
          const button = s => [...document.querySelectorAll('button')].find(b=>b.textContent===s);
          async function wait(f) { for(let i=0;i<100;i++){if(f())return f();await new Promise(r=>setTimeout(r,60))} throw Error('Fixture setup timed out'); }
          try {
            (await wait(()=>button('Share an excerpt'))).click();
            const input=await wait(()=>document.querySelector('textarea'));
            input.value='Fictional preview cedar. Email editor@example.org.';
            (await wait(()=>button('Review excerpt'))).click();
            const s=await wait(()=>button('Share reviewed text'));
            const approved=document.querySelectorAll('textarea')[1];
            if(!approved?.value.includes('[email-')||approved.value.includes('example.org'))throw Error('Review filtering failed');
            s.scrollIntoView({block:'center'});
            const report=()=>state('Reviewed: '+approved.value+'; share button '+(s.disabled?'busy':'ready'));
            report();setInterval(report,300);
          } catch(e){state('Setup error: '+e.message)}
        })()
        """#
        webView.evaluateJavaScript(setup,completionHandler:nil)
    }
}
