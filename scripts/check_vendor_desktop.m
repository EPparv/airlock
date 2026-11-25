// Exercise the shipping macOS launcher with a real app on a disposable GitHub runner.
#import "../macos/WorkspacePanel.m"

static void require(BOOL condition, NSString *message) {
    if (!condition) {
        fprintf(stderr, "%s\n", message.UTF8String);
        exit(1);
    }
}

static BOOL waitUntil(BOOL (^check)(void)) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:60];
    while (!check() && deadline.timeIntervalSinceNow > 0) {
        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
    }
    return check();
}

static void openDesktop(AirlockPanel *panel, NSString *agent, BOOL running) {
    __block BOOL done = NO;
    __block NSDictionary *reply = nil;
    __block NSString *problem = nil;
    [panel openClient:agent reply:^(id result, NSString *error) {
        reply = result;
        problem = error;
        done = YES;
    }];
    require(waitUntil(^BOOL{ return done; }), @"Timed out waiting for the macOS launcher.");
    require(!problem && [reply[@"opened"] boolValue], problem ?: @"The launcher did not open the app.");
    require([reply[@"wasRunning"] boolValue] == running, @"Unexpected cold or running activation result.");
    require([reply[@"newChatRequested"] boolValue] == [agent isEqual:@"codex"],
            @"The installed app did not accept the expected new-chat or ordinary launch request.");
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        require(argc == 3, @"Usage: check-vendor-desktop codex|cursor /path/to/app");
        NSString *agent = [NSString stringWithUTF8String:argv[1]];
        require([agent isEqual:@"codex"] || [agent isEqual:@"cursor"], @"Unknown client.");
        NSBundle *installed = [NSBundle bundleWithPath:[NSString stringWithUTF8String:argv[2]]];
        NSString *identifier = [agent isEqual:@"codex"] ? @"com.openai.codex" : @"com.todesktop.230313mzl4w4u92";
        require([installed.bundleIdentifier isEqual:identifier], @"Unexpected vendor bundle identifier.");
        [NSApplication.sharedApplication setActivationPolicy:NSApplicationActivationPolicyAccessory];
        [NSApp finishLaunching];
        AirlockPanel *panel = [AirlockPanel new];
        NSArray *(^instances)(void) = ^{ return [NSRunningApplication runningApplicationsWithBundleIdentifier:identifier]; };
        require(instances().count == 0, @"Expected a fresh runner with the selected desktop app closed.");
        openDesktop(panel, agent, NO);
        require(waitUntil(^BOOL{ return instances().count == 1; }), @"No unique running vendor app was found.");
        NSRunningApplication *first = instances().firstObject;
        require([first.bundleURL.URLByResolvingSymlinksInPath.path isEqual:installed.bundleURL.URLByResolvingSymlinksInPath.path],
                @"The running app came from an unexpected location.");
        require(waitUntil(^BOOL{ return first.finishedLaunching && !first.terminated; }), @"The vendor app did not finish launching.");
        openDesktop(panel, agent, YES);
        NSRunningApplication *second = instances().firstObject;
        require(instances().count == 1 && !first.terminated && second.processIdentifier == first.processIdentifier,
                @"Reopening the app replaced its process.");
        printf("%s version %s: cold launch and second activation used PID %d.\n", identifier.UTF8String,
               [[installed objectForInfoDictionaryKey:@"CFBundleShortVersionString"] UTF8String], first.processIdentifier);
    }
    return 0;
}
