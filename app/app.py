#!/usr/bin/env python3
"""
OwlCheck desktop app.

The window uses the system's web view (WebKit on macOS, WebView2 on Windows,
Qt on Linux) only to draw the interface. The analysis runs in Python with the
same code as the command line (owlcheck.py).

The page is loaded from memory, with no server, and its Content Security Policy
blocks every outside connection.
"""

import base64
import json
import os
import sys
import time
import traceback
from pathlib import Path


def _open_log():
    """The packaged app has no console, so a startup crash would leave no trace. Everything goes to
    owlcheck-log.txt next to the executable (or in the config folder if that isn't writable).
    The file is rewritten on every launch and holds technical messages only; the one project
    detail in it is the path of the analyzed folder."""
    if not getattr(sys, "frozen", False):
        return None
    appdata = os.environ.get("APPDATA") or str(Path.home())
    for folder in (Path(sys.executable).parent, Path(appdata) / "OwlCheck"):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            fh = open(folder / "owlcheck-log.txt", "w", encoding="utf-8", buffering=1)
        except OSError:
            continue
        sys.stdout = sys.stderr = fh
        import faulthandler
        import logging
        faulthandler.enable(fh)  # also catches crashes outside Python, e.g. in the web view
        logging.basicConfig(stream=fh, level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
        print(time.strftime("%Y-%m-%d %H:%M:%S"), "OwlCheck starting |", sys.version.split()[0], "|", sys.platform,
              "|", sys.executable)
        return folder / "owlcheck-log.txt"
    return None


LOG_PATH = _open_log()


def _trace_windows_startup():
    """Windows build only: logs each step of loading .NET and WebView2, plus any unhandled .NET
    exception, which would otherwise close the app silently."""
    if not (LOG_PATH and sys.platform == "win32"):
        return
    import logging
    import threading
    logging.getLogger("pywebview").setLevel(logging.DEBUG)

    def thread_error(args):
        print("error in thread:", args.thread.name)
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)
    threading.excepthook = thread_error
    for key in ("PYTHONNET_PYDLL", "PYTHONNET_RUNTIME"):
        print(key, "=", os.environ.get(key))
    try:
        print("loading pythonnet (clr)...")
        import clr  # noqa: F401
        print("pythonnet ok:", getattr(clr, "__file__", "?"))
        from System import AppDomain

        def dotnet_error(sender, args):
            print(".NET error:", args.ExceptionObject)
            sys.stdout.flush()
        AppDomain.CurrentDomain.UnhandledException += dotnet_error
        print(".NET ok:", AppDomain.CurrentDomain.FriendlyName)
    except BaseException:  # noqa: BLE001
        traceback.print_exc()
    sys.stdout.flush()


def _fatal(message):
    """Shows the error in a message box, since the .exe has no console, and exits."""
    print(message)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "OwlCheck", 0x10)
        except Exception:  # noqa: BLE001
            pass
    sys.exit(1)


try:
    import webview
    from webview.dom import DOMEventHandler
except Exception:  # noqa: BLE001
    traceback.print_exc()
    _fatal("OwlCheck couldn't load its window engine (pywebview).\n\n"
           + (f"Details in: {LOG_PATH}" if LOG_PATH else traceback.format_exc()))

FROZEN = getattr(sys, "frozen", False)
ROOT = Path(sys._MEIPASS) if FROZEN else Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
sys.path.insert(0, str(ROOT))

import owlcheck as core  # noqa: E402

APP_NAME = "OwlCheck"
MAX_RECENT = 8
ALLOWED_PREFS = {"motion": bool, "lang": core.norm_lang, "theme": lambda v: "dark" if v == "dark" else "light"}
THEME_BG = {"light": "#F2F1EC", "dark": "#16161A"}

TEXT = {
    "en": {
        "no_folder": "Couldn't find that folder. Choose your game's project folder.",
        "projects_inside": "The folder “{name}” isn't a project, but it has these inside: {list}. Choose one of them.",
        "gone": "Project not found. Run the analysis again.",
        "inside": "For safety, OwlCheck doesn't save files inside the project. Choose another folder.",
        "save_failed": "Couldn't save: {err}",
        "html": "HTML page (*.html)", "md": "Markdown (*.md)", "json": "JSON (*.json)", "slug": "project",
    },
    "es": {
        "no_folder": "No encontré esa carpeta. Elige la carpeta del proyecto de tu juego.",
        "projects_inside": "La carpeta “{name}” no es un proyecto, pero tiene estos dentro: {list}. Elige uno de ellos.",
        "gone": "Proyecto no encontrado. Vuelve a ejecutar el análisis.",
        "inside": "Por seguridad, OwlCheck no guarda archivos dentro del proyecto. Elige otra carpeta.",
        "save_failed": "No se pudo guardar: {err}",
        "html": "Página HTML (*.html)", "md": "Markdown (*.md)", "json": "JSON (*.json)", "slug": "proyecto",
    },
    "pt": {
        "no_folder": "Não encontrei essa pasta. Escolha a pasta do projeto do seu jogo.",
        "projects_inside": "A pasta “{name}” não é um projeto, mas tem estes dentro: {list}. Escolha um deles.",
        "gone": "Projeto não encontrado. Rode a análise de novo.",
        "inside": "Por segurança, o OwlCheck não salva arquivos dentro do projeto. Escolha outra pasta.",
        "save_failed": "Não consegui salvar: {err}",
        "html": "Página HTML (*.html)", "md": "Markdown (*.md)", "json": "JSON (*.json)", "slug": "projeto",
    },
}


def config_dir():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "owlcheck"


class Store:
    """Recent project paths, ticked items and preferences. Nothing else is stored."""

    def __init__(self, path=None):
        self.path = Path(path) if path else config_dir() / "state.json"
        old = self.path.with_name("estado.json")  # name used by early builds
        if path is None and not self.path.exists() and old.exists():
            try:
                old.replace(self.path)
            except OSError:
                self.path = old
        self.data = {"recent": [], "checks": {}, "prefs": {}}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data["recent"] = [r for r in loaded.get("recent", []) if isinstance(r, dict)]
                self.data["checks"] = loaded.get("checks", {}) if isinstance(loaded.get("checks"), dict) else {}
                prefs = loaded.get("prefs", {})
                self.data["prefs"] = {k: v for k, v in prefs.items() if k in ALLOWED_PREFS} if isinstance(prefs, dict) else {}
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass  # read-only config folder: the app still works, it just won't remember

    def add_recent(self, path, name):
        rec = [r for r in self.data["recent"] if r.get("path") != path]
        rec.insert(0, {"path": path, "name": name, "when": int(time.time())})
        self.data["recent"] = rec[:MAX_RECENT]
        self.save()

    def remove_recent(self, path):
        self.data["recent"] = [r for r in self.data["recent"] if r.get("path") != path]
        self.save()

    def set_pref(self, key, value):
        if key not in ALLOWED_PREFS:
            return False
        self.data["prefs"][key] = ALLOWED_PREFS[key](value)
        self.save()
        return True

    def checks(self, path):
        return self.data["checks"].get(path, {})

    def set_check(self, path, key, value):
        proj = self.data["checks"].setdefault(path, {})
        if value:
            proj[key] = True
        else:
            proj.pop(key, None)
        self.save()


def finding_key(f):
    """Same in every language, so ticks survive a language switch."""
    return f.uid


def resolve_project(path):
    """The project folder, or a file that identifies the engine (project.godot, a .yyp...)."""
    return core.resolve_root(path)


class Api:
    """Functions the page can call. pywebview exposes every public attribute and, on Windows, walks
    each exposed object. A public reference to the window made it walk the whole WinForms window,
    and the bridge ended up without its functions ("Choose folder" did nothing in the .exe).
    That's why the window and the store are private."""

    def __init__(self, store=None):
        self._store = store or Store()
        self._window = None
        self._last = {}  # path -> Checker from the last analysis

    @property
    def lang(self):
        return core.norm_lang(self._store.data["prefs"].get("lang", core.DEFAULT_LANG))

    def _t(self, key, **kw):
        s = TEXT[self.lang][key]
        return s.format(**kw) if kw else s

    def get_state(self):
        recent = [r for r in self._store.data["recent"] if Path(r["path"]).is_dir()]
        return {"version": core.VERSION, "recent": recent, "platform": sys.platform,
                "prefs": dict(self._store.data["prefs"]), "config_path": str(self._store.path)}

    def set_pref(self, key, value):
        return self._store.set_pref(key, value)

    def remove_recent(self, path):
        self._store.remove_recent(path)
        return self.get_state()

    def set_checked(self, path, key, value):
        self._store.set_check(path, key, bool(value))
        return True

    def choose_folder(self):
        if LOG_PATH:
            print("choose folder")
        if not self._window:
            return None
        res = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not res:
            return None
        return self.analyze(res[0] if isinstance(res, (list, tuple)) else res)

    def analyze(self, path):
        root = resolve_project(path)
        if root is None:
            return {"error": self._t("no_folder")}
        if core.detect_engine(root) == "generic":
            inside = core.find_projects(root)
            if inside:
                names = ", ".join(f"{p.name} ({core.ENGINE_NAMES[e]})" for p, e in inside[:6])
                return {"error": self._t("projects_inside", name=root.name, list=names)}
        t0 = time.perf_counter()
        checker = core.Checker(root, lang=self.lang)
        findings = checker.run()
        elapsed = time.perf_counter() - t0
        key = str(root)
        self._last[key] = checker
        self._store.add_recent(key, checker.project_name)
        checks = self._store.checks(key)
        return {
            "path": key,
            "name": checker.project_name,
            "lang": checker.lang,
            "engine": checker.engine,
            "engine_name": checker.engine_name,
            "engine_version": checker.engine_version,
            "elapsed": round(elapsed, 3),
            "scan": dict(checker.stats, findings=len(findings)),
            "counts": core.counts(findings),
            "stats": checker.facts(),
            "findings": [{
                "key": finding_key(f), "severity": f.severity, "category": f.category,
                "title": f.title, "detail": f.detail, "fix": f.fix,
                "items": [str(i) for i in f.items], "checked": bool(checks.get(finding_key(f))),
            } for f in findings],
        }

    def _checker(self, path):
        checker = self._last.get(path)
        if checker is None or checker.lang != self.lang:
            root = resolve_project(path)
            if root is None:
                return None
            checker = core.Checker(root, lang=self.lang)
            checker.run()
            self._last[path] = checker
        return checker

    def _save_dialog(self, filename, desc):
        if not self._window:
            return None
        res = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename,
                                             file_types=(desc,))
        if not res:
            return None
        return Path(res[0] if isinstance(res, (list, tuple)) else res)

    def _guard_target(self, target, path):
        project = Path(path).resolve()
        target = target.resolve()
        if target == project or project in target.parents:
            return self._t("inside")
        return None

    def export_report(self, path, fmt="html"):
        checker = self._checker(path)
        if checker is None:
            return {"error": self._t("gone")}
        slug = "".join(c if c.isalnum() else "-" for c in checker.project_name).strip("-").lower() or self._t("slug")
        if fmt == "md":
            target = self._save_dialog(f"owlcheck-{slug}.md", self._t("md"))
            content = core.render_markdown(checker, checker.findings)
        else:
            target = self._save_dialog(f"owlcheck-{slug}.html", self._t("html"))
            content = core.render_html(checker, checker.findings)
        if target is None:
            return {"cancelled": True}
        err = self._guard_target(target, path)
        if err:
            return {"error": err}
        try:
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return {"error": self._t("save_failed", err=exc)}
        return {"saved": str(target)}

    def make_manifest(self, path):
        checker = self._checker(path)
        if checker is None:
            return {"error": self._t("gone")}
        target = self._save_dialog("owlcheck-manifest.json", self._t("json"))
        if target is None:
            return {"cancelled": True}
        err = self._guard_target(target, path)
        if err:
            return {"error": err}
        manifest = core.build_manifest(checker.root, checker.files, self.lang)
        try:
            target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            return {"error": self._t("save_failed", err=exc)}
        return {"saved": str(target), "hash": manifest["aggregate_sha256"],
                "files": manifest["file_count"], "when": manifest["generated_at_utc"]}


def _data_uri(path, mime):
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def build_html(theme=None):
    html = (APP_DIR / "ui" / "index.html").read_text(encoding="utf-8")
    html = html.replace("{{MASCOT}}", _data_uri(APP_DIR / "assets" / "owl.png", "image/png"))
    fonts = APP_DIR / "assets" / "fonts"
    for key, name in (("SILK_400", "silkscreen-latin-400-normal"), ("SILK_700", "silkscreen-latin-700-normal"),
                      ("RUBIK_400", "rubik-latin-400-normal"), ("RUBIK_500", "rubik-latin-500-normal"),
                      ("RUBIK_700", "rubik-latin-700-normal"), ("RUBIK_900", "rubik-latin-900-normal")):
        html = html.replace("{{FONT_" + key + "}}", _data_uri(fonts / f"{name}.woff2", "font/woff2"))
    if theme in THEME_BG:  # start in the saved theme, no flash
        html = html.replace('<html lang="en">', f'<html lang="en" data-theme="{theme}">', 1)
    return html.replace("{{VERSION}}", core.VERSION)


def _on_drop(api, window):
    def handler(event):
        files = (event.get("dataTransfer") or {}).get("files") or []
        path = next((f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")), None)
        window.evaluate_js(f"window.owlDropped({json.dumps(path)})")
    return handler


def main():
    try:
        _run()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        _fatal("OwlCheck couldn't open.\n\n" + (f"Details in: {LOG_PATH}" if LOG_PATH else traceback.format_exc()))


def _run():
    api = Api()
    theme = api._store.data["prefs"].get("theme")
    window = webview.create_window(
        APP_NAME, html=build_html(theme), js_api=api,
        width=1120, height=780, min_size=(760, 560), background_color=THEME_BG.get(theme, THEME_BG["light"]),
    )
    api._window = window

    def on_loaded():
        print("window loaded")
        doc = window.dom.document
        doc.events.dragover += DOMEventHandler(lambda e: None, True, True)
        doc.events.drop += DOMEventHandler(_on_drop(api, window), True, True)

    window.events.loaded += on_loaded
    gui = "qt" if sys.platform.startswith("linux") else None
    _trace_windows_startup()
    print("opening window | pywebview", getattr(webview, "__version__", "?"))
    # On Windows the icon goes through .NET's System.Drawing.Icon, which only takes an .ico with
    # bitmap frames (see packaging/make_icons.py). Passing a .png crashes the app at startup.
    icon = APP_DIR / "assets" / ("icon.ico" if sys.platform == "win32" else "icon.png")
    webview.start(gui=gui, debug=os.environ.get("OWLCHECK_DEBUG") == "1", http_server=False, private_mode=True,
                  icon=str(icon))
    print("window closed")


if __name__ == "__main__":
    main()
