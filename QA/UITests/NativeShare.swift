import XCTest

final class NativeShare: XCTestCase {
    let safari = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")
    let spring = XCUIApplication(bundleIdentifier: "com.apple.springboard")

    func button(_ text: String, in app: XCUIApplication) -> XCUIElement {
        app.buttons.matching(NSPredicate(format:"label ==[c] %@", text)).firstMatch
    }
    func find(_ label: String, in root: XCUIElement) -> XCUIElement {
        root.descendants(matching: .any).matching(NSPredicate(format:"label ==[c] %@", label)).firstMatch
    }
    func testWebShareCancelledWithoutSending() throws {
        continueAfterFailure = false
        let host = XCUIApplication()
        host.launch()
        host.buttons["Open local Airlock in Safari"].tap()
        let more = button("Share an excerpt", in: safari)
        for _ in 0..<8 where !more.exists {
            if more.waitForExistence(timeout: 2) { break }
            for text in ["Continue","Not Now","Start Page","Start Using Safari","Use Safari","Get Started","Done","Open"] {
                let option = button(text,in:safari)
                if option.exists && option.isHittable { option.tap(); break }
            }
        }
        XCTAssertTrue(more.waitForExistence(timeout: 14), "Safari onboarding or page missing. " + safari.debugDescription)
        more.tap()
        let input = safari.webViews.textViews.firstMatch
        XCTAssertTrue(input.waitForExistence(timeout: 8), safari.debugDescription)
        input.tap()
        input.typeText("Fictional preview cedar. Email editor@example.org.")
        if safari.keyboards.count > 0 {
            let done = button("Done",in:safari)
            if done.exists && done.isHittable { done.tap() }
        }
        let review = button("Review excerpt", in: safari)
        XCTAssertTrue(review.exists, safari.debugDescription)
        if !review.isHittable { safari.webViews.firstMatch.swipeUp() }
        review.tap()
        let share = button("Share reviewed text", in: safari)
        XCTAssertTrue(share.waitForExistence(timeout: 10), safari.debugDescription)
        let filtered = safari.webViews.descendants(matching:.any).matching(NSPredicate(format:"value CONTAINS[c] %@ AND value CONTAINS[c] %@", "cedar","[email-")).firstMatch
        XCTAssertTrue(filtered.exists, safari.debugDescription)
        let prior = try XCTUnwrap(filtered.value as? String)
        XCTAssertFalse(prior.contains("example.org"))
        if !share.isHittable { safari.webViews.firstMatch.swipeUp() }
        share.tap()
        var sheetApp: XCUIApplication?
        var matched = [String]()
        for _ in 0..<15 {
            for candidate in [safari,spring] {
                let markers = ["AirDrop","Messages","Copy","Mail","More","Add to Quick Note","Save to Files"].filter { s in
                    let e = find(s,in:candidate); return e.exists && e.isHittable
                }
                if markers.count >= 2 { sheetApp = candidate; matched = markers; break }
            }
            if sheetApp != nil { break }
            Thread.sleep(forTimeInterval: 0.2)
        }
        let active = try XCTUnwrap(sheetApp, "No native activity sheet. Safari: " + safari.debugDescription + " SpringBoard: " + spring.debugDescription)
        print("NATIVE-SHARE: system activity choices visible: " + matched.joined(separator:", "))
        var dismissed = false
        for label in ["Close","Close Share Sheet","Cancel","Dismiss","Dismiss Share Sheet"] {
            let action = button(label, in:active)
            if action.exists && action.isHittable {
                action.tap()
                dismissed = true
                break
            }
        }
        if !dismissed {
            let grip = active.descendants(matching:.any).matching(NSPredicate(format:"label CONTAINS[c] %@ OR identifier CONTAINS[c] %@", "grabber","grabber")).firstMatch
            if grip.exists && grip.isHittable {
                grip.coordinate(withNormalizedOffset: CGVector(dx:0.5,dy:0.5)).press(forDuration:0.1,thenDragTo:active.coordinate(withNormalizedOffset:CGVector(dx:0.5,dy:0.96)))
            } else {
                active.coordinate(withNormalizedOffset:CGVector(dx:0.5,dy:0.48)).press(forDuration:0.15,thenDragTo:active.coordinate(withNormalizedOffset:CGVector(dx:0.5,dy:0.98)))
            }
        }
        let returned = NSPredicate { _,_ in
            let choices = matched.filter { s in let item = self.find(s,in:active); return item.exists && item.isHittable }
            return choices.count < 2 && share.exists && share.isHittable
        }
        XCTAssertEqual(XCTWaiter.wait(for:[XCTNSPredicateExpectation(predicate:returned,object:nil)],timeout:10),.completed, "Share sheet still displayed: " + active.debugDescription)
        XCTAssertEqual(filtered.value as? String,prior)
        XCTAssertFalse((filtered.value as? String ?? "").contains("example.org"))
        print("NATIVE-SHARE: cancelled, reviewed text retained, no app selected.")
    }
}
