"""Packaging tests: icons, the PyInstaller spec, the .exe build and the Windows .bat."""

import ast
import importlib.util
import re
import sys
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "app" / "assets"
BAT = ROOT / "Install OwlCheck.bat"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestIcons(unittest.TestCase):
    def test_ico_has_all_windows_sizes(self):
        data = (ASSETS / "icon.ico").read_bytes()
        _, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual(kind, 1)
        sizes = set()
        for i in range(count):
            w, h = data[6 + 16 * i], data[7 + 16 * i]
            sizes.add((w or 256, h or 256))
        for s in (16, 24, 32, 48, 256):
            self.assertIn((s, s), sizes)

    def test_ico_frames_are_classic_bitmaps(self):
        """.NET Framework, which draws the app window on Windows, rejects PNG frames inside an .ico."""
        data = (ASSETS / "icon.ico").read_bytes()
        count = struct.unpack("<H", data[4:6])[0]
        for i in range(count):
            size, offset = struct.unpack("<II", data[6 + 16 * i + 8:6 + 16 * i + 16])
            self.assertNotEqual(data[offset:offset + 4], b"\x89PNG", f"frame {i} is a PNG")
            self.assertEqual(struct.unpack("<I", data[offset:offset + 4])[0], 40, "expected a BITMAPINFOHEADER")

    def test_icon_files_exist(self):
        for name in ("icon.ico", "icon.icns", "icon.png", "owl.png"):
            self.assertTrue((ASSETS / name).is_file(), name)
        self.assertEqual((ASSETS / "icon.icns").read_bytes()[:4], b"icns")

    def test_sprite_is_16x16(self):
        # read the sprite from the source, so the test doesn't need Pillow
        tree = ast.parse((ROOT / "packaging" / "make_icons.py").read_text(encoding="utf-8"))
        owl = next(ast.literal_eval(n.value) for n in tree.body
                   if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "OWL")
        self.assertEqual(len(owl), 16)
        self.assertTrue(all(len(r) == 16 and set(r) <= {"#", "."} for r in owl))


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.mod = _load("build_exe", ROOT / "packaging" / "build_exe.py")

    def test_spec_reads_version_from_script(self):
        spec = (ROOT / "packaging" / "owlcheck.spec").read_text(encoding="utf-8")
        self.assertIn('VERSION = re.search(r\'^VERSION = "([^"]+)"\'', spec)
        self.assertNotRegex(spec, r'\nVERSION = "\d')
        self.assertIn("COLLECT(exe", spec.split('elif sys.platform == "win32":')[-1],
                      "on Windows the app ships as a folder")

    def test_fingerprint_tracks_app_sources(self):
        names = {p.relative_to(ROOT).as_posix() for p in self.mod.sources()}
        for n in ("owlcheck.py", "app/app.py", "app/ui/index.html", "app/assets/icon.ico", "packaging/owlcheck.spec"):
            self.assertIn(n, names)
        self.assertEqual(self.mod.fingerprint(), self.mod.fingerprint())

    def test_up_to_date_needs_exe_and_matching_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            self.mod.DIST, self.mod.STAMP = dist, dist / ".owlcheck-build"
            exe = self.mod.target()
            self.assertFalse(self.mod.up_to_date())
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_bytes(b"x")
            self.assertFalse(self.mod.up_to_date(), "no fingerprint, so rebuild")
            self.mod.STAMP.write_text(self.mod.fingerprint(), encoding="utf-8")
            self.assertTrue(self.mod.up_to_date())
            self.mod.STAMP.write_text("outra", encoding="utf-8")
            self.assertFalse(self.mod.up_to_date(), "sources changed, so rebuild")


class TestInstaller(unittest.TestCase):
    def setUp(self):
        self.raw_iss = (ROOT / "packaging" / "owlcheck.iss").read_bytes()
        self.iss = self.raw_iss.decode("utf-8-sig")
        self.mod = _load("build_exe_inst", ROOT / "packaging" / "build_exe.py")

    def test_installs_per_user_and_updates_in_place(self):
        self.assertIn("PrivilegesRequired=lowest", self.iss)
        self.assertIn("DefaultDirName={autopf}", self.iss)
        self.assertIn("AppId={{400EFEF6-3D5C-4BD6-9E9F-205CFAE5A7E8}", self.iss,
                      "never change the AppId, or updates install as a separate app")
        self.assertIn('Name: "{app}\\_internal"', self.iss, "updates should wipe the old libraries")
        self.assertIn("CloseApplications=yes", self.iss)

    def test_three_languages_and_shortcuts(self):
        for isl in ("Default.isl", "Spanish.isl", "BrazilianPortuguese.isl"):
            self.assertIn(isl, self.iss)
        self.assertIn("{autoprograms}", self.iss)
        self.assertIn("Tasks: desktopicon", self.iss)
        # the translations have accents, and Inno Setup only reads UTF-8 correctly when the file has a BOM
        self.assertTrue(self.raw_iss.startswith(b"\xef\xbb\xbf"), "the .iss needs a BOM")
        for lang in ("english", "spanish", "brazilianportuguese"):
            for key in ("WelcomeLabel1", "WelcomeLabel2", "FinishedHeadingLabel", "FinishedLabel", "OpenOwlCheck"):
                self.assertIn(f"{lang}.{key}=", self.iss)

    def test_owlcheck_look(self):
        for rel in ("wizard-large-100.bmp", "wizard-large-200.bmp", "wizard-small-100.bmp", "fonts/Silkscreen-Bold.ttf",
                    "fonts/Rubik-Regular.ttf", "fonts/OFL-Silkscreen.txt", "fonts/OFL-Rubik.txt"):
            self.assertTrue((ROOT / "packaging" / "installer" / rel).is_file(), rel)
            self.assertIn(rel.split("/")[-1], self.iss) if rel.endswith((".bmp", ".ttf")) else None
        self.assertIn("PAPER = $00ECF1F2", self.iss, "the app's paper color, in BGR")
        self.assertIn("FR_PRIVATE", self.iss, "fonts are loaded privately, never installed on the system")
        self.assertIn("DisableWelcomePage=no", self.iss)
        bmp = (ROOT / "packaging" / "installer" / "wizard-large-100.bmp").read_bytes()
        self.assertEqual(bmp[:2], b"BM")
        self.assertEqual(struct.unpack("<ii", bmp[18:26]), (164, 314))

    def test_paths_in_script_exist(self):
        for rel in ("app/assets/icon.ico",):
            self.assertTrue((ROOT / rel).is_file())
        self.assertIn('Source: "..\\dist\\OwlCheck\\*"', self.iss)

    def test_version_and_name(self):
        src = (ROOT / "owlcheck.py").read_text(encoding="utf-8")
        self.assertIn(f'VERSION = "{self.mod.version()}"', src)
        self.assertEqual(self.mod.installer_path().name, f"OwlCheck-Setup-{self.mod.version()}.exe")
        if sys.platform != "win32":
            self.assertEqual(self.mod.build_installer(), 2)

    def test_build_installer_bat(self):
        raw = (ROOT / "packaging" / "build-installer.bat").read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        text = raw.decode("utf-8")
        self.assertIn("build_exe.py --installer", text)
        used = set(re.findall(r"(?:goto|call) :(\w+)", text))
        self.assertEqual(used - set(re.findall(r"^:(\w+)", text, re.M)), set())

    def test_ci_builds_installer(self):
        wf = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
        self.assertIn("python packaging/build_exe.py --installer", wf)
        self.assertIn("OwlCheck-Setup.exe", wf)


class TestWindowsBat(unittest.TestCase):
    def setUp(self):
        self.raw = BAT.read_bytes()
        self.text = self.raw.decode("utf-8")

    def test_crlf_and_utf8(self):
        self.assertEqual(self.raw.count(b"\n"), self.raw.count(b"\r\n"), "Windows cmd needs CRLF")
        self.assertFalse(self.raw.startswith(b"\xef\xbb\xbf"), "no BOM: cmd would try to run it as a command")
        # the owl and the "Λ" are UTF-8, so chcp 65001 has to come before the first non-ASCII character
        first_non_ascii = next(i for i, ch in enumerate(self.text) if ord(ch) > 127)
        self.assertLess(self.text.index("chcp 65001"), first_non_ascii)

    def test_git_keeps_crlf(self):
        attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.bat text eol=crlf", attrs, "without it, a Linux or macOS checkout gets LF .bat files")

    def test_owl_and_english(self):
        self.assertIn("██▄▄▄▄▄▄▄▄██", self.text)
        self.assertIn("Developed by PΛTTRN", self.text)
        self.assertIn('choice /c YN', self.text)
        self.assertNotIn("Abrindo", self.text)

    def test_builds_exe_and_falls_back_to_python(self):
        self.assertIn(r'"%VPY%" packaging\build_exe.py', self.text)
        self.assertIn(r'set "OWL_EXE=%~dp0dist\OwlCheck\OwlCheck.exe"', self.text)
        self.assertIn('start "" "%OWL_EXE%"', self.text)
        self.assertIn('start "" "%VPYW%"', self.text)

    def test_labels_exist(self):
        used = set(re.findall(r"(?:goto|call) :(\w+)", self.text))
        defined = set(re.findall(r"^:(\w+)", self.text, re.M))
        self.assertEqual(used - defined, set())


if __name__ == "__main__":
    unittest.main()
