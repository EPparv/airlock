import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var task: Process?
    private var window: NSWindow?
    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "Quit Airlock", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        NSApp.mainMenu = menu
        guard let settingsURL = Bundle.main.url(forResource: "workspace", withExtension: "json"),
              let data = try? Data(contentsOf: settingsURL),
              let settings = try? JSONSerialization.jsonObject(with: data) as? [String:String],
              let root = settings["path"],
              FileManager.default.isExecutableFile(atPath: root + "/.venv/bin/python") else {
            fail("Your workspace could not be found. Keep the Privacy Layer folder in its original location, then open this app again."); return
        }
        let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 380, height: 150), styleMask: [.titled, .closable], backing: .buffered, defer: false)
        panel.title = "Airlock"; panel.center()
        let label = NSTextField(labelWithString: "Opening your private workspace…")
        label.font = .systemFont(ofSize: 16, weight: .medium); label.frame = NSRect(x: 40, y: 85, width: 320, height: 25)
        let detail = NSTextField(labelWithString: "Your control panel will open in your browser.")
        detail.textColor = .secondaryLabelColor; detail.frame = NSRect(x: 40, y: 58, width: 320, height: 22)
        let progress = NSProgressIndicator(frame: NSRect(x: 40, y: 29, width: 300, height: 8))
        progress.style = .bar; progress.isIndeterminate = true; progress.startAnimation(nil)
        panel.contentView?.addSubview(label); panel.contentView?.addSubview(detail); panel.contentView?.addSubview(progress)
        panel.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true); window = panel
        do {
            let logURL = URL(fileURLWithPath: root).appendingPathComponent(".private/app-launch.log")
            if !FileManager.default.fileExists(atPath: logURL.path) {
                FileManager.default.createFile(atPath: logURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
            }
            let log = try FileHandle(forWritingTo: logURL); try log.seekToEnd()
            let process = Process(); process.executableURL = URL(fileURLWithPath: root + "/.venv/bin/python")
            process.currentDirectoryURL = URL(fileURLWithPath: root)
            process.arguments = ["-m", "privacy_layer.launcher"]
            process.standardInput = FileHandle.nullDevice; process.standardOutput = log; process.standardError = log
            process.terminationHandler = { [weak self] completed in
                try? log.close()
                DispatchQueue.main.async {
                    if completed.terminationStatus == 0 { NSApp.terminate(nil) }
                    else { self?.fail("The local service could not open. Make sure your Mac can access the Airlock workspace, then try again. Your saved data has not been changed.") }
                }
            }
            task = process; try process.run()
        } catch { fail("Airlock could not start its local service. Try opening the app again.") }
    }
    private func fail(_ message: String) {
        window?.orderOut(nil)
        let alert = NSAlert(); alert.messageText = "Couldn't open Airlock"; alert.informativeText = message; alert.alertStyle = .warning
        alert.addButton(withTitle: "OK"); alert.runModal(); NSApp.terminate(nil)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate; app.setActivationPolicy(.regular); app.run()
