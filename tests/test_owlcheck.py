"""OwlCheck tests. Run with:  python -m unittest discover -s tests -v"""

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import owlcheck  # noqa: E402

GODOT_ICON = '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#478cbf"/></svg>'

BAD_PROJECT = '''config_version=5

[application]

config/name="Gato Teste"
run/main_scene="res://scenes/menu.tscn"
config/features=PackedStringArray("4.7", "Forward Plus")
config/icon="res://icon.svg"
'''

BAD_PRESETS = '''[preset.0]

name="Windows Desktop"
platform="Windows Desktop"
runnable=true
custom_features=""
export_filter="all_resources"
include_filter="*.md, *.env"
exclude_filter=""
export_path="build/jogo.exe"
encrypt_pck=false
encrypt_directory=false
script_export_mode=0

[preset.0.options]

application/company_name=""
application/product_name=""

[preset.1]

name="Demo Dev Fest"
platform="macOS"
custom_features="demo"
export_filter="all_resources"
include_filter=""
exclude_filter=""
encrypt_pck=false
script_export_mode=2

[preset.1.options]

application/bundle_identifier="com.example.gatoteste"
'''

GOOD_PROJECT = '''config_version=5

[application]

config/name="Gato Limpo"
config/version="0.1.0-demo"
config/features=PackedStringArray("4.7", "Forward Plus")
config/icon="res://art/icone.png"
'''

GOOD_PRESETS = '''[preset.0]

name="Demo Windows"
platform="Windows Desktop"
custom_features="demo"
export_filter="scenes"
export_files=PackedStringArray("res://scenes/menu.tscn", "res://scenes/fase_01.tscn")
include_filter=""
exclude_filter=""
encrypt_pck=true
encrypt_directory=true
script_export_mode=2

[preset.0.options]

application/company_name="Moth Lamp Games"
application/product_name="Gato Limpo"
application/file_version="0.1.0"
application/product_version="0.1.0"
'''


def write(base, rel, content=""):
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")
    return p


def make_bad(base):
    write(base, "project.godot", BAD_PROJECT)
    write(base, "export_presets.cfg", BAD_PRESETS)
    write(base, "icon.svg", GODOT_ICON)
    write(base, "scenes/menu.tscn", "[gd_scene format=3]")
    for i in range(1, 6):
        write(base, f"scenes/fase_{i:02d}.tscn", "[gd_scene format=3]")
    write(base, "scenes/boss_final.tscn", "[gd_scene format=3]")
    write(base, "scripts/rede.gd",
          'extends Node\nconst API_KEY = "a8F3kZ91mQ02xLp7"\n'
          'var hook = "https://discord.com/api/webhooks/123456/abcDEF-ghi"\n')
    write(base, "scripts/main.gd",
          "extends Node\nfunc _ready():\n"
          '\tif "--autotest" in OS.get_cmdline_args():\n\t\tpass\n'
          "\tprint(\"iniciou\")\n\tprint(\"de novo\")\n"
          "\tvar god_mode = false\n\tbreakpoint\n\t# TODO tirar isso\n"
          '\tif OS.has_feature("demo"):\n\t\tpass\n')
    write(base, "docs/GDD.md", "# GDD secreto\nFase 6 surpresa")
    write(base, ".env", "STEAM_KEY=abc")
    write(base, "fonts/Pixel.ttf", b"\x00\x01")
    write(base, "addons/plugin_x/plugin.cfg", "[plugin]")


def make_good(base):
    write(base, "project.godot", GOOD_PROJECT)
    write(base, "export_presets.cfg", GOOD_PRESETS)
    write(base, "art/icone.png", b"\x89PNG")
    write(base, "scenes/menu.tscn", "[gd_scene format=3]")
    write(base, "scenes/fase_01.tscn", "[gd_scene format=3]")
    write(base, "scenes/fase_02.tscn", "[gd_scene format=3]")
    write(base, "scripts/main.gd",
          "extends Node\nfunc _ready():\n"
          "\tif OS.is_debug_build():\n"
          '\t\tif "--autotest" in OS.get_cmdline_args():\n\t\t\tpass\n')
    write(base, "fonts/Pixel.ttf", b"\x00\x01")
    write(base, "fonts/OFL.txt", "SIL Open Font License")
    write(base, "CREDITS.md", "Feito com Godot Engine (MIT).")
    write(base, "AI_DISCLOSURE.md", "Assets gerados por IA generativa e editados a mao.")


def titles(findings, severity=None):
    return [f.title for f in findings if severity is None or f.severity == severity]


class TestParser(unittest.TestCase):
    def test_parse_values(self):
        d = owlcheck.parse_godot_cfg(
            'a=1\n[s]\nb="x \\"y\\""\nc=true\n'
            'd=PackedStringArray("res://a.tscn",\n "res://b.tscn")\ne=2.5\n')
        self.assertEqual(d[""]["a"], 1)
        self.assertEqual(d["s"]["b"], 'x "y"')
        self.assertIs(d["s"]["c"], True)
        self.assertEqual(d["s"]["d"], ["res://a.tscn", "res://b.tscn"])
        self.assertEqual(d["s"]["e"], 2.5)


class TestBadProject(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / "projeto_ruim"
        make_bad(cls.root)
        cls.findings = owlcheck.Checker(cls.root, lang="pt").run()
        cls.all = " | ".join(titles(cls.findings))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_demo_leak_is_critical(self):
        crit = titles(self.findings, "CRITICAL")
        self.assertTrue(any("exporta o jogo inteiro" in t for t in crit), crit)
        leak = next(f for f in self.findings if "exporta o jogo inteiro" in f.title)
        self.assertTrue(any("boss_final" in i for i in leak.items))

    def test_demo_flag_only_code(self):
        self.assertIn("Bloqueio da demo feito só pelo código", self.all)

    def test_secrets_in_build(self):
        f = next(f for f in self.findings if f.title.startswith("Possíveis chaves") and f.severity == "CRITICAL")
        joined = " ".join(f.items)
        self.assertIn("scripts/rede.gd:2", joined)
        self.assertIn("Webhook do Discord", joined)
        self.assertNotIn("a8F3kZ91mQ02xLp7", joined, "the secret should show up masked")

    def test_env_exported(self):
        self.assertIn("Arquivos de credencial entrando na build", titles(self.findings, "CRITICAL"))

    def test_gdd_exported(self):
        f = next(f for f in self.findings if "arquivos de trabalho na build" in f.title)
        self.assertIn("docs/GDD.md", f.items)

    def test_protection(self):
        self.assertIn("pacote (.pck) sem criptografia", self.all)
        self.assertIn("scripts exportados como texto", self.all)

    def test_debug(self):
        self.assertIn("Ganchos de linha de comando sem proteção", self.all)
        self.assertIn("Possíveis cheats ou menus de desenvolvedor", self.all)
        self.assertIn("Breakpoints esquecidos no código", self.all)
        self.assertIn("Chamadas de print no código exportado (2)", self.all)

    def test_scan_stats_are_real(self):
        c = owlcheck.Checker(self.root, lang="pt")
        c.run()
        s = c.stats
        self.assertEqual(s["files"], len(c.files))
        self.assertEqual(s["presets"], 2)
        self.assertEqual(s["scripts"], 2)
        self.assertGreaterEqual(s["secret_files"], 4)
        self.assertEqual(s["demos"], [{"name": "Demo Dev Fest", "scenes": 7}])
        self.assertEqual(s["checks"], len(owlcheck.Checker.CHECKS["godot"]))

    def test_metadata_and_licenses(self):
        self.assertIn("Ícone padrão do Godot", self.all)
        self.assertIn("Projeto sem número de versão", self.all)
        self.assertTrue(any("identificador padrão" in t for t in titles(self.findings)))
        self.assertIn("Fontes sem arquivo de licença ao lado", self.all)
        self.assertIn("Plugins sem licença identificada", self.all)
        self.assertIn("Sem registro do uso de IA no projeto", self.all)


class TestGoodProject(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / "projeto_limpo"
        make_good(cls.root)
        cls.findings = owlcheck.Checker(cls.root, lang="pt").run()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_no_critical_or_warning(self):
        bad = [(f.severity, f.title) for f in self.findings if f.severity in ("CRITICAL", "WARNING")]
        self.assertEqual(bad, [])

    def test_selected_demo_is_ok(self):
        f = next(f for f in self.findings if f.category == "Demo")
        self.assertEqual(f.severity, "OK")
        self.assertNotIn("scenes/fase_02.tscn", " ".join(f.items))


class TestCli(unittest.TestCase):
    def test_reports_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bad, good, out = tmp / "ruim", tmp / "limpo", tmp / "saida"
            make_bad(bad)
            make_good(good)
            before = sorted(p.as_posix() for p in bad.rglob("*"))
            code = owlcheck.main([str(bad), "--out", str(out), "--md", "--json", "--manifest", "--no-color"])
            self.assertEqual(code, 1)
            for name in owlcheck.REPORT_FILES.values():
                self.assertTrue((out / name).is_file(), name)
            manifest = json.loads((out / owlcheck.REPORT_FILES["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["aggregate_sha256"]), 64)
            after = sorted(p.as_posix() for p in bad.rglob("*"))
            self.assertEqual(before, after, "OwlCheck must never modify the project")
            self.assertEqual(owlcheck.main([str(good), "--out", str(out), "--no-color"]), 0)

    def test_refuses_to_write_inside_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p"
            make_good(root)
            self.assertEqual(owlcheck.main([str(root), "--out", str(root / "relatorios")]), 2)


class TestLanguages(unittest.TestCase):
    """Every message exists in all three languages, with the same fields."""

    def test_catalog_complete(self):
        import string
        fields = lambda s: sorted(f for _, f, _, _ in string.Formatter().parse(s) if f)
        for code, langs in owlcheck.MESSAGES.items():
            self.assertEqual(set(langs), set(owlcheck.LANGS), code)
            ref = [fields(s) for s in langs["en"]]
            for lang, triple in langs.items():
                self.assertEqual(len(triple), 3, (code, lang))
                self.assertEqual([fields(s) for s in triple], ref, (code, lang))
                self.assertTrue(triple[0], (code, lang))
        for table in (owlcheck.CATEGORIES, owlcheck.SECRET_LABELS):
            for key, langs in table.items():
                self.assertEqual(set(langs), set(owlcheck.LANGS), key)
        for lang in owlcheck.LANGS:
            self.assertEqual(set(owlcheck.TEXT[lang]), set(owlcheck.TEXT["en"]), lang)

    def test_default_is_english_and_ids_are_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p"
            make_bad(root)
            en = owlcheck.Checker(root).run()
            es = owlcheck.Checker(root, lang="es").run()
            pt = owlcheck.Checker(root, lang="pt").run()
            self.assertIn("Demo preset 'Demo Dev Fest' exports the whole game", [f.title for f in en])
            self.assertIn("El preset de demo 'Demo Dev Fest' exporta el juego entero", [f.title for f in es])
            self.assertEqual([f.uid for f in en], [f.uid for f in es])
            self.assertEqual([f.uid for f in en], [f.uid for f in pt])
            self.assertEqual(len({f.uid for f in en}), len(en), "every finding needs a unique id")
            self.assertEqual(owlcheck.Checker(root, lang="xx").lang, "en")

    def test_reports_follow_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p"
            make_bad(root)
            for lang, word, html_lang in (("en", "How to fix", 'lang="en"'), ("es", "Cómo resolverlo", 'lang="es"'),
                                          ("pt", "Como resolver", 'lang="pt-BR"')):
                c = owlcheck.Checker(root, lang=lang)
                fs = c.run()
                self.assertIn(word, owlcheck.render_markdown(c, fs))
                page = owlcheck.render_html(c, fs)
                self.assertIn(html_lang, page)
                self.assertIn(word, page)


class TestNoNetwork(unittest.TestCase):
    """Reads OwlCheck's own source to prove it has no way to reach the network."""

    FORBIDDEN = {"socket", "ssl", "http", "urllib", "urllib2", "urllib3", "requests", "httpx",
                 "aiohttp", "ftplib", "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc",
                 "asyncio", "subprocess", "ctypes", "multiprocessing", "webbrowser", "socketserver"}

    def test_no_network_imports(self):
        tree = ast.parse((ROOT / "owlcheck.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("__import__", "exec", "eval"):
                self.fail("__import__, exec and eval aren't allowed")
        self.assertEqual(imported & self.FORBIDDEN, set())


if __name__ == "__main__":
    unittest.main()
