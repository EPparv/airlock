// Exercise the shipping Cocoa delegate and WebKit view inside a disposable app bundle.
#define main airlock_application_main
#import "../macos/Portable.m"
#undef main

static BOOL waitFor(BOOL (^condition)(void), NSTimeInterval timeout) {
    NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:timeout];
    do {
        if (condition()) return YES;
        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.04]];
    } while (deadline.timeIntervalSinceNow>0);
    return NO;
}
static id javascript(WKWebView *view, NSString *source) {
    __block BOOL done=NO; __block id result=nil; __block NSError *error=nil;
    [view evaluateJavaScript:source completionHandler:^(id value,NSError *problem){result=value;error=problem;done=YES;}];
    if (!waitFor(^BOOL{return done;},7) || error) return nil;
    return result;
}
static void require(BOOL value, NSString *label) {
    if (!value) { fprintf(stderr,"Window check failed: %s\n",label.UTF8String); exit(1); }
}
static void pageHas(WKWebView *view,NSString *expression) {
    require(waitFor(^BOOL{return [javascript(view,expression) isEqual:@YES];},12), expression);
}

static NSURL *fixtureURLReceipt(NSBundle *bundle) {
    return [bundle.bundleURL.URLByDeletingLastPathComponent URLByAppendingPathComponent:@"fixture-url.txt"];
}
@interface DesktopFixtureDelegate : NSObject <NSApplicationDelegate>
@end
@implementation DesktopFixtureDelegate
- (void)application:(NSApplication *)application openURLs:(NSArray<NSURL *> *)urls {
    NSString *received=[[urls valueForKey:@"absoluteString"] componentsJoinedByString:@"\n"];
    [received writeToURL:fixtureURLReceipt(NSBundle.mainBundle) atomically:YES encoding:NSUTF8StringEncoding error:NULL];
}
@end

static void click(WKWebView *view, NSString *label) {
    NSString *button=[NSString stringWithFormat:@"Array.from(document.querySelectorAll('button')).find(b=>(b.getAttribute('aria-label')||b.textContent.trim())==='%@' && !b.disabled && b.getClientRects().length)",label];
    pageHas(view,[NSString stringWithFormat:@"Boolean(%@)",button]);
    require([javascript(view,[NSString stringWithFormat:@"(%@).click();true",button]) isEqual:@YES],label);
}

static void checkClientLaunch(PrivacyLauncher *launcher, NSBundle *fixture, NSString *name) {
    WKWebView *view=launcher.panel.view;
    NSString *client=[name lowercaseString];
    NSString *bundleID=[client isEqual:@"codex"] ? @"com.openai.codex" : @"com.todesktop.230313mzl4w4u92";
    require([fixture.bundleIdentifier isEqual:bundleID],@"expected fixture bundle ID");
    NSArray *(^instances)(void)=^{return [NSRunningApplication runningApplicationsWithBundleIdentifier:bundleID];};
    require(instances().count==0,@"fixture initially closed");
    pageHas(view,@"document.querySelectorAll('#app.home nav button').length===3");
    click(view,@"Connect agent");
    require(instances().count==0,@"opening the picker does not open an app");
    click(view,name);
    require(waitFor(^BOOL{return instances().count==1;},25),@"one approval launched the desktop fixture");
    NSRunningApplication *first=instances().firstObject;
    require([first.bundleURL.URLByResolvingSymlinksInPath.path isEqual:fixture.bundleURL.URLByResolvingSymlinksInPath.path],@"launched the intended fixture bundle");
    NSString *expected=[client isEqual:@"codex"]?@"codex://threads/new":@"cursor://anysphere.cursor-deeplink/prompt";
    NSString *param=[client isEqual:@"codex"]?@"prompt":@"text";
    BOOL (^receivedPrompt)(void)=^BOOL{
        NSString *raw=[NSString stringWithContentsOfURL:fixtureURLReceipt(fixture) encoding:NSUTF8StringEncoding error:NULL];
        if(!raw)return NO;
        NSURLComponents *components=[NSURLComponents componentsWithString:raw];
        NSArray<NSURLQueryItem *> *query=components.queryItems;
        components.query=nil;
        if (![components.string isEqual:expected]) return NO;
        NSMutableDictionary *values=[NSMutableDictionary dictionary];
        for (NSURLQueryItem *item in query) {
            if (!item.value || values[item.name]) return NO;
            values[item.name]=item.value;
        }
        if (![values[param] isEqual:@"Call only the Airlock privacy_status tool and report whether it responds."]) return NO;
        if ([client isEqual:@"cursor"]) return query.count==1;
        NSString *folder=[NSHomeDirectory() stringByAppendingPathComponent:@"Library/Caches/Airlock Agent Checks/codex"];
        if (query.count!=2 || ![values[@"path"] isEqual:folder]) return NO;
        NSDictionary *attrs=[NSFileManager.defaultManager attributesOfItemAtPath:folder error:nil];
        NSArray *contents=[NSFileManager.defaultManager contentsOfDirectoryAtPath:folder error:nil];
        return [attrs[NSFileType] isEqual:NSFileTypeDirectory] && [attrs[NSFilePosixPermissions] unsignedIntegerValue]==0700 && contents && !contents.count;
    };
    require(waitFor(receivedPrompt,12),@"the app received its documented compose URL and only the fixed status prompt");
    pageHas(view,@"[...document.querySelectorAll('#app button')].some(b=>b.textContent==='Manage access' && b.getClientRects().length)");
    require([javascript(view,@"!document.querySelector('dialog[open]') && !document.querySelector('#app').innerText.includes('Copy test request')") isEqual:@YES],@"no manual settings dialog");
    click(view,@"Manage access");
    pageHas(view,@"[...document.querySelectorAll('#app button')].some(b=>b.textContent==='Save access' && b.getClientRects().length)");
    require([[NSFileManager defaultManager] removeItemAtURL:fixtureURLReceipt(fixture) error:NULL],@"clear the first draft receipt");
    [view loadRequest:[NSURLRequest requestWithURL:launcher.url]];
    pageHas(view,@"document.querySelectorAll('#app.home nav button').length===3");
    click(view,@"Connect agent");click(view,name);
    pageHas(view,@"[...document.querySelectorAll('#app button')].some(b=>b.textContent==='Manage access' && b.getClientRects().length)");
    require(waitFor(receivedPrompt,12),@"the running app received the second status draft");
    require(instances().count==1 && !first.terminated && ((NSRunningApplication *)instances().firstObject).processIdentifier==first.processIdentifier,@"second open reused the same PID");
    // Terminate only the unique disposable fixture that this test created.
    kill(first.processIdentifier,SIGTERM); require(waitFor(^BOOL{return instances().count==0;},8),@"fixture closed");
    [launcher.panel detach];
}
int main(int argc,const char *argv[]) {
    @autoreleasepool {
        umask(0077);
        NSApplication *app=NSApplication.sharedApplication;
        if ([[NSBundle.mainBundle objectForInfoDictionaryKey:@"AirlockDisposableLaunchFixture"] boolValue]) {
            if ([NSProcessInfo.processInfo.arguments containsObject:@"--register-disposable-fixture"]) {
                [app finishLaunching];
                return 0;
            }
            static DesktopFixtureDelegate *delegate;
            delegate=[DesktopFixtureDelegate new];
            app.delegate=delegate;
            [app setActivationPolicy:NSApplicationActivationPolicyRegular];
            NSWindow *window=[[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,250,180) styleMask:NSWindowStyleMaskTitled
                                      backing:NSBackingStoreBuffered defer:NO];
            window.title=@"Airlock test client";
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW,90*NSEC_PER_SEC),dispatch_get_main_queue(),^{ [NSApp terminate:nil]; });
            [window makeKeyAndOrderFront:nil]; [app run]; return 0;
        }
        [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
        [app finishLaunching];
        NSString *sample=@"https://airlock.example.test/phone#pair=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
        NSData *png=AirlockPhonePairingPNG(sample);
        require(png.length>100,@"pairing QR generated on Mac");
        CIDetector *scanner=[CIDetector detectorOfType:CIDetectorTypeQRCode context:nil options:@{CIDetectorAccuracy:CIDetectorAccuracyHigh}];
        NSArray *codes=[scanner featuresInImage:[CIImage imageWithData:png]];
        require(codes.count==1 && [[(CIQRCodeFeature *)codes.firstObject messageString] isEqual:sample],@"camera-readable complete pairing URL");
        NSArray *options=NSProcessInfo.processInfo.arguments;
        NSUInteger lookup=[options indexOfObject:@"--find-installed-bundle"];
        if (lookup!=NSNotFound) {
            NSString *identifier=options[lookup+1];
            NSURL *installed=[NSWorkspace.sharedWorkspace URLForApplicationWithBundleIdentifier:identifier];
            if (installed) puts(installed.path.UTF8String);
            return 0;
        }
        PrivacyLauncher *launcher=[PrivacyLauncher new];
        [launcher applicationDidFinishLaunching:nil];
        require(waitFor(^BOOL{return launcher.panel!=nil;},25),@"authenticated native window");
        NSArray *args=NSProcessInfo.processInfo.arguments;
        NSUInteger fixtureIndex=[args indexOfObject:@"--test-client"];
        if (fixtureIndex!=NSNotFound) {
            NSBundle *fixture=[NSBundle bundleWithPath:args[fixtureIndex+1]];
            require([[fixture objectForInfoDictionaryKey:@"AirlockDisposableLaunchFixture"] boolValue],@"isolated desktop fixture");
            checkClientLaunch(launcher,fixture,args[fixtureIndex+2]);
            puts("One-click connection launched the expected desktop client and reused its running process.");
            return 0;
        }
        WKWebView *view=launcher.panel.view;
        require(launcher.window.contentView==view && launcher.window.visible,@"Airlock owns the visible workspace");
        pageHas(view,@"document.querySelectorAll('#app.home nav button').length===3");
        NSArray *buttons=javascript(view,@"Array.from(document.querySelectorAll('nav button'), b=>b.textContent)");
        require([buttons isEqual:@[@"Connect agent",@"Context & memory",@"Privacy & connections"]],@"home controls");
        javascript(view,@"document.querySelectorAll('nav button')[0].click();true");
        pageHas(view,@"document.querySelector('h1')?.textContent==='Connect agent'");
        NSArray *picker=javascript(view,@"Array.from(document.querySelectorAll('#app button:not(.back),#app a[href],#app summary')).filter(b=>b.getClientRects().length).map(b=>b.getAttribute('aria-label')||b.textContent.trim())");
        for (NSString *label in @[@"Codex",@"Cursor",@"Claude Desktop",@"Claude Code",@"Meta Muse",@"OpenClaw",@"VS Code · GitHub Copilot",@"Gemini CLI",@"ChatGPT",@"Dot"])
            require([picker containsObject:label],[NSString stringWithFormat:@"%@ is directly selectable",label]);
        require(![picker containsObject:@"Other agents"],@"no extra directory click");
        require([javascript(view,@"!document.querySelector('dialog').open && location.pathname==='/workspace' && !sessionStorage.getItem('private-ai-owner')") isEqual:@YES],@"choosing Connect agent preserves the locked workspace");
        javascript(view,@"document.querySelector('.back').click();true");
        pageHas(view,@"document.querySelectorAll('nav button').length===3");
        javascript(view,@"document.querySelectorAll('nav button')[1].click();true");
        pageHas(view,@"Array.from(document.querySelectorAll('.menu-row')).some(b=>b.textContent==='Memories')");
        javascript(view,@"document.querySelector('.back').click();document.querySelectorAll('nav button')[2].click();true");
        pageHas(view,@"Array.from(document.querySelectorAll('.menu-row')).some(b=>b.textContent==='Data protection')");
        javascript(view,@"Array.from(document.querySelectorAll('.menu-row')).find(b=>b.textContent==='App settings').click();true");
        pageHas(view,@"Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Check for updates')");
        require([javascript(view,@"location.hash==='' && sessionStorage.getItem('private-ai-owner')===null") isEqual:@YES],@"owner session stays locked");
        [launcher.window orderOut:nil];[launcher openPanel:nil];
        require(waitFor(^BOOL{return !launcher.preparing;},10),@"Dock service check completed");
        require(launcher.window.visible && launcher.panel.view==view,@"a healthy Dock reopen preserves navigation");
        pageHas(view,@"document.querySelector('h1')?.textContent==='App settings'");
        NSURLComponents *stale=[NSURLComponents componentsWithURL:launcher.url resolvingAgainstBaseURL:NO];
        stale.query=@"view=connect";
        stale.fragment=@"expired-fixture-owner";
        [view loadRequest:[NSURLRequest requestWithURL:stale.URL]];
        pageHas(view,@"document.querySelector('.workspace-recovery h2')?.textContent==='Open Airlock again'");
        click(view,@"Reconnect Airlock");
        require(waitFor(^BOOL{return launcher.panel && launcher.panel.view!=view;},20),@"reconnect replaced stale web view");
        WKWebView *fresh=launcher.panel.view;
        pageHas(fresh,@"document.querySelectorAll('#app.home nav button').length===3");
        click(fresh,@"Connect agent");
        pageHas(fresh,@"document.querySelectorAll('.agent-option').length===15 && !document.querySelector('.workspace-recovery')");
        require([javascript(fresh,@"location.hash==='' && !sessionStorage.getItem('private-ai-owner')") isEqual:@YES],@"recovery authenticates the locked entry only");
        [launcher.panel detach];
        puts("Packaged native window, three navigation paths, unlock boundary, settings bridge and reopen passed.");
    }
    return 0;
}
