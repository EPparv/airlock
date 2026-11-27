import XCTest

final class SafariPair: XCTestCase {
    private let safari = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")

    private func text(_ phrase: String, in page: XCUIElement) -> XCUIElement {
        page.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", phrase)).firstMatch
    }

    private func button(_ title: String, in target: XCUIElement) -> XCUIElement {
        target.buttons.matching(NSPredicate(format: "label ==[c] %@", title)).firstMatch
    }

    private func tap(_ element: XCUIElement, step: String) throws {
        guard element.waitForExistence(timeout: 12) else {
            throw ProbeFailure.missing(step)
        }
        for _ in 0..<3 {
            if element.isHittable { break }
            safari.swipeUp()
        }
        element.tap()
    }

    // A newly-created simulator can show one-time Safari welcome screens.
    // No action is taken outside the simulator or on unrelated applications.
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
        let page = safari.webViews.firstMatch
        let connect = button("Connect to Mac", in: page)
        guard waitForPairButton(connect) else {
            throw ProbeFailure.missing("Connect to Mac in Mobile Safari")
        }
        try tap(connect, step: "connect")
        XCTAssertTrue(text("1 shared record", in: page).waitForExistence(timeout: 20), "Phone did not receive its Mac scope")
        print("AIRLOCK_SAFARI_PAIR connected")

        var searchInput = page.searchFields.firstMatch
        if !searchInput.exists { searchInput = page.textFields.firstMatch }
        try tap(searchInput, step: "query field")
        searchInput.typeText("Cypress\n")
        let result = text("Thursday", in: page)
        if !result.waitForExistence(timeout: 4) {
            try tap(button("Search", in: page), step: "submit query")
        }
        XCTAssertTrue(result.waitForExistence(timeout: 15), "Approved synthetic result was missing")
        XCTAssertFalse(text("robin@example.test", in: page).exists, "Raw fictional address was returned")
        XCTAssertFalse(text("Vermilion", in: page).exists, "Unselected record was returned")
        XCTAssertFalse(text("device-only stone", in: page).exists, "Device-only record was returned")
        print("AIRLOCK_SAFARI_PAIR scoped_read")

        let done = button("Done", in: safari)
        if safari.keyboards.firstMatch.exists && done.exists && done.isHittable { done.tap() }
        try tap(button("Check actions", in: page), step: "list assigned actions")
        let request = button("Request Mac approval", in: page)
        try tap(request, step: "request Mac approval")
        XCTAssertTrue(text("Waiting for approval on your Mac", in: page).waitForExistence(timeout: 16), "Action did not reach Mac approval queue")
        print("AIRLOCK_SAFARI_PAIR pending_mac_approval")

        try tap(button("Disconnect this iPhone", in: page), step: "disconnect")
        XCTAssertTrue(text("Disconnected.", in: page).waitForExistence(timeout: 16), "Disconnect did not complete on the Mac")
        XCTAssertFalse(button("Check actions", in: page).exists)
        XCTAssertFalse(result.exists, "Previously displayed data remained on the disconnected phone")
        print("AIRLOCK_SAFARI_PAIR disconnected")
    }
}
