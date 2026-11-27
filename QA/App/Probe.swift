import UIKit

@main
final class Probe: UIResponder, UIApplicationDelegate {
    var window: UIWindow?
    func application(_ app: UIApplication, didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey:Any]?) -> Bool {
        let view = UIViewController()
        window = UIWindow(frame: UIScreen.main.bounds)
        window?.rootViewController = view
        window?.makeKeyAndVisible()
        let link = UIButton(type: .system)
        link.setTitle("Open local Airlock in Safari", for: .normal)
        link.frame = CGRect(x: 12, y: 160, width: 335, height: 60)
        link.addTarget(self, action: #selector(openPage), for: .touchUpInside)
        view.view.addSubview(link)
        return true
    }
    @objc func openPage() { UIApplication.shared.open(URL(string:"https://127.0.0.1:8742/iphone/#connect")!) }
}
