#import "WorkspacePanel.m"
#import <sys/stat.h>
#import <signal.h>

@interface PrivacyLauncher : NSObject <NSApplicationDelegate, NSURLSessionTaskDelegate>
@property NSWindow *window;
@property AirlockPanel *panel;
@property NSView *startup;
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
@property BOOL updating;
@property BOOL updateReady;
@property BOOL checkedAutomatically;
@property NSTask *updateTask;
@property NSMenuItem *automaticUpdatesItem;
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
 self.window=[[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,640,536) styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable|NSWindowStyleMaskMiniaturizable|NSWindowStyleMaskResizable backing:NSBackingStoreBuffered defer:NO];
 self.window.title=@"Airlock";self.window.releasedWhenClosed=NO;self.window.contentMinSize=NSMakeSize(350,300);
 self.startup=self.window.contentView;
 self.detail=[self label:@"Opening Airlock…" frame:NSMakeRect(60,233,520,44) size:15];
 self.detail.autoresizingMask=NSViewMinYMargin|NSViewMaxYMargin|NSViewWidthSizable;
 self.spinner=[[NSProgressIndicator alloc] initWithFrame:NSMakeRect(308,283,24,24)];self.spinner.style=NSProgressIndicatorStyleSpinning;
 self.spinner.autoresizingMask=NSViewMinXMargin|NSViewMaxXMargin|NSViewMinYMargin|NSViewMaxYMargin;[self.startup addSubview:self.spinner];
 self.button=[NSButton buttonWithTitle:@"Try again" target:self action:@selector(openPanel:)];self.button.frame=NSMakeRect(245,187,150,32);self.button.hidden=YES;
 self.button.autoresizingMask=self.spinner.autoresizingMask;[self.startup addSubview:self.button];
 NSMenu *menu=[NSMenu new];NSMenuItem *item=[NSMenuItem new];[menu addItem:item];NSMenu *appMenu=[NSMenu new];item.submenu=appMenu;
 [appMenu addItemWithTitle:@"About Airlock" action:@selector(about:) keyEquivalent:@""].target=self;
 [appMenu addItemWithTitle:@"Open Airlock" action:@selector(openPanel:) keyEquivalent:@"o"].target=self;
 [appMenu addItemWithTitle:@"Check for Updates…" action:@selector(checkForUpdates:) keyEquivalent:@""].target=self;
 self.automaticUpdatesItem=[appMenu addItemWithTitle:@"Check for updates on launch" action:@selector(toggleUpdates:) keyEquivalent:@""];self.automaticUpdatesItem.target=self;
 [NSUserDefaults.standardUserDefaults registerDefaults:@{@"AirlockCheckUpdatesOnLaunch":@YES}];self.automaticUpdatesItem.state=[NSUserDefaults.standardUserDefaults boolForKey:@"AirlockCheckUpdatesOnLaunch"]?NSControlStateValueOn:NSControlStateValueOff;
 [appMenu addItemWithTitle:@"Version history" action:@selector(versionHistory:) keyEquivalent:@""].target=self;
 [appMenu addItem:NSMenuItem.separatorItem];
 [appMenu addItemWithTitle:@"Quit Airlock" action:@selector(terminate:) keyEquivalent:@"q"];NSMenuItem *editItem=[NSMenuItem new];editItem.title=@"Edit";[menu addItem:editItem];NSMenu *edit=[[NSMenu alloc] initWithTitle:@"Edit"];editItem.submenu=edit;
 for(NSArray *command in @[@[@"Undo",@"undo:",@"z"],@[@"Redo",@"redo:",@"Z"],@[@"Cut",@"cut:",@"x"],@[@"Copy",@"copy:",@"c"],@[@"Paste",@"paste:",@"v"],@[@"Select All",@"selectAll:",@"a"]])
     [edit addItemWithTitle:command[0] action:NSSelectorFromString(command[1]) keyEquivalent:command[2]];
 NSApp.mainMenu=menu;
 [self.window center];[self.window makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];[self prepare];
}
- (void)ready:(NSDictionary *)record {
 dispatch_async(dispatch_get_main_queue(),^{if(self.quitting)return;self.preparing=NO;self.url=[NSURL URLWithString:record[@"url"]];self.serverPID=record[@"pid"];[self.spinner stopAnimation:nil];self.spinner.hidden=YES;[self.panel detach];
  self.panel=[[AirlockPanel alloc] initWithWindow:self.window entry:self.url];
  __weak PrivacyLauncher *weakSelf=self;
  self.panel.setAutomatic=^(BOOL enabled){[weakSelf setAutomaticUpdates:enabled];};
  self.panel.checkUpdates=^{[weakSelf checkUpdates:YES];};
  self.window.contentView=self.panel.view;[self.window makeKeyAndOrderFront:nil];[self.window makeFirstResponder:self.panel.view];
  if(!self.checkedAutomatically){self.checkedAutomatically=YES;
   if([NSProcessInfo.processInfo.arguments containsObject:@"--update-restored"])[self alert:@"Previous version restored" message:@"The update could not start. Airlock restored the previous app. Your library has not been reset."];
   if(![NSProcessInfo.processInfo.arguments containsObject:@"--no-update-check"]&&[NSUserDefaults.standardUserDefaults boolForKey:@"AirlockCheckUpdatesOnLaunch"])[self checkUpdates:NO];
  }
 });
}
- (void)failed {
 dispatch_async(dispatch_get_main_queue(),^{self.preparing=NO;[self.spinner stopAnimation:nil];self.spinner.hidden=YES;self.button.hidden=NO;self.button.title=@"Try again";self.detail.stringValue=@"Setup could not finish. Check your internet connection and try again.";[self.window makeKeyAndOrderFront:nil];});
}
- (void)prepare {
 if(self.preparing)return;self.preparing=YES;self.button.hidden=YES;self.spinner.hidden=NO;[self.spinner startAnimation:nil];
 dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
  NSString *resource=NSBundle.mainBundle.resourcePath;
  NSDictionary *release=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:[resource stringByAppendingPathComponent:@"payload/release.json"]] options:0 error:nil];
  NSDictionary *existing=[self session];
  if(existing&&[existing[@"version"] isEqual:release[@"version"]]&&[existing[@"mode"] isEqual:@"safe-test"]){[self ready:existing];return;}
  if(existing){
   // Replace only this installation's authenticated service; keep its vault and key.
   int pid=[existing[@"pid"] intValue];if(pid<=1){[self failed];return;}
   kill(pid,SIGTERM);
   for(int i=0;i<40&&[self session]&&!self.quitting;i++)[NSThread sleepForTimeInterval:.25];
   if(self.quitting)return;if([self session]){[self failed];return;}
  }
  [[NSFileManager defaultManager] createDirectoryAtPath:self.base withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@0700} error:nil];
  NSTask *task=[NSTask new];task.executableURL=[NSURL fileURLWithPath:@"/bin/bash"];task.arguments=@[[resource stringByAppendingPathComponent:@"bootstrap.sh"],[resource stringByAppendingPathComponent:@"payload"],self.base];
  NSMutableDictionary *env=[NSProcessInfo.processInfo.environment mutableCopy];if(self.profileHome)env[@"PRIVATE_AI_PROFILE_HOME"]=self.profileHome;task.environment=env;
  task.standardOutput=[NSFileHandle fileHandleForWritingAtPath:@"/dev/null"];task.standardError=[NSFileHandle fileHandleForWritingAtPath:@"/dev/null"];task.standardInput=[NSFileHandle fileHandleForReadingAtPath:@"/dev/null"];self.task=task;
  NSError *error=nil;if(![task launchAndReturnError:&error]){[self failed];return;}
  while(task.running&&!self.quitting){NSString *progress=[NSString stringWithContentsOfFile:[self.base stringByAppendingPathComponent:@"progress.txt"] encoding:NSUTF8StringEncoding error:nil];if(progress.length&&progress.length<200)dispatch_async(dispatch_get_main_queue(),^{self.detail.stringValue=progress;});[NSThread sleepForTimeInterval:.4];}
  if(self.quitting)return;NSDictionary *record=[self session];if(task.terminationStatus==0&&record)[self ready:record];else[self failed];
 });
}
- (void)alert:(NSString *)title message:(NSString *)message {
 NSAlert *alert=[NSAlert new];alert.messageText=title;alert.informativeText=message;[alert addButtonWithTitle:@"OK"];[NSApp activateIgnoringOtherApps:YES];[alert runModal];
}
- (void)about:(id)sender {
 NSDictionary *release=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:[NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"payload/release.json"]] options:0 error:nil];
 [self alert:@"Airlock" message:[NSString stringWithFormat:@"Version %@\n\nUpdates are checked against a signed release from Airlock’s GitHub build. Checks send no library content. Installation requires your click.",release[@"version"]?:@"Unknown"]];
}
- (void)versionHistory:(id)sender { [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:@"https://github.com/EPparv/airlock/releases"]]; }
- (void)toggleUpdates:(id)sender { [self setAutomaticUpdates:![NSUserDefaults.standardUserDefaults boolForKey:@"AirlockCheckUpdatesOnLaunch"]]; }
- (void)setAutomaticUpdates:(BOOL)value {
 [NSUserDefaults.standardUserDefaults setBool:value forKey:@"AirlockCheckUpdatesOnLaunch"];self.automaticUpdatesItem.state=value?NSControlStateValueOn:NSControlStateValueOff;
}
- (NSTask *)updateCommand:(NSArray *)arguments {
 NSTask *task=[NSTask new];task.executableURL=[NSURL fileURLWithPath:[self.base stringByAppendingPathComponent:@"runtime/venv/bin/python"]];
 task.currentDirectoryURL=[NSURL fileURLWithPath:[self.base stringByAppendingPathComponent:@"app"]];
 task.arguments=[@[@"-m",@"privacy_layer.updater"] arrayByAddingObjectsFromArray:arguments];
 NSMutableDictionary *env=[NSProcessInfo.processInfo.environment mutableCopy];[env removeObjectForKey:@"PYTHONPATH"];[env removeObjectForKey:@"PYTHONHOME"];env[@"PYTHONDONTWRITEBYTECODE"]=@"1";task.environment=env;
 task.standardInput=[NSFileHandle fileHandleForReadingAtPath:@"/dev/null"];task.standardError=[NSFileHandle fileHandleForWritingAtPath:@"/dev/null"];return task;
}
- (void)checkForUpdates:(id)sender { [self checkUpdates:YES]; }
- (void)checkUpdates:(BOOL)manual {
 if(self.preparing||self.updating){if(manual)[self alert:@"Airlock is busy" message:@"Let the current setup or update finish, then try again."];return;}
 self.updating=YES;
 dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
  NSTask *task=[self updateCommand:@[@"check",@"--base",self.base]];self.updateTask=task;NSPipe *pipe=[NSPipe pipe];task.standardOutput=pipe;
  NSError *error=nil;BOOL launched=[task launchAndReturnError:&error];NSDictionary *result=nil;
  if(launched){dispatch_after(dispatch_time(DISPATCH_TIME_NOW,90*NSEC_PER_SEC),dispatch_get_global_queue(QOS_CLASS_UTILITY,0),^{if(task.running)[task terminate];});NSData *data=[pipe.fileHandleForReading readDataToEndOfFile];[task waitUntilExit];if(data.length<32768)result=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];}
  dispatch_async(dispatch_get_main_queue(),^{self.updating=NO;if(self.quitting)return;
   if(!launched||task.terminationStatus!=0||![result isKindOfClass:NSDictionary.class]||result[@"error"]){if(manual)[self alert:@"Could not check for updates" message:result[@"error"]?:@"Check your connection and try again. Your current app is unchanged."];return;}
   if(![result[@"available"] boolValue]){if(manual)[self alert:@"You’re up to date" message:[NSString stringWithFormat:@"Airlock %@ is installed.",result[@"current"]]];return;}
   if(![result[@"compatible"] boolValue]){if(manual)[self alert:@"A newer version needs a newer macOS" message:@"Your current Airlock will keep working. See Version history for the new version’s requirements."];return;}
   NSAlert *alert=[NSAlert new];alert.messageText=[NSString stringWithFormat:@"Airlock %@ is available",result[@"latest"]];alert.informativeText=[NSString stringWithFormat:@"%@\n\nUpdate and restart Airlock now? Your library and connections stay in place. Personal access closes on restart.",result[@"notes"]?:@""];[alert addButtonWithTitle:@"Update and Restart"];[alert addButtonWithTitle:@"Later"];[NSApp activateIgnoringOtherApps:YES];
   if([alert runModal]==NSAlertFirstButtonReturn)[self installUpdate:result];
  });
 });
}
- (void)installUpdate:(NSDictionary *)release {
 self.window.contentView=self.startup;self.updating=YES;self.updateReady=NO;self.button.hidden=YES;self.spinner.hidden=NO;[self.spinner startAnimation:nil];self.detail.stringValue=@"Downloading and verifying the update…";[self.window makeKeyAndOrderFront:nil];
 NSString *status=[self.base stringByAppendingPathComponent:[NSString stringWithFormat:@"update-%@.json",NSUUID.UUID.UUIDString]];
 NSMutableArray *args=[@[@"install",@"--app",NSBundle.mainBundle.bundlePath,@"--base",self.base,@"--expected-build",[release[@"build"] stringValue],@"--parent-pid",[NSString stringWithFormat:@"%d",getpid()],@"--status",status] mutableCopy];if(self.profileHome)[args addObjectsFromArray:@[@"--profile-home",self.profileHome]];
 dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
  NSTask *task=[self updateCommand:args];self.updateTask=task;task.standardOutput=[NSFileHandle fileHandleForWritingAtPath:@"/dev/null"];NSError *error=nil;BOOL launched=[task launchAndReturnError:&error];NSDictionary *state=nil;
  NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:180];
  while(launched&&task.running&&!self.quitting){
   NSData *data=[NSData dataWithContentsOfFile:status];if(data.length&&data.length<8192)state=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
   if([state[@"phase"] isEqual:@"ready"]){dispatch_async(dispatch_get_main_queue(),^{self.updateReady=YES;[NSApp terminate:nil];});return;}
   if([deadline timeIntervalSinceNow]<0){[task terminate];break;}[NSThread sleepForTimeInterval:.2];
  }
  NSData *data=[NSData dataWithContentsOfFile:status];if(data.length&&data.length<8192)state=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
  [[NSFileManager defaultManager] removeItemAtPath:status error:nil];
  dispatch_async(dispatch_get_main_queue(),^{self.updating=NO;if(self.quitting)return;[self.spinner stopAnimation:nil];self.spinner.hidden=YES;self.button.hidden=NO;if(self.panel)self.window.contentView=self.panel.view;[self alert:@"Update not installed" message:state[@"message"]?:@"The update could not be verified or downloaded. Your current app is unchanged. Try again from Check for Updates."];});
 });
}
- (void)openPanel:(id)sender { [self.window makeKeyAndOrderFront:nil];if(self.preparing||self.updating||self.panel)return;[self prepare]; }
- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag { [self openPanel:nil];return YES; }
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender { return NO; }
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender { self.quitting=YES;if(self.task.running)[self.task terminate];if(self.updateTask.running&&!self.updateReady)[self.updateTask terminate];NSDictionary *live=[self session];if(self.serverPID.intValue>1&&[live[@"pid"] isEqual:self.serverPID])kill(self.serverPID.intValue,SIGTERM);return NSTerminateNow; }
@end
int main(int argc,const char *argv[]){@autoreleasepool{umask(0077);NSApplication *app=NSApplication.sharedApplication;PrivacyLauncher *delegate=[PrivacyLauncher new];app.delegate=delegate;[app setActivationPolicy:NSApplicationActivationPolicyRegular];[app run];}return 0;}
