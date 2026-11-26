// Launch real iOS WebKit in a disposable simulator; the app uses HTTPS and its own origin.
#import <UIKit/UIKit.h>
#import <WebKit/WebKit.h>

@interface PhoneProbe : UIResponder <UIApplicationDelegate,WKNavigationDelegate>
@property(nonatomic,strong) UIWindow *window;
@property(nonatomic,strong) WKWebView *web;
@property(nonatomic) NSInteger phase;
@property(nonatomic) BOOL finished;
@end
@implementation PhoneProbe
- (void)finish:(NSString *)message {
    if (self.finished) return;
    self.finished=YES;
    NSURL *dir=[NSFileManager.defaultManager URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask].firstObject;
    [message writeToURL:[dir URLByAppendingPathComponent:@"phone-result.txt"] atomically:YES encoding:NSUTF8StringEncoding error:nil];
}
- (BOOL)application:(UIApplication *)app didFinishLaunchingWithOptions:(NSDictionary *)options {
    self.window=[[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *controller=[UIViewController new];
    self.web=[[WKWebView alloc] initWithFrame:self.window.bounds]; self.web.navigationDelegate=self;
    controller.view=self.web; self.window.rootViewController=controller; [self.window makeKeyAndVisible];
    self.phase=1;
    NSURL *url=[NSURL URLWithString:NSProcessInfo.processInfo.environment[@"AIRLOCK_TEST_URL"]];
    [self.web loadRequest:[NSURLRequest requestWithURL:url]];
    return YES;
}
- (void)webView:(WKWebView *)web didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    [self finish:[NSString stringWithFormat:@"Navigation failed (%ld): %@",(long)error.code,error.localizedDescription]];
}
- (void)webViewWebContentProcessDidTerminate:(WKWebView *)web { [self finish:@"WebKit unexpectedly stopped."]; }
- (void)webView:(WKWebView *)web didFinishNavigation:(WKNavigation *)navigation {
    NSInteger phase=self.phase;
    NSString *script=(phase<=2 ? @"iphone_flow":@"iphone_companion_flow");
    NSString *path=[NSBundle.mainBundle pathForResource:script ofType:@"js"];
    NSString *js=[NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:nil];
    if (!js) { [self finish:@"Missing simulator test resource."];return; }
    [web callAsyncJavaScript:js arguments:@{@"phase":@(phase)} inFrame:nil inContentWorld:WKContentWorld.pageWorld
     completionHandler:^(id result,NSError *error) {
        if (error || ![result isEqual:@YES]) {
            NSString *why=error.userInfo[@"WKJavaScriptExceptionMessage"] ?: error.localizedDescription ?: @"Unexpected JavaScript result";
            [self finish:[NSString stringWithFormat:@"Step %ld: %@",(long)phase,why]];return;
        }
        if (phase==1) { self.phase=2; [web reload]; }
        else if (phase==2 && NSProcessInfo.processInfo.environment[@"AIRLOCK_PAIR_URL"]) {
            self.phase=3;
            [web loadRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:NSProcessInfo.processInfo.environment[@"AIRLOCK_PAIR_URL"]]]];
        } else [self finish:@"passed"];
    }];
}
@end
int main(int argc,char *argv[]){@autoreleasepool{return UIApplicationMain(argc,argv,nil,NSStringFromClass(PhoneProbe.class));}}
