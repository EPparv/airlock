// Exercise the shipping Cocoa delegate and WebKit view inside a disposable app bundle.
#define main airlock_application_main
#import "../macos/Portable.m"
#undef main

static BOOL waitFor(BOOL (^condition)(void), NSTimeInterval timeout) {
    NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:timeout];
    while (!condition() && deadline.timeIntervalSinceNow>0)
        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.04]];
    return condition();
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

// Only this test executable substitutes the installed bundle. Launch and activation
// still go through the shipping bridge and the real macOS Launch Services.
@interface ClientLaunchProbePanel : AirlockPanel
@property(nonatomic,strong) NSBundle *fixture;
@property(nonatomic,copy) NSString *requestedID;
@end
@implementation ClientLaunchProbePanel
- (NSBundle *)desktopBundle:(NSString *)identifier {
    self.requestedID=identifier;
    return self.fixture;
}
@end

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
    NSString *button=[NSString stringWithFormat:@"Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='%@' && !b.disabled && b.getClientRects().length)",label];
    pageHas(view,[NSString stringWithFormat:@"Boolean(%@)",button]);
    require([javascript(view,[NSString stringWithFormat:@"(%@).click();true",button]) isEqual:@YES],label);
}

static void checkClientLaunch(PrivacyLauncher *launcher, NSBundle *fixture, NSString *name) {
    [launcher.panel detach];
    ClientLaunchProbePanel *panel=[[ClientLaunchProbePanel alloc] initWithWindow:launcher.window entry:launcher.url];
    panel.fixture=fixture;
    launcher.panel=panel;
    launcher.window.contentView=panel.view;
    WKWebView *view=panel.view;
    NSString *client=[name lowercaseString];
    NSString *bundleID=[client isEqual:@"codex"] ? @"com.openai.codex" : @"com.todesktop.230313mzl4w4u92";
    NSArray *(^instances)(void)=^{ return [NSRunningApplication runningApplicationsWithBundleIdentifier:fixture.bundleIdentifier]; };
    require(instances().count==0,@"fixture initially closed");
    pageHas(view,@"document.querySelectorAll('#app.home nav button').length===3");
    // A message from the introductory page cannot open anything without approval.
    javascript(view,@"webkit.messageHandlers.airlockSettings.postMessage({action:'open-client',agent:'cursor'}).then(()=>window.gate='opened',()=>window.gate='blocked');true");
    pageHas(view,@"window.gate==='blocked'");
    click(view,@"Connect agent");
    require(!panel.requestedID && instances().count==0,@"opening the picker does not open an app");
    click(view,[@"Connect & open " stringByAppendingString:name]);
    require(waitFor(^BOOL{return instances().count==1;},20),@"one approval launched the desktop fixture");
    require([panel.requestedID isEqual:bundleID],@"resolved the requested desktop client identifier");
    NSRunningApplication *first=instances().firstObject;
    require([first.bundleURL.URLByResolvingSymlinksInPath.path isEqual:fixture.bundleURL.URLByResolvingSymlinksInPath.path],@"launched the intended fixture bundle");
    if ([client isEqual:@"codex"]) {
        require(waitFor(^BOOL{
            NSString *value=[NSString stringWithContentsOfURL:fixtureURLReceipt(fixture) encoding:NSUTF8StringEncoding error:NULL];
            return [value isEqual:@"codex://threads/new"];
        },10),@"Codex received only its documented new-chat link");
    }
    NSString *again=[NSString stringWithFormat:@"webkit.messageHandlers.airlockSettings.postMessage({action:'open-client',agent:'%@'}).then(r=>window.reused=r.opened && r.wasRunning);true",client];
    javascript(view,again); pageHas(view,@"window.reused===true");
    require(instances().count==1 && ((NSRunningApplication *)instances().firstObject).processIdentifier==first.processIdentifier,@"second open reused the same PID");
    javascript(view,@"webkit.messageHandlers.airlockSettings.postMessage({action:'open-client',agent:'other'}).then(()=>window.unknown='opened',()=>window.unknown='blocked');true");
    pageHas(view,@"window.unknown==='blocked'");
    // Terminate only the unique disposable fixture that this test created.
    kill(first.processIdentifier,SIGTERM); require(waitFor(^BOOL{return instances().count==0;},8),@"fixture closed");
    [panel detach];
}
int main(int argc,const char *argv[]) {
    @autoreleasepool {
        umask(0077);
        NSApplication *app=NSApplication.sharedApplication;
        if ([NSBundle.mainBundle.bundleIdentifier hasPrefix:@"com.airlock.fixture.desktop."]) {
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
        PrivacyLauncher *launcher=[PrivacyLauncher new];
        [launcher applicationDidFinishLaunching:nil];
        require(waitFor(^BOOL{return launcher.panel!=nil;},25),@"authenticated native window");
        NSArray *args=NSProcessInfo.processInfo.arguments;
        NSUInteger fixtureIndex=[args indexOfObject:@"--test-client"];
        if (fixtureIndex!=NSNotFound) {
            NSBundle *fixture=[NSBundle bundleWithPath:args[fixtureIndex+1]];
            require([fixture.bundleIdentifier hasPrefix:@"com.airlock.fixture.desktop."],@"isolated desktop fixture");
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
        pageHas(view,@"['Codex','Cursor'].every(name=>[...document.querySelectorAll('button')].some(b=>b.textContent==='Connect & open '+name && b.getClientRects().length))");
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
        require(launcher.window.visible && launcher.panel.view==view,@"reopen preserves navigation");
        [launcher.panel detach];
        puts("Packaged native window, three navigation paths, unlock boundary, settings bridge and reopen passed.");
    }
    return 0;
}
