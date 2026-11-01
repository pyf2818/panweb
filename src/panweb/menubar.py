"""Swift 菜单栏常驻小工具。"""
import os
import shutil
import subprocess

from . import runtime
from .errors import PanwebError

MENUBAR_SWIFT = r"""import AppKit

let home = FileManager.default.homeDirectoryForCurrentUser
let stateFile = home.appendingPathComponent(".panweb/menubar-state.json").path

final class AppDelegate: NSObject, NSApplicationDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    var timer: Timer?

    func applicationDidFinishLaunching(_ _: Notification) {
        let menu = NSMenu()
        let open = NSMenuItem(title: "打开控制台", action: #selector(openConsole), keyEquivalent: "")
        open.target = self
        let stop = NSMenuItem(title: "停止全部发布", action: #selector(stopAll), keyEquivalent: "")
        stop.target = self
        let quit = NSMenuItem(title: "退出菜单栏", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.addItem(open); menu.addItem(stop); menu.addItem(.separator()); menu.addItem(quit)
        item.menu = menu
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in self?.refresh() }
    }

    @objc func openConsole() {
        NSWorkspace.shared.open(URL(string: "http://127.0.0.1:7788")!)
    }

    @objc func stopAll() {
        guard let url = URL(string: "http://127.0.0.1:7788/api/stop") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["target": "all"])
        URLSession.shared.dataTask(with: req).resume()
        refresh()
    }

    func refresh() {
        var title = "◈"
        if let data = FileManager.default.contents(atPath: stateFile),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let online = obj["online"] as? Int {
            title = online > 0 ? "◈ \(online)" : "◈"
        }
        DispatchQueue.main.async { self.item.button?.title = title }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
"""


def core_install_menubar():
    if not shutil.which("swiftc"):
        raise PanwebError(3, "dependency_missing", "未找到 swiftc",
                          "安装 Xcode Command Line Tools 后重试（xcode-select --install）")
    app = os.path.expanduser("~/Applications/panweb-menubar.app")
    macos = os.path.join(app, "Contents", "MacOS")
    os.makedirs(macos, exist_ok=True)
    src = os.path.join(runtime.HOME_DIR, "menubar-main.swift")
    with open(src, "w", encoding="utf-8") as f:
        f.write(MENUBAR_SWIFT)
    bin_path = os.path.join(macos, "panweb-menubar")
    out = subprocess.run(["swiftc", "-O", "-swift-version", "5", src,
                          "-o", bin_path],
                         capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise PanwebError(9, "build_failed",
                          "菜单栏编译失败：%s" % (out.stderr or "")[-400:])
    with open(os.path.join(app, "Contents", "Info.plist"), "w",
              encoding="utf-8") as f:
        f.write("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>panweb-menubar</string>
  <key>CFBundleIdentifier</key><string>com.panweb.menubar</string>
  <key>CFBundleExecutable</key><string>panweb-menubar</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
</dict></plist>""")
    try:
        os.remove(src)
    except OSError:
        pass
    subprocess.Popen([bin_path], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return {"app": app, "binary": bin_path}
