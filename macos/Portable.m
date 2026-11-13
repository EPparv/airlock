#import <Cocoa/Cocoa.h>
#import <sys/stat.h>
#import <signal.h>

@interface PrivacyLauncher : NSObject <NSApplicationDelegate, NSURLSessionTaskDelegate>
@property NSWindow *window;
@property NSTextField *detail;
@property NSProgressIndicator *spinner;
@property NSButton *button;
@property NSTask *task;
@property NSString *base;
@property NSString *profileHome;
@property NSURL *url;
@property NSNumber *serverPID;
@property BOOL preparing;
@property BOOL quitting;
@end

@implementation PrivacyLauncher
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request completionHandler:(void (^)(NSURLRequest *))completion { completion(nil); }
- (NSDictionary *)session {
 NSString *path=[self.base stringByAppendingPathComponent:@"app/.private/launch.json"];
 struct stat st;if(lstat(path.fileSystemRepresentation,&st)||!S_ISREG(st.st_mode)||st.st_uid!=getuid()||(st.st_mode&0077)||st.st_size>8192)return nil;
 NSDictionary *record=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:path]?:[NSData data] options:0 error:nil];
 if(![record isKindOfClass:NSDictionary.class]||![record[@"url"] isKindOfClass:NSString.class]||![record[@"owner_token"] isKindOfClass:NSString.class]||![record[@"pid"] isKindOfClass:NSNumber.class])return nil;
 NSURL *url=[NSURL URLWithString:record[@"url"]];
 if(![url.scheme isEqual:@"http"]||![url.host isEqual:@"127.0.0.1"]||url.user||url.password||url.port.integerValue<1||url.port.integerValue>65535)return nil;
 NSMutableURLRequest *request=[NSMutableURLRequest requestWithURL:[NSURL URLWithString:[NSString stringWithFormat:@"http://127.0.0.1:%@/api/state",url.port]] cachePolicy:NSURLRequestReloadIgnoringLocalCacheData timeoutInterval:2];
 request.HTTPMethod=@"POST";request.HTTPBody=[@"{}" dataUsingEncoding:NSUTF8StringEncoding];
 [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
 [request setValue:[@"Bearer " stringByAppendingString:record[@"owner_token"]] forHTTPHeaderField:@"Authorization"];
 NSURLSessionConfiguration *config=NSURLSessionConfiguration.ephemeralSessionConfiguration;config.connectionProxyDictionary=@{};
 NSURLSession *session=[NSURLSession sessionWithConfiguration:config delegate:self delegateQueue:nil];
 dispatch_semaphore_t done=dispatch_semaphore_create(0);__block BOOL ok=NO;
 [[session dataTaskWithRequest:request completionHandler:^(NSData *data,NSURLResponse *response,NSError *error){ok=!error&&[(NSHTTPURLResponse *)response statusCode]==200;dispatch_semaphore_signal(done);}] resume];
 dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,3*NSEC_PER_SEC));[session invalidateAndCancel];return ok?record:nil;
}
- (NSTextField *)label:(NSString *)text frame:(NSRect)frame size:(CGFloat)size {
 NSTextField *label=[NSTextField wrappingLabelWithString:text];label.frame=frame;label.alignment=NSTextAlignmentCenter;label.font=[NSFont systemFontOfSize:size];label.textColor=NSColor.labelColor;[self.window.contentView addSubview:label];return label;
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
 // Keep legacy storage in place: its encryption key is bound to this path.
 NSString *support=[NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support"];
 NSString *legacy=[support stringByAppendingPathComponent:@"Private AI Privacy"];
 self.base=[[NSFileManager defaultManager] fileExistsAtPath:[legacy stringByAppendingPathComponent:@"app/.private/connections.enc"]]?legacy:[support stringByAppendingPathComponent:@"Airlock"];
 NSArray *args=NSProcessInfo.processInfo.arguments;
 NSUInteger n=[args indexOfObject:@"--data-dir"];if(n!=NSNotFound&&n+1<args.count)self.base=[args[n+1] stringByStandardizingPath];
 n=[args indexOfObject:@"--profile-home"];if(n!=NSNotFound&&n+1<args.count)self.profileHome=[args[n+1] stringByStandardizingPath];
 self.window=[[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,460,310) styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable|NSWindowStyleMaskMiniaturizable backing:NSBackingStoreBuffered defer:NO];
 self.window.title=@"Airlock";self.window.releasedWhenClosed=NO;self.window.appearance=[NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];self.window.backgroundColor=[NSColor colorWithRed:.047 green:.063 blue:.09 alpha:1];
 NSImageView *brand=[[NSImageView alloc] initWithFrame:NSMakeRect(193,207,74,74)];brand.image=[NSImage imageNamed:NSImageNameApplicationIcon];[self.window.contentView addSubview:brand];
 [self label:@"Welcome to Airlock." frame:NSMakeRect(25,163,410,35) size:23];
 self.detail=[self label:@"Opening…" frame:NSMakeRect(35,85,390,65) size:14];self.detail.textColor=NSColor.secondaryLabelColor;
 self.spinner=[[NSProgressIndicator alloc] initWithFrame:NSMakeRect(215,50,30,30)];self.spinner.style=NSProgressIndicatorStyleSpinning;[self.window.contentView addSubview:self.spinner];
 self.button=[NSButton buttonWithTitle:@"Open control panel" target:self action:@selector(openPanel:)];self.button.frame=NSMakeRect(130,20,200,30);self.button.hidden=YES;[self.window.contentView addSubview:self.button];
 NSMenu *menu=[NSMenu new];NSMenuItem *item=[NSMenuItem new];[menu addItem:item];NSMenu *appMenu=[NSMenu new];item.submenu=appMenu;
 [appMenu addItemWithTitle:@"Open control panel" action:@selector(openPanel:) keyEquivalent:@"o"].target=self;
 [appMenu addItemWithTitle:@"Quit Airlock" action:@selector(terminate:) keyEquivalent:@"q"];NSApp.mainMenu=menu;
 [self.window center];[self.window makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];[self prepare];
}
- (void)ready:(NSDictionary *)record {
 dispatch_async(dispatch_get_main_queue(),^{if(self.quitting)return;self.preparing=NO;self.url=[NSURL URLWithString:record[@"url"]];self.serverPID=record[@"pid"];[self.spinner stopAnimation:nil];self.spinner.hidden=YES;self.button.hidden=NO;self.button.title=@"Open control panel";self.detail.stringValue=@"Ready. Keep this app open while your AI uses your context.";[[NSWorkspace sharedWorkspace] openURL:self.url];[self.window orderOut:nil];});
}
- (void)failed {
 dispatch_async(dispatch_get_main_queue(),^{self.preparing=NO;[self.spinner stopAnimation:nil];self.spinner.hidden=YES;self.button.hidden=NO;self.button.title=@"Try again";self.detail.stringValue=@"Setup could not finish. Check your internet connection and allow any macOS Keychain prompt, then try again. Your data has not been reset.";[self.window makeKeyAndOrderFront:nil];});
}
- (void)prepare {
 if(self.preparing)return;self.preparing=YES;self.button.hidden=YES;self.spinner.hidden=NO;[self.spinner startAnimation:nil];
 dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
  NSDictionary *existing=[self session];if(existing){[self ready:existing];return;}
  [[NSFileManager defaultManager] createDirectoryAtPath:self.base withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@0700} error:nil];
  NSString *resource=NSBundle.mainBundle.resourcePath;NSTask *task=[NSTask new];task.executableURL=[NSURL fileURLWithPath:@"/bin/bash"];task.arguments=@[[resource stringByAppendingPathComponent:@"bootstrap.sh"],[resource stringByAppendingPathComponent:@"payload"],self.base];
  NSMutableDictionary *env=[NSProcessInfo.processInfo.environment mutableCopy];if(self.profileHome)env[@"PRIVATE_AI_PROFILE_HOME"]=self.profileHome;task.environment=env;
  task.standardOutput=[NSFileHandle fileHandleForWritingAtPath:@"/dev/null"];task.standardError=[NSFileHandle fileHandleForWritingAtPath:@"/dev/null"];task.standardInput=[NSFileHandle fileHandleForReadingAtPath:@"/dev/null"];self.task=task;
  NSError *error=nil;if(![task launchAndReturnError:&error]){[self failed];return;}
  while(task.running&&!self.quitting){NSString *progress=[NSString stringWithContentsOfFile:[self.base stringByAppendingPathComponent:@"progress.txt"] encoding:NSUTF8StringEncoding error:nil];if(progress.length&&progress.length<200)dispatch_async(dispatch_get_main_queue(),^{self.detail.stringValue=progress;});[NSThread sleepForTimeInterval:.4];}
  if(self.quitting)return;NSDictionary *record=[self session];if(task.terminationStatus==0&&record)[self ready:record];else[self failed];
 });
}
- (void)openPanel:(id)sender { if(self.preparing){[self.window makeKeyAndOrderFront:nil];return;}[self prepare]; }
- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag { [self openPanel:nil];return YES; }
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender { return NO; }
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender { self.quitting=YES;if(self.task.running)[self.task terminate];NSDictionary *live=[self session];if(self.serverPID.intValue>1&&[live[@"pid"] isEqual:self.serverPID])kill(self.serverPID.intValue,SIGTERM);return NSTerminateNow; }
@end
int main(int argc,const char *argv[]){@autoreleasepool{umask(0077);NSApplication *app=NSApplication.sharedApplication;PrivacyLauncher *delegate=[PrivacyLauncher new];app.delegate=delegate;[app setActivationPolicy:NSApplicationActivationPolicyRegular];[app run];}return 0;}
