// Exercise the ordinary browser's loopback workspace with an installed vendor app.
#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

static void require(BOOL condition, NSString *message) {
    if (!condition) { fprintf(stderr,"%s\n",message.UTF8String); exit(1); }
}

static BOOL waitUntil(BOOL (^check)(void), NSTimeInterval seconds) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:seconds];
    do {
        if (check()) return YES;
        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.1]];
    } while (deadline.timeIntervalSinceNow > 0);
    return NO;
}

static id javascript(WKWebView *view, NSString *source) {
    __block BOOL done = NO;
    __block id result = nil;
    [view evaluateJavaScript:source completionHandler:^(id value, NSError *error) {
        result = error ? nil : value;
        done = YES;
    }];
    return waitUntil(^BOOL{ return done; }, 5) ? result : nil;
}

static void choose(WKWebView *view, NSString *selector, NSString *name) {
    NSString *button = [NSString stringWithFormat:@"Array.from(document.querySelectorAll('%@')).find(b=>(b.getAttribute('aria-label')||b.textContent.trim())==='%@' && !b.disabled && b.getClientRects().length)",selector,name];
    if (!waitUntil(^BOOL{ return [javascript(view,[NSString stringWithFormat:@"Boolean(%@)",button]) boolValue]; },25)) {
        NSString *page=javascript(view,@"JSON.stringify({path:location.pathname,ready:document.readyState,view:history.state?.view,heading:document.querySelector('#app h1')?.textContent,recovery:document.querySelector('.workspace-recovery h2')?.textContent,rendering:!!document.querySelector('#app [aria-busy=true]'),buttons:document.querySelectorAll('#app button').length})");
        require(NO,[NSString stringWithFormat:@"Missing action %@ on %@.",name,page ?: @"unavailable page"]);
    }
    require([javascript(view,[NSString stringWithFormat:@"(%@).click();true",button]) boolValue],@"Could not activate the picker action.");
}

static void connectInBrowser(WKWebView *view, NSURL *entry, NSString *name) {
    [view loadRequest:[NSURLRequest requestWithURL:entry]];
    choose(view, @"#app.home nav button", @"Connect agent");
    require(![javascript(view,@"!!window.webkit?.messageHandlers?.airlockSettings") boolValue],@"This must be an ordinary browser session with no native bridge.");
    choose(view, @"#app .agent-option", name);
    require(waitUntil(^BOOL{ return [javascript(view,@"!!Array.from(document.querySelectorAll('#app button')).find(b=>b.textContent==='Manage access' && b.getClientRects().length)") boolValue]; },45),@"The browser did not reach the launch receipt.");
    require([javascript(view,@"history.state?.options?.method==='draft' && history.state?.options?.opened===true") boolValue],@"Airlock did not hand the status draft to the selected app.");
    require([javascript(view,@"!document.querySelector('dialog[open]') && !document.getElementById('app').innerText.includes('Copy test request')") boolValue],@"The browser displayed a manual handoff instead of launching.");
}

int main(int argc,const char *argv[]) {
    @autoreleasepool {
        require(argc==3,@"Expected a vendor key and a bundle path.");
        NSString *agent=[NSString stringWithUTF8String:argv[1]];
        NSDictionary *names=@{@"codex":@"Codex", @"cursor":@"Cursor", @"claude-desktop":@"Claude Desktop"};
        NSDictionary *identifiers=@{@"codex":@"com.openai.codex", @"cursor":@"com.todesktop.230313mzl4w4u92",
                                     @"claude-desktop":@"com.anthropic.claudefordesktop"};
        NSString *name=names[agent], *identifier=identifiers[agent];
        require(name != nil && identifier != nil, @"Unknown test agent.");
        NSBundle *installed=[NSBundle bundleWithPath:[NSString stringWithUTF8String:argv[2]]];
        require([installed.bundleIdentifier isEqual:identifier],@"Unexpected vendor bundle.");
        NSURL *entry=[NSURL URLWithString:NSProcessInfo.processInfo.environment[@"AIRLOCK_VENDOR_WORKSPACE"]];
        require([entry.host isEqual:@"127.0.0.1"] && [entry.path isEqual:@"/workspace/personal"],@"Expected the disposable authenticated loopback workspace.");
        [NSApplication.sharedApplication setActivationPolicy:NSApplicationActivationPolicyAccessory];
        [NSApp finishLaunching];
        WKWebViewConfiguration *config=[WKWebViewConfiguration new];
        config.websiteDataStore=WKWebsiteDataStore.nonPersistentDataStore;
        WKWebView *view=[[WKWebView alloc] initWithFrame:NSMakeRect(0,0,800,700) configuration:config];
        NSWindow *window=[[NSWindow alloc] initWithContentRect:view.frame styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
        window.contentView=view;
        [window orderFront:nil];
        NSArray *(^instances)(void)=^{return [NSRunningApplication runningApplicationsWithBundleIdentifier:identifier];};
        require(instances().count==0,@"Expected the signed vendor app to be closed.");
        connectInBrowser(view,entry,name);
        puts("The first browser handoff reached the receipt.");
        require(waitUntil(^BOOL{return instances().count==1;},60),@"No unique vendor process appeared.");
        NSRunningApplication *first=instances().firstObject;
        require([first.bundleURL.URLByResolvingSymlinksInPath.path isEqual:installed.bundleURL.URLByResolvingSymlinksInPath.path],@"Unexpected running vendor app path.");
        require(waitUntil(^BOOL{return first.finishedLaunching && !first.terminated;},60),@"Vendor app failed to open.");
        connectInBrowser(view,entry,name);
        require(instances().count==1 && !first.terminated && ((NSRunningApplication *)instances().firstObject).processIdentifier==first.processIdentifier,@"Second browser connection replaced the running app.");
        printf("%s version %s: a real loopback browser connected in two clicks, both times using PID %d.\n", identifier.UTF8String,[[installed objectForInfoDictionaryKey:@"CFBundleShortVersionString"] UTF8String],first.processIdentifier);
    }
    return 0;
}
