"""Build OwlCheck with PyInstaller, skipping the build when nothing changed.

From the repo root, with the app's requirements installed:
    python packaging/build_exe.py               build if needed
    python packaging/build_exe.py --force       rebuild anyway
    python packaging/build_exe.py --check       exit 0 if up to date, 1 if not
    python packaging/build_exe.py --installer   (Windows) also build OwlCheck-Setup-<version>.exe
                                                with Inno Setup; exits 3 if Inno Setup is missing

"Install OwlCheck.bat" runs this on every launch, so it stores a SHA-256 of the app's
sources next to the build and only rebuilds when that changes. Exit codes: 0 when the
executable is ready, 2 when the build failed.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WORK = ROOT / "build"
SPEC = ROOT / "packaging" / "owlcheck.spec"
REQS = ROOT / "packaging" / "requirements-build.txt"
STAMP = DIST / ".owlcheck-build"
ISS = ROOT / "packaging" / "owlcheck.iss"


def target():
    if sys.platform == "win32":
        return DIST / "OwlCheck" / "OwlCheck.exe"
    if sys.platform == "darwin":
        return DIST / "OwlCheck.app"
    return DIST / "OwlCheck"


def sources():
    files = [ROOT / "owlcheck.py", ROOT / "requirements-app.txt", SPEC, REQS]
    files += [p for p in (ROOT / "app").rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    return sorted(files)


def fingerprint():
    h = hashlib.sha256()
    h.update(f"{sys.version_info[:2]}|{sys.platform}".encode())
    for p in sources():
        h.update(p.relative_to(ROOT).as_posix().encode() + b"\0")
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def up_to_date():
    try:
        return target().exists() and STAMP.read_text(encoding="utf-8").strip() == fingerprint()
    except OSError:
        return False


def run(cmd):
    print("   >", " ".join(str(c) for c in cmd[2:]), flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def build():
    print("   Building the executable. The first time takes a minute or two...", flush=True)
    pip = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(REQS)]
    if run(pip) != 0:
        print("   Couldn't install PyInstaller. Check your internet connection and try again.")
        return 2
    STAMP.unlink(missing_ok=True)
    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--log-level", "WARN",
           "--distpath", str(DIST), "--workpath", str(WORK)]
    if run(cmd) != 0 or not target().exists():
        print("   PyInstaller couldn't build the executable.")
        return 2
    STAMP.write_text(fingerprint() + "\n", encoding="utf-8")
    print(f"   Done: {target().relative_to(ROOT)}")
    return 0


def version():
    text = (ROOT / "owlcheck.py").read_text(encoding="utf-8")
    return re.search(r'^VERSION = "([^"]+)"', text, re.M).group(1)


def find_iscc():
    """Find ISCC.exe on PATH or in Inno Setup's usual install folders (per-user first)."""
    found = shutil.which("iscc")
    if found:
        return Path(found)
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        for sub in ("Programs/Inno Setup 6", "Inno Setup 6"):
            if base and (Path(base) / sub / "ISCC.exe").is_file():
                return Path(base) / sub / "ISCC.exe"
    return None


def installer_path():
    return DIST / f"OwlCheck-Setup-{version()}.exe"


def build_installer():
    if sys.platform != "win32":
        print("   The installer is built on Windows only.")
        return 2
    iscc = find_iscc()
    if iscc is None:
        print("   Inno Setup isn't installed (it's free: https://jrsoftware.org/isdl.php).")
        return 3
    print(f"   Building the installer for OwlCheck {version()}...", flush=True)
    if subprocess.call([str(iscc), "/Q", f"/DMyAppVersion={version()}", str(ISS)], cwd=ROOT) != 0 \
            or not installer_path().exists():
        print("   Inno Setup couldn't build the installer.")
        return 2
    print(f"   Done: {installer_path().relative_to(ROOT)}")
    return 0


def main(argv):
    if "--check" in argv:
        return 0 if up_to_date() else 1
    if "--force" not in argv and up_to_date():
        print(f"   The executable is up to date: {target().relative_to(ROOT)}")
        code = 0
    else:
        code = build()
    if code == 0 and "--installer" in argv:
        code = build_installer()
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
