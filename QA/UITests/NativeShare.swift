import XCTest

final class NativeShare: XCTestCase {
    let safari = XCUIApplication()
    let spring = XCUIApplication(bundleIdentifier: "com.apple.springboard")

    func button(_ text: String, in app: XCUIApplication) -> XCUIElement {
        app.buttons.matching(NSPredicate(format:"label ==[c] %@", text)).firstMatch
    }
    func find(_ label: String, in root: XCUIElement) -> XCUIElement {
        root.descendants(matching: .any).matching(NSPredicate(format:"label ==[c] %@", label)).firstMatch
    }
    func testWebShareCancelledWithoutSending() throws {
        continueAfterFailure = false
        safari.launch()
        let state = safari.staticTexts["fixture-state"]
        XCTAssertTrue(state.waitForExistence(timeout: 20), safari.debugDescription)
        let ready = NSPredicate(format:"label CONTAINS %@ AND label ENDSWITH %@", "[email-","ready")
        XCTAssertEqual(XCTWaiter.wait(for:[XCTNSPredicateExpectation(predicate:ready,object:state)],timeout:30),.completed,safari.debugDescription)
        let prior = state.label
        XCTAssertFalse(prior.contains("example.org"))
        let share = button("Share reviewed text", in:safari)
        XCTAssertTrue(share.exists && share.isHittable, safari.debugDescription)
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
        XCTAssertEqual(XCTWaiter.wait(for:[XCTNSPredicateExpectation(predicate:ready,object:state)],timeout:8),.completed)
        XCTAssertEqual(state.label,prior)
        XCTAssertFalse(state.label.contains("example.org"))
        print("NATIVE-SHARE: cancelled, reviewed text retained, no app selected.")
    }
}
