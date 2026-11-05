import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "ui", "src")
BUILT = os.path.join(ROOT, "ui", "index.html")


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8", errors="replace") as fh:
        return fh.read()


def ui(*parts):
    return read(UI, *parts)


class RailGroupContractTests(unittest.TestCase):
    def test_group_state_is_boolean_only_and_marked_up(self):
        src = ui("js", "depgroups.js")
        self.assertIn('const DEP_GROUP_KEYS = ["links", "status", "visitors", '
                      '"history", "process"];', src)
        self.assertIn('const DEP_GROUP_STORE = "panweb-dep-groups";', src)
        self.assertIn("out[k] = !!state[k]", src)
        self.assertIn("localStorage.setItem(DEP_GROUP_STORE, JSON.stringify(out))", src)
        self.assertIn("typeof raw[k] === \"boolean\"", src)
        self.assertIn("links: true, status: true, visitors: false, "
                      "history: false, process: false", src)
        html = ui("index.html")
        for key in ("links", "status", "visitors", "history", "process"):
            self.assertIn('id="dep-group-%s"' % key, html)
            self.assertIn('aria-controls="dep-body-%s"' % key, html)
        self.assertIn('id="dep-actions"', html)
        self.assertIn("position: sticky", ui("styles", "deploy.css"))

    def test_no_pin_value_written_to_storage(self):
        for name in os.listdir(os.path.join(UI, "js")):
            if not name.endswith(".js") or name.startswith("qrcode"):
                continue
            for line in ui("js", name).splitlines():
                if "localStorage" in line and "pin" in line.lower():
                    self.fail("%s 把口令写进 localStorage：%s" % (name, line))
                if "sessionStorage" in line and "pin" in line.lower() and name != "publish.js":
                    self.fail("%s 出现意外口令存储：%s" % (name, line))


class RailFilterContractTests(unittest.TestCase):
    def test_filter_groups_and_memory(self):
        wb = ui("js", "workbench.js")
        self.assertIn('const ASSET_FILTERS = ["all", "online", "offline", '
                      '"expired", "hosted"];', wb)
        self.assertIn('const ASSET_FILTER_KEY = "panweb-asset-filter";', wb)
        self.assertIn("localStorage.setItem(ASSET_FILTER_KEY, f)", wb)
        self.assertIn('let assetFilter = ASSET_FILTERS.includes(', wb)
        self.assertIn('"all"', wb)
        html = ui("index.html")
        for key in ("all", "online", "offline", "expired", "hosted"):
            self.assertIn('data-filter="%s"' % key, html)
            self.assertIn('aria-pressed=', html)
        self.assertIn("清除筛选", wb)

    def test_timeline_is_collapsible_and_global_without_selection(self):
        wb = ui("js", "workbench.js")
        self.assertIn('const RAIL_TL_KEY = "panweb-rail-timeline";', wb)
        self.assertIn('localStorage.setItem(RAIL_TL_KEY, railTimelineOpen ? '
                      '"true" : "false")', wb)
        self.assertIn('api("/api/history?limit=" + GLOBAL_LIMIT)', wb)
        self.assertIn("function loadGlobalTimeline", wb)
        self.assertIn("function showGlobalTimeline", wb)
        self.assertIn("globalPreview", wb)
        self.assertIn("function sortAssets", wb)
        self.assertIn("assetActivity", wb)


class StageContractTests(unittest.TestCase):
    """三栏常驻 + 快捷指令区，对话式入口彻底移除。"""

    def test_three_pane_structure_is_permanent(self):
        pages = ui("partials", "pages.html")
        for marker in ('id="page-apps"', 'id="stage"', 'id="stage-head"', 'id="stage-body"',
                       'id="stage-empty"', 'id="stage-preview"', 'id="stage-create"',
                       'id="stage-quickbar"', 'id="stage-note"', 'id="stage-tools"'):
            self.assertIn(marker, pages)
        html = ui("index.html")
        for marker in ('id="asset-rail"', 'id="viz-rail"', 'id="rail-new"'):
            self.assertIn(marker, html)
        self.assertIn('id="topbar-new"', pages)
        css = ui("styles", "console.css")
        self.assertIn("position: sticky", css)
        self.assertIn("top: 0", css)
        self.assertIn("@media (max-width: 900px)", css)
        self.assertNotIn("chat-log", pages)
        self.assertNotIn("cmd-input", pages)
        self.assertNotIn("cmd-form", pages)
        self.assertNotIn("cmd-hints", pages)
        self.assertNotIn("guide-card", pages)

    def test_no_frontend_command_endpoint_or_composer(self):
        self.assertFalse(os.path.exists(os.path.join(UI, "js", "composer.js")),
                         "composer.js 应已删除")
        self.assertNotIn("js/composer.js", ui("manifest.json"))
        for name in os.listdir(os.path.join(UI, "js")):
            if not name.endswith(".js") or name.startswith("qrcode"):
                continue
            self.assertNotIn("/api/command", ui("js", name),
                             "%s 不应再调用 /api/command" % name)
        self.assertNotIn("fillTemplate", ui("partials", "pages.html"))
        self.assertNotIn("openPublish('port')", ui("partials", "overlays.html"))
        self.assertNotIn('id="pub-overlay"', ui("partials", "overlays.html"))

    def test_capability_map_has_entries_for_every_action(self):
        pages = ui("partials", "pages.html")
        html = ui("index.html")
        ids = ["stage-open", "stage-copy", "stage-refresh", "stage-stop", "stage-republish",
               "quick-port", "quick-pages", "quick-project", "quick-stop", "quick-check",
               "quick-scan", "topbar-new"]
        for item in ids:
            self.assertIn('id="%s"' % item, pages)
        self.assertIn('id="rail-new"', html)
        for item in ("dep-pin-btn", "dep-check-btn", "dep-retry-btn", "dep-republish-btn",
                     "viz-qr", "dep-url", "dep-share-url"):
            self.assertIn('id="%s"' % item, html)
        for fn in ("stageOpen", "stageCopy", "stageRefresh", "stageStop", "stageRepublish",
                   "quickPublish", "quickStopCurrent", "quickCheckCurrent", "quickScan",
                   "openPublishPort", "openPublish", "vizRepublish", "vizRetry", "vizSetPin"):
            self.assertIn("function %s" % fn, ui("js", "stage.js") + ui("js", "preview.js") +
                          ui("js", "viz.js") + ui("js", "publish.js") +
                          ui("js", "lastpub.js") + ui("js", "workbench.js") +
                          ui("js", "commands.js"))

    def test_quickbar_calls_existing_apis(self):
        stage = ui("js", "stage.js")
        self.assertIn('api("/api/discover")', stage)
        self.assertIn("stopCurrent()", stage)
        self.assertIn("doCheck({scope: \"current\"})", stage)
        self.assertIn("openPublish(\"port\")", stage)
        cmd = ui("js", "commands.js")
        self.assertIn('api("/api/stop", {target})', cmd)
        self.assertIn('api("/api/check", {id})', cmd)
        pub = ui("js", "publish.js")
        self.assertIn("function doPublish", pub)
        for endpoint in ('"/api/publish"', '"/api/pages"', '"/api/run"'):
            self.assertIn(endpoint, pub)


class PreviewSecurityContractTests(unittest.TestCase):
    def test_iframe_only_from_preview_api_with_sandbox(self):
        pv = ui("js", "preview.js")
        self.assertIn('api("/api/preview?id="', pv)
        self.assertIn('sandbox="allow-scripts allow-same-origin allow-forms allow-popups"', pv)
        self.assertIn('referrerpolicy="no-referrer"', pv)
        self.assertIn("8 秒", pv)
        self.assertIn("该应用禁止内嵌，请用打开", pv)
        self.assertIn("云端托管不提供本地预览", pv)
        self.assertNotIn("entry.url", pv)
        self.assertNotIn("a.url +", pv)
        stage = ui("js", "stage.js")
        self.assertIn("stageRepublish", stage)
        self.assertIn("stageStop", stage)

    def test_backend_only_returns_localhost_and_checks_headers(self):
        acts = read(ROOT, "src", "panweb", "ui_actions.py")
        self.assertIn('if path == "/api/preview":', acts)
        self.assertIn("http://127.0.0.1:%d/", acts)
        self.assertIn('headers.get("X-Frame-Options")', acts)
        self.assertIn("frame-ancestors", acts)
        self.assertIn('PREVIEW_BLOCK_REASON = "该应用禁止内嵌，请用打开"', acts)
        self.assertIn('PREVIEW_DOWN_REASON = "本机预览加载失败，请用打开"', acts)
        self.assertIn("frame-src http://127.0.0.1:* http://localhost:*",
                      read(ROOT, "src", "panweb", "ui_server.py"))


class NotifyPanelContractTests(unittest.TestCase):
    def test_panel_uses_history_and_jumps_to_entry(self):
        nt = ui("js", "notify.js")
        self.assertIn('api("/api/history?limit=" + NOTIFY_LIMIT)', nt)
        self.assertIn("function notifyGo", nt)
        self.assertIn("findAsset(ev.entry_id)", nt)
        self.assertIn("selectAsset(ev.entry_id)", nt)
        self.assertIn("function notifyPanelClose", nt)
        self.assertNotIn("setInterval", nt)
        pages = ui("partials", "pages.html")
        self.assertIn('id="bell-btn"', pages)
        self.assertIn('aria-label="通知"', pages)
        self.assertIn('id="bell-panel"', pages)
        core = ui("js", "core.js")
        self.assertIn('panweb-read-ts', core)


class EmptyStateAccessibilityTests(unittest.TestCase):
    def test_three_step_guide_and_port_scan(self):
        pages = ui("partials", "pages.html")
        self.assertIn("三步发出一个网址", pages)
        self.assertIn("选择要发布的东西", pages)
        self.assertIn("确认能被访问", pages)
        self.assertIn("发送给别人", pages)
        self.assertIn('onclick="quickScan()"', pages)
        stage = ui("js", "stage.js")
        self.assertIn('api("/api/discover")', stage)
        wb = ui("js", "workbench.js")
        self.assertIn("function scanPorts(target)", wb)
        self.assertIn('id="viz-empty"', ui("index.html"))
        self.assertIn("扫描本机端口", ui("index.html"))

    def test_copy_announces_via_aria_live(self):
        self.assertIn('id="sr-live" aria-live="polite"', ui("index.html"))
        apps = ui("js", "apps.js")
        self.assertIn("function announce(text)", apps)
        self.assertIn('announce("已复制 ', apps)
        self.assertIn('aria-live="polite"', ui("partials", "pages.html"))

    def test_shortcuts(self):
        ws = ui("js", "workspace.js")
        self.assertIn("e.metaKey || e.ctrlKey", ws)
        self.assertIn('page.classList.contains("show")', ws)
        self.assertIn('document.querySelector("#stage-quickbar .quick-btn:not([disabled])")', ws)
        self.assertIn('document.querySelectorAll(".overlay.show")', ws)
        self.assertIn("notifyPanelClose", ws)


class StoppedSnapshotContractTests(unittest.TestCase):
    def test_stopped_entry_renders_snapshot_and_republish_reuses_backend(self):
        viz = ui("js", "viz.js")
        self.assertIn("renderStopped(found.a)", viz)
        self.assertIn("currentSnapshot", viz)
        lp = ui("js", "lastpub.js")
        self.assertIn("function renderStopped(snap)", lp)
        self.assertIn('endpoint = "/api/publish"', lp)
        self.assertIn("body.port = snap.port", lp)
        self.assertIn("body.folder = snap.folder", lp)
        self.assertIn("body.name = snap.name", lp)
        self.assertIn("用同样配置重新发布", ui("index.html"))
        self.assertNotIn("body.expires", lp)
        self.assertNotIn("body.share", lp)
        self.assertIn("pollJob", lp)
        wb = ui("js", "workbench.js")
        self.assertIn("STATE.last_deployments", wb)

    def test_recent_visitors_live_under_status_group(self):
        html = ui("index.html")
        self.assertIn('id="dep-group-visitors"', html)
        self.assertIn('id="viz-visitors"', html)
        dep = ui("js", "depgroups.js")
        self.assertIn('api("/api/visits?id="', dep)
        self.assertIn("VISITS_LOADED", dep)
        deploy = ui("styles", "deploy.css")
        self.assertIn(".dep-group-body", deploy)

    def test_built_bundle_contains_new_modules(self):
        built = read(BUILT)
        for marker in ("function renderStopped(snap)", "function toggleDepGroup",
                       "function renderVizVisitors", "function initDepGroups",
                       "function renderStage", "function renderPreview",
                       "function toggleBell", "panweb-dep-groups",
                       "panweb-asset-filter", "sr-live"):
            self.assertIn(marker, built)


if __name__ == "__main__":
    unittest.main()
