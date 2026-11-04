"""Desktop app tests. They need pywebview (pip install -r requirements-app.txt)."""

import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(HERE))

try:
    import app as owlapp
except ImportError:  # no pywebview: the command-line script still gets tested
    owlapp = None

import test_owlcheck as fixtures  # noqa: E402


class FakeWindow:
    """Stands in for the window's save dialog and returns a fixed path."""

    def __init__(self, target):
        self.target = target

    def create_file_dialog(self, *args, **kwargs):
        return (str(self.target),) if self.target else None


@unittest.skipIf(owlapp is None, "pywebview not installed")
class TestApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.bad, self.good = base / "ruim", base / "limpo"
        fixtures.make_bad(self.bad)
        fixtures.make_good(self.good)
        self.store_path = base / "estado" / "estado.json"
        self.api = owlapp.Api(owlapp.Store(self.store_path))
        self.base = base

    def tearDown(self):
        self.tmp.cleanup()

    def test_analyze_bad_project(self):
        res = self.api.analyze(str(self.bad))
        self.assertEqual(res["counts"]["CRITICAL"], 3)
        self.assertEqual(res["name"], "Gato Teste")
        self.assertTrue(all({"key", "severity", "title", "items", "checked"} <= set(f) for f in res["findings"]))

    def test_accepts_project_godot_file(self):
        res = self.api.analyze(str(self.good / "project.godot"))
        self.assertNotIn("error", res)
        self.assertEqual(res["counts"]["CRITICAL"], 0)

    def test_rejects_folder_without_project(self):
        self.assertIn("error", self.api.analyze(str(self.base)))
        self.assertIn("error", self.api.analyze(str(self.base / "nao-existe")))
        self.assertIn("error", self.api.analyze(""))

    def test_checks_persist(self):
        res = self.api.analyze(str(self.bad))
        key = res["findings"][0]["key"]
        self.api.set_checked(res["path"], key, True)
        api2 = owlapp.Api(owlapp.Store(self.store_path))
        res2 = api2.analyze(str(self.bad))
        self.assertTrue(next(f for f in res2["findings"] if f["key"] == key)["checked"])
        self.assertEqual(api2.get_state()["recent"][0]["name"], "Gato Teste")
        api2.remove_recent(res2["path"])
        self.assertEqual(api2.get_state()["recent"], [])

    def test_other_engines_and_folder_of_projects(self):
        import test_engines as eng
        unity, gm = self.base / "jogos" / "u", self.base / "jogos" / "g"
        eng.make_unity_bad(unity)
        eng.make_gm_good(gm)
        res = self.api.analyze(str(unity / "Assets"))
        self.assertEqual((res["engine"], res["engine_name"], res["engine_version"]), ("unity", "Unity", "2022.3.20f1"))
        self.assertEqual(res["stats"]["units"]["kind"], "build_scenes")
        self.assertEqual(res["stats"]["scripts"], 4)  # every .cs in the project, Editor and plugins included
        res = self.api.analyze(str(gm / "GatoGM.yyp"))
        self.assertEqual(res["engine"], "gamemaker")
        self.assertEqual(res["counts"]["CRITICAL"], 0)
        err = self.api.analyze(str(self.base / "jogos"))["error"]
        self.assertIn("u (Unity)", err)
        self.assertIn("g (GameMaker)", err)
        plain = self.base / "pasta-qualquer"
        plain.mkdir()
        (plain / "notas.txt").write_text("oi", encoding="utf-8")
        self.assertEqual(self.api.analyze(str(plain))["engine"], "generic")

    def test_bridge_exposes_only_functions(self):
        """pywebview on Windows walks every public attribute, and a public window or store broke the .exe."""
        public = {n for n in dir(self.api) if not n.startswith("_")}
        self.assertEqual(public - {"lang"}, {"get_state", "set_pref", "analyze", "choose_folder", "remove_recent",
                                            "set_checked", "export_report", "make_manifest"})
        self.assertTrue(all(callable(getattr(self.api, n)) for n in public - {"lang"}))

    def test_motion_pref_persists(self):
        self.assertEqual(self.api.get_state()["prefs"], {})
        self.assertTrue(self.api.set_pref("motion", False))
        self.assertFalse(self.api.set_pref("algo_estranho", True))
        api2 = owlapp.Api(owlapp.Store(self.store_path))
        self.assertEqual(api2.get_state()["prefs"], {"motion": False})

    def test_language_pref_and_checks_survive_switch(self):
        res = self.api.analyze(str(self.bad))
        self.assertEqual(res["lang"], "en")
        demo = next(f for f in res["findings"] if f["severity"] == "CRITICAL" and "demo" in f["key"])
        self.assertIn("exports the whole game", demo["title"])
        self.api.set_checked(res["path"], demo["key"], True)
        self.api.set_pref("lang", "es")
        res_es = self.api.analyze(str(self.bad))
        demo_es = next(f for f in res_es["findings"] if f["key"] == demo["key"])
        self.assertIn("exporta el juego entero", demo_es["title"])
        self.assertTrue(demo_es["checked"], "a checked item stays checked in another language")
        self.assertIn("carpeta", self.api.analyze(str(self.base))["error"])
        self.api.set_pref("lang", "zz")
        self.assertEqual(self.api.lang, "en")

    def test_theme_pref(self):
        self.api.set_pref("theme", "dark")
        self.assertEqual(owlapp.Api(owlapp.Store(self.store_path)).get_state()["prefs"]["theme"], "dark")
        self.api.set_pref("theme", "qualquer")
        self.assertEqual(self.api.get_state()["prefs"]["theme"], "light")
        self.assertIn('data-theme="dark"', owlapp.build_html("dark"))
        self.assertNotIn('<html lang="en" data-theme', owlapp.build_html(None))

    def test_export_and_manifest(self):
        res = self.api.analyze(str(self.bad))
        out = self.base / "saida.html"
        self.api._window = FakeWindow(out)
        self.assertEqual(self.api.export_report(res["path"], "html")["saved"], str(out))
        self.assertIn("<title>OwlCheck - Gato Teste</title>", out.read_text(encoding="utf-8"))
        man = self.base / "manifesto.json"
        self.api._window = FakeWindow(man)
        m = self.api.make_manifest(res["path"])
        self.assertEqual(len(m["hash"]), 64)
        self.api._window = FakeWindow(None)
        self.assertTrue(self.api.export_report(res["path"], "md")["cancelled"])

    def test_never_writes_inside_project(self):
        res = self.api.analyze(str(self.bad))
        before = sorted(p.as_posix() for p in self.bad.rglob("*"))
        self.api._window = FakeWindow(self.bad / "relatorio.html")
        self.assertIn("error", self.api.export_report(res["path"], "html"))
        self.api._window = FakeWindow(self.bad / "sub" / "manifesto.json")
        self.assertIn("error", self.api.make_manifest(res["path"]))
        self.assertEqual(before, sorted(p.as_posix() for p in self.bad.rglob("*")))


@unittest.skipIf(owlapp is None, "pywebview not installed")
class TestPage(unittest.TestCase):
    """The page has to be fully self-contained and unable to connect anywhere."""

    def setUp(self):
        self.html = owlapp.build_html()

    def test_csp_blocks_network(self):
        csp = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', self.html)
        self.assertIsNotNone(csp)
        policy = csp.group(1)
        self.assertIn("default-src 'none'", policy)
        self.assertIn("connect-src 'none'", policy)
        self.assertNotRegex(policy, r"https?:")
        # pywebview needs eval for the Python bridge (confirmed with the real window)
        self.assertIn("'unsafe-eval'", policy)

    def test_no_external_references(self):
        urls = re.findall(r"""(?:src|href|url)\s*[=(]\s*["']?(https?://[^"')\s]+)""", self.html)
        self.assertEqual(urls, [])
        # the SVG namespace URI is just an identifier, not a connection
        others = [u for u in re.findall(r"https?://[^\s\"'<>)]+", self.html) if "www.w3.org/2000/svg" not in u]
        self.assertEqual(others, [], "the page must not reference any internet address")

    def test_ui_strings_complete(self):
        """All three UI languages have exactly the same keys."""
        src = (ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
        block = src[src.index("const STR = {"):src.index("const LANGS = [")]
        parts = re.split(r"\n    (en|es|pt): \{", block)
        key_rx = re.compile(r"(?:^|,)\s*(\w+):\s*[\"\[]", re.M)
        keys = {parts[i]: set(key_rx.findall(parts[i + 1])) for i in range(1, len(parts), 2)}
        self.assertEqual(set(keys), {"en", "es", "pt"})
        self.assertEqual(keys["es"], keys["en"], keys["en"] ^ keys["es"])
        self.assertEqual(keys["pt"], keys["en"], keys["en"] ^ keys["pt"])
        for k in ("nightOnAria", "motionOnAria", "vCritText", "complete"):
            self.assertIn(k, keys["en"])

    def test_bridge_is_never_cached(self):
        """On Windows pywebview can replace window.pywebview.api after the page loads.

        The UI has to look up the current object on every call and wait until its functions exist."""
        src = (ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"\bapi\s*=\s*window\.pywebview\.api")
        self.assertIn("bridgeReady()", src)
        self.assertIn('addEventListener("pywebviewready", boot)', src)

    def test_starts_in_light_theme(self):
        src = (ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("prefers-color-scheme", src)
        self.assertNotIn("data-theme", owlapp.build_html(None).split("<head>")[0])

    def test_placeholders_filled(self):
        self.assertNotIn("{{", self.html)
        self.assertIn("data:image/png;base64,", self.html)


@unittest.skipIf(owlapp is None, "pywebview not installed")
class TestAppSource(unittest.TestCase):
    def test_windows_window_icon_is_ico(self):
        """pywebview on Windows calls System.Drawing.Icon(path), and a .png makes the app crash on launch."""
        src = (ROOT / "app" / "app.py").read_text(encoding="utf-8")
        self.assertIn('"icon.ico" if sys.platform == "win32" else "icon.png"', src)

    def test_no_http_server_and_inline_page(self):
        src = (ROOT / "app" / "app.py").read_text(encoding="utf-8")
        self.assertIn("http_server=False", src)
        self.assertRegex(src, r"create_window\([^)]*html=build_html\(")
        self.assertNotRegex(src, r"create_window\([^)]*url=")


if __name__ == "__main__":
    unittest.main()
