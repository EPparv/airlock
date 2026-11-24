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
int main(int argc,const char *argv[]) {
    @autoreleasepool {
        umask(0077);
        NSApplication *app=NSApplication.sharedApplication;
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
        WKWebView *view=launcher.panel.view;
        require(launcher.window.contentView==view && launcher.window.visible,@"Airlock owns the visible workspace");
        pageHas(view,@"document.querySelectorAll('#app.home nav button').length===3");
        NSArray *buttons=javascript(view,@"Array.from(document.querySelectorAll('nav button'), b=>b.textContent)");
        require([buttons isEqual:@[@"Connect agent",@"Context & memory",@"Privacy & connections"]],@"home controls");
        javascript(view,@"document.querySelectorAll('nav button')[0].click();true");
        pageHas(view,@"document.querySelector('h1')?.textContent==='Connect agent'");
        javascript(view,@"Array.from(document.querySelectorAll('.menu-row')).find(b=>b.textContent==='Codex').click();true");
        pageHas(view,@"document.querySelector('dialog').open && document.getElementById('dialog-title').textContent==='Unlock your workspace'");
        javascript(view,@"document.getElementById('close').click();document.querySelector('.back').click();true");
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
