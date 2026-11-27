import Foundation
import XCTest

final class SafariPair: XCTestCase {
    private let safari = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")

    private func text(_ phrase: String, in page: XCUIElement) -> XCUIElement {
        page.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", phrase)).firstMatch
    }

    private func button(_ title: String, in target: XCUIElement) -> XCUIElement {
        target.buttons.matching(NSPredicate(format: "label ==[c] %@", title)).firstMatch
    }

    private func waitFor(_ seconds: TimeInterval, _ condition: () -> Bool) -> Bool {
        let end = Date().addingTimeInterval(seconds)
        repeat {
            if condition() { return true }
            Thread.sleep(forTimeInterval: 0.25)
        } while Date() < end
        return condition()
    }

    private func searchField(in page: XCUIElement) -> XCUIElement {
        let search = page.searchFields.firstMatch
        return search.exists ? search : page.textFields.firstMatch
    }

    private func failure(_ step: String) -> ProbeFailure {
        let page = safari.webViews.firstMatch
        let hints = [
            ("connect_visible", "Connect to Mac"),
            ("scoped", "shared record"),
            ("connected_controls", "Check actions"),
            ("closed", "connection has closed"),
            ("offline", "couldn’t reach"),
            ("unavailable", "connection is unavailable"),
            ("incomplete_status", "incomplete connection status"),
            ("no_session", "didn’t return a phone session"),
            ("malformed_response", "did not return an Airlock response"),
            ("foreign_origin", "origin"),
            ("expired", "expired"),
            ("not_approved", "denied"),
            ("welcome", "Pair iPhone"),
            ("pending", "pending"),
            ("disconnected", "Disconnected.")
        ]
        for (name, phrase) in hints where text(phrase, in: page).exists {
            print("AIRLOCK_SAFARI_HINT " + name)
        }
        return .missing(step)
    }

    private func tap(_ element: XCUIElement, step: String) throws {
        guard element.waitForExistence(timeout: 12) else { throw failure(step) }
        for _ in 0..<3 {
            if element.isHittable { break }
            safari.swipeUp()
        }
        element.tap()
    }

    private func openFreshPairing() throws {
        let launched = expectation(description: "Fresh isolated fixture available")
        var status = 0
        let url = URL(string: "https://127.0.0.1:39791/qa/start")!
        URLSession.shared.dataTask(with: url) { _, response, _ in
            status = (response as? HTTPURLResponse)?.statusCode ?? 0
            launched.fulfill()
        }.resume()
        guard XCTWaiter.wait(for: [launched], timeout: 35) == .completed,
              [200, 204].contains(status) else {
            print("AIRLOCK_SAFARI_HINT fixture_start_status_" + String(status))
            throw ProbeFailure.missing("fixture coordinator")
        }
    }

    private func waitForPairButton(_ target: XCUIElement) -> Bool {
        for _ in 0..<6 {
            if target.waitForExistence(timeout: 3) { return true }
            for title in ["Not Now", "Continue", "Done", "Start Browsing"] {
                let control = button(title, in: safari)
                if control.exists && control.isHittable {
                    control.tap()
                    break
                }
            }
        }
        return target.exists
    }

    private enum ProbeFailure: Error { case missing(String) }

    func testPairAndDisconnectInMobileSafari() throws {
        continueAfterFailure = false
        safari.activate()
        try openFreshPairing()
        let page = safari.webViews.firstMatch
        let connect = button("Connect to Mac", in: page)
        guard waitForPairButton(connect) else { throw failure("Connect to Mac in Mobile Safari") }
        try tap(connect, step: "connect")
        guard waitFor(20, {
            self.text("1 shared record", in: page).exists ||
            (self.searchField(in: page).exists && self.button("Check actions", in: page).exists)
        }) else { throw failure("Phone did not receive its Mac scope") }
        print("AIRLOCK_SAFARI_PAIR connected")

        let searchInput = searchField(in: page)
        try tap(searchInput, step: "query field")
        searchInput.typeText("Cypress\n")
        let result = text("Thursday", in: page)
        if !result.waitForExistence(timeout: 4) {
            try tap(button("Search", in: page), step: "submit query")
        }
        guard result.waitForExistence(timeout: 15) else { throw failure("approved synthetic result") }
        XCTAssertFalse(text("robin@example.test", in: page).exists, "Raw fictional address was returned")
        XCTAssertFalse(text("Vermilion", in: page).exists, "Unselected record was returned")
        XCTAssertFalse(text("device-only stone", in: page).exists, "Device-only record was returned")
        print("AIRLOCK_SAFARI_PAIR scoped_read")

        let done = button("Done", in: safari)
        if safari.keyboards.firstMatch.exists && done.exists && done.isHittable { done.tap() }
        let checkActions = button("Check actions", in: page)
        try tap(checkActions, step: "list assigned actions")
        let request = button("Request Mac approval", in: page)
        try tap(request, step: "request Mac approval")
        guard waitFor(16, {
            self.text("Waiting for approval on your Mac", in: page).exists ||
            self.text("pending", in: page).exists
        }) else { throw failure("Mac approval queue") }
        print("AIRLOCK_SAFARI_PAIR pending_mac_approval")

        try tap(button("Disconnect this iPhone", in: page), step: "disconnect")
        guard waitFor(16, {
            !checkActions.exists && !result.exists &&
            (self.text("Disconnected.", in: page).exists || self.text("Pair iPhone", in: page).exists)
        }) else { throw failure("Phone did not discard the active session") }
        print("AIRLOCK_SAFARI_PAIR disconnected")
    }
}
