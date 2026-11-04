"""Engine detection and the Unity, GameMaker and generic checks.

The sample projects use each engine's real file formats (Unity's YAML, GameMaker's JSON with trailing
commas), checked against public projects."""

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import owlcheck  # noqa: E402
from test_owlcheck import make_good, write  # noqa: E402

UNITY_BAD_SETTINGS = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!129 &1
PlayerSettings:
  m_ObjectHideFlags: 0
  serializedVersion: 26
  productGUID: 1f2e3d4c5b6a
  companyName: DefaultCompany
  productName: Gato Unity
  defaultCursor: {fileID: 0}
  bundleVersion:
  preloadedAssets: []
  applicationIdentifier:
    Android: com.Company.ProductName
    Standalone: com.DefaultCompany.GatoUnity
  m_BuildTargetIcons: []
  m_BuildTargetPlatformIcons: []
  m_BuildTargetBatching:
  - m_BuildTarget: Standalone
    m_StaticBatching: 1
  scriptingDefineSymbols:
    Standalone: DEMO_BUILD;CROSS_PLATFORM_INPUT
  scriptingBackend:
    Android: 0
  il2cppCompilerConfiguration: {}
"""

UNITY_GOOD_SETTINGS = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!129 &1
PlayerSettings:
  companyName: Moth Lamp Games
  productName: Gato Unity
  bundleVersion: 0.1.0
  applicationIdentifier:
    Standalone: com.mothlamp.gatounity
  m_BuildTargetIcons:
  - m_BuildTarget:
    m_Icons:
    - serializedVersion: 2
      m_Icon: {fileID: 2800000, guid: 6a4f0c2b9e1d4f3a8b7c6d5e4f3a2b1c, type: 3}
      m_Width: 128
  scriptingBackend:
    Standalone: 1
"""


def build_settings(scenes):
    body = "".join(f"  - enabled: {1 if on else 0}\n    path: {p}\n    guid: 0123456789abcdef\n" for p, on in scenes)
    return ("%YAML 1.1\n--- !u!1045 &1\nEditorBuildSettings:\n  m_ObjectHideFlags: 0\n  serializedVersion: 2\n"
            "  m_Scenes:\n" + body + "  m_configObjects: {}\n")


UNITY_BAD_CODE = """using System;
using UnityEngine;

namespace Gato
{
    public class Net : MonoBehaviour
    {
        private const string ApiKey = "a8F3kZ91mQ02xLp7Q";
        private string hook = "https://discord.com/api/webhooks/123456/abcDEF-ghi";
        public bool godMode;

#if UNITY_EDITOR
        bool noclip;
#endif
        /* public bool infiniteHealth; (comentado) */

        void Start()
        {
            Debug.Log("iniciou");
            Debug.Log("de novo");
            if (Debug.isDebugBuild)
            {
                var args = Environment.GetCommandLineArgs();
            }
            Debug.Break(); // TODO tirar isso
        }
    }
}
"""

UNITY_EDITOR_CODE = """using UnityEditor;
public class Tools { public bool godMode; void A() { UnityEngine.Debug.Log("editor"); } }
"""

UNITY_GOOD_CODE = """using UnityEngine;
public class Player : MonoBehaviour
{
    void Update()
    {
#if DEVELOPMENT_BUILD || UNITY_EDITOR
        if (Input.GetKeyDown(KeyCode.F1)) godMode = !godMode;
#endif
    }
#if DEVELOPMENT_BUILD || UNITY_EDITOR
    bool godMode;
#endif
}
"""


def make_unity_bad(base):
    write(base, "ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 2022.3.20f1\n")
    write(base, "ProjectSettings/ProjectSettings.asset", UNITY_BAD_SETTINGS)
    write(base, "ProjectSettings/EditorBuildSettings.asset", build_settings([
        ("Assets/Scenes/MainMenu.unity", True), ("Assets/Scenes/Level_01.unity", True),
        ("Assets/Scenes/Level_02.unity", True), ("Assets/Scenes/Boss_Final.unity", True),
        ("Assets/Scenes/TestScene.unity", True), ("Assets/Scenes/Old.unity", False)]))
    for s in ("MainMenu", "Level_01", "Level_02", "Boss_Final", "TestScene", "Old"):
        write(base, f"Assets/Scenes/{s}.unity", "%YAML 1.1\n")
    write(base, "Assets/Scripts/Net.cs", UNITY_BAD_CODE)
    write(base, "Assets/Scripts/Net.cs.meta", "guid: 1\n")
    write(base, "Assets/Editor/Tools.cs", UNITY_EDITOR_CODE)
    write(base, "Assets/Resources/Levels/level_05.prefab", "%YAML 1.1\n")
    write(base, "Assets/Resources/Docs/GDD_v3.docx", b"PK")
    write(base, "Assets/StreamingAssets/config.env", "TOKEN=1\n")
    write(base, "Assets/StreamingAssets/dialogos.json", '{"oi": "ola"}')
    write(base, "Assets/Data/Online.asset", "MonoBehaviour:\n  m_Name: Online\n  apiKey: Qw9aZ7xL2mN4bV6cT1\n")
    write(base, "Assets/Plugins/CoolTween/CoolTween.cs", "public class CoolTween {}\n")
    write(base, "Assets/Plugins/x86_64/steam_api64.dll", b"MZ")
    write(base, "Assets/Fonts/Pixel.ttf", b"\0\1")
    write(base, "Library/ArtifactDB", "x" * 100)
    write(base, "Assets/Samples~/Extra/Demo.cs", 'class X { string token = "Zx81mN0pQ2rS4tU6"; }')


def make_unity_good(base):
    write(base, "ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 6000.0.30f1\n")
    write(base, "ProjectSettings/ProjectSettings.asset", UNITY_GOOD_SETTINGS)
    write(base, "ProjectSettings/EditorBuildSettings.asset", build_settings([
        ("Assets/Scenes/MainMenu.unity", True), ("Assets/Scenes/Level_01.unity", True)]))
    write(base, "Assets/Scenes/MainMenu.unity", "%YAML 1.1\n")
    write(base, "Assets/Scenes/Level_01.unity", "%YAML 1.1\n")
    write(base, "Assets/Scripts/Player.cs", UNITY_GOOD_CODE)
    write(base, "Assets/Fonts/Pixel.ttf", b"\0\1")
    write(base, "Assets/Fonts/Pixel - OFL.txt", "SIL Open Font License")
    write(base, "CREDITS.md", "# Créditos\n")
    write(base, "AI_DISCLOSURE.md", "Uso de IA generativa: ...\n")


def gm_yyp(name, rooms, configs=()):
    res = "".join(f'    {{"id":{{"name":"{r}","path":"rooms/{r}/{r}.yy",}},}},\n' for r in rooms)
    res += '    {"id":{"name":"obj_player","path":"objects/obj_player/obj_player.yy",},},\n'
    children = "".join(f'{{"children":[],"name":"{c}",}},' for c in configs)
    return ('{\n  "$GMProject":"v1",\n  "%Name":"' + name + '",\n  "configs":{\n    "children":[' + children +
            '],\n    "name":"Default",\n  },\n  "MetaData":{\n    "IDEVersion":"2024.11.0.179",\n  },\n'
            '  "name":"' + name + '",\n  "resources":[\n' + res + '  ],\n  "resourceType":"GMProject",\n}\n')


GM_WINDOWS_DEFAULT = """{
  "$GMWindowsOptions":"v2",
  "%Name":"Windows",
  "option_windows_company_info":"YoYo Games Ltd",
  "option_windows_copyright_info":"",
  "option_windows_description_info":"A GameMaker Studio 2 Game",
  "option_windows_display_name":"Created with GameMaker Studio 2",
  "option_windows_product_info":"Created with GameMaker Studio 2",
  "option_windows_version":"1.0.0.0",
  "resourceType":"GMWindowsOptions",
}
"""

GM_WINDOWS_GOOD = """{
  "$GMWindowsOptions":"v2",
  "option_windows_company_info":"Moth Lamp Games",
  "option_windows_copyright_info":"(c) 2026 Moth Lamp Games",
  "option_windows_description_info":"Gato GM",
  "option_windows_display_name":"Gato GM",
  "option_windows_product_info":"Gato GM",
  "option_windows_version":"0.1.0.0",
}
"""


def make_gm_bad(base):
    write(base, "GatoGM.yyp", gm_yyp("GatoGM", ["rm_menu", "rm_level_01", "rm_boss_final", "rm_test_physics"],
                                     configs=["Demo"]))
    write(base, "GatoGM.resource_order", "{}")
    write(base, "options/main/options_main.yy", '{\n  "option_remove_unused_assets":false,\n  "option_author":"",\n}\n')
    write(base, "options/windows/options_windows.yy", GM_WINDOWS_DEFAULT)
    write(base, "options/android/options_android.yy",
          '{\n  "option_android_package_company":"company",\n  "option_android_package_domain":"com",\n'
          '  "option_android_package_product":"game",\n}\n')
    write(base, "objects/obj_player/Step_0.gml",
          "if keyboard_check_pressed(vk_f1) god_mode = true;\nshow_debug_message(\"passo\");\n"
          "show_debug_overlay(true);\nvar p = parameter_string(1); // TODO revisar\n")
    write(base, "objects/obj_debug/Create_0.gml",
          "if (debug_mode) {\n    noclip = true;\n    show_debug_overlay(true);\n}\n")
    write(base, "scripts/scr_net/scr_net.gml", 'global.api_key = "a8F3kZ91mQ02xLp7Q";\n')
    write(base, "datafiles/segredo.env", "TOKEN=1\n")
    write(base, "datafiles/notas_gdd.docx", b"PK")
    write(base, "datafiles/dialogos.json", '{"oi": "ola"}')
    write(base, "notes/ideias/ideias.txt", 'token = "Zx81mN0pQ2rS4tU6"\n')
    write(base, "extensions/CoolExt/CoolExt.yy", "{}")


def make_gm_good(base):
    write(base, "GatoGM.yyp", gm_yyp("GatoGM", ["rm_menu", "rm_level_01"]))
    write(base, "options/main/options_main.yy", '{\n  "option_remove_unused_assets":true,\n}\n')
    write(base, "options/windows/options_windows.yy", GM_WINDOWS_GOOD)
    write(base, "objects/obj_player/Step_0.gml",
          "if (debug_mode) {\n    if keyboard_check_pressed(vk_f1) god_mode = !god_mode;\n}\n")
    write(base, "CREDITS.md", "# Créditos\n")
    write(base, "AI_DISCLOSURE.md", "Uso de IA generativa: ...\n")


def run(path, lang="en"):
    c = owlcheck.Checker(path, lang=lang)
    return c, c.run()


def codes(findings, severity=None):
    return {f.code for f in findings if severity is None or f.severity == severity}


def get(findings, code):
    return [f for f in findings if f.code == code]


class TestDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.unity, self.gm, self.godot = self.base / "u", self.base / "g", self.base / "jogos" / "gd"
        make_unity_good(self.unity)
        make_gm_good(self.gm)
        make_good(self.godot)

    def tearDown(self):
        self.tmp.cleanup()

    def test_detects_each_engine(self):
        self.assertEqual(owlcheck.detect_engine(self.unity), "unity")
        self.assertEqual(owlcheck.detect_engine(self.gm), "gamemaker")
        self.assertEqual(owlcheck.detect_engine(self.godot), "godot")
        self.assertEqual(owlcheck.detect_engine(self.base), "generic")

    def test_resolve_root_accepts_markers(self):
        r = owlcheck.resolve_root
        self.assertEqual(r(self.gm / "GatoGM.yyp"), self.gm.resolve())
        self.assertEqual(r(self.godot / "project.godot"), self.godot.resolve())
        self.assertEqual(r(self.unity / "ProjectSettings" / "ProjectVersion.txt"), self.unity.resolve())
        self.assertEqual(r(self.unity / "Assets"), self.unity.resolve())
        self.assertIsNone(r(self.unity / "CREDITS.md"))
        self.assertIsNone(r(self.base / "nao-existe"))
        self.assertIsNone(r(""))

    def test_finds_projects_inside_a_folder(self):
        found = {(p.name, e) for p, e in owlcheck.find_projects(self.base)}
        self.assertEqual(found, {("u", "unity"), ("g", "gamemaker"), ("gd", "godot")})

    def test_engine_order_and_names(self):
        self.assertEqual(owlcheck.ENGINES, ("unity", "godot", "gamemaker"))
        c = owlcheck.Checker(self.unity, lang="pt")
        self.assertEqual(c.engine_name, "Unity")
        self.assertEqual(c.engine_version, "6000.0.30f1")
        self.assertEqual(owlcheck.Checker(self.base, lang="pt").engine_name, "engine não reconhecida")


class TestUnity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bad, cls.good = Path(cls.tmp.name) / "bad", Path(cls.tmp.name) / "good"
        make_unity_bad(cls.bad)
        make_unity_good(cls.good)
        cls.c, cls.f = run(cls.bad)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_skips_library_meta_and_tilde_folders(self):
        rels = [f.rel for f in self.c.files]
        self.assertFalse(any(r.startswith("Library/") or r.endswith(".meta") for r in rels))
        self.assertTrue(next(f for f in self.c.files if "Samples~" in f.rel).ignored)

    def test_mono_backend(self):
        mono = get(self.f, "unity_mono")
        self.assertEqual({f.uid for f in mono}, {"unity_mono:Standalone", "unity_mono:Android"})
        self.assertIn("PC, Mac & Linux", mono[0].title + mono[1].title)

    def test_scenes_and_demo(self):
        self.assertEqual(get(self.f, "unity_test_scenes")[0].items, ["Assets/Scenes/TestScene.unity"])
        demo = get(self.f, "unity_demo")[0]
        self.assertEqual(demo.severity, "WARNING")
        self.assertIn("DEMO_BUILD", demo.detail)
        self.assertIn("Assets/Scenes/Boss_Final.unity", demo.items)
        self.assertIn("Assets/Resources/Levels/level_05.prefab", demo.items)
        self.assertEqual(self.c.stats["units"]["kind"], "build_scenes")
        self.assertEqual(len(self.c.stats["units"]["names"]), 5)

    def test_folders_that_always_ship(self):
        self.assertEqual(get(self.f, "unity_resources")[0].severity, "RECOMMENDED")
        self.assertEqual(len(get(self.f, "unity_streaming")[0].items), 2)
        self.assertEqual(get(self.f, "cred_build")[0].items, ["Assets/StreamingAssets/config.env"])
        self.assertEqual(get(self.f, "dev_files")[0].items, ["Assets/Resources/Docs/GDD_v3.docx"])

    def test_secrets(self):
        hits = get(self.f, "secrets_build")[0]
        self.assertEqual(hits.severity, "CRITICAL")
        text = " ".join(hits.items)
        self.assertIn("Assets/Scripts/Net.cs:8", text)
        self.assertIn("Assets/Data/Online.asset", text, "unquoted secret in YAML")
        self.assertNotIn("Samples~", text, "folders ending in ~ never ship")

    def test_debug_code(self):
        cheats = " ".join(get(self.f, "cheats")[0].items)
        self.assertIn("godMode", cheats)
        self.assertNotIn("noclip", cheats, "inside #if UNITY_EDITOR")
        self.assertNotIn("infiniteHealth", cheats, "inside a block comment")
        self.assertNotIn("Editor/", cheats, "Editor folders never ship")
        self.assertIn("Debug.Log", get(self.f, "prints")[0].title)
        self.assertEqual(get(self.f, "prints")[0].title.count("(2)"), 1)
        self.assertEqual(get(self.f, "cmdline_guarded")[0].severity, "OK")
        self.assertIn("Debug.Break", get(self.f, "breakpoints")[0].title)
        self.assertTrue(get(self.f, "todos"))

    def test_metadata_and_licenses(self):
        self.assertIn("DefaultCompany", get(self.f, "unity_company")[0].title)
        self.assertTrue({"no_version", "no_icon"} <= codes(self.f))
        self.assertEqual({f.uid for f in get(self.f, "default_id")}, {"default_id:Android", "default_id:Standalone"})
        self.assertTrue(any("PC, Mac & Linux" in f.title for f in get(self.f, "default_id")))
        self.assertEqual(get(self.f, "addons_nolicense")[0].items, ["Assets/Plugins/CoolTween"])
        self.assertEqual(get(self.f, "addons_nolicense")[0].severity, "RECOMMENDED")
        self.assertIn("Godot", " ".join(m[1] for m in owlcheck.MESSAGES["no_credits"].values()))
        self.assertNotIn("Godot", get(self.f, "no_credits")[0].detail)

    def test_good_project(self):
        c, f = run(self.good)
        self.assertEqual(codes(f, "CRITICAL") | codes(f, "WARNING"), set(), [x.title for x in f])
        self.assertIn("unity_il2cpp", codes(f, "OK"))
        self.assertEqual(c.project_name, "Gato Unity")

    def test_languages(self):
        for lang, word in (("pt", "Cenas de teste"), ("es", "Escenas de prueba")):
            _, f = run(self.bad, lang)
            self.assertIn(word, get(f, "unity_test_scenes")[0].title)


class TestGameMaker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bad, cls.good = Path(cls.tmp.name) / "bad", Path(cls.tmp.name) / "good"
        make_gm_bad(cls.bad)
        make_gm_good(cls.good)
        cls.c, cls.f = run(cls.bad)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_reads_project(self):
        self.assertEqual(self.c.engine, "gamemaker")
        self.assertEqual(self.c.project_name, "GatoGM")
        self.assertEqual(self.c.engine_version, "2024.11.0.179")
        self.assertEqual(self.c.gm["configs"], ["Default", "Demo"])
        self.assertEqual(len(self.c.gm["rooms"]), 4)

    def test_demo_and_rooms(self):
        demo = get(self.f, "gm_demo")[0]
        self.assertIn("config Demo", demo.detail)
        self.assertIn("rm_boss_final", demo.items)
        self.assertEqual(get(self.f, "gm_test_rooms")[0].items, ["rm_test_physics"])
        self.assertIn("gm_remove_unused", codes(self.f))
        self.assertIn("gm_yyc", codes(self.f, "RECOMMENDED"))

    def test_datafiles(self):
        self.assertEqual(get(self.f, "cred_build")[0].items, ["datafiles/segredo.env"])
        self.assertEqual(get(self.f, "dev_files")[0].items, ["datafiles/notas_gdd.docx"])
        self.assertEqual(len(get(self.f, "gm_datafiles")[0].items), 3)

    def test_secrets_build_vs_notes(self):
        self.assertIn("scripts/scr_net/scr_net.gml", " ".join(get(self.f, "secrets_build")[0].items))
        self.assertIn("notes/ideias/ideias.txt", " ".join(get(self.f, "secrets_local")[0].items))

    def test_debug_code(self):
        cheats = " ".join(get(self.f, "cheats")[0].items)
        self.assertIn("obj_player/Step_0.gml", cheats)
        self.assertNotIn("obj_debug", cheats, "inside if (debug_mode)")
        self.assertEqual(get(self.f, "gm_overlay")[0].items, ["objects/obj_player/Step_0.gml:3"])
        self.assertEqual(get(self.f, "cmdline_unguarded")[0].items, ["objects/obj_player/Step_0.gml:4"])
        self.assertIn("show_debug_message", get(self.f, "prints")[0].title)

    def test_metadata(self):
        self.assertIn("Created with GameMaker", get(self.f, "gm_display_name")[0].title)
        self.assertIn("company_info: YoYo Games Ltd", get(self.f, "exe_meta")[0].items)
        self.assertEqual(get(self.f, "default_id")[0].items, ["Android: com.company.game"])
        self.assertEqual(get(self.f, "addons_nolicense")[0].items, ["extensions/CoolExt"])

    def test_good_project(self):
        _, f = run(self.good)
        self.assertEqual(codes(f, "CRITICAL") | codes(f, "WARNING"), set(), [x.title for x in f])


class TestGeneric(unittest.TestCase):
    def test_general_checks_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write(base, "src/config.json", '{"api_key": "sk-abcdefghijklmnopqrstuvwxyz123456"}')
            write(base, ".env.local", "X=1")
            write(base, "keys/release.keystore", b"\0")
            c, f = run(base)
            self.assertEqual(c.engine, "generic")
            self.assertEqual(c.CHECKS["generic"][0], "generic_notice")
            self.assertTrue({"engine_unknown", "secrets_generic", "cred_local", "no_credits"} <= codes(f))
            self.assertFalse(codes(f, "CRITICAL"), "without knowing what ships, nothing is critical")
            self.assertNotIn("Godot", get(f, "no_credits")[0].detail)


class TestCliEngines(unittest.TestCase):
    def test_json_has_engine_and_folder_of_projects_is_refused(self):
        import io
        import json
        from contextlib import redirect_stderr, redirect_stdout
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_unity_bad(base / "jogos" / "unity")
            out = base / "saida"
            with redirect_stdout(io.StringIO()):
                code = owlcheck.main([str(base / "jogos" / "unity"), "--out", str(out), "--json", "--no-html"])
            self.assertEqual(code, 1)
            data = json.loads((out / owlcheck.REPORT_FILES["json"]).read_text(encoding="utf-8"))
            self.assertEqual(data["engine"], "unity")
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = owlcheck.main([str(base / "jogos"), "--out", str(out)])
            self.assertEqual(code, 2)
            self.assertIn("unity", err.getvalue())


if __name__ == "__main__":
    unittest.main()
