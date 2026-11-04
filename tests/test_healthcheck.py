"""远程自检的探测与结论翻译：不联网也能验证"看到什么 → 说什么"。"""
import unittest

from helpers import (PUBLIC_HOST, GOOD_PAGE, LOGIN_PAGE, AlwaysForbidden,
                     FakeApp, HostGate, free_port, serve, stop_server)
from panweb import healthcheck


def root(status=200, body=GOOD_PAGE, headers=None, length=None, error=None):
    return {"status": status, "body": body, "headers": headers or {},
            "length": len(body) if length is None else length,
            "final_url": "https://%s/" % PUBLIC_HOST, "error": error}


def codes(signals):
    return [s["code"] for s in signals]


class DiagnoseTests(unittest.TestCase):
    entry = {"id": "e", "kind": "port", "target": 3000, "proxy_port": 5555,
             "host_mode": "loopback"}

    def with_entry(self, **kw):
        base = dict(self.entry)
        base.update(kw)
        return base

    def test_network_failure_is_unreachable(self):
        out = healthcheck.diagnose_root(
            root(error="ConnectionRefusedError: refused"), self.entry)
        self.assertEqual(codes(out), ["unreachable"])
        self.assertEqual(healthcheck._verdict(out)[0], "blocked")

    def test_local_dns_miss_with_edge_response_is_only_a_warning(self):
        """本机解析器跟不上时不能说"打不开"——边缘直连有响应就是访客能打开。"""
        rescue = dict(root(error="URLError: nodename nor servname provided"),
                      edge_status=200)
        out = healthcheck.diagnose_root(rescue, self.entry)
        self.assertEqual(codes(out), ["dns_slow"])
        self.assertEqual(healthcheck._verdict(out)[0], "warn")
        self.assertIn("边缘", out[0]["label"] + out[0]["advice"])

    def test_403_with_loopback_host_suggests_host_mode(self):
        out = healthcheck.diagnose_root(root(403, ""), self.entry)
        self.assertEqual(out[0]["code"], "host_rejected")

    def test_403_in_tunnel_mode_means_the_app_wants_credentials(self):
        out = healthcheck.diagnose_root(
            root(403, ""), self.with_entry(host_mode="tunnel"))
        self.assertEqual(codes(out), ["auth_required"])

    def test_403_without_proxy_is_the_apps_own_rule(self):
        out = healthcheck.diagnose_root(
            root(403, ""), self.with_entry(proxy_port=None))
        self.assertEqual(codes(out), ["direct_403"])
        self.assertIn("allowedHosts", out[0]["advice"])

    def test_530_blames_the_tunnel_not_the_app(self):
        out = healthcheck.diagnose_root(root(530, ""), self.entry)
        self.assertEqual(codes(out), ["tunnel_down"])
        self.assertIn("不是应用的错", out[0]["advice"])

    def test_server_error_and_not_found_are_blocked(self):
        for status in (500, 502, 404):
            out = healthcheck.diagnose_root(root(status, ""), self.entry)
            self.assertEqual(healthcheck._verdict(out)[0], "blocked", status)

    def test_cross_origin_redirect_is_reported_with_location(self):
        out = healthcheck.diagnose_root(
            root(302, "", {"Location": "https://accounts.google.com/o"}),
            self.entry)
        self.assertEqual(codes(out), ["redirect_out"])
        self.assertIn("accounts.google.com", out[0]["label"])

    def test_panweb_pin_page_is_normal_not_a_problem(self):
        out = healthcheck.diagnose_root(
            root(200, '<form action="/__panweb/login"><input name="pw">'
                       '<p>输入主人分享的口令后即可打开</p>', length=400),
            self.entry)
        self.assertEqual(codes(out), ["own_pin_gate"])
        self.assertEqual(healthcheck._verdict(out)[0], "ok")

    def test_app_login_page_is_a_warning(self):
        out = healthcheck.diagnose_root(root(200, LOGIN_PAGE), self.entry)
        self.assertIn("app_login", codes(out))
        self.assertEqual(healthcheck._verdict(out)[0], "warn")

    def test_tiny_json_api_answer_is_not_a_blank_page(self):
        out = healthcheck.diagnose_root(
            root(200, '{"ok":true}', {"Content-Type": "application/json"}),
            self.entry)
        self.assertEqual(codes(out), ["looks_good"])

    def test_short_html_page_is_flagged(self):
        out = healthcheck.diagnose_root(
            root(200, "<html><body>ok</body></html>",
                 {"content-type": "text/html"}, length=10), self.entry)
        self.assertIn("blank_page", codes(out))

    def test_clean_page_is_ok(self):
        out = healthcheck.diagnose_root(root(), self.entry)
        self.assertEqual(healthcheck._verdict(out), ("ok", "访客现在能正常打开"))

    def test_signal_labels_format_placeholders(self):
        self.assertEqual(healthcheck._sig("asset_404", "3")["label"],
                         "3 个页面资源打不开")
        self.assertEqual(healthcheck._sig("auth_required", "401")["label"],
                         "应用自己要凭据（HTTP 401）")
        # 没有占位符的信号不能因为 detail 就崩掉
        self.assertEqual(healthcheck._sig("looks_good", "200")["label"],
                         "首页正常返回")

    def test_every_signal_code_has_a_label_and_severity(self):
        for code in healthcheck.SIGNALS:
            sig = healthcheck._sig(code, "x")
            self.assertTrue(sig["label"], code)
            self.assertIn(sig["severity"], ("info", "warn", "bad"), code)


class AssetTests(unittest.TestCase):
    def test_only_same_origin_css_and_js_are_candidates(self):
        body = ('<script src="/app.js"></script>'
                '<script src="/src/main.tsx"></script>'
                '<link href="https://cdn.example.com/x.css">'
                '<link href="//cdn.example.com/y.css">'
                '<img src="data:image/png;base64,AAA">'
                '<a href="/docs/#top">x</a>'
                '<script src="app.js"></script>')
        self.assertEqual(healthcheck.asset_paths(body), ["/app.js", "app.js"])

    def test_source_references_are_collected(self):
        body = ('<script type="module" src="/src/main.tsx"></script>'
                '<link href="/styles/site.scss">')
        self.assertEqual(healthcheck.source_refs(body),
                         ["/src/main.tsx", "/styles/site.scss"])

    def test_asset_candidates_are_capped(self):
        body = "".join('<script src="/a%d.js"></script>' % i for i in range(20))
        self.assertEqual(len(healthcheck.asset_paths(body)),
                         healthcheck.MAX_ASSETS)

    def test_check_assets_reports_missing_paths_and_carries_visitor_host(self):
        srv, port = serve(HostGate)
        url = "http://127.0.0.1:%d/" % port
        try:
            self.assertEqual(healthcheck.check_assets(
                url, '<script src="/app.js"></script>', host=PUBLIC_HOST), [])
            self.assertEqual(healthcheck.check_assets(
                url, '<script src="/missing.js"></script>', host=PUBLIC_HOST),
                ["/missing.js"])
            # 不带公网 Host 时，校验 Host 的应用会把资源也变成 403。
            self.assertEqual(healthcheck.check_assets(
                url, '<script src="/app.js"></script>'), ["/app.js"])
        finally:
            stop_server(srv)


class ProbeTests(unittest.TestCase):
    def test_status_codes_are_conclusions_not_errors(self):
        srv, port = serve(FakeApp, force_code=404)
        try:
            res = healthcheck.probe("http://127.0.0.1:%d/" % port)
            self.assertEqual(res["status"], 404)
            self.assertIsNone(res["error"])
            self.assertTrue(res["body"])
        finally:
            stop_server(srv)

    def test_same_origin_redirect_is_followed_cross_origin_is_not(self):
        srv, port = serve(FakeApp, redirect=("/", "/app/"))
        base = "http://127.0.0.1:%d" % port
        try:
            res = healthcheck.probe(base + "/")
            self.assertEqual(res["status"], 200)
            self.assertEqual(res["final_url"], base + "/app/")
        finally:
            stop_server(srv)
        srv, port = serve(FakeApp,
                          redirect=("/", "https://accounts.google.com/o"))
        try:
            res = healthcheck.probe("http://127.0.0.1:%d/" % port)
            self.assertEqual(res["status"], 302)
            self.assertIn("accounts.google.com",
                          healthcheck._header(res, "location"))
        finally:
            stop_server(srv)

    def test_connection_failure_returns_error(self):
        res = healthcheck.probe("http://127.0.0.1:%d/" % free_port())
        self.assertIsNone(res["status"])
        self.assertTrue(res["error"])


class WebSocketProbeTests(unittest.TestCase):
    def test_plain_http_server_is_not_a_websocket(self):
        srv, port = serve(HostGate)
        try:
            res = healthcheck.ws_probe("http://127.0.0.1:%d/" % port)
            self.assertFalse(res["ok"])
            self.assertNotEqual(res["status"], 101)
        finally:
            stop_server(srv)


class HostEvidenceTests(unittest.TestCase):
    url = "https://%s/" % PUBLIC_HOST

    def test_evidence_needs_local_rejected_and_public_allowed(self):
        srv, port = serve(HostGate)
        try:
            got = healthcheck.host_evidence({"kind": "port", "port": port},
                                            self.url)
            self.assertEqual(got, {"local": 403, "public": 200})
        finally:
            stop_server(srv)

    def test_no_evidence_when_the_app_refuses_everything(self):
        srv, port = serve(AlwaysForbidden)
        try:
            self.assertIsNone(healthcheck.host_evidence(
                {"kind": "port", "port": port}, self.url))
        finally:
            stop_server(srv)

    def test_no_evidence_for_pages_or_missing_port(self):
        self.assertIsNone(healthcheck.host_evidence(
            {"kind": "pages", "folder": 3000}, self.url))
        self.assertIsNone(healthcheck.host_evidence({"kind": "port"}, self.url))


if __name__ == "__main__":
    unittest.main()
