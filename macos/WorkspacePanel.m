#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#import <CoreImage/CoreImage.h>

// Build the pairing image entirely on the Mac. The empty white border is part of the QR.
static NSData *AirlockPhonePairingPNG(NSString *url) {
    CIFilter *filter=[CIFilter filterWithName:@"CIQRCodeGenerator"];
    [filter setValue:[url dataUsingEncoding:NSUTF8StringEncoding] forKey:@"inputMessage"];
    [filter setValue:@"M" forKey:@"inputCorrectionLevel"];
    CIImage *qr=filter.outputImage;
    if (!qr) return nil;
    CGAffineTransform scale={6,0,0,6,0,0};
    CIImage *pixels=[[qr imageBySamplingNearest] imageByApplyingTransform:scale];
    CGRect frame=pixels.extent;
    frame.origin.x-=24; frame.origin.y-=24; frame.size.width+=48; frame.size.height+=48;
    CIImage *white=[[CIImage imageWithColor:[CIColor colorWithRed:1 green:1 blue:1]] imageByCroppingToRect:frame];
    NSBitmapImageRep *bitmap=[[NSBitmapImageRep alloc] initWithCIImage:[pixels imageByCompositingOverImage:white]];
    return [bitmap representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
}

// The owner interface is a single, ephemeral web view on the running service's port.
@interface AirlockPanel : NSObject <WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandlerWithReply>
@property(nonatomic,strong) WKWebView *view;
@property(nonatomic,weak) NSWindow *window;
@property(nonatomic,strong) NSURL *entry;
@property(nonatomic,copy) void (^checkUpdates)(void);
@property(nonatomic,copy) void (^reconnect)(void);
@property(nonatomic,copy) void (^loadFailed)(void);
@property(nonatomic,copy) void (^setAutomatic)(BOOL);
- (instancetype)initWithWindow:(NSWindow *)window entry:(NSURL *)entry;
- (void)detach;
@end

@implementation AirlockPanel
// Look up the installed desktop bundle by identity, including renamed or moved apps.
- (instancetype)initWithWindow:(NSWindow *)window entry:(NSURL *)entry {
    if (!(self=[super init])) return nil;
    self.window=window;
    self.entry=entry;
    WKWebViewConfiguration *config=[WKWebViewConfiguration new];
    config.websiteDataStore=WKWebsiteDataStore.nonPersistentDataStore;
    [config.userContentController addScriptMessageHandlerWithReply:self contentWorld:WKContentWorld.pageWorld name:@"airlockSettings"];
    self.view=[[WKWebView alloc] initWithFrame:window.contentView.bounds configuration:config];
    self.view.autoresizingMask=NSViewWidthSizable|NSViewHeightSizable;
    self.view.navigationDelegate=self;
    self.view.UIDelegate=self;
    [self.view loadRequest:[NSURLRequest requestWithURL:entry]];
    return self;
}
- (void)detach {
    [self.view.configuration.userContentController removeScriptMessageHandlerForName:@"airlockSettings" contentWorld:WKContentWorld.pageWorld];
    self.view.navigationDelegate=nil;
    self.view.UIDelegate=nil;
    [self.view stopLoading];
    [self.view removeFromSuperview];
}
- (BOOL)isWorkspace:(NSURL *)url {
    return [url.scheme isEqualToString:@"http"] && [url.host isEqualToString:@"127.0.0.1"] &&
        !url.user && !url.password && [url.port isEqual:self.entry.port] &&
        ([url.path isEqualToString:@"/workspace"] || [url.path isEqualToString:@"/workspace/personal"]);
}
- (BOOL)trusted:(WKFrameInfo *)frame {
    WKSecurityOrigin *origin=frame.securityOrigin;
    return frame.isMainFrame && [origin.protocol isEqualToString:@"http"] &&
        [origin.host isEqualToString:@"127.0.0.1"] && origin.port==self.entry.port.integerValue &&
        [self isWorkspace:frame.request.URL] && [self isWorkspace:self.view.URL];
}
- (void)webView:(WKWebView *)webView decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decide {
    NSURL *url=action.request.URL;
    if (action.targetFrame.isMainFrame && [self isWorkspace:url]) {
        decide(WKNavigationActionPolicyAllow);
        return;
    }
    if (action.navigationType==WKNavigationTypeLinkActivated && [self trusted:action.sourceFrame] &&
        [url.scheme isEqualToString:@"https"] && [url.host isEqualToString:@"accounts.google.com"] &&
        !url.user && !url.password && !url.port && !url.fragment) {
        [[NSWorkspace sharedWorkspace] openURL:url];
    }
    decide(WKNavigationActionPolicyCancel);
}
- (void)webView:(WKWebView *)webView didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    if ([error.domain isEqual:NSURLErrorDomain] && error.code!=NSURLErrorCancelled && self.loadFailed)
        self.loadFailed();
}
- (void)webView:(WKWebView *)webView didFailNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    [self webView:webView didFailProvisionalNavigation:navigation withError:error];
}
- (void)webViewWebContentProcessDidTerminate:(WKWebView *)webView {
    [webView loadRequest:[NSURLRequest requestWithURL:self.entry]];
}
- (void)webView:(WKWebView *)webView runOpenPanelWithParameters:(WKOpenPanelParameters *)params initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(NSArray<NSURL *> *))complete {
    if (![self trusted:frame]) { complete(nil); return; }
    NSOpenPanel *panel=[NSOpenPanel openPanel];
    panel.canChooseDirectories=NO;
    panel.canChooseFiles=YES;
    panel.allowsMultipleSelection=params.allowsMultipleSelection;
    [panel beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse response) {
        complete(response==NSModalResponseOK ? panel.URLs : nil);
    }];
}
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message replyHandler:(void (^)(id, NSString *))reply {
    if (![self trusted:message.frameInfo] || ![message.body isKindOfClass:NSDictionary.class]) {
        reply(nil,@"This action is available in the local workspace.");
        return;
    }
    NSDictionary *value=message.body;
    NSString *action=value[@"action"];
    if ([action isEqual:@"status"]) {
        reply(@{@"automatic":@([NSUserDefaults.standardUserDefaults boolForKey:@"AirlockCheckUpdatesOnLaunch"])},nil);
    } else if ([action isEqual:@"automatic"] && [value[@"enabled"] isKindOfClass:NSNumber.class] && self.setAutomatic) {
        self.setAutomatic([value[@"enabled"] boolValue]);
        reply(@YES,nil);
    } else if ([action isEqual:@"reconnect"] && self.reconnect) {
        reply(@YES,nil);
        dispatch_async(dispatch_get_main_queue(),self.reconnect);
    } else if ([action isEqual:@"check"] && self.checkUpdates) {
        reply(@YES,nil);
        dispatch_async(dispatch_get_main_queue(),self.checkUpdates);
    } else if ([action isEqual:@"phone-qr"] || [action isEqual:@"phone-proof-qr"]) {
        NSString *url=value[@"url"];
        if (![self.view.URL.path isEqual:@"/workspace/personal"] || ![url isKindOfClass:NSString.class] || url.length>512) {
            reply(nil,@"Open the personal workspace to pair."); return;
        }
        NSURLComponents *parts=[NSURLComponents componentsWithString:url];
        BOOL verification=[action isEqual:@"phone-proof-qr"];
        BOOL acceptedPath=verification
            ? ([parts.host hasSuffix:@".trycloudflare.com"] && !parts.port && !parts.fragment && parts.path.length==44 &&
               [parts.path rangeOfString:@"^/link-check/[0-9a-f]{32}$" options:NSRegularExpressionSearch].location!=NSNotFound)
            : ([parts.path isEqual:@"/phone"] &&
               [parts.fragment rangeOfString:@"^pair=[A-Za-z0-9_-]{43}$" options:NSRegularExpressionSearch].location!=NSNotFound &&
               parts.fragment.length==48);
        if (![parts.scheme isEqual:@"https"] || !parts.host.length || parts.user || parts.password || parts.query || !acceptedPath) {
            reply(nil,@"Create a new pairing link."); return;
        }
        NSData *png=AirlockPhonePairingPNG(url);
        reply([png base64EncodedStringWithOptions:0], png ? nil : @"Copy the one-time link to Safari.");
    } else if ([action isEqual:@"save-file"]) {
        NSString *name=value[@"name"], *content=value[@"content"];
        if (![name isKindOfClass:NSString.class] || !name.length || name.length>255 ||
            ![name.lastPathComponent isEqual:name] || [name hasPrefix:@"."] || [name containsString:@":"] ||
            ![content isKindOfClass:NSString.class] || content.length>12*1024*1024) {
            reply(nil,@"Choose a valid output file."); return;
        }
        NSData *bytes=[[NSData alloc] initWithBase64EncodedString:content options:0];
        if (!bytes) { reply(nil,@"The output could not be read."); return; }
        NSSavePanel *panel=[NSSavePanel savePanel];
        panel.nameFieldStringValue=name;
        [panel beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse response) {
            if (response!=NSModalResponseOK) { reply(@NO,nil); return; }
            NSError *error=nil;
            BOOL ok=[bytes writeToURL:panel.URL options:NSDataWritingAtomic error:&error];
            reply(ok ? @YES : nil,ok ? nil : @"The file could not be saved.");
        }];
    } else {
        reply(nil,@"Unknown setting.");
    }
}
@end
