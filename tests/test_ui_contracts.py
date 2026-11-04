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


class ComposerContractTests(unittest.TestCase):
    def test_quick_templates_fill_placeholders_without_executing(self):
        pages = ui("partials", "pages.html")
        self.assertIn("fillTemplate('发布 <端口>', '<端口>')", pages)
        self.assertIn("fillTemplate('发布 <文件夹路径>', '<文件夹路径>')", pages)
        self.assertIn("fillTemplate('停止 当前', '')", pages)
        self.assertIn("fillTemplate('检查 当前', '')", pages)
        self.assertNotIn("fillCommand('发布 3000')", pages)
        comp = ui("js", "composer.js")
        self.assertIn("function fillTemplate(text, token)", comp)
        self.assertIn("setSelectionRange(at, at + token.length)", comp)
        self.assertNotIn("submitCommand(", comp)

    def test_live_hint_reuses_backend_command_parser(self):
        comp = ui("js", "composer.js")
        self.assertIn('api("/api/command", {text: text})', comp)
        self.assertIn("setTimeout(() => checkCmdSyntax(text), 400)", comp)
        self.assertIn("err.hint", comp)
        self.assertIn("/<[^>]+>/", comp)
        self.assertIn('id="cmd-hint-line"', ui("partials", "pages.html"))

    def test_history_is_memory_only_and_strips_pin(self):
        comp = ui("js", "composer.js")
        self.assertIn("const CMD_HISTORY = [];", comp)
        self.assertIn("function stripPin(text)", comp)
        self.assertIn("rememberCommand(text)", ui("js", "commands.js"))
        self.assertIn("CMD_HISTORY.push(clean)", comp)
        self.assertNotIn("localStorage", comp)
        self.assertNotIn("sessionStorage", comp)
        self.assertIn("ArrowUp", comp)


class EmptyStateAccessibilityTests(unittest.TestCase):
    def test_three_step_guide_and_port_scan(self):
        pages = ui("partials", "pages.html")
        self.assertIn("三步发出一个网址", pages)
        self.assertIn("选择要发布的东西", pages)
        self.assertIn("确认能被访问", pages)
        self.assertIn("发送给别人", pages)
        self.assertIn("scanPorts('guide')", pages)
        wb = ui("js", "workbench.js")
        self.assertIn('api("/api/discover")', wb)
        self.assertIn("function scanPorts(target)", wb)
        self.assertIn('id="viz-empty"', ui("index.html"))
        self.assertIn("扫描本机端口", ui("index.html"))

    def test_copy_announces_via_aria_live(self):
        self.assertIn('id="sr-live" aria-live="polite"', ui("index.html"))
        apps = ui("js", "apps.js")
        self.assertIn("function announce(text)", apps)
        self.assertIn('announce("已复制 ', apps)

    def test_shortcuts(self):
        ws = ui("js", "workspace.js")
        self.assertIn("e.metaKey || e.ctrlKey", ws)
        self.assertIn('page.classList.contains("show")', ws)
        self.assertIn('document.getElementById("cmd-input")', ws)
        self.assertIn('document.querySelectorAll(".overlay.show")', ws)


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
                       "function fillTemplate", "panweb-dep-groups",
                       "panweb-asset-filter", "sr-live"):
            self.assertIn(marker, built)


if __name__ == "__main__":
    unittest.main()
