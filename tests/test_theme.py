"""主题契约：首屏不闪、默认跟随系统、偏好只落 panweb-theme、两套变量都在产物里。"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def luminance(color):
    color = color.lstrip("#")
    channels = [int(color[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
                for c in channels]
    return (0.2126 * channels[0] + 0.7152 * channels[1]
            + 0.0722 * channels[2])


def contrast(fg, bg):
    high, low = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def token_block(css, selector=":root"):
    block = css.split(selector + " {", 1)[1].split("}", 1)[0]
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,8});", block))


def root_tokens(css):
    """取出 :root 浅色令牌块里的 --name: #hex。"""
    return token_block(css)


def dark_tokens(css):
    return token_block(css, 'html[data-theme="dark"]')


class ThemeBootTests(unittest.TestCase):
    def test_boot_runs_before_styles(self):
        source = read("ui", "src", "index.html")
        boot = source.find('localStorage.getItem("panweb-theme")')
        styles = source.find("/*__PANWEB_STYLES__*/")
        self.assertGreater(boot, 0)
        self.assertGreater(styles, boot)
        self.assertIn("(prefers-color-scheme: dark)", source)
        self.assertIn('setAttribute("data-theme", theme)', source)
        self.assertIn('setAttribute("data-theme-pref", pref)', source)
        self.assertIn("root.style.colorScheme = theme", source)

    def test_theme_module_defaults_to_auto(self):
        source = read("ui", "src", "js", "theme.js")
        self.assertIn('const THEME_KEY = "panweb-theme"', source)
        self.assertIn('const THEME_CHOICES = ["auto", "light", "dark"]', source)
        self.assertIn('return "auto";', source)
        self.assertIn("localStorage.setItem(THEME_KEY, pref)", source)
        self.assertIn('THEME_MQ.addEventListener("change", follow)', source)
        self.assertIn('else if (THEME_MQ.addListener) THEME_MQ.addListener(follow)',
                      source)
        self.assertIn('{auto: "light", light: "dark", dark: "auto"}', source)
        self.assertIn("applyThemePreference(next, true)", source)
        self.assertIn("function applyThemePreference(pref, persist)", source)

    def test_theme_module_only_persists_theme_pref(self):
        source = read("ui", "src", "js", "theme.js")
        self.assertEqual(source.count("localStorage.setItem"), 1)
        self.assertNotIn('localStorage.setItem("', source)
        self.assertNotIn("sessionStorage", source)

    def test_theme_control_is_labelled(self):
        source = read("ui", "src", "partials", "pages.html")
        self.assertIn('id="theme-btn"', source)
        self.assertIn("cycleTheme()", source)
        self.assertIn('aria-label="主题：跟随系统"', source)
        self.assertIn('id="theme-label"', source)


class ThemePaletteTests(unittest.TestCase):
    def test_built_output_has_both_themes(self):
        built = read("ui", "index.html")
        self.assertIn('html[data-theme="dark"]', built)
        self.assertIn('html[data-theme="light"]', built)
        self.assertIn("--bg: #eef2f5;", built)
        self.assertIn("--bg: #05080d;", built)
        self.assertIn("data-theme-pref", built)
        self.assertIn("/*__PANWEB_STYLES__*/", read("ui", "src", "index.html"))
        self.assertNotIn("/*__PANWEB_STYLES__*/", built)

    def test_motion_fallbacks_survive_in_build(self):
        built = read("ui", "index.html")
        self.assertIn("@media (prefers-reduced-motion: reduce)", built)
        self.assertIn("body.low-power", built)
        self.assertIn("body.page-hidden", built)

    def assert_palette(self, tokens):
        pairs = [
            ("ink", "bg", 4.5), ("ink", "surface", 4.5),
            ("muted", "surface", 4.5), ("faint", "surface", 4.5),
            ("faint", "bg", 4.5), ("accent", "surface", 4.5),
            ("danger", "surface", 4.5), ("online", "bg", 4.5),
            ("expired", "bg", 4.5), ("hosted", "bg", 4.5),
            ("offline", "bg", 4.5), ("gold", "surface", 4.5),
        ]
        for fg, bg, floor in pairs:
            self.assertIn(fg, tokens, fg)
            self.assertIn(bg, tokens, bg)
            ratio = contrast(tokens[fg], tokens[bg])
            self.assertGreaterEqual(
                round(ratio, 2), floor, "%s on %s = %.2f" % (fg, bg, ratio))
        for accent in ("accent", "accent-2"):
            self.assertIn(accent, tokens)
            ratio = contrast(tokens["on-accent"], tokens[accent])
            self.assertGreaterEqual(
                round(ratio, 2), 4.5,
                "on-accent on %s = %.2f" % (accent, ratio))

    def test_light_palette_meets_wcag_aa(self):
        self.assert_palette(root_tokens(read("ui", "src", "styles", "scifi.css")))

    def test_dark_palette_meets_wcag_aa(self):
        self.assert_palette(dark_tokens(read("ui", "src", "styles", "scifi.css")))


if __name__ == "__main__":
    unittest.main()
