#!/usr/bin/env python3
"""
OwlCheck: a pre-release checklist for Unity, Godot 4 and GameMaker projects,
with general checks for any other folder.

Everything runs locally. The script only reads the project, never writes inside
it, and imports no networking modules (the test suite enforces this).

Usage:
    python owlcheck.py PROJECT_PATH [--lang en|es|pt] [--out FOLDER] [--md]
                       [--json] [--manifest] [--no-html] [--no-color]
"""

import argparse
import datetime
import fnmatch
import hashlib
import html
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "0.11.0"

SEVERITIES = ["CRITICAL", "WARNING", "RECOMMENDED", "OK"]

# Caches, version control and IDE folders, skipped everywhere.
SKIP_DIRS = {".godot", ".import", ".git", ".svn", ".hg", "__pycache__",
             ".vscode", ".idea", "node_modules", ".mono"}
# Top-level folders each engine generates on its own (caches, builds, logs).
SKIP_TOP = {
    "unity": {"Library", "Temp", "Logs", "obj", "UserSettings", "Build", "Builds", "MemoryCaptures", "Recordings"},
    "gamemaker": {"tmp", "Build", "Builds", "output"},
    "godot": set(),
    "generic": {"Library", "Temp", "obj", "bin", "build", "dist", "target", "venv", ".venv"},
}
MAX_FILES_GENERIC = 60000   # for unknown folders; someone may drop a whole drive

ENGINES = ("unity", "godot", "gamemaker")   # ordered by how common they are on Steam
ENGINE_NAMES = {"unity": "Unity", "godot": "Godot", "gamemaker": "GameMaker"}

# What Godot treats as a resource and exports in "all_resources" mode. An
# approximation: the real exporter also follows dependencies.
RESOURCE_EXT = {
    "tscn", "scn", "tres", "res", "gd", "cs", "gdshader", "gdshaderinc",
    "shader", "png", "jpg", "jpeg", "webp", "svg", "bmp", "tga", "exr",
    "hdr", "ktx", "dds", "wav", "ogg", "mp3", "ttf", "otf", "woff", "woff2",
    "fnt", "font", "glb", "gltf", "blend", "fbx", "obj", "dae", "json",
    "csv", "translation", "gdextension", "material", "anim", "theme",
}

# Work files that shouldn't end up in a public build.
DEV_EXT = {
    "md", "txt", "doc", "docx", "odt", "pdf", "rtf", "xlsx", "xls", "ods",
    "psd", "kra", "xcf", "aseprite", "ase", "afphoto", "afdesign", "ai",
    "sai", "clip", "blend1", "mov", "mp4", "zip", "rar", "7z", "log",
}
SENSITIVE_EXT = {"env", "pem", "key", "p12", "pfx", "keystore", "jks"}
DEV_NAME_HINTS = re.compile(
    r"(?i)(gdd|design[_\- ]?doc|roteiro|script_draft|rascunho|draft|notes?|"
    r"anotac|todo|backlog|changelog_interno|senha|password)")

# Text files worth scanning for secrets.
TEXT_SCAN_EXT = {
    "gd", "cs", "cfg", "json", "tres", "tscn", "env", "txt", "ini", "yaml",
    "yml", "xml", "toml", "csv", "md", "gdshader", "properties",
    "gml", "yy", "yyp", "asset", "prefab", "unity", "js", "lua", "py",
}
YAML_EXT = {"asset", "prefab", "unity", "yaml", "yml"}
MAX_TEXT_BYTES = 2 * 1024 * 1024

SECRET_PATTERNS = [
    ("private_key", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----")),
    ("aws", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    ("sk", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("github", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("discord", re.compile(
        r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+")),
]
GENERIC_SECRET = re.compile(
    r"(?i)\b(api[_\-]?key|apikey|secret|client[_\-]?secret|token|"
    r"access[_\-]?key|password|passwd|senha)\b\s*[:=]\s*[\"']([^\"']{8,})[\"']")
# Unity YAML (ScriptableObjects, scenes) stores values unquoted.
YAML_SECRET = re.compile(
    r"(?i)^\s*-?\s*(?:m_)?(api[_\-]?key|apikey|secret|client[_\-]?secret|token|access[_\-]?token|"
    r"access[_\-]?key|password|passwd|senha)\s*:\s*['\"]?([A-Za-z0-9_\-./+=]{12,})['\"]?\s*$")
PLACEHOLDER_HINTS = ("your", "example", "changeme", "placeholder", "xxxx",
                     "seu_", "sua_", "insira", "<", "${")

PRINT_RE = re.compile(
    r"^\s*(print|prints|printt|printerr|printraw|print_rich|print_debug)\s*\(")
BREAKPOINT_RE = re.compile(r"^\s*breakpoint\b")
CHEAT_RE = re.compile(
    r"(?i)\b(cheats?|god_?mode|noclip|no_clip|unlock_?all|debug_?menu|"
    r"skip_?level|level_?skip|infinite_?(?:lives|health|money|ammo)|"
    r"dev_?mode|modo_?dev|trapaca)\b")
CMDLINE_RE = re.compile(r"\bget_cmdline_(?:user_)?args\b")
GUARD_RE = re.compile(r"\b(is_debug_build|has_feature)\b")
DEMO_FEATURE_RE = re.compile(r"has_feature\(\s*[\"']demo[\"']\s*\)")
TODO_RE = re.compile(r"#.*\b(TODO|FIXME|HACK|XXX)\b")
C_TODO_RE = re.compile(r"(?://|/\*|^\s*\*).*\b(TODO|FIXME|HACK|XXX)\b")
CS_PRINT_RE = re.compile(r"\bDebug\.(?:Log|LogFormat|LogWarning|LogWarningFormat)\s*\(")
CS_BREAK_RE = re.compile(r"\b(?:Debug|Debugger)\.Break\s*\(")
CS_CMDLINE_RE = re.compile(r"\bEnvironment\.(?:GetCommandLineArgs\s*\(|CommandLine\b)")
CS_GUARD_RE = re.compile(r"\b(?:Debug\.isDebugBuild|Application\.isEditor)\b")
CS_PP_GUARD_RE = re.compile(r"(?<!!)\b(UNITY_EDITOR|DEVELOPMENT_BUILD|DEBUG)\b")
GML_PRINT_RE = re.compile(r"\bshow_debug_message(?:_ext)?\s*\(")
GML_OVERLAY_RE = re.compile(r"\bshow_debug_overlay\s*\(\s*true\b")
GML_CMDLINE_RE = re.compile(r"\bparameter_(?:string|count)\s*\(")
GML_GUARD_RE = re.compile(r"\b(?:debug_mode|GM_build_type)\b")
GML_DEMO_RE = re.compile(r"(?i)#macro\s+(?:\w+:)?\w*demo\w*\b")
TEST_WORDS = {"test", "tests", "testing", "debug", "sandbox", "playground", "prototype", "proto", "temp", "tmp",
              "wip", "teste", "testes", "dev", "scratch"}


def _words(name):
    """'TestScene_02' -> ['test', 'scene', '02']"""
    return [w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name)]


def looks_like_test(name):
    return any(w in TEST_WORDS for w in _words(name))
UNITY_EDITOR_DIRS = {"Editor", "Editor Default Resources", "Gizmos"}
UNITY_PLATFORM_DIRS = {"x86", "x86_64", "arm64", "Android", "iOS", "macOS", "OSX", "Windows", "Linux", "WebGL",
                       "Editor", "tvOS", "Switch", "PS4", "PS5", "XboxOne", "GameCore"}
LEVEL_HINT_RE = re.compile(
    r"(?i)(level|fase|stage|world|mundo|nivel|chapter|capitulo|mission|missao|"
    r"boss|ending|final)[_\- ]?\d*")

LICENSE_NAMES = re.compile(r"(?i)(license|licence|licen[cç]a|copying|\bofl\b|notice)")
CREDITS_NAMES = re.compile(r"(?i)(credits|creditos|third[_\-]?party|attribution)")
AI_DISCLOSURE_HINTS = re.compile(
    r"(?i)(ai[_\- ]?disclosure|declaracao[_\- ]?de[_\- ]?ia|uso[_\- ]?de[_\- ]?ia|"
    r"generative ai|ia generativa|gerad[oa]s? (?:por|com) ia|ai[- ]generated)")

GODOT_DEFAULT_ICON_MARK = "#478cbf"


# Languages

LANGS = ("en", "es", "pt")
DEFAULT_LANG = "en"


def norm_lang(lang):
    lang = str(lang or "").lower()[:2]
    return lang if lang in LANGS else DEFAULT_LANG


TEXT = {
    "en": {
        "sev.CRITICAL": "Critical", "sev.WARNING": "Warning", "sev.RECOMMENDED": "Recommended", "sev.OK": "OK",
        "more": "... and {n} more", "how_fix": "How to fix", "summary": "Summary",
        "local": "Local analysis. Nothing left your computer.",
        "md_generated": "Generated on {date} with OwlCheck {version}. Analysis done locally.",
        "html_priv": "Report generated locally. OwlCheck only read the project files; nothing was changed and nothing left your computer.",
        "version": "version", "html_lang": "en",
        "footer": "OwlCheck · Owlgorithm Research · open source",
        "virtual_preset": "(default, no export_presets.cfg)",
        "cli_not_found": "Folder not found: {path}",
        "cli_inside": "For safety, OwlCheck never writes inside the project. Use --out with another folder.",
        "cli_saved": "Saved: {path}",
        "manifest_note": ("Keep this file and record the aggregate_sha256 somewhere with a verifiable date "
                          "(e.g. OpenTimestamps, an email to yourself, a digital notary). "
                          "It helps prove the project existed on this date."),
        "date_fmt": "%Y-%m-%d %H:%M",
        "engine.generic": "unknown engine", "project_of": "{engine} project",
        "cli_projects_inside": "This folder isn't a project, but it contains these projects. Run OwlCheck on one of them:",
    },
    "es": {
        "sev.CRITICAL": "Crítico", "sev.WARNING": "Atención", "sev.RECOMMENDED": "Recomendado", "sev.OK": "OK",
        "more": "... y {n} más", "how_fix": "Cómo resolverlo", "summary": "Resumen",
        "local": "Análisis local. Nada salió de tu computadora.",
        "md_generated": "Generado el {date} con OwlCheck {version}. Análisis hecho localmente.",
        "html_priv": "Informe generado localmente. OwlCheck solo leyó los archivos del proyecto; no se cambió nada y nada salió de tu computadora.",
        "version": "versión", "html_lang": "es",
        "footer": "OwlCheck · Owlgorithm Research · código abierto",
        "virtual_preset": "(por defecto, sin export_presets.cfg)",
        "cli_not_found": "Carpeta no encontrada: {path}",
        "cli_inside": "Por seguridad, OwlCheck no escribe dentro del proyecto. Usa --out con otra carpeta.",
        "cli_saved": "Guardado: {path}",
        "manifest_note": ("Guarda este archivo y registra el aggregate_sha256 en algún lugar con fecha verificable "
                          "(p. ej., OpenTimestamps, un correo a ti mismo, un notario digital). "
                          "Ayuda a demostrar que el proyecto existía en esta fecha."),
        "date_fmt": "%d/%m/%Y %H:%M",
        "engine.generic": "motor no reconocido", "project_of": "Proyecto de {engine}",
        "cli_projects_inside": "Esta carpeta no es un proyecto, pero contiene estos proyectos. Ejecuta OwlCheck en uno de ellos:",
    },
    "pt": {
        "sev.CRITICAL": "Crítico", "sev.WARNING": "Atenção", "sev.RECOMMENDED": "Recomendado", "sev.OK": "OK",
        "more": "... e mais {n}", "how_fix": "Como resolver", "summary": "Resumo",
        "local": "Análise local. Nada saiu do seu computador.",
        "md_generated": "Gerado em {date} com OwlCheck {version}. Análise feita localmente.",
        "html_priv": "Relatório gerado localmente. O OwlCheck só leu os arquivos do projeto; nada foi alterado e nada saiu do seu computador.",
        "version": "versão", "html_lang": "pt-BR",
        "footer": "OwlCheck · Owlgorithm Research · open source",
        "virtual_preset": "(padrão, sem export_presets.cfg)",
        "cli_not_found": "Pasta não encontrada: {path}",
        "cli_inside": "Por segurança, o OwlCheck não escreve dentro do projeto. Use --out com outra pasta.",
        "cli_saved": "Salvo: {path}",
        "manifest_note": ("Guarde este arquivo e registre o aggregate_sha256 em algum lugar com data verificável "
                          "(ex.: OpenTimestamps, e-mail para você mesmo, cartório digital). "
                          "Isso ajuda a provar que o projeto existia nesta data."),
        "date_fmt": "%d/%m/%Y %H:%M",
        "engine.generic": "engine não reconhecida", "project_of": "Projeto {engine}",
        "cli_projects_inside": "Esta pasta não é um projeto, mas tem estes projetos dentro. Rode o OwlCheck em um deles:",
    },
}

CATEGORIES = {
    "project":    {"en": "Project",    "es": "Proyecto",    "pt": "Projeto"},
    "export":     {"en": "Export",     "es": "Exportación", "pt": "Exportação"},
    "protection": {"en": "Protection", "es": "Protección",  "pt": "Proteção"},
    "demo":       {"en": "Demo",       "es": "Demo",        "pt": "Demo"},
    "secrets":    {"en": "Secrets",    "es": "Secretos",    "pt": "Segredos"},
    "files":      {"en": "Files",      "es": "Archivos",    "pt": "Arquivos"},
    "debug":      {"en": "Debug",      "es": "Depuración",  "pt": "Debug"},
    "metadata":   {"en": "Metadata",   "es": "Metadatos",   "pt": "Metadados"},
    "licenses":   {"en": "Licenses",   "es": "Licencias",   "pt": "Licenças"},
    "ai":         {"en": "AI",         "es": "IA",          "pt": "IA"},
}

SECRET_LABELS = {
    "private_key": {"en": "Private key", "es": "Clave privada", "pt": "Chave privada"},
    "aws": {"en": "AWS key", "es": "Clave de AWS", "pt": "Chave AWS"},
    "google": {"en": "Google API key", "es": "Clave de API de Google", "pt": "Chave de API do Google"},
    "sk": {"en": "API key (sk- format)", "es": "Clave de API (formato sk-)", "pt": "Chave de API (formato sk-)"},
    "github": {"en": "GitHub token", "es": "Token de GitHub", "pt": "Token do GitHub"},
    "slack": {"en": "Slack token", "es": "Token de Slack", "pt": "Token do Slack"},
    "discord": {"en": "Discord webhook", "es": "Webhook de Discord", "pt": "Webhook do Discord"},
}

# Each check: (title, detail, how to fix). {fields} are filled in when the finding is added.
MESSAGES = {
    "no_project": {
        "en": ("project.godot not found",
               "The folder you chose doesn't look like the root of a Godot project.",
               "Point OwlCheck at the folder that contains project.godot."),
        "es": ("No se encontró project.godot",
               "La carpeta indicada no parece ser la raíz de un proyecto de Godot.",
               "Ejecuta OwlCheck apuntando a la carpeta que contiene project.godot."),
        "pt": ("project.godot não encontrado",
               "A pasta indicada não parece ser a raiz de um projeto Godot.",
               "Rode o OwlCheck apontando para a pasta que contém o project.godot."),
    },
    "godot3": {
        "en": ("Project uses Godot {version}", "OwlCheck was built for Godot 4. Some checks may not apply to 3.x.", ""),
        "es": ("Proyecto en Godot {version}", "OwlCheck está hecho para Godot 4. Algunas comprobaciones pueden no aplicar a 3.x.", ""),
        "pt": ("Projeto em Godot {version}", "O OwlCheck foi feito para Godot 4. Algumas checagens podem não valer para o 3.x.", ""),
    },
    "no_presets": {
        "en": ("No export presets configured",
               "Without export_presets.cfg, the analysis assumes Godot's default: export all resources.",
               "Create your presets in Project > Export before building."),
        "es": ("No hay presets de exportación configurados",
               "Sin export_presets.cfg, el análisis asume el comportamiento por defecto de Godot: exportar todos los recursos.",
               "Crea los presets en Proyecto > Exportar antes de generar la build."),
        "pt": ("Nenhum preset de exportação configurado",
               "Sem export_presets.cfg, a análise assume o padrão do Godot: exportar todos os recursos.",
               "Crie os presets em Projeto > Exportar antes de gerar a build."),
    },
    "enc_dir_off": {
        "en": ("Preset '{name}' ({platform}): pack directory not encrypted",
               "The contents are encrypted, but the list of files inside the .pck is still visible.",
               "Check 'Encrypt Directory' in the preset's Encryption tab."),
        "es": ("Preset '{name}' ({platform}): directorio del paquete sin cifrar",
               "El contenido está cifrado, pero la lista de archivos del .pck sigue visible.",
               "Marca 'Encrypt Directory' en la pestaña Encryption del preset."),
        "pt": ("Preset '{name}' ({platform}): diretório do pacote sem criptografia",
               "O conteúdo está criptografado, mas a lista de arquivos do .pck fica visível.",
               "Marque 'Encrypt Directory' na aba Encryption do preset."),
    },
    "enc_ok": {
        "en": ("Preset '{name}' ({platform}): pack encrypted",
               "Remember: the key lives inside the executable. This raises the cost of extraction; it doesn't prevent it.", ""),
        "es": ("Preset '{name}' ({platform}): paquete cifrado",
               "Recuerda: la clave queda dentro del ejecutable. Esto encarece la extracción, no la impide.", ""),
        "pt": ("Preset '{name}' ({platform}): pacote criptografado",
               "Lembre: a chave fica dentro do executável. Isso aumenta o custo de extrair, não impede.", ""),
    },
    "enc_off": {
        "en": ("Preset '{name}' ({platform}): pack (.pck) not encrypted",
               "Any public extraction tool can open the .pck and copy scenes, scripts and assets.",
               "Turn on 'Encrypt PCK' and 'Encrypt Directory'. This requires compiling your own export templates with "
               "the key (SCRIPT_AES256_ENCRYPTION_KEY). Someone who knows how can extract the key from the executable, "
               "so treat it as a barrier, not a vault."),
        "es": ("Preset '{name}' ({platform}): paquete (.pck) sin cifrar",
               "Cualquier herramienta pública de extracción abre el .pck y copia escenas, scripts y assets.",
               "Activa 'Encrypt PCK' y 'Encrypt Directory'. Requiere compilar tus propias plantillas de exportación con "
               "la clave (SCRIPT_AES256_ENCRYPTION_KEY). Quien sepa cómo puede extraer la clave del ejecutable, así que "
               "tómalo como una barrera, no como una caja fuerte."),
        "pt": ("Preset '{name}' ({platform}): pacote (.pck) sem criptografia",
               "Qualquer ferramenta pública de extração abre o .pck e copia cenas, scripts e assets.",
               "Ative 'Encrypt PCK' e 'Encrypt Directory'. Exige compilar templates de exportação próprios com a chave "
               "(SCRIPT_AES256_ENCRYPTION_KEY). A chave pode ser extraída do executável por quem souber, então trate "
               "como barreira, não cofre."),
    },
    "script_mode_unset": {
        "en": ("Preset '{name}' ({platform}): script export mode not set",
               "In older versions of Godot 4 (before 4.3), scripts ship as readable text.",
               "Use Godot 4.3+ and set 'Script Export Mode' to compressed binary."),
        "es": ("Preset '{name}' ({platform}): modo de exportación de scripts no definido",
               "En versiones antiguas de Godot 4 (antes de la 4.3), los scripts se exportan como texto legible.",
               "Usa Godot 4.3+ y define 'Script Export Mode' como binario comprimido."),
        "pt": ("Preset '{name}' ({platform}): modo de exportação de scripts não definido",
               "Em versões antigas do Godot 4 (antes da 4.3) os scripts vão como texto legível.",
               "Use Godot 4.3+ e defina 'Script Export Mode' como binário comprimido."),
    },
    "script_text": {
        "en": ("Preset '{name}' ({platform}): scripts exported as text",
               "Your GDScript code ships readable inside the build, names and comments included.",
               "In the preset's Scripts tab, switch to 'Compressed binary tokens'."),
        "es": ("Preset '{name}' ({platform}): scripts exportados como texto",
               "Tu código GDScript va legible dentro de la build, con nombres y comentarios.",
               "En la pestaña Scripts del preset, cambia a 'Compressed binary tokens'."),
        "pt": ("Preset '{name}' ({platform}): scripts exportados como texto",
               "Seu código GDScript vai legível, com nomes e comentários, dentro da build.",
               "Na aba Scripts do preset, troque para 'Compressed binary tokens'."),
    },
    "script_bin": {
        "en": ("Preset '{name}' ({platform}): scripts exported as binary",
               "Helps against casual reading. Decompilers can still rebuild the code.", ""),
        "es": ("Preset '{name}' ({platform}): scripts exportados en formato binario",
               "Ayuda contra la lectura casual. Los descompiladores aún pueden reconstruir el código.", ""),
        "pt": ("Preset '{name}' ({platform}): scripts exportados em formato binário",
               "Ajuda contra leitura casual. Decompiladores ainda conseguem reconstruir o código.", ""),
    },
    "demo_flag_no_preset": {
        "en": ("Code uses the 'demo' flag, but there is no demo preset",
               "There's a demo check in the code, but no preset has 'demo' in its name or features.",
               "Create a separate preset for the demo, with 'demo' in Custom Features."),
        "es": ("El código usa el flag 'demo', pero no hay preset de demo",
               "Hay una comprobación de demo en el código, pero ningún preset tiene 'demo' en el nombre o en las features.",
               "Crea un preset aparte para la demo, con 'demo' en Custom Features."),
        "pt": ("Código usa a flag 'demo', mas não há preset de demo",
               "Existe checagem de demo no código, mas nenhum preset com 'demo' no nome ou nas features.",
               "Crie um preset separado para a demo, com 'demo' em Custom Features."),
    },
    "no_demo": {
        "en": ("No demo preset found", "If you're shipping a demo, create a separate preset with 'demo' in its name.", ""),
        "es": ("No se encontró preset de demo", "Si vas a lanzar una demo, crea un preset aparte con 'demo' en el nombre.", ""),
        "pt": ("Nenhum preset de demo encontrado", "Se for lançar uma demo, crie um preset separado com 'demo' no nome.", ""),
    },
    "demo_full": {
        "en": ("Demo preset '{name}' exports the whole game",
               "The preset exports every resource ({scenes} scenes). Locking levels in code doesn't remove them from "
               "the .pck: anyone can extract the full game from the demo file.",
               "Change the preset filter to 'Export selected scenes' and tick only what the demo uses, or fill the "
               "exclude filter with the full game's folders."),
        "es": ("El preset de demo '{name}' exporta el juego entero",
               "El preset exporta todos los recursos ({scenes} escenas). Bloquear niveles por código no los quita del "
               ".pck: cualquiera puede extraer el juego completo del archivo de la demo.",
               "Cambia el filtro del preset a 'Exportar escenas seleccionadas' y marca solo lo que usa la demo, o "
               "completa el filtro de exclusión con las carpetas del juego completo."),
        "pt": ("Preset de demo '{name}' exporta o jogo inteiro",
               "O preset exporta todos os recursos ({scenes} cenas). Bloquear fases pelo código não tira o conteúdo do "
               ".pck: qualquer pessoa extrai o jogo completo do arquivo da demo.",
               "Mude o filtro do preset para 'Exportar cenas selecionadas' e marque só o que a demo usa, ou preencha o "
               "filtro de exclusão com as pastas do jogo completo."),
    },
    "demo_exclude": {
        "en": ("Demo preset '{name}' uses an exclude filter",
               "{scenes} scenes still go in. Make sure nothing beyond the demo slipped through.",
               "Review the list below. Scenes that look like levels, bosses or endings deserve a closer look."),
        "es": ("El preset de demo '{name}' usa filtro de exclusión",
               "Todavía entran {scenes} escenas. Comprueba que no se haya colado nada más allá de la demo.",
               "Revisa la lista de abajo. Las escenas que parecen niveles, jefes o finales merecen atención."),
        "pt": ("Preset de demo '{name}' usa filtro de exclusão",
               "Ainda entram {scenes} cenas. Confira se nada além da demo ficou.",
               "Revise a lista abaixo. Cenas com cara de fase, chefe ou final merecem atenção."),
    },
    "demo_selected": {
        "en": ("Demo preset '{name}' exports selected files only",
               "{files} files ticked (Godot also adds their dependencies).",
               "Open the demo build and confirm only the planned content is there."),
        "es": ("El preset de demo '{name}' exporta solo archivos seleccionados",
               "{files} archivos marcados (Godot también incluye sus dependencias).",
               "Abre la build de la demo y confirma que solo está el contenido previsto."),
        "pt": ("Preset de demo '{name}' exporta só arquivos selecionados",
               "{files} arquivos marcados (o Godot inclui também as dependências deles).",
               "Abra a build da demo e confirme que só o conteúdo planejado está lá."),
    },
    "demo_code_only": {
        "en": ("Demo lock done only in code",
               "has_feature('demo') hides content during play, but the content is still in the pack.",
               "Combine the code lock with the export filter; never rely on it alone."),
        "es": ("Bloqueo de la demo hecho solo por código",
               "has_feature('demo') oculta contenido durante el juego, pero el contenido sigue en el paquete.",
               "Usa el bloqueo por código junto con el filtro de exportación, nunca solo."),
        "pt": ("Bloqueio da demo feito só pelo código",
               "has_feature('demo') esconde conteúdo durante o jogo, mas o conteúdo continua no pacote.",
               "Use o bloqueio no código junto com o filtro de exportação, nunca sozinho."),
    },
    "secrets_build": {
        "en": ("Possible keys or passwords inside the build",
               "These files go into the exported game. Anyone who extracts the pack can read the values.",
               "Take the keys out of the project. If the game needs to talk to a service, put your own server in "
               "between. Rotate (revoke) any key that already shipped in a build."),
        "es": ("Posibles claves o contraseñas dentro de la build",
               "Estos archivos van al juego exportado. Cualquiera que extraiga el paquete puede leer los valores.",
               "Saca las claves del proyecto. Si el juego necesita hablar con un servicio, usa un servidor propio como "
               "intermediario. Cambia (revoca) cualquier clave que ya haya ido en una build."),
        "pt": ("Possíveis chaves ou senhas dentro da build",
               "Esses arquivos vão para o jogo exportado. Qualquer pessoa que extrair o pacote lê os valores.",
               "Tire as chaves do projeto. Se o jogo precisa falar com um serviço, use um servidor seu como "
               "intermediário. Troque (revogue) qualquer chave que já tenha ido para uma build."),
    },
    "secrets_local": {
        "en": ("Possible keys or passwords in the project (outside the build)",
               "They don't go into the game, but they leak if the project folder ends up on GitHub or in a public backup.",
               "Move them out of the project folder, or at least make sure they're in .gitignore."),
        "es": ("Posibles claves o contraseñas en el proyecto (fuera de la build)",
               "No van al juego, pero se filtran si la carpeta del proyecto termina en GitHub o en una copia pública.",
               "Muévelas fuera de la carpeta del proyecto o asegúrate de que estén en el .gitignore."),
        "pt": ("Possíveis chaves ou senhas no projeto (fora da build)",
               "Não vão para o jogo, mas vazam se a pasta do projeto for para o GitHub ou um backup público.",
               "Mova para fora da pasta do projeto ou garanta que estão no .gitignore."),
    },
    "secrets_none": {
        "en": ("No obvious keys or passwords found", "The search looks for known patterns; it doesn't replace your own review.", ""),
        "es": ("No se encontraron claves ni contraseñas aparentes", "La búsqueda es por patrones conocidos; no sustituye tu propia revisión.", ""),
        "pt": ("Nenhuma chave ou senha aparente encontrada", "A busca é por padrões conhecidos; não substitui uma revisão sua.", ""),
    },
    "cred_build": {
        "en": ("Credential files going into the build",
               ".env files, keys or keystores are included in the export.",
               "Remove them from the preset's include filter and move these files out of the project folder."),
        "es": ("Archivos de credenciales entrando en la build",
               "Archivos .env, claves o keystores están incluidos en la exportación.",
               "Quítalos del filtro de inclusión del preset y saca esos archivos de la carpeta del proyecto."),
        "pt": ("Arquivos de credencial entrando na build",
               "Arquivos .env, chaves ou keystores estão incluídos na exportação.",
               "Remova do filtro de inclusão do preset e tire esses arquivos da pasta do projeto."),
    },
    "cred_local": {
        "en": ("Credential files inside the project folder",
               "They don't go into the game, but they're exposed if the project is shared or put under version control.",
               "Keep keystores and .env files outside the project, or at least in .gitignore."),
        "es": ("Archivos de credenciales dentro de la carpeta del proyecto",
               "No van al juego, pero quedan expuestos si el proyecto se comparte o se versiona.",
               "Guarda keystores y .env fuera del proyecto, o como mínimo en el .gitignore."),
        "pt": ("Arquivos de credencial dentro da pasta do projeto",
               "Não vão para o jogo, mas ficam expostos se o projeto for compartilhado ou versionado.",
               "Guarde keystores e .env fora do projeto, ou no mínimo no .gitignore."),
    },
    "dev_files": {
        "en": ("Preset '{name}': work files in the build",
               "Documents, drafts or art source files are being exported. A leaked GDD or note gives away plans and "
               "upcoming content.",
               "Adjust the include filter or add those folders to the exclude filter. Work-only folders can get a "
               ".gdignore file."),
        "es": ("Preset '{name}': archivos de trabajo en la build",
               "Se están exportando documentos, borradores o archivos fuente de arte. Un GDD o una nota filtrada "
               "revela planes y contenido futuro.",
               "Ajusta el filtro de inclusión o añade esas carpetas al filtro de exclusión. Las carpetas solo de "
               "trabajo pueden llevar un archivo .gdignore."),
        "pt": ("Preset '{name}': arquivos de trabalho na build",
               "Documentos, rascunhos ou arquivos-fonte de arte estão sendo exportados. Um GDD ou anotação vazado "
               "entrega planos e conteúdo futuro.",
               "Ajuste o filtro de inclusão ou adicione as pastas ao filtro de exclusão. Pastas só de trabalho podem "
               "ganhar um arquivo .gdignore."),
    },
    "breakpoints": {
        "en": ("Leftover breakpoints in the code",
               "'breakpoint' does nothing in the final build, but it points to test code left behind.",
               "Remove them before shipping."),
        "es": ("Breakpoints olvidados en el código",
               "'breakpoint' no hace nada en la build final, pero indica código de prueba que se quedó atrás.",
               "Quítalos antes de lanzar."),
        "pt": ("Breakpoints esquecidos no código",
               "'breakpoint' não faz nada na build final, mas indica código de teste que ficou para trás.",
               "Remova antes de lançar."),
    },
    "cheats": {
        "en": ("Possible cheats or developer menus",
               "Terms typical of test tools show up in the exported code. Players tend to find and trigger these shortcuts.",
               "Guard them with 'if OS.is_debug_build():' or a feature tag that only exists in the test build."),
        "es": ("Posibles trucos o menús de desarrollador",
               "Aparecen en el código exportado términos típicos de herramientas de prueba. Los jugadores suelen "
               "encontrar y activar estos atajos.",
               "Protégelos con 'if OS.is_debug_build():' o con una feature tag que solo exista en la build de prueba."),
        "pt": ("Possíveis cheats ou menus de desenvolvedor",
               "Termos típicos de ferramentas de teste aparecem no código exportado. Jogadores costumam achar e ativar "
               "esses atalhos.",
               "Proteja com 'if OS.is_debug_build():' ou com uma feature tag que só existe na build de teste."),
    },
    "cmdline_unguarded": {
        "en": ("Unguarded command-line hooks",
               "The game reads command-line arguments (e.g. --autotest) with no debug-build check around them. Any "
               "player can pass the argument and trigger the test mode.",
               "Wrap them in 'if OS.is_debug_build():' or use OS.has_feature() with a test-only tag."),
        "es": ("Ganchos de línea de comandos sin protección",
               "El juego lee argumentos de línea de comandos (p. ej., --autotest) sin ninguna comprobación de build de "
               "depuración alrededor. Cualquier jugador puede pasar el argumento y activar el modo de prueba.",
               "Envuélvelos en 'if OS.is_debug_build():' o usa OS.has_feature() con una tag solo de prueba."),
        "pt": ("Ganchos de linha de comando sem proteção",
               "O jogo lê argumentos de linha de comando (ex.: --autotest) sem nenhuma checagem de build de debug em "
               "volta. Qualquer jogador pode passar o argumento e acionar o modo de teste.",
               "Envolva com 'if OS.is_debug_build():' ou use OS.has_feature() com uma tag só de teste."),
    },
    "cmdline_guarded": {
        "en": ("Command-line hooks appear guarded",
               "The hooks that read arguments sit inside an is_debug_build/has_feature check. Double-check it's the right one.", ""),
        "es": ("Ganchos de línea de comandos con protección aparente",
               "Los ganchos que leen argumentos están dentro de una comprobación de is_debug_build/has_feature. "
               "Verifica que sea la correcta.", ""),
        "pt": ("Ganchos de linha de comando com proteção aparente",
               "Os ganchos que leem argumentos estão dentro de uma checagem de is_debug_build/has_feature. Confira se "
               "é a checagem certa.", ""),
    },
    "prints": {
        "en": ("Print calls in exported code ({n})",
               "Prints go to the player's log and can reveal internal structure or hint at ways to cheat.",
               "Remove the debugging ones or switch to print_debug (which only shows in debug builds)."),
        "es": ("Llamadas a print en el código exportado ({n})",
               "Los prints van al log del jugador y pueden revelar la estructura interna o dar pistas para hacer trampa.",
               "Quita los de depuración o cámbialos por print_debug (que solo aparece en builds de depuración)."),
        "pt": ("Chamadas de print no código exportado ({n})",
               "Prints vão para o log do jogador e podem revelar estrutura interna ou dar pistas para trapaça.",
               "Remova os de depuração ou troque por print_debug (que só aparece em builds de debug)."),
    },
    "todos": {
        "en": ("TODO/FIXME/HACK markers ({n})",
               "They don't affect the game, but check whether any of them is unfinished work before release.", ""),
        "es": ("Marcadores TODO/FIXME/HACK ({n})",
               "No afectan al juego, pero vale la pena revisar si alguno es trabajo pendiente antes del lanzamiento.", ""),
        "pt": ("Marcadores TODO/FIXME/HACK ({n})",
               "Não afetam o jogo, mas vale revisar se algum é pendência antes do lançamento.", ""),
    },
    "no_name": {
        "en": ("Project has no name", "The name shows up in the game window and in several places in the system.",
               "Set it in Project Settings > Application > Config > Name."),
        "es": ("Proyecto sin nombre", "El nombre aparece en la ventana del juego y en varios lugares del sistema.",
               "Defínelo en Configuración del Proyecto > Aplicación > Config > Nombre."),
        "pt": ("Projeto sem nome", "O nome aparece na janela do jogo e em vários lugares do sistema.",
               "Defina em Configurações do Projeto > Aplicação > Config > Nome."),
    },
    "no_version": {
        "en": ("Project has no version number", "A version helps players report bugs and helps you track builds.",
               "Set application/config/version (e.g. 0.1.0-demo)."),
        "es": ("Proyecto sin número de versión", "La versión ayuda a los jugadores a reportar errores y a ti a seguir las builds.",
               "Define application/config/version (p. ej., 0.1.0-demo)."),
        "pt": ("Projeto sem número de versão", "Versão ajuda o jogador a reportar bugs e você a rastrear builds.",
               "Defina application/config/version (ex.: 0.1.0-demo)."),
    },
    "no_icon": {
        "en": ("Project has no icon", "Without an icon, the game uses Godot's default.", "Set your own icon."),
        "es": ("Proyecto sin icono", "Sin icono, el juego usa el de Godot por defecto.", "Define un icono propio."),
        "pt": ("Projeto sem ícone definido", "Sem ícone, o jogo usa o padrão do Godot.", "Defina um ícone próprio."),
    },
    "default_icon": {
        "en": ("Default Godot icon", "The project icon is still the little blue robot every new project starts with.",
               "Replace it with your game's icon."),
        "es": ("Icono por defecto de Godot", "El icono del proyecto sigue siendo el robotito azul que trae todo proyecto nuevo.",
               "Cámbialo por el icono de tu juego."),
        "pt": ("Ícone padrão do Godot", "O ícone do projeto ainda é o robozinho azul que vem com todo projeto novo.",
               "Troque pelo ícone do seu jogo."),
    },
    "exe_meta": {
        "en": ("Preset '{name}': executable details left blank",
               "They show up under Properties > Details for the .exe on Windows. Leaving them blank looks amateurish and "
               "can increase antivirus warnings.",
               "Fill them in on the preset's Options tab."),
        "es": ("Preset '{name}': datos del ejecutable en blanco",
               "Aparecen en Propiedades > Detalles del .exe en Windows. En blanco se ve poco profesional y puede "
               "aumentar las alertas del antivirus.",
               "Complétalos en la pestaña Options del preset."),
        "pt": ("Preset '{name}': dados do executável em branco",
               "Aparecem em Propriedades > Detalhes do .exe no Windows. Em branco passa amadorismo e pode aumentar "
               "alertas de antivírus.",
               "Preencha na aba Options do preset."),
    },
    "default_id": {
        "en": ("Preset '{name}': default identifier ({value})",
               "Stores use this identifier as the app's unique ID, and it can't be changed later.",
               "Use something like com.yourstudio.yourgame."),
        "es": ("Preset '{name}': identificador por defecto ({value})",
               "Las tiendas usan este identificador como ID único de la app y no se puede cambiar después.",
               "Usa algo como com.tuestudio.tujuego."),
        "pt": ("Preset '{name}': identificador padrão ({value})",
               "Lojas usam esse identificador como ID único do app e ele não pode ser trocado depois.",
               "Use algo como com.seuestudio.seujogo."),
    },
    "no_credits": {
        "en": ("No credits or license file at the root",
               "Godot's MIT license requires including the engine's copyright notice in the game (credits screen or a "
               "file). The same goes for third-party fonts, plugins and music.",
               "Create a CREDITS.md and a credits screen with Godot's notice and one for each third-party asset."),
        "es": ("No hay archivo de créditos ni de licencias en la raíz",
               "La licencia MIT de Godot exige incluir el aviso de copyright del motor en el juego (pantalla de "
               "créditos o archivo). Lo mismo vale para fuentes, plugins y música de terceros.",
               "Crea un CREDITS.md y una pantalla de créditos con el aviso de Godot y el de cada asset de terceros."),
        "pt": ("Nenhum arquivo de créditos ou licenças na raiz",
               "A licença MIT do Godot exige incluir o aviso de copyright do motor no jogo (tela de créditos ou "
               "arquivo). O mesmo vale para fontes, plugins e músicas de terceiros.",
               "Crie um CREDITS.md e uma tela de créditos com o aviso do Godot e de cada asset de terceiros."),
    },
    "fonts_nolicense": {
        "en": ("Fonts without a license file next to them",
               "Many free fonts (e.g. OFL-licensed ones) require shipping the license alongside them. Commercial fonts "
               "may not even allow use in games.",
               "Put each font's license file in the same folder and mention it in the credits."),
        "es": ("Fuentes sin archivo de licencia al lado",
               "Muchas fuentes gratuitas (p. ej., con licencia OFL) exigen distribuir la licencia junto con ellas. Las "
               "fuentes comerciales pueden incluso no permitir su uso en juegos.",
               "Pon el archivo de licencia de cada fuente en la misma carpeta y cítala en los créditos."),
        "pt": ("Fontes sem arquivo de licença ao lado",
               "Muitas fontes gratuitas (ex.: licença OFL) exigem distribuir a licença junto. Fontes comerciais podem "
               "nem permitir uso em jogo.",
               "Coloque o arquivo de licença de cada fonte na mesma pasta e cite nos créditos."),
    },
    "addons_nolicense": {
        "en": ("Plugins without an identified license",
               "No license was found inside these plugins. Without one, you can't tell whether you may ship the plugin "
               "in a commercial game.",
               "Check the license in each plugin's original repository and keep a copy in its folder."),
        "es": ("Plugins sin licencia identificada",
               "No se encontró licencia dentro de estos plugins. Sin licencia, no sabes si puedes distribuir el plugin "
               "en un juego comercial.",
               "Consulta la licencia en el repositorio original de cada plugin y guarda una copia en su carpeta."),
        "pt": ("Plugins sem licença identificada",
               "Não foi encontrada licença dentro destes plugins. Sem licença, você não sabe se pode distribuir o "
               "plugin dentro de um jogo comercial.",
               "Confira a licença no repositório original de cada plugin e guarde uma cópia na pasta dele."),
    },
    "ai_ok": {
        "en": ("AI usage record found", "Keep it up to date: the store declaration needs to match what's in the game.", ""),
        "es": ("Registro de uso de IA encontrado", "Mantenlo al día: la declaración de la tienda tiene que coincidir con lo que hay en el juego.", ""),
        "pt": ("Registro de uso de IA encontrado", "Mantenha atualizado: a declaração da loja precisa bater com o que está no jogo.", ""),
    },
    "ai_missing": {
        "en": ("No record of AI usage in the project",
               "Steam asks you to disclose AI-generated content when registering the game. Keeping a record in the "
               "project (what was generated, with which tool, what was edited by hand) makes the disclosure easier and "
               "documents it if anyone asks.",
               "Create an AI_DISCLOSURE.md at the project root, even if it's just to say you didn't use AI."),
        "es": ("Sin registro del uso de IA en el proyecto",
               "Steam pide declarar el contenido generado por IA al registrar el juego. Tener un registro en el "
               "proyecto (qué se generó, con qué herramienta, qué se editó a mano) facilita la declaración y sirve de "
               "documentación si alguien pregunta.",
               "Crea un AI_DISCLOSURE.md en la raíz del proyecto, aunque sea para decir que no usaste IA."),
        "pt": ("Sem registro do uso de IA no projeto",
               "A Steam pede que você declare conteúdo gerado por IA no cadastro do jogo. Ter um registro no projeto "
               "(o que foi gerado, com qual ferramenta, o que foi editado a mão) facilita a declaração e serve de "
               "documentação se alguém questionar.",
               "Crie um AI_DISCLOSURE.md na raiz do projeto, mesmo que seja para dizer que não usou IA."),
    },
}


# Any folder (no engine recognized)
_NO_CREDITS_ANY = {
    "en": ("No credits or license file at the root",
           "Third-party fonts, plugins, music and code usually require credit or a copy of their license in the game.",
           "Create a CREDITS.md and a credits screen listing each third-party asset and its license."),
    "es": ("No hay archivo de créditos ni de licencias en la raíz",
           "Las fuentes, plugins, música y código de terceros suelen exigir crédito o una copia de su licencia en el juego.",
           "Crea un CREDITS.md y una pantalla de créditos con cada asset de terceros y su licencia."),
    "pt": ("Nenhum arquivo de créditos ou licenças na raiz",
           "Fontes, plugins, músicas e código de terceiros costumam exigir crédito ou uma cópia da licença no jogo.",
           "Crie um CREDITS.md e uma tela de créditos com cada asset de terceiros e a licença dele."),
}

ENGINE_MESSAGES = {
    "engine_unknown": {
        "en": ("Engine not recognized: general checks only",
               "OwlCheck didn't find a Unity, Godot or GameMaker project here, so it ran only the checks that work for "
               "any game: keys and passwords, credential files, licenses and AI usage record.",
               "If the game uses one of those engines, choose the project root: the folder with ProjectSettings/ "
               "(Unity), project.godot (Godot) or the .yyp file (GameMaker)."),
        "es": ("Motor no reconocido: solo comprobaciones generales",
               "OwlCheck no encontró aquí un proyecto de Unity, Godot o GameMaker, así que solo hizo las comprobaciones "
               "que valen para cualquier juego: claves y contraseñas, archivos de credenciales, licencias y registro "
               "de uso de IA.",
               "Si el juego usa uno de esos motores, elige la raíz del proyecto: la carpeta con ProjectSettings/ "
               "(Unity), project.godot (Godot) o el archivo .yyp (GameMaker)."),
        "pt": ("Engine não reconhecida: só checagens gerais",
               "O OwlCheck não encontrou aqui um projeto Unity, Godot ou GameMaker, então rodou só as checagens que "
               "valem para qualquer jogo: chaves e senhas, arquivos de credencial, licenças e registro de uso de IA.",
               "Se o jogo usa uma dessas engines, escolha a raiz do projeto: a pasta com ProjectSettings/ (Unity), "
               "project.godot (Godot) ou o arquivo .yyp (GameMaker)."),
    },
    "too_many_files": {
        "en": ("Folder too large: only the first {n} files were read",
               "This doesn't look like a single game project. The result covers only part of it.",
               "Choose the game's project folder instead."),
        "es": ("Carpeta demasiado grande: solo se leyeron los primeros {n} archivos",
               "No parece ser un único proyecto de juego. El resultado cubre solo una parte.",
               "Elige la carpeta del proyecto del juego."),
        "pt": ("Pasta grande demais: só os primeiros {n} arquivos foram lidos",
               "Não parece ser um único projeto de jogo. O resultado cobre só uma parte.",
               "Escolha a pasta do projeto do jogo."),
    },
    "secrets_generic": {
        "en": ("Possible keys or passwords in the project",
               "OwlCheck can't tell which files go into the build for this engine. If any of these ship with the game, "
               "anyone can read the values.",
               "Take the keys out of the project and put your own server between the game and the service. Rotate "
               "(revoke) any key that already shipped."),
        "es": ("Posibles claves o contraseñas en el proyecto",
               "OwlCheck no puede saber qué archivos van a la build con este motor. Si alguno va con el juego, "
               "cualquiera puede leer los valores.",
               "Saca las claves del proyecto y pon un servidor propio entre el juego y el servicio. Cambia (revoca) "
               "cualquier clave que ya haya salido."),
        "pt": ("Possíveis chaves ou senhas no projeto",
               "O OwlCheck não consegue saber quais arquivos vão para a build nesta engine. Se algum deles for junto "
               "com o jogo, qualquer pessoa lê os valores.",
               "Tire as chaves do projeto e coloque um servidor seu entre o jogo e o serviço. Troque (revogue) "
               "qualquer chave que já tenha saído."),
    },
    "no_credits@generic": _NO_CREDITS_ANY,

    # Unity
    "no_credits@unity": _NO_CREDITS_ANY,
    "unity_mono": {
        "en": ("Scripts compiled with Mono ({platform})",
               "Your C# ships as ordinary .NET DLLs (Assembly-CSharp.dll). Free decompilers such as ILSpy rebuild it "
               "almost exactly as you wrote it, minus the comments.",
               "Switch Player Settings > Other Settings > Scripting Backend to IL2CPP (it needs the IL2CPP module "
               "installed). Class names and strings still end up in global-metadata.dat, so treat it as a barrier, "
               "not a vault."),
        "es": ("Scripts compilados con Mono ({platform})",
               "Tu C# va en DLLs .NET comunes (Assembly-CSharp.dll). Descompiladores gratuitos como ILSpy lo "
               "reconstruyen casi igual a como lo escribiste, salvo los comentarios.",
               "Cambia Player Settings > Other Settings > Scripting Backend a IL2CPP (necesita el módulo IL2CPP "
               "instalado). Los nombres de clases y los textos siguen en global-metadata.dat, así que tómalo como una "
               "barrera, no como una caja fuerte."),
        "pt": ("Scripts compilados com Mono ({platform})",
               "Seu C# vai em DLLs .NET comuns (Assembly-CSharp.dll). Decompiladores gratuitos como o ILSpy "
               "reconstroem o código quase igual ao que você escreveu, tirando os comentários.",
               "Mude Player Settings > Other Settings > Scripting Backend para IL2CPP (precisa do módulo IL2CPP "
               "instalado). Nomes de classes e textos continuam no global-metadata.dat, então trate como barreira, "
               "não cofre."),
    },
    "unity_il2cpp": {
        "en": ("Scripts compiled with IL2CPP ({platform})",
               "Much harder to read than Mono. Class names and strings still sit in global-metadata.dat, so keep "
               "secrets out of the code.", ""),
        "es": ("Scripts compilados con IL2CPP ({platform})",
               "Mucho más difícil de leer que con Mono. Los nombres de clases y los textos siguen en "
               "global-metadata.dat, así que no pongas secretos en el código.", ""),
        "pt": ("Scripts compilados com IL2CPP ({platform})",
               "Bem mais difícil de ler do que com Mono. Nomes de classes e textos continuam no global-metadata.dat, "
               "então não deixe segredos no código.", ""),
    },
    "unity_test_scenes": {
        "en": ("Test scenes in the build list",
               "Every scene ticked in Build Settings goes into the game, test ones included, and can be opened by "
               "anyone who digs into the files.",
               "Untick them in File > Build Settings (Build Profiles in Unity 6)."),
        "es": ("Escenas de prueba en la lista de la build",
               "Toda escena marcada en Build Settings va al juego, también las de prueba, y cualquiera que revise "
               "los archivos puede abrirlas.",
               "Desmárcalas en File > Build Settings (Build Profiles en Unity 6)."),
        "pt": ("Cenas de teste na lista da build",
               "Toda cena marcada em Build Settings vai para o jogo, inclusive as de teste, e quem fuçar nos arquivos "
               "consegue abrir.",
               "Desmarque em File > Build Settings (Build Profiles no Unity 6)."),
    },
    "unity_no_scenes": {
        "en": ("No scenes in the build list",
               "With an empty list, Unity builds only the scene that happens to be open in the editor.",
               "Add the game's scenes in File > Build Settings (Build Profiles in Unity 6)."),
        "es": ("No hay escenas en la lista de la build",
               "Con la lista vacía, Unity genera la build solo con la escena que esté abierta en el editor.",
               "Añade las escenas del juego en File > Build Settings (Build Profiles en Unity 6)."),
        "pt": ("Nenhuma cena na lista da build",
               "Com a lista vazia, o Unity gera a build só com a cena que estiver aberta no editor.",
               "Adicione as cenas do jogo em File > Build Settings (Build Profiles no Unity 6)."),
    },
    "unity_demo": {
        "en": ("Demo: check what goes into the build",
               "The project shows signs of a demo ({hint}). Unity ships every scene ticked in Build Settings "
               "({scenes}) and everything inside Resources folders ({resources} files), used or not. Locking levels "
               "in code doesn't remove them: anyone can pull them out of the demo files.",
               "Give the demo its own scene list (a separate Build Profile in Unity 6) with only its scenes, and keep "
               "full-game content out of Resources."),
        "es": ("Demo: revisa lo que entra en la build",
               "El proyecto tiene señales de demo ({hint}). Unity incluye toda escena marcada en Build Settings "
               "({scenes}) y todo lo que hay en carpetas Resources ({resources} archivos), se use o no. Bloquear "
               "niveles por código no los quita: cualquiera puede sacarlos de los archivos de la demo.",
               "Dale a la demo su propia lista de escenas (un Build Profile aparte en Unity 6) solo con sus escenas, y "
               "deja el contenido del juego completo fuera de Resources."),
        "pt": ("Demo: confira o que vai para a build",
               "O projeto tem sinais de demo ({hint}). O Unity inclui toda cena marcada em Build Settings ({scenes}) "
               "e tudo que está em pastas Resources ({resources} arquivos), usado ou não. Bloquear fases pelo código "
               "não tira esse conteúdo: qualquer pessoa extrai dos arquivos da demo.",
               "Dê à demo uma lista de cenas própria (um Build Profile separado no Unity 6) só com as cenas dela, e "
               "deixe o conteúdo do jogo completo fora de Resources."),
    },
    "no_demo@unity": {
        "en": ("No demo build detected",
               "If you're shipping a demo, give it its own scene list and a DEMO scripting define.", ""),
        "es": ("No se detectó build de demo",
               "Si vas a lanzar una demo, dale su propia lista de escenas y un scripting define DEMO.", ""),
        "pt": ("Nenhuma build de demo detectada",
               "Se for lançar uma demo, dê a ela uma lista de cenas própria e um scripting define DEMO.", ""),
    },
    "unity_resources": {
        "en": ("Resources folders go into every build ({n} files)",
               "Everything inside a folder named Resources ships with the game, even if nothing uses it.",
               "Keep there only what you load with Resources.Load, and move the rest out (or use Addressables)."),
        "es": ("Las carpetas Resources van en toda build ({n} archivos)",
               "Todo lo que está en una carpeta llamada Resources va con el juego, aunque nada lo use.",
               "Deja ahí solo lo que cargas con Resources.Load y saca el resto (o usa Addressables)."),
        "pt": ("Pastas Resources vão em toda build ({n} arquivos)",
               "Tudo que está numa pasta chamada Resources vai junto com o jogo, mesmo que nada use.",
               "Deixe lá só o que você carrega com Resources.Load e tire o resto (ou use Addressables)."),
    },
    "unity_streaming": {
        "en": ("StreamingAssets ships as plain files ({n})",
               "Files in StreamingAssets are copied into the build exactly as they are. Anyone can open them.",
               "Don't keep anything private there. Encrypt or move data players shouldn't read."),
        "es": ("StreamingAssets va como archivos sueltos ({n})",
               "Los archivos de StreamingAssets se copian a la build tal cual. Cualquiera puede abrirlos.",
               "No guardes nada privado ahí. Cifra o mueve los datos que los jugadores no deberían leer."),
        "pt": ("StreamingAssets vai como arquivos soltos ({n})",
               "Os arquivos de StreamingAssets são copiados para a build exatamente como estão. Qualquer pessoa abre.",
               "Não guarde nada privado ali. Criptografe ou tire os dados que o jogador não deveria ler."),
    },
    "cred_build@unity": {
        "en": ("Credential files going into the build",
               ".env files, keys or keystores sit in Resources or StreamingAssets, which ship with the game.",
               "Move them out of the project folder. Rotate any key that already shipped."),
        "es": ("Archivos de credenciales entrando en la build",
               "Hay archivos .env, claves o keystores en Resources o StreamingAssets, que van con el juego.",
               "Sácalos de la carpeta del proyecto. Cambia cualquier clave que ya haya salido."),
        "pt": ("Arquivos de credencial entrando na build",
               "Há arquivos .env, chaves ou keystores em Resources ou StreamingAssets, que vão junto com o jogo.",
               "Tire esses arquivos da pasta do projeto. Troque qualquer chave que já tenha saído."),
    },
    "dev_files@unity": {
        "en": ("Work files in Resources or StreamingAssets",
               "Documents, drafts or art source files sit in folders that always ship. A leaked GDD or note gives away "
               "plans and upcoming content.",
               "Move them out of Resources and StreamingAssets."),
        "es": ("Archivos de trabajo en Resources o StreamingAssets",
               "Hay documentos, borradores o archivos fuente de arte en carpetas que siempre van en la build. Un GDD o "
               "una nota filtrada revela planes y contenido futuro.",
               "Sácalos de Resources y StreamingAssets."),
        "pt": ("Arquivos de trabalho em Resources ou StreamingAssets",
               "Há documentos, rascunhos ou arquivos-fonte de arte em pastas que sempre vão para a build. Um GDD ou "
               "anotação vazado entrega planos e conteúdo futuro.",
               "Tire esses arquivos de Resources e StreamingAssets."),
    },
    "cheats@unity": {
        "en": ("Possible cheats or developer menus",
               "Terms typical of test tools show up in code that goes into the build. Players tend to find and "
               "trigger these shortcuts.",
               "Wrap them in #if UNITY_EDITOR || DEVELOPMENT_BUILD, or at least check Debug.isDebugBuild."),
        "es": ("Posibles trucos o menús de desarrollador",
               "Aparecen términos típicos de herramientas de prueba en código que va a la build. Los jugadores suelen "
               "encontrar y activar estos atajos.",
               "Envuélvelos en #if UNITY_EDITOR || DEVELOPMENT_BUILD o, como mínimo, comprueba Debug.isDebugBuild."),
        "pt": ("Possíveis cheats ou menus de desenvolvedor",
               "Termos típicos de ferramentas de teste aparecem em código que vai para a build. Jogadores costumam "
               "achar e ativar esses atalhos.",
               "Envolva com #if UNITY_EDITOR || DEVELOPMENT_BUILD ou, no mínimo, cheque Debug.isDebugBuild."),
    },
    "cmdline_unguarded@unity": {
        "en": ("Unguarded command-line hooks",
               "The game reads command-line arguments (Environment.GetCommandLineArgs) with no debug check around "
               "them. Any player can pass the argument and trigger the test mode.",
               "Wrap them in #if DEVELOPMENT_BUILD or check Debug.isDebugBuild first."),
        "es": ("Ganchos de línea de comandos sin protección",
               "El juego lee argumentos de línea de comandos (Environment.GetCommandLineArgs) sin ninguna comprobación "
               "de depuración alrededor. Cualquier jugador puede pasar el argumento y activar el modo de prueba.",
               "Envuélvelos en #if DEVELOPMENT_BUILD o comprueba antes Debug.isDebugBuild."),
        "pt": ("Ganchos de linha de comando sem proteção",
               "O jogo lê argumentos de linha de comando (Environment.GetCommandLineArgs) sem nenhuma checagem de "
               "debug em volta. Qualquer jogador pode passar o argumento e acionar o modo de teste.",
               "Envolva com #if DEVELOPMENT_BUILD ou cheque Debug.isDebugBuild antes."),
    },
    "cmdline_guarded@unity": {
        "en": ("Command-line hooks appear guarded",
               "The hooks that read arguments sit inside a DEVELOPMENT_BUILD/UNITY_EDITOR block or a "
               "Debug.isDebugBuild check. Double-check it's the right one.", ""),
        "es": ("Ganchos de línea de comandos con protección aparente",
               "Los ganchos que leen argumentos están dentro de un bloque DEVELOPMENT_BUILD/UNITY_EDITOR o de una "
               "comprobación de Debug.isDebugBuild. Verifica que sea la correcta.", ""),
        "pt": ("Ganchos de linha de comando com proteção aparente",
               "Os ganchos que leem argumentos estão dentro de um bloco DEVELOPMENT_BUILD/UNITY_EDITOR ou de uma "
               "checagem de Debug.isDebugBuild. Confira se é a checagem certa.", ""),
    },
    "prints@unity": {
        "en": ("Debug.Log calls in the game code ({n})",
               "Unity keeps Debug.Log in release builds: it writes to the player's log file and costs performance. "
               "Messages can reveal internal structure or hint at ways to cheat.",
               "Remove the debugging ones, or route them through a method marked "
               "[Conditional(\"DEVELOPMENT_BUILD\")]."),
        "es": ("Llamadas a Debug.Log en el código del juego ({n})",
               "Unity mantiene Debug.Log en las builds finales: escribe en el log del jugador y cuesta rendimiento. "
               "Los mensajes pueden revelar la estructura interna o dar pistas para hacer trampa.",
               "Quita los de depuración o pásalos por un método marcado con [Conditional(\"DEVELOPMENT_BUILD\")]."),
        "pt": ("Chamadas de Debug.Log no código do jogo ({n})",
               "O Unity mantém o Debug.Log nas builds finais: ele escreve no log do jogador e custa desempenho. As "
               "mensagens podem revelar estrutura interna ou dar pistas para trapaça.",
               "Remova os de depuração ou passe por um método marcado com [Conditional(\"DEVELOPMENT_BUILD\")]."),
    },
    "breakpoints@unity": {
        "en": ("Leftover Debug.Break calls",
               "Debug.Break pauses the editor and points to test code left behind.", "Remove them before shipping."),
        "es": ("Llamadas a Debug.Break olvidadas",
               "Debug.Break pausa el editor e indica código de prueba que se quedó atrás.", "Quítalas antes de lanzar."),
        "pt": ("Chamadas de Debug.Break esquecidas",
               "Debug.Break pausa o editor e indica código de teste que ficou para trás.", "Remova antes de lançar."),
    },
    "unity_company": {
        "en": ("Company name is still '{value}'",
               "It shows up in the folder where the game saves data (AppData/LocalLow/Company/Game) and in crash "
               "reports. Changing it after launch moves players' save files.",
               "Set it in Edit > Project Settings > Player > Company Name before the first public build."),
        "es": ("El nombre de la empresa sigue siendo '{value}'",
               "Aparece en la carpeta donde el juego guarda datos (AppData/LocalLow/Empresa/Juego) y en los reportes "
               "de errores. Cambiarlo después del lanzamiento mueve las partidas guardadas de los jugadores.",
               "Defínelo en Edit > Project Settings > Player > Company Name antes de la primera build pública."),
        "pt": ("Nome da empresa ainda é '{value}'",
               "Aparece na pasta onde o jogo salva os dados (AppData/LocalLow/Empresa/Jogo) e nos relatórios de "
               "erro. Trocar depois do lançamento muda o lugar dos saves dos jogadores.",
               "Defina em Edit > Project Settings > Player > Company Name antes da primeira build pública."),
    },
    "no_name@unity": {
        "en": ("Product name is empty", "The name shows up in the game window and in several places in the system.",
               "Set it in Edit > Project Settings > Player > Product Name."),
        "es": ("Nombre del producto vacío", "El nombre aparece en la ventana del juego y en varios lugares del sistema.",
               "Defínelo en Edit > Project Settings > Player > Product Name."),
        "pt": ("Nome do produto em branco", "O nome aparece na janela do jogo e em vários lugares do sistema.",
               "Defina em Edit > Project Settings > Player > Product Name."),
    },
    "no_version@unity": {
        "en": ("Project has no version number", "A version helps players report bugs and helps you track builds.",
               "Set it in Edit > Project Settings > Player > Version (e.g. 0.1.0-demo)."),
        "es": ("Proyecto sin número de versión", "La versión ayuda a los jugadores a reportar errores y a ti a seguir las builds.",
               "Defínela en Edit > Project Settings > Player > Version (p. ej., 0.1.0-demo)."),
        "pt": ("Projeto sem número de versão", "Versão ajuda o jogador a reportar bugs e você a rastrear builds.",
               "Defina em Edit > Project Settings > Player > Version (ex.: 0.1.0-demo)."),
    },
    "no_icon@unity": {
        "en": ("Project has no icon", "Without an icon, the game uses Unity's default.",
               "Set it in Edit > Project Settings > Player > Default Icon."),
        "es": ("Proyecto sin icono", "Sin icono, el juego usa el de Unity por defecto.",
               "Defínelo en Edit > Project Settings > Player > Default Icon."),
        "pt": ("Projeto sem ícone definido", "Sem ícone, o jogo usa o padrão do Unity.",
               "Defina em Edit > Project Settings > Player > Default Icon."),
    },
    "default_id@unity": {
        "en": ("{name}: default identifier ({value})",
               "Stores use this identifier as the app's unique ID, and it can't be changed later.",
               "Set it in Player Settings > Other Settings > Identification, e.g. com.yourstudio.yourgame."),
        "es": ("{name}: identificador por defecto ({value})",
               "Las tiendas usan este identificador como ID único de la app y no se puede cambiar después.",
               "Defínelo en Player Settings > Other Settings > Identification, p. ej., com.tuestudio.tujuego."),
        "pt": ("{name}: identificador padrão ({value})",
               "Lojas usam esse identificador como ID único do app e ele não pode ser trocado depois.",
               "Defina em Player Settings > Other Settings > Identification, ex.: com.seuestudio.seujogo."),
    },
    "addons_nolicense@unity": {
        "en": ("Plugins without an identified license",
               "No license file was found in these plugin folders. Asset Store packages are covered by the Asset "
               "Store license; anything that came from elsewhere needs its own.",
               "For each plugin that didn't come from the Asset Store, check the license at the source and keep a "
               "copy in its folder."),
        "es": ("Plugins sin licencia identificada",
               "No se encontró archivo de licencia en estas carpetas de plugins. Los paquetes de la Asset Store están "
               "cubiertos por su licencia; lo que vino de otro lugar necesita la suya.",
               "Para cada plugin que no vino de la Asset Store, revisa la licencia en el origen y guarda una copia en "
               "su carpeta."),
        "pt": ("Plugins sem licença identificada",
               "Não foi encontrado arquivo de licença nestas pastas de plugins. Pacotes da Asset Store são cobertos "
               "pela licença da loja; o que veio de outro lugar precisa da sua.",
               "Para cada plugin que não veio da Asset Store, confira a licença na origem e guarde uma cópia na "
               "pasta dele."),
    },

    # GameMaker
    "no_credits@gamemaker": _NO_CREDITS_ANY,
    "gm_yyc": {
        "en": ("Build with YYC, not VM",
               "The compiler is picked in the build target, not saved in the project, so OwlCheck can't see which one "
               "you use. VM builds keep your GML as bytecode in data.win, which public tools decompile back into "
               "readable code; YYC compiles it to native code.",
               "In the target selector, choose YYC before Create Executable (on Windows it needs Visual Studio)."),
        "es": ("Genera la build con YYC, no con VM",
               "El compilador se elige en el destino de la build, no se guarda en el proyecto, así que OwlCheck no "
               "puede ver cuál usas. Las builds VM guardan tu GML como bytecode en data.win, que herramientas públicas "
               "descompilan a código legible; YYC lo compila a código nativo.",
               "En el selector de destino, elige YYC antes de Create Executable (en Windows necesita Visual Studio)."),
        "pt": ("Gere a build com YYC, não VM",
               "O compilador é escolhido no destino da build, não fica salvo no projeto, então o OwlCheck não consegue "
               "ver qual você usa. Builds VM guardam seu GML como bytecode no data.win, que ferramentas públicas "
               "decompilam de volta em código legível; o YYC compila para código nativo.",
               "No seletor de destino, escolha YYC antes de Create Executable (no Windows precisa do Visual Studio)."),
    },
    "gm_remove_unused": {
        "en": ("'Remove unused assets' is off",
               "Sprites, sounds and other assets that nothing references still go into the build.",
               "Turn it on in Game Options > Main."),
        "es": ("'Remove unused assets' está desactivado",
               "Sprites, sonidos y otros assets que nada usa siguen entrando en la build.",
               "Actívalo en Game Options > Main."),
        "pt": ("'Remove unused assets' está desligado",
               "Sprites, sons e outros assets que nada usa continuam indo para a build.",
               "Ligue em Game Options > Main."),
    },
    "gm_demo": {
        "en": ("Demo: the whole game goes into the build",
               "The project shows signs of a demo ({hint}). GameMaker packs every room in the project ({rooms}) into "
               "every build, whatever the configuration. Locking levels in code doesn't remove them: anyone can pull "
               "them out of the demo's data file.",
               "Build the demo from a copy of the project that only has the demo's content. It's the only way to be "
               "sure the rest of the game stays out."),
        "es": ("Demo: el juego entero entra en la build",
               "El proyecto tiene señales de demo ({hint}). GameMaker mete todas las rooms del proyecto ({rooms}) en "
               "toda build, sea cual sea la configuración. Bloquear niveles por código no las quita: cualquiera puede "
               "sacarlas del archivo de datos de la demo.",
               "Genera la demo desde una copia del proyecto que tenga solo el contenido de la demo. Es la única forma "
               "de asegurar que el resto del juego quede fuera."),
        "pt": ("Demo: o jogo inteiro vai para a build",
               "O projeto tem sinais de demo ({hint}). O GameMaker coloca todas as rooms do projeto ({rooms}) em toda "
               "build, seja qual for a configuração. Bloquear fases pelo código não tira esse conteúdo: qualquer "
               "pessoa extrai do arquivo de dados da demo.",
               "Gere a demo a partir de uma cópia do projeto só com o conteúdo dela. É o único jeito de garantir que "
               "o resto do jogo fica de fora."),
    },
    "no_demo@gamemaker": {
        "en": ("No demo configuration detected",
               "If you're shipping a demo, remember GameMaker packs every room into every build: build it from a copy "
               "of the project with only the demo's content.", ""),
        "es": ("No se detectó configuración de demo",
               "Si vas a lanzar una demo, recuerda que GameMaker mete todas las rooms en toda build: genérala desde una "
               "copia del proyecto solo con el contenido de la demo.", ""),
        "pt": ("Nenhuma configuração de demo detectada",
               "Se for lançar uma demo, lembre que o GameMaker coloca todas as rooms em toda build: gere a demo a "
               "partir de uma cópia do projeto só com o conteúdo dela.", ""),
    },
    "gm_test_rooms": {
        "en": ("Test rooms go into the build",
               "Every room in the project ships with the game, test ones included, and can be reached by anyone who "
               "digs into the data file.",
               "Delete test rooms before the release build, or keep them in a separate project."),
        "es": ("Las rooms de prueba entran en la build",
               "Todas las rooms del proyecto van con el juego, también las de prueba, y cualquiera que revise el "
               "archivo de datos puede llegar a ellas.",
               "Borra las rooms de prueba antes de la build final o guárdalas en un proyecto aparte."),
        "pt": ("Rooms de teste vão para a build",
               "Todas as rooms do projeto vão junto com o jogo, inclusive as de teste, e quem fuçar no arquivo de "
               "dados chega nelas.",
               "Apague as rooms de teste antes da build final ou guarde num projeto separado."),
    },
    "gm_datafiles": {
        "en": ("Included Files ship as plain files ({n})",
               "Everything in Included Files (the datafiles folder) is copied next to the game exactly as it is. "
               "Anyone can open it.",
               "Don't keep anything private there. Encrypt or move data players shouldn't read."),
        "es": ("Included Files va como archivos sueltos ({n})",
               "Todo lo que está en Included Files (la carpeta datafiles) se copia junto al juego tal cual. Cualquiera "
               "puede abrirlo.",
               "No guardes nada privado ahí. Cifra o mueve los datos que los jugadores no deberían leer."),
        "pt": ("Included Files vai como arquivos soltos ({n})",
               "Tudo que está em Included Files (a pasta datafiles) é copiado ao lado do jogo exatamente como está. "
               "Qualquer pessoa abre.",
               "Não guarde nada privado ali. Criptografe ou tire os dados que o jogador não deveria ler."),
    },
    "cred_build@gamemaker": {
        "en": ("Credential files going into the build",
               ".env files, keys or keystores are in Included Files (datafiles), which ship with the game.",
               "Remove them from Included Files and move them out of the project folder. Rotate any key that already "
               "shipped."),
        "es": ("Archivos de credenciales entrando en la build",
               "Hay archivos .env, claves o keystores en Included Files (datafiles), que van con el juego.",
               "Quítalos de Included Files y sácalos de la carpeta del proyecto. Cambia cualquier clave que ya haya "
               "salido."),
        "pt": ("Arquivos de credencial entrando na build",
               "Há arquivos .env, chaves ou keystores em Included Files (datafiles), que vão junto com o jogo.",
               "Tire de Included Files e da pasta do projeto. Troque qualquer chave que já tenha saído."),
    },
    "dev_files@gamemaker": {
        "en": ("Work files in Included Files",
               "Documents, drafts or art source files are in datafiles, which always ships. A leaked GDD or note gives "
               "away plans and upcoming content.",
               "Remove them from Included Files."),
        "es": ("Archivos de trabajo en Included Files",
               "Hay documentos, borradores o archivos fuente de arte en datafiles, que siempre va en la build. Un GDD "
               "o una nota filtrada revela planes y contenido futuro.",
               "Quítalos de Included Files."),
        "pt": ("Arquivos de trabalho em Included Files",
               "Há documentos, rascunhos ou arquivos-fonte de arte em datafiles, que sempre vai para a build. Um GDD "
               "ou anotação vazado entrega planos e conteúdo futuro.",
               "Tire esses arquivos de Included Files."),
    },
    "cheats@gamemaker": {
        "en": ("Possible cheats or developer menus",
               "Terms typical of test tools show up in the game's GML. Players tend to find and trigger these "
               "shortcuts.",
               "Guard them with if (debug_mode) or if (GM_build_type == \"run\"), which are only true when running "
               "from the IDE."),
        "es": ("Posibles trucos o menús de desarrollador",
               "Aparecen términos típicos de herramientas de prueba en el GML del juego. Los jugadores suelen "
               "encontrar y activar estos atajos.",
               "Protégelos con if (debug_mode) o if (GM_build_type == \"run\"), que solo son verdaderos al ejecutar "
               "desde el IDE."),
        "pt": ("Possíveis cheats ou menus de desenvolvedor",
               "Termos típicos de ferramentas de teste aparecem no GML do jogo. Jogadores costumam achar e ativar "
               "esses atalhos.",
               "Proteja com if (debug_mode) ou if (GM_build_type == \"run\"), que só valem quando o jogo roda pela "
               "IDE."),
    },
    "cmdline_unguarded@gamemaker": {
        "en": ("Unguarded command-line hooks",
               "The game reads command-line arguments (parameter_string) with no debug check around them. Any player "
               "can pass the argument and trigger the test mode.",
               "Wrap them in if (debug_mode) or if (GM_build_type == \"run\")."),
        "es": ("Ganchos de línea de comandos sin protección",
               "El juego lee argumentos de línea de comandos (parameter_string) sin ninguna comprobación de depuración "
               "alrededor. Cualquier jugador puede pasar el argumento y activar el modo de prueba.",
               "Envuélvelos en if (debug_mode) o if (GM_build_type == \"run\")."),
        "pt": ("Ganchos de linha de comando sem proteção",
               "O jogo lê argumentos de linha de comando (parameter_string) sem nenhuma checagem de debug em volta. "
               "Qualquer jogador pode passar o argumento e acionar o modo de teste.",
               "Envolva com if (debug_mode) ou if (GM_build_type == \"run\")."),
    },
    "cmdline_guarded@gamemaker": {
        "en": ("Command-line hooks appear guarded",
               "The hooks that read arguments sit inside a debug_mode/GM_build_type check. Double-check it's the right "
               "one.", ""),
        "es": ("Ganchos de línea de comandos con protección aparente",
               "Los ganchos que leen argumentos están dentro de una comprobación de debug_mode/GM_build_type. Verifica "
               "que sea la correcta.", ""),
        "pt": ("Ganchos de linha de comando com proteção aparente",
               "Os ganchos que leem argumentos estão dentro de uma checagem de debug_mode/GM_build_type. Confira se é "
               "a checagem certa.", ""),
    },
    "prints@gamemaker": {
        "en": ("show_debug_message calls ({n})",
               "Messages left in the code can reveal internal structure or hint at ways to cheat.",
               "Remove the debugging ones or guard them with if (debug_mode)."),
        "es": ("Llamadas a show_debug_message ({n})",
               "Los mensajes que quedan en el código pueden revelar la estructura interna o dar pistas para hacer "
               "trampa.",
               "Quita los de depuración o protégelos con if (debug_mode)."),
        "pt": ("Chamadas de show_debug_message ({n})",
               "Mensagens esquecidas no código podem revelar estrutura interna ou dar pistas para trapaça.",
               "Remova as de depuração ou proteja com if (debug_mode)."),
    },
    "gm_overlay": {
        "en": ("Debug overlay turned on in code",
               "show_debug_overlay(true) outside a debug check shows the debug panel to players.",
               "Guard it with if (debug_mode) or remove it."),
        "es": ("Overlay de depuración activado en el código",
               "show_debug_overlay(true) fuera de una comprobación de depuración muestra el panel de depuración a los "
               "jugadores.",
               "Protégelo con if (debug_mode) o quítalo."),
        "pt": ("Overlay de debug ligado no código",
               "show_debug_overlay(true) fora de uma checagem de debug mostra o painel de debug para os jogadores.",
               "Proteja com if (debug_mode) ou remova."),
    },
    "gm_display_name": {
        "en": ("{name}: display name is still '{value}'",
               "It's the window title and the name the system shows for the game.",
               "Change it in Game Options > {name} > General > Display Name."),
        "es": ("{name}: el nombre visible sigue siendo '{value}'",
               "Es el título de la ventana y el nombre que el sistema muestra para el juego.",
               "Cámbialo en Game Options > {name} > General > Display Name."),
        "pt": ("{name}: nome de exibição ainda é '{value}'",
               "É o título da janela e o nome que o sistema mostra para o jogo.",
               "Troque em Game Options > {name} > General > Display Name."),
    },
    "exe_meta@gamemaker": {
        "en": ("Windows: executable details left at GameMaker's defaults",
               "They show up under Properties > Details for the .exe. Leaving the defaults looks amateurish and can "
               "increase antivirus warnings.",
               "Fill them in at Game Options > Windows > General."),
        "es": ("Windows: datos del ejecutable con los valores por defecto de GameMaker",
               "Aparecen en Propiedades > Detalles del .exe. Con los valores por defecto se ve poco profesional y puede "
               "aumentar las alertas del antivirus.",
               "Complétalos en Game Options > Windows > General."),
        "pt": ("Windows: dados do executável com os padrões do GameMaker",
               "Aparecem em Propriedades > Detalhes do .exe. Com os valores padrão passa amadorismo e pode aumentar "
               "alertas de antivírus.",
               "Preencha em Game Options > Windows > General."),
    },
    "default_id@gamemaker": {
        "en": ("{name}: default identifier ({value})",
               "Stores use this identifier as the app's unique ID, and it can't be changed later.",
               "Change it in Game Options > {name}, e.g. com.yourstudio.yourgame."),
        "es": ("{name}: identificador por defecto ({value})",
               "Las tiendas usan este identificador como ID único de la app y no se puede cambiar después.",
               "Cámbialo en Game Options > {name}, p. ej., com.tuestudio.tujuego."),
        "pt": ("{name}: identificador padrão ({value})",
               "Lojas usam esse identificador como ID único do app e ele não pode ser trocado depois.",
               "Troque em Game Options > {name}, ex.: com.seuestudio.seujogo."),
    },
    "addons_nolicense@gamemaker": {
        "en": ("Extensions without an identified license",
               "No license file was found in these extension folders. Marketplace assets are covered by the "
               "Marketplace license; anything that came from elsewhere needs its own.",
               "For each extension that didn't come from the Marketplace, check the license at the source and keep "
               "a copy with the project."),
        "es": ("Extensiones sin licencia identificada",
               "No se encontró archivo de licencia en estas carpetas de extensiones. Los assets del Marketplace están "
               "cubiertos por su licencia; lo que vino de otro lugar necesita la suya.",
               "Para cada extensión que no vino del Marketplace, revisa la licencia en el origen y guarda una copia "
               "con el proyecto."),
        "pt": ("Extensões sem licença identificada",
               "Não foi encontrado arquivo de licença nestas pastas de extensões. Assets do Marketplace são cobertos "
               "pela licença da loja; o que veio de outro lugar precisa da sua.",
               "Para cada extensão que não veio do Marketplace, confira a licença na origem e guarde uma cópia junto "
               "do projeto."),
    },
}
MESSAGES.update(ENGINE_MESSAGES)


def tr(lang, key, **kw):
    """Falls back to English when a string is missing."""
    table = TEXT.get(lang, TEXT[DEFAULT_LANG])
    s = table.get(key, TEXT[DEFAULT_LANG].get(key, key))
    return s.format(**kw) if kw else s


@dataclass
class Finding:
    severity: str
    category: str
    title: str
    detail: str
    fix: str = ""
    items: list = field(default_factory=list)
    code: str = ""   # check id, the same in every language
    cat: str = ""
    uid: str = ""    # code + preset; the app keys ticked items on it


@dataclass
class ProjFile:
    rel: str           # posix-style, relative to the project root
    path: Path
    ext: str
    size: int
    ignored: bool      # under a folder with .gdignore


@dataclass
class Preset:
    index: str
    name: str
    platform: str
    export_filter: str
    include: list
    exclude: list
    export_files: set
    custom_features: str
    options: dict
    raw: dict
    virtual: bool = False

    @property
    def is_demo(self):
        blob = f"{self.name} {self.custom_features}".lower()
        return "demo" in blob


# Godot .cfg files

def _balanced(value):
    depth, in_quote, escape = 0, False, False
    for ch in value:
        if in_quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_quote = False
        else:
            if ch == '"':
                in_quote = True
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
    return not in_quote and depth <= 0


def _parse_value(value):
    v = value.strip()
    if v.startswith("PackedStringArray(") or v.startswith("Array["):
        return [m.replace('\\"', '"') for m in re.findall(r'"((?:[^"\\]|\\.)*)"', v)]
    if len(v) >= 2 and v.startswith('"') and v.endswith('"'):
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if v == "true":
        return True
    if v == "false":
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def parse_godot_cfg(text):
    """project.godot or export_presets.cfg as {section: {key: value}}."""
    data = {"": {}}
    section = ""
    pending_key, pending = None, []
    for raw in text.splitlines():
        if pending_key is not None:
            pending.append(raw)
            joined = "\n".join(pending)
            if _balanced(joined):
                data[section][pending_key] = _parse_value(joined)
                pending_key, pending = None, []
            continue
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]") and "=" not in line:
            section = line[1:-1].strip()
            data.setdefault(section, {})
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if _balanced(value):
                data[section][key] = _parse_value(value)
            else:
                pending_key, pending = key, [value]
    return data


def _split_filters(value):
    if not isinstance(value, str):
        return []
    return [f.strip() for f in value.split(",") if f.strip()]


def load_presets(root):
    cfg_path = root / "export_presets.cfg"
    if not cfg_path.is_file():
        return []
    data = parse_godot_cfg(cfg_path.read_text(encoding="utf-8", errors="replace"))
    presets = []
    for sec, values in data.items():
        m = re.fullmatch(r"preset\.(\d+)", sec)
        if not m:
            continue
        idx = m.group(1)
        files = values.get("export_files", [])
        presets.append(Preset(
            index=idx,
            name=str(values.get("name", f"preset {idx}")),
            platform=str(values.get("platform", "")),
            export_filter=str(values.get("export_filter", "all_resources")),
            include=_split_filters(values.get("include_filter", "")),
            exclude=_split_filters(values.get("exclude_filter", "")),
            export_files=set(files if isinstance(files, list) else []),
            custom_features=str(values.get("custom_features", "")),
            options=data.get(f"preset.{idx}.options", {}),
            raw=values,
        ))
    presets.sort(key=lambda p: int(p.index))
    return presets


# Engine detection

def detect_engine(root):
    """'godot', 'unity', 'gamemaker' or 'generic', from the files each engine keeps at the root."""
    root = Path(root)
    if (root / "project.godot").is_file():
        return "godot"
    if (root / "ProjectSettings").is_dir() and (
            (root / "Assets").is_dir() or (root / "ProjectSettings" / "ProjectVersion.txt").is_file()):
        return "unity"
    try:
        if any(p.suffix.lower() == ".yyp" and p.is_file() for p in root.iterdir()):
            return "gamemaker"
    except OSError:
        pass
    return "generic"


def find_projects(root, depth=2, limit=12):
    """Projects up to two levels inside a folder that isn't one itself."""
    found = []

    def walk(d, level):
        try:
            subs = sorted(p for p in d.iterdir()
                          if p.is_dir() and not p.name.startswith(".") and p.name not in SKIP_DIRS)
        except OSError:
            return
        for s in subs:
            if len(found) >= limit:
                return
            eng = detect_engine(s)
            if eng != "generic":
                found.append((s, eng))
            elif level < depth:
                walk(s, level + 1)

    walk(Path(root), 1)
    return found


def resolve_root(path):
    """Accepts the project folder or something inside it that points there: project.godot, a
    GameMaker .yyp, Unity's Assets or ProjectSettings folder, or a file in ProjectSettings."""
    if not path:
        return None
    p = Path(str(path)).expanduser()
    try:
        p = p.resolve()
    except OSError:
        return None
    if p.is_file():
        if p.name == "project.godot" or p.suffix.lower() == ".yyp":
            p = p.parent
        elif p.parent.name == "ProjectSettings":
            p = p.parent.parent
        else:
            return None
    if p.is_dir() and p.name in ("Assets", "ProjectSettings") and detect_engine(p.parent) == "unity":
        p = p.parent
    return p if p.is_dir() else None


# Unity settings (a small YAML subset)

def _unq(v):
    v = str(v).strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1]
    return v


def parse_unity_settings(text):
    """First object of a Unity .asset as {key: value | {subkey: value}}. Lists and deeper levels
    are skipped; the checks only need plain keys."""
    data, current, base = {}, None, None
    for raw in text.splitlines():
        if not raw.strip() or raw.startswith(("%", "---")):
            continue
        ind = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if ind == 0:
            if data:
                break  # next object
            continue
        if base is None:
            base = ind
        if ind == base:
            current = None
            if line.startswith("- ") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            v = v.strip()
            if v == "":
                data[k.strip()] = {}
                current = k.strip()
            else:
                data[k.strip()] = _unq(v)
        elif current is not None and ind == base + 2 and ":" in line and not line.startswith("- "):
            k, v = line.split(":", 1)
            if isinstance(data.get(current), dict):
                data[current][k.strip()] = _unq(v)
    # "key:" with nothing nested under it is an empty value, not a map
    return {k: ("" if v == {} else v) for k, v in data.items()}


def _unity_section(text, key):
    """Lines of a PlayerSettings key, up to the next key at the same level."""
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        if raw.strip().startswith(key + ":"):
            ind = len(raw) - len(raw.lstrip(" "))
            out = [raw]
            for nxt in lines[i + 1:]:
                if nxt.strip() and len(nxt) - len(nxt.lstrip(" ")) <= ind and not nxt.lstrip().startswith("- "):
                    break
                out.append(nxt)
            return "\n".join(out)
    return ""


def load_unity(root):
    ps = root / "ProjectSettings"

    def read(name):
        try:
            return (ps / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    player_text = read("ProjectSettings.asset")
    player = parse_unity_settings(player_text)
    icons = _unity_section(player_text, "m_BuildTargetIcons") + _unity_section(player_text, "m_BuildTargetPlatformIcons")
    scenes = [(m.group(2).strip(), m.group(1) == "1") for m in
              re.finditer(r"-\s*enabled:\s*(\d)\s*\n\s*path:\s*(.+)", read("EditorBuildSettings.asset"))]
    ver = re.search(r"m_EditorVersion:\s*(\S+)", read("ProjectVersion.txt"))
    return {"player": player, "scenes": scenes, "version": ver.group(1) if ver else "",
            "icon_set": bool(re.search(r"fileID:\s*[1-9]", icons)), "has_settings": bool(player_text)}


# GameMaker files

def parse_gm_json(text):
    """GameMaker .yy/.yyp files are JSON with trailing commas."""
    cleaned = re.sub(r'("(?:[^"\\]|\\.)*")|,(\s*[}\]])', lambda m: m.group(1) or m.group(2), text)
    return json.loads(cleaned)


GM_PLATFORMS = {"windows": "Windows", "mac": "macOS", "linux": "Linux", "android": "Android", "ios": "iOS"}


def load_gamemaker(root):
    out = {"name": "", "version": "", "configs": [], "rooms": [], "options": {}, "ok": False}
    yyp = sorted(p for p in root.iterdir() if p.suffix.lower() == ".yyp" and p.is_file())
    if not yyp:
        return out
    try:
        data = parse_gm_json(yyp[0].read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        out["name"] = yyp[0].stem
        return out
    out["ok"] = True
    out["name"] = str(data.get("%Name") or data.get("name") or yyp[0].stem)
    out["version"] = str((data.get("MetaData") or {}).get("IDEVersion", ""))

    def configs(node):
        if isinstance(node, dict):
            if node.get("name"):
                out["configs"].append(str(node["name"]))
            for ch in node.get("children", []) or []:
                configs(ch)
    configs(data.get("configs") or {})
    for res in data.get("resources", []) or []:
        rid = res.get("id", {}) if isinstance(res, dict) else {}
        if str(rid.get("path", "")).startswith("rooms/"):
            out["rooms"].append(str(rid.get("name", "")))
    opt_dir = root / "options"
    if opt_dir.is_dir():
        for d in sorted(opt_dir.iterdir()):
            if d.is_dir():
                yy = sorted(d.glob("*.yy"))
                if yy:
                    try:
                        out["options"][d.name] = parse_gm_json(yy[0].read_text(encoding="utf-8", errors="replace"))
                    except (OSError, ValueError):
                        pass
    return out


# Project scan

def collect_files(root, engine="godot"):
    """Returns (files, truncated)."""
    files = []
    skip_top = SKIP_TOP.get(engine, set())
    cap = MAX_FILES_GENERIC if engine == "generic" else None
    truncated = False
    gd_ignored = set()
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        rel_dir = here.relative_to(root)
        top = str(rel_dir) == "."
        dirnames[:] = sorted(d for d in dirnames
                             if d not in SKIP_DIRS and not d.startswith(".") and not (top and d in skip_top))
        if engine == "godot":
            ignored = (here / ".gdignore").exists() or any(str(p) in gd_ignored for p in rel_dir.parents) \
                or str(rel_dir) in gd_ignored
            if ignored:
                gd_ignored.add(str(rel_dir))
        elif engine == "unity":
            # Unity ignores folders ending in "~", like Samples~
            ignored = any(part.endswith("~") for part in rel_dir.parts)
        else:
            ignored = False
        for name in sorted(filenames):
            if name == ".gdignore" or name.endswith((".import", ".uid")):
                continue
            if engine == "unity" and name.endswith(".meta"):
                continue
            p = here / name
            rel = (rel_dir / name).as_posix() if not top else name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            files.append(ProjFile(rel=rel, path=p, ext=ext, size=size, ignored=ignored))
            if cap and len(files) >= cap:
                truncated = True
                break
        if truncated:
            break
    files.sort(key=lambda f: f.rel)
    return files, truncated


def _matches(patterns, rel):
    if not patterns:
        return False
    base = rel.rsplit("/", 1)[-1]
    res = "res://" + rel
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(base, pat) or fnmatch.fnmatch(res, pat):
            return True
    return False


def is_exported(f, preset):
    """Roughly what Godot packs into the .pck for this preset."""
    if f.ignored or f.rel in ("export_presets.cfg",):
        return False
    if _matches(preset.exclude, f.rel):
        return False
    res = "res://" + f.rel
    mode = preset.export_filter
    if mode in ("scenes", "resources", "customized"):
        base = res in preset.export_files
    elif mode == "exclude":
        base = f.ext in RESOURCE_EXT and res not in preset.export_files
    else:  # all_resources, the default
        base = f.ext in RESOURCE_EXT
    return base or _matches(preset.include, f.rel)


def read_text(f):
    if f.size > MAX_TEXT_BYTES:
        return None
    try:
        return f.path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _code_part(line):
    """GDScript line without its # comment."""
    in_q, q = False, ""
    for i, ch in enumerate(line):
        if in_q:
            if ch == q:
                in_q = False
        elif ch in "\"'":
            in_q, q = True, ch
        elif ch == "#":
            return line[:i]
    return line


def _indent(line):
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip())


def _is_guarded(lines, idx):
    """Whether line idx sits inside an `if` that checks is_debug_build or has_feature."""
    if GUARD_RE.search(_code_part(lines[idx])):
        return True
    level = _indent(lines[idx])
    for j in range(idx - 1, -1, -1):
        code = _code_part(lines[j])
        if not code.strip():
            continue
        ind = _indent(lines[j])
        if ind < level:
            stripped = code.strip()
            if re.match(r"(if|elif)\b", stripped) and GUARD_RE.search(stripped):
                return True
            if re.match(r"(static\s+)?func\b|class\b", stripped) or ind == 0:
                return False
            level = ind
    return False


def _mask(secret):
    secret = secret.strip()
    if len(secret) <= 6:
        return "***"
    return secret[:4] + "*" * min(8, len(secret) - 4)


def _limit(items, lang=DEFAULT_LANG, n=15):
    if len(items) <= n:
        return items
    return items[:n] + [tr(lang, "more", n=len(items) - n)]


# Checks

def _strip_block_comments(text):
    """Blanks out /* ... */ comments in C# or GML, keeping line breaks so line numbers still match."""
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    return re.sub(r'"(?:[^"\\\n]|\\.)*"|/\*.*?\*/', lambda m: m.group(0) if m.group(0)[0] == '"' else blank(m),
                  text, flags=re.S)


def _code_part_c(line):
    """C# or GML line without its // comment, ignoring // inside strings."""
    in_q, q, i = False, "", 0
    while i < len(line):
        ch = line[i]
        if in_q:
            if ch == "\\":
                i += 1
            elif ch == q:
                in_q = False
        elif ch in "\"'":
            in_q, q = True, ch
        elif line.startswith("//", i):
            return line[:i]
        i += 1
    return line


def _is_guarded_brace(lines, idx, guard_re):
    """_is_guarded for brace languages (C#, GML): is the line inside a debug `if` block?"""
    if guard_re.search(_code_part_c(lines[idx])):
        return True
    level = _indent(lines[idx])
    for j in range(idx - 1, -1, -1):
        code = _code_part_c(lines[j]).strip()
        if not code or code == "{":
            continue
        ind = _indent(lines[j])
        if ind < level:
            if re.match(r"(?:\}\s*)?(?:else\s+)?if\b", code) and guard_re.search(code):
                return True
            if ind == 0:
                return False
            level = ind
    return False


def _pp_guarded(lines):
    """C# lines inside #if UNITY_EDITOR, DEVELOPMENT_BUILD or DEBUG."""
    stack, out = [], set()
    any_token = re.compile(r"\b(UNITY_EDITOR|DEVELOPMENT_BUILD|DEBUG)\b")
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("#if"):
            cond = s[3:]
            stack.append([bool(CS_PP_GUARD_RE.search(cond)), bool(any_token.search(cond))])
            continue
        if s.startswith("#elif") and stack:
            cond = s[5:]
            stack[-1] = [bool(CS_PP_GUARD_RE.search(cond)), bool(any_token.search(cond))]
            continue
        if s.startswith("#else") and stack:
            if stack[-1][1]:
                stack[-1][0] = not stack[-1][0]
            continue
        if s.startswith("#endif") and stack:
            stack.pop()
            continue
        if any(g for g, _ in stack):
            out.add(i)
    return out


# Per-engine patterns for the debug code check
CODE_RULES = {
    "godot": {"ext": {"gd"}, "style": "py", "print": PRINT_RE, "brk": BREAKPOINT_RE, "brk_code": "breakpoints",
              "cmd": CMDLINE_RE, "guard": GUARD_RE, "todo": TODO_RE},
    "unity": {"ext": {"cs"}, "style": "brace", "print": CS_PRINT_RE, "brk": CS_BREAK_RE, "brk_code": "breakpoints",
              "cmd": CS_CMDLINE_RE, "guard": CS_GUARD_RE, "todo": C_TODO_RE},
    "gamemaker": {"ext": {"gml"}, "style": "brace", "print": GML_PRINT_RE, "brk": GML_OVERLAY_RE,
                  "brk_code": "gm_overlay", "cmd": GML_CMDLINE_RE, "guard": GML_GUARD_RE, "todo": C_TODO_RE},
}


class Checker:
    def __init__(self, root, lang=DEFAULT_LANG):
        self.root = Path(root)
        self.lang = norm_lang(lang)
        self.engine = detect_engine(self.root)
        self.findings = []
        self.files, self.truncated = collect_files(self.root, self.engine)
        self.project = {}
        self.presets = []
        self.unity = {}
        self.gm = {}
        if self.engine == "godot":
            self.project = parse_godot_cfg((self.root / "project.godot").read_text(encoding="utf-8", errors="replace"))
            self.presets = load_presets(self.root)
        elif self.engine == "unity":
            self.unity = load_unity(self.root)
        elif self.engine == "gamemaker":
            self.gm = load_gamemaker(self.root)
        self.analysis_presets = self.presets or [Preset(
            index="-", name=tr(self.lang, "virtual_preset"), platform="",
            export_filter="all_resources", include=[], exclude=[],
            export_files=set(), custom_features="", options={}, raw={},
            virtual=True)]
        self._texts = {}
        # what the scan actually did; the app's scan log shows these numbers
        self.stats = {"engine": self.engine, "engine_version": self.engine_version, "files": len(self.files),
                      "gdignored": sum(1 for f in self.files if f.ignored) if self.engine == "godot" else 0,
                      "presets": len(self.presets), "units": self.units, "secret_files": 0, "scripts": 0,
                      "demos": [], "checks": 0}

    def add(self, severity, cat, code, items=None, uid="", **params):
        msg = MESSAGES.get(f"{code}@{self.engine}") or MESSAGES[code]
        title, detail, fix = (s.format(**params) for s in msg[self.lang])
        self.findings.append(Finding(
            severity=severity, category=CATEGORIES[cat][self.lang], title=title, detail=detail, fix=fix,
            items=list(items or []), code=code, cat=cat, uid=f"{code}:{uid}" if uid else code))

    def lim(self, items):
        return _limit(items, self.lang)

    def text(self, f):
        if f.rel not in self._texts:
            self._texts[f.rel] = read_text(f)
        return self._texts[f.rel]

    def exported_by_any(self, f):
        return any(is_exported(f, p) for p in self.analysis_presets)

    def _dirs(self, f):
        return f.rel.split("/")[:-1]

    def ships(self, f):
        """Does the file, or what it compiles to, end up in a build?"""
        if self.engine == "godot":
            return self.exported_by_any(f)
        if self.engine == "unity":
            parts = self._dirs(f)
            return (bool(parts) and parts[0] == "Assets" and not f.ignored
                    and not any(p in UNITY_EDITOR_DIRS for p in parts))
        if self.engine == "gamemaker":
            parts = self._dirs(f)
            return bool(parts) and parts[0] not in ("notes", "options")
        return False

    def ships_as_is(self, f):
        """Shipped as-is, whether or not anything references it."""
        if self.engine == "godot":
            return self.exported_by_any(f)
        if self.engine == "unity":
            return self.ships(f) and any(p in ("Resources", "StreamingAssets") for p in self._dirs(f))
        if self.engine == "gamemaker":
            return f.rel.startswith("datafiles/")
        return False

    @property
    def engine_name(self):
        return ENGINE_NAMES.get(self.engine) or tr(self.lang, "engine.generic")

    @property
    def engine_version(self):
        if self.engine == "godot":
            feats = self.project.get("application", {}).get("config/features", [])
            return next((str(x) for x in feats if re.fullmatch(r"\d+\.\d+", str(x))), "")
        if self.engine == "unity":
            return self.unity.get("version", "")
        if self.engine == "gamemaker":
            return self.gm.get("version", "")
        return ""

    @property
    def units(self):
        """What decides a build's content: export presets (Godot), build scenes (Unity), rooms (GameMaker)."""
        if self.engine == "godot":
            return {"kind": "presets", "names": [p.name for p in self.presets]}
        if self.engine == "unity":
            return {"kind": "build_scenes", "names": [p for p, on in self.unity.get("scenes", []) if on]}
        if self.engine == "gamemaker":
            return {"kind": "rooms", "names": list(self.gm.get("rooms", []))}
        return {"kind": "", "names": []}

    @property
    def project_name(self):
        if self.engine == "godot":
            return str(self.project.get("application", {}).get("config/name", "")) or self.root.name
        if self.engine == "unity":
            return self.unity.get("player", {}).get("productName", "") or self.root.name
        if self.engine == "gamemaker":
            return self.gm.get("name", "") or self.root.name
        return self.root.name

    def facts(self):
        """Project numbers shown at the top of the results in the app."""
        scene_ext = {"godot": ("tscn", "scn"), "unity": ("unity",)}.get(self.engine, ())
        code_ext = {"godot": ("gd", "cs"), "unity": ("cs",), "gamemaker": ("gml",)}.get(self.engine, ())
        scenes = (len(self.gm.get("rooms", [])) if self.engine == "gamemaker"
                  else sum(1 for f in self.files if f.ext in scene_ext))
        return {"files": len(self.files), "scenes": scenes,
                "scripts": sum(1 for f in self.files if f.ext in code_ext),
                "size_mb": round(sum(f.size for f in self.files) / (1024 * 1024), 1),
                "units": self.units}

    CHECKS = {
        "godot": ("check_project_file", "check_presets_basics", "check_demo_leak", "check_secrets",
                  "check_dev_files", "check_debug_code", "check_metadata", "check_licenses", "check_ai_disclosure"),
        "unity": ("unity_protection", "unity_scenes", "unity_folders", "check_secrets", "check_dev_files",
                  "check_debug_code", "unity_metadata", "check_licenses", "check_ai_disclosure"),
        "gamemaker": ("gm_protection", "gm_rooms", "gm_datafiles", "check_secrets", "check_dev_files",
                      "check_debug_code", "gm_metadata", "check_licenses", "check_ai_disclosure"),
        "generic": ("generic_notice", "check_secrets", "check_dev_files", "check_licenses", "check_ai_disclosure"),
    }

    def run(self):
        checks = self.CHECKS[self.engine]
        for name in checks:
            getattr(self, name)()
        self.stats["checks"] = len(checks)
        order = {s: i for i, s in enumerate(SEVERITIES)}
        self.findings.sort(key=lambda x: (order[x.severity], x.cat))
        return self.findings

    # Godot

    def check_project_file(self):
        if not self.project:
            self.add("CRITICAL", "project", "no_project")
            return
        version = self.engine_version
        if version and version.startswith("3."):
            self.add("WARNING", "project", "godot3", version=version)

    def check_presets_basics(self):
        if not self.presets:
            self.add("WARNING", "export", "no_presets")
            return
        for p in self.presets:
            kw = {"name": p.name, "platform": p.platform, "uid": p.index}
            if p.raw.get("encrypt_pck", False) is True:
                if p.raw.get("encrypt_directory", False) is not True:
                    self.add("RECOMMENDED", "protection", "enc_dir_off", **kw)
                else:
                    self.add("OK", "protection", "enc_ok", **kw)
            else:
                self.add("WARNING", "protection", "enc_off", **kw)

            mode = p.raw.get("script_export_mode", None)
            if mode is None:
                self.add("RECOMMENDED", "protection", "script_mode_unset", **kw)
            elif mode == 0:
                self.add("WARNING", "protection", "script_text", **kw)
            else:
                self.add("OK", "protection", "script_bin", **kw)

    def check_demo_leak(self):
        demos = [p for p in self.presets if p.is_demo]
        uses_demo_flag = []
        for f in self.files:
            if f.ext == "gd":
                t = self.text(f)
                if t and DEMO_FEATURE_RE.search(t):
                    uses_demo_flag.append(f.rel)
        scenes = [f for f in self.files if f.ext in ("tscn", "scn") and not f.ignored]

        if not demos:
            if uses_demo_flag:
                self.add("WARNING", "demo", "demo_flag_no_preset", self.lim(uses_demo_flag))
            else:
                self.add("OK", "demo", "no_demo")
            return

        for p in demos:
            exported_scenes = [f.rel for f in scenes if is_exported(f, p)]
            self.stats["demos"].append({"name": p.name, "scenes": len(exported_scenes)})
            level_like = [s for s in exported_scenes if LEVEL_HINT_RE.search(s)]
            if p.export_filter in ("all_resources", "exclude") and not p.exclude:
                self.add("CRITICAL", "demo", "demo_full", self.lim(level_like or exported_scenes),
                         uid=p.index, name=p.name, scenes=len(exported_scenes))
            elif p.export_filter in ("all_resources", "exclude"):
                self.add("WARNING", "demo", "demo_exclude", self.lim(level_like or exported_scenes),
                         uid=p.index, name=p.name, scenes=len(exported_scenes))
            else:
                self.add("OK", "demo", "demo_selected", self.lim(level_like),
                         uid=p.index, name=p.name, files=len(p.export_files))
            if uses_demo_flag and p.export_filter in ("all_resources", "exclude"):
                self.add("WARNING", "demo", "demo_code_only", self.lim(uses_demo_flag), uid=p.index)

    def check_metadata(self):
        app = self.project.get("application", {})
        if not self.project:
            return
        if not app.get("config/name"):
            self.add("WARNING", "metadata", "no_name")
        if not app.get("config/version"):
            self.add("RECOMMENDED", "metadata", "no_version")
        icon = str(app.get("config/icon", ""))
        if not icon:
            self.add("RECOMMENDED", "metadata", "no_icon")
        elif icon.startswith("res://"):
            ip = self.root / icon[len("res://"):]
            if ip.is_file() and ip.suffix.lower() == ".svg":
                try:
                    if GODOT_DEFAULT_ICON_MARK in ip.read_text(encoding="utf-8", errors="replace").lower():
                        self.add("WARNING", "metadata", "default_icon")
                except OSError:
                    pass

        for p in self.presets:
            o = p.options
            if "windows" in p.platform.lower():
                missing = [k.split("/")[-1] for k in ("application/company_name",
                                                      "application/product_name",
                                                      "application/file_version",
                                                      "application/product_version")
                           if not o.get(k)]
                if missing:
                    self.add("RECOMMENDED", "metadata", "exe_meta", missing, uid=p.index, name=p.name)
            for key in ("application/bundle_identifier", "package/unique_name"):
                val = str(o.get(key, ""))
                if "com.example" in val or "$genname" in val:
                    self.add("WARNING", "metadata", "default_id", uid=f"{p.index}:{key}", name=p.name, value=val)

    # Unity

    def unity_protection(self):
        backend = self.unity.get("player", {}).get("scriptingBackend", {})
        backend = backend if isinstance(backend, dict) else {}
        targets = {"Standalone": backend.get("Standalone", "0")}
        targets.update({k: v for k, v in backend.items() if k and k != "Standalone"})
        for plat, val in targets.items():
            name = "PC, Mac & Linux" if plat == "Standalone" else plat
            if str(val).strip() == "1":
                self.add("OK", "protection", "unity_il2cpp", uid=plat, platform=name)
            else:
                self.add("WARNING", "protection", "unity_mono", uid=plat, platform=name)

    def _unity_demo_hint(self):
        player = self.unity.get("player", {})
        defines = player.get("scriptingDefineSymbols", {})
        tokens = set()
        for v in (defines.values() if isinstance(defines, dict) else [defines]):
            tokens.update(t.strip() for t in str(v).split(";") if t.strip())
        demo_defines = sorted(t for t in tokens if "DEMO" in t.upper())
        if demo_defines:
            return "define " + ", ".join(demo_defines)
        if "demo" in str(player.get("productName", "")).lower():
            return f"Product Name '{player.get('productName')}'"
        for path, on in self.unity.get("scenes", []):
            if on and "demo" in _words(Path(path).stem):
                return f"scene {Path(path).stem}"
        return ""

    def unity_scenes(self):
        enabled = [p for p, on in self.unity.get("scenes", []) if on]
        if self.unity.get("has_settings") and not enabled:
            self.add("RECOMMENDED", "export", "unity_no_scenes")
        tests = [p for p in enabled if looks_like_test(Path(p).stem)]
        if tests:
            self.add("WARNING", "export", "unity_test_scenes", self.lim(tests))
        hint = self._unity_demo_hint()
        if not hint:
            self.add("OK", "demo", "no_demo")
            return
        resources = [f.rel for f in self.files if self.ships_as_is(f) and "Resources" in self._dirs(f)]
        self.stats["demos"].append({"name": hint, "scenes": len(enabled)})
        level_like = [p for p in enabled if LEVEL_HINT_RE.search(Path(p).stem)]
        level_like += [r for r in resources if LEVEL_HINT_RE.search(r.rsplit("/", 1)[-1])]
        self.add("WARNING", "demo", "unity_demo", self.lim(level_like or enabled),
                 hint=hint, scenes=len(enabled), resources=len(resources))

    def unity_folders(self):
        res = [f.rel for f in self.files if self.ships_as_is(f) and "Resources" in self._dirs(f)]
        if res:
            self.add("RECOMMENDED", "export", "unity_resources", self.lim(res), n=len(res))
        streaming = [f.rel for f in self.files if self.ships_as_is(f) and "StreamingAssets" in self._dirs(f)]
        if streaming:
            self.add("RECOMMENDED", "files", "unity_streaming", self.lim(streaming), n=len(streaming))

    def unity_metadata(self):
        if not self.unity.get("has_settings"):
            return
        pl = self.unity.get("player", {})
        company = str(pl.get("companyName", ""))
        if company in ("", "DefaultCompany"):
            self.add("WARNING", "metadata", "unity_company", value=company or "DefaultCompany")
        if not pl.get("productName"):
            self.add("WARNING", "metadata", "no_name")
        if not pl.get("bundleVersion"):
            self.add("RECOMMENDED", "metadata", "no_version")
        if not self.unity.get("icon_set"):
            self.add("RECOMMENDED", "metadata", "no_icon")
        ids = pl.get("applicationIdentifier", {})
        for plat, val in (ids.items() if isinstance(ids, dict) else []):
            if re.search(r"(?i)\bcom\.(?:DefaultCompany|Company|example)\.|\.ProductName$", str(val)):
                label = {"Standalone": "PC, Mac & Linux", "": "Default"}.get(plat, plat)
                self.add("WARNING", "metadata", "default_id", uid=plat, name=label, value=val)

    # GameMaker

    def gm_protection(self):
        self.add("RECOMMENDED", "protection", "gm_yyc")
        main = self.gm.get("options", {}).get("main", {})
        if main.get("option_remove_unused_assets") is False:
            self.add("RECOMMENDED", "export", "gm_remove_unused")

    def _gm_demo_hint(self):
        demo_cfg = [c for c in self.gm.get("configs", []) if "demo" in c.lower()]
        if demo_cfg:
            return "config " + ", ".join(demo_cfg)
        for f in self.files:
            if f.ext == "gml":
                t = self.text(f)
                m = t and GML_DEMO_RE.search(t)
                if m:
                    return m.group(0).strip()
        return ""

    def gm_rooms(self):
        rooms = self.gm.get("rooms", [])
        tests = [r for r in rooms if looks_like_test(r)]
        if tests:
            self.add("WARNING", "export", "gm_test_rooms", self.lim(tests))
        hint = self._gm_demo_hint()
        if not hint:
            self.add("OK", "demo", "no_demo")
            return
        self.stats["demos"].append({"name": hint, "scenes": len(rooms)})
        level_like = [r for r in rooms if LEVEL_HINT_RE.search(r)]
        self.add("WARNING", "demo", "gm_demo", self.lim(level_like or rooms), hint=hint, rooms=len(rooms))

    def gm_datafiles(self):
        data = [f.rel for f in self.files if self.ships_as_is(f)]
        if data:
            self.add("RECOMMENDED", "files", "gm_datafiles", self.lim(data), n=len(data))

    def gm_metadata(self):
        opts = self.gm.get("options", {})
        names = []
        for plat in ("windows", "mac", "linux"):
            val = str(opts.get(plat, {}).get(f"option_{plat}_display_name", ""))
            if val.startswith("Created with GameMaker"):
                names.append((GM_PLATFORMS[plat], val))
        if names:
            self.add("WARNING", "metadata", "gm_display_name", [n for n, _ in names], uid="display",
                     name=names[0][0], value=names[0][1])
        win = opts.get("windows", {})
        if win:
            defaults = []
            for key, bad in (("company_info", ("", "YoYo Games Ltd")),
                             ("product_info", ("", "Created with GameMaker Studio 2", "Created with GameMaker")),
                             ("description_info", ("", "A GameMaker Studio 2 Game", "A GameMaker Game")),
                             ("copyright_info", ("",))):
                val = str(win.get(f"option_windows_{key}", ""))
                if val in bad:
                    defaults.append(f"{key}: {val or '-'}")
            if defaults:
                self.add("RECOMMENDED", "metadata", "exe_meta", defaults, uid="windows")
        ids = []
        android = opts.get("android", {})
        if android:
            aid = ".".join(str(android.get(f"option_android_package_{k}", "")) for k in ("domain", "company", "product"))
            if aid == "com.company.game":
                ids.append(("Android", aid))
        for plat, key in (("mac", "option_mac_app_id"), ("ios", "option_ios_bundle_name")):
            val = str(opts.get(plat, {}).get(key, ""))
            if val.startswith("com.company.") or "yoyogames" in val:
                ids.append((GM_PLATFORMS[plat], val))
        if ids:
            self.add("RECOMMENDED", "metadata", "default_id", [f"{p}: {v}" for p, v in ids], uid="ids",
                     name=ids[0][0], value=ids[0][1])

    # No engine recognized

    def generic_notice(self):
        self.add("WARNING", "project", "engine_unknown")
        if self.truncated:
            self.add("WARNING", "project", "too_many_files", n=MAX_FILES_GENERIC)

    # Every engine

    def check_secrets(self):
        hits_build, hits_local = [], []
        for f in self.files:
            if f.ext not in TEXT_SCAN_EXT and f.ext not in SENSITIVE_EXT:
                continue
            t = self.text(f)
            if not t:
                continue
            self.stats["secret_files"] += 1
            yaml_like = f.ext in YAML_EXT
            for lineno, line in enumerate(t.splitlines(), 1):
                found = None
                for label_id, rx in SECRET_PATTERNS:
                    m = rx.search(line)
                    if m:
                        found = f"{SECRET_LABELS[label_id][self.lang]}: {_mask(m.group(0))}"
                        break
                if not found:
                    m = GENERIC_SECRET.search(line) or (YAML_SECRET.search(line) if yaml_like else None)
                    if m:
                        val = m.group(2)
                        low = val.lower()
                        # real keys have no spaces; skips things like "JUST FOR TESTING" or code fragments
                        if (not any(h in low for h in PLACEHOLDER_HINTS) and len(set(val)) > 3
                                and not re.search(r"\s", val)):
                            found = f"'{m.group(1)}' = {_mask(val)}"
                if found:
                    entry = f"{f.rel}:{lineno} - {found}"
                    (hits_build if self.engine != "generic" and self.ships(f) else hits_local).append(entry)
        if self.engine == "generic":
            if hits_local:
                self.add("WARNING", "secrets", "secrets_generic", self.lim(hits_local))
            else:
                self.add("OK", "secrets", "secrets_none")
            return
        if hits_build:
            self.add("CRITICAL", "secrets", "secrets_build", self.lim(hits_build))
        if hits_local:
            self.add("WARNING", "secrets", "secrets_local", self.lim(hits_local))
        if not hits_build and not hits_local:
            self.add("OK", "secrets", "secrets_none")

    def check_dev_files(self):
        sensitive = [f for f in self.files if f.ext in SENSITIVE_EXT]
        sens_build = [f.rel for f in sensitive if self.ships_as_is(f)]
        sens_local = [f.rel for f in sensitive if not self.ships_as_is(f)]
        if sens_build:
            self.add("CRITICAL", "files", "cred_build", self.lim(sens_build))
        if sens_local:
            self.add("WARNING", "files", "cred_local", self.lim(sens_local))

        if self.engine == "godot":
            for p in self.analysis_presets:
                dev = [f.rel for f in self.files
                       if f.ext not in SENSITIVE_EXT
                       and (f.ext in DEV_EXT or DEV_NAME_HINTS.search(f.rel.rsplit("/", 1)[-1]))
                       and is_exported(f, p)]
                if dev:
                    self.add("WARNING", "files", "dev_files", self.lim(dev), uid=p.index, name=p.name)
        elif self.engine in ("unity", "gamemaker"):
            # .txt, .csv and .json under Resources or datafiles are usually game data (dialogue, tables)
            dev_ext = DEV_EXT - {"txt", "csv", "json"}
            dev = [f.rel for f in self.files
                   if f.ext not in SENSITIVE_EXT and self.ships_as_is(f)
                   and (f.ext in dev_ext or DEV_NAME_HINTS.search(f.rel.rsplit("/", 1)[-1]))]
            if dev:
                self.add("WARNING", "files", "dev_files", self.lim(dev), uid=self.engine, name="")

    def check_debug_code(self):
        rules = CODE_RULES[self.engine]
        prints, breaks, cheats, cmdline, todos = {}, [], [], [], 0
        for f in self.files:
            if f.ext not in rules["ext"] or not self.ships(f):
                continue
            t = self.text(f)
            if not t:
                continue
            self.stats["scripts"] += 1
            raw_lines = t.splitlines()
            if rules["style"] == "brace":
                lines = _strip_block_comments(t).splitlines()
                code_of = _code_part_c
                pp = _pp_guarded(lines) if self.engine == "unity" else set()

                def guarded(i):
                    return i in pp or _is_guarded_brace(lines, i, rules["guard"])
            else:
                lines = raw_lines
                code_of = _code_part
                pp = set()

                def guarded(i):
                    return _is_guarded(lines, i)
            for i, line in enumerate(lines):
                lineno = i + 1
                if i < len(raw_lines) and rules["todo"].search(raw_lines[i]):
                    todos += 1
                code = code_of(line)
                if not code.strip() or i in pp:
                    continue
                if rules["print"].search(code):
                    prints[f.rel] = prints.get(f.rel, 0) + 1
                if rules["brk"].search(code) and (self.engine != "gamemaker" or not guarded(i)):
                    breaks.append(f"{f.rel}:{lineno}")
                m = CHEAT_RE.search(code)
                if m and (self.engine == "godot" or not guarded(i)):
                    cheats.append(f"{f.rel}:{lineno} - '{m.group(0)}'")
                if rules["cmd"].search(code):
                    cmdline.append((f"{f.rel}:{lineno}", guarded(i)))

        if breaks:
            self.add("WARNING", "debug", rules["brk_code"], self.lim(breaks))
        if cheats:
            self.add("WARNING", "debug", "cheats", self.lim(cheats))
        unguarded = [loc for loc, g in cmdline if not g]
        if unguarded:
            self.add("WARNING", "debug", "cmdline_unguarded", self.lim(unguarded))
        elif cmdline:
            self.add("OK", "debug", "cmdline_guarded", self.lim([loc for loc, _ in cmdline]))
        total_prints = sum(prints.values())
        if total_prints:
            top = sorted(prints.items(), key=lambda kv: -kv[1])
            self.add("RECOMMENDED", "debug", "prints", self.lim([f"{k}: {v}" for k, v in top]), n=total_prints)
        if todos:
            self.add("RECOMMENDED", "debug", "todos", n=todos)

    def _plugin_dirs(self):
        """Third-party plugin folders per engine, as (prefix, severity)."""
        if self.engine == "godot":
            return "addons/", "WARNING", set()
        if self.engine == "unity":
            return "Assets/Plugins/", "RECOMMENDED", UNITY_PLATFORM_DIRS
        if self.engine == "gamemaker":
            return "extensions/", "RECOMMENDED", set()
        return None, None, set()

    def check_licenses(self):
        root_names = [f.rel for f in self.files if "/" not in f.rel]
        has_credits = any(CREDITS_NAMES.search(n) or LICENSE_NAMES.search(n) for n in root_names)
        if not has_credits:
            self.add("RECOMMENDED", "licenses", "no_credits")

        font_dirs = {}
        for f in self.files:
            if f.ext in ("ttf", "otf", "woff", "woff2"):
                d = f.rel.rsplit("/", 1)[0] if "/" in f.rel else ""
                font_dirs.setdefault(d, []).append(f.rel)
        no_license = []
        for d, fonts in font_dirs.items():
            siblings = [f.rel.rsplit("/", 1)[-1] for f in self.files
                        if (f.rel.rsplit("/", 1)[0] if "/" in f.rel else "") == d]
            if not any(LICENSE_NAMES.search(s) for s in siblings):
                no_license.extend(fonts)
        if no_license:
            self.add("WARNING", "licenses", "fonts_nolicense", self.lim(no_license))

        prefix, severity, skip = self._plugin_dirs()
        if not prefix:
            return
        depth = prefix.count("/")
        plugins = sorted({f.rel.split("/")[depth] for f in self.files
                          if f.rel.startswith(prefix) and f.rel.count("/") > depth})
        bare = []
        for a in plugins:
            if a in skip:
                continue
            names = [f.rel.rsplit("/", 1)[-1] for f in self.files if f.rel.startswith(f"{prefix}{a}/")]
            if not any(LICENSE_NAMES.search(n) for n in names):
                bare.append(f"{prefix}{a}")
        if bare:
            self.add(severity, "licenses", "addons_nolicense", self.lim(bare))

    def check_ai_disclosure(self):
        found = any(AI_DISCLOSURE_HINTS.search(f.rel) for f in self.files)
        if not found:
            for f in self.files:
                if "/" not in f.rel and f.ext in ("md", "txt"):
                    t = self.text(f)
                    if t and AI_DISCLOSURE_HINTS.search(t):
                        found = True
                        break
        self.add("OK", "ai", "ai_ok") if found else self.add("RECOMMENDED", "ai", "ai_missing")


# Authorship manifest

def build_manifest(root, files, lang=DEFAULT_LANG):
    entries = []
    agg = hashlib.sha256()
    for f in files:
        h = hashlib.sha256()
        try:
            with open(f.path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
        except OSError:
            continue
        digest = h.hexdigest()
        entries.append({"path": f.rel, "size": f.size, "sha256": digest})
        agg.update(f"{f.rel}\0{digest}\n".encode("utf-8"))
    return {
        "tool": f"OwlCheck {VERSION}",
        "project": root.name,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(entries),
        "aggregate_sha256": agg.hexdigest(),
        "files": entries,
        "note": tr(norm_lang(lang), "manifest_note"),
    }


# Reports

def counts(findings):
    c = {s: 0 for s in SEVERITIES}
    for f in findings:
        c[f.severity] += 1
    return c


def sev_label(lang, sev):
    return tr(lang, "sev." + sev)


def render_terminal(checker, findings, color=True):
    L = checker.lang
    colors = {"CRITICAL": "\033[91m", "WARNING": "\033[93m", "RECOMMENDED": "\033[96m", "OK": "\033[92m"}
    reset, bold, dim = "\033[0m", "\033[1m", "\033[2m"
    if not color:
        colors = {k: "" for k in colors}
        reset = bold = dim = ""
    out = [f"{bold}OwlCheck {VERSION}{reset} - {checker.project_name} ({checker.engine_name})",
           f"{dim}{tr(L, 'local')}{reset}\n"]
    for f in findings:
        out.append(f"{colors[f.severity]}{bold}[{sev_label(L, f.severity).upper()}]{reset} "
                   f"{bold}{f.title}{reset}  {dim}({f.category}){reset}")
        out.append(f"    {f.detail}")
        if f.fix:
            out.append(f"    {dim}{tr(L, 'how_fix')}:{reset} {f.fix}")
        for it in f.items:
            out.append(f"      - {it}")
        out.append("")
    c = counts(findings)
    out.append(f"{bold}{tr(L, 'summary')}:{reset} "
               + "  ".join(f"{colors[s]}{sev_label(L, s)}: {c[s]}{reset}" for s in SEVERITIES))
    return "\n".join(out)


def render_markdown(checker, findings):
    L = checker.lang
    c = counts(findings)
    now = datetime.datetime.now().strftime(tr(L, "date_fmt"))
    md = [f"# OwlCheck - {checker.project_name}", "", f"**{checker.engine_name}**", "",
          tr(L, "md_generated", date=now, version=VERSION), "",
          "| " + " | ".join(sev_label(L, s) for s in SEVERITIES) + " |", "|---|---|---|---|",
          "| " + " | ".join(str(c[s]) for s in SEVERITIES) + " |", ""]
    for sev in SEVERITIES:
        group = [f for f in findings if f.severity == sev]
        if not group:
            continue
        md.extend([f"## {sev_label(L, sev)}", ""])
        for f in group:
            box = "x" if sev == "OK" else " "
            md.append(f"- [{box}] **{f.title}** _({f.category})_  ")
            md.append(f"  {f.detail}  ")
            if f.fix:
                md.append(f"  **{tr(L, 'how_fix')}:** {f.fix}")
            for it in f.items:
                md.append(f"  - `{it}`")
            md.append("")
    return "\n".join(md)


def render_html(checker, findings):
    L = checker.lang
    c = counts(findings)
    e = html.escape
    now = datetime.datetime.now().strftime(tr(L, "date_fmt"))
    cards = []
    for sev in SEVERITIES:
        group = [f for f in findings if f.severity == sev]
        if not group:
            continue
        cards.append(f'<h2 class="sec sec-{sev.lower()}">{e(sev_label(L, sev))} <span>{len(group)}</span></h2>')
        for f in group:
            items = "".join(f"<li><code>{e(str(i))}</code></li>" for i in f.items)
            items_html = f"<ul>{items}</ul>" if items else ""
            fix_html = f'<p class="fix"><b>{e(tr(L, "how_fix"))}:</b> {e(f.fix)}</p>' if f.fix else ""
            check = "checked disabled" if sev == "OK" else ""
            cards.append(
                f'<div class="card card-{sev.lower()}"><label><input type="checkbox" {check}>'
                f'<span class="t">{e(f.title)}</span><span class="cat">{e(f.category)}</span></label>'
                f'<p>{e(f.detail)}</p>{fix_html}{items_html}</div>')
    sums = "\n".join(f'<div class="c-{s.lower()}"><b>{c[s]}</b><span>{e(sev_label(L, s))}</span></div>' for s in SEVERITIES)
    return f"""<!doctype html>
<html lang="{tr(L, 'html_lang')}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OwlCheck - {e(checker.project_name)}</title>
<style>
:root {{ --paper:#F2F1EC; --paper2:#E8E7E1; --block:#D6D5CF; --mid:#8C8B86; --soft:#55544F; --ink:#111; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
.wrap {{ max-width:860px; margin:0 auto; padding:32px 16px 64px; }}
header h1 {{ margin:0; font-size:28px; font-weight:900; letter-spacing:-.02em; }}
header p {{ margin:4px 0 0; color:var(--soft); font-size:13px; }}
.priv {{ margin-top:16px; padding:10px 14px; border:2px solid var(--ink); border-radius:12px; font-size:13px; }}
.sum {{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin:20px 0 8px; }}
.sum div {{ border:2px solid var(--ink); border-radius:12px; padding:12px; text-align:center; }}
.sum div.c-critico {{ background:var(--ink); color:var(--paper); }}
.sum b {{ display:block; font-size:26px; font-family:ui-monospace,Menlo,Consolas,monospace; }}
.sum span {{ font-size:12px; letter-spacing:.06em; }}
.sec {{ margin:32px 0 10px; font-size:14px; letter-spacing:.08em; display:flex; gap:10px; align-items:center; }}
.sec::after {{ content:""; flex:1; height:2px; background:var(--ink); }}
.sec span {{ color:var(--mid); font-weight:400; }}
.card {{ border:2px solid var(--ink); border-radius:14px; padding:14px 16px; margin:10px 0; background:var(--paper); }}
.card-critico {{ border-width:2.5px; box-shadow:5px 5px 0 var(--ink); margin-bottom:18px; }}
.card-atencao {{ position:relative; padding-left:34px; overflow:hidden; }}
.card-atencao::before {{ content:""; position:absolute; left:0; top:0; bottom:0; width:16px; border-right:2px solid var(--ink);
  background-image:repeating-linear-gradient(135deg,var(--ink) 0 2px,transparent 2px 6px); }}
.card-recomendado {{ background:var(--paper2); border-color:var(--soft); }}
.card-ok {{ border-style:dashed; border-color:var(--mid); }}
.card label {{ display:grid; grid-template-columns:auto 1fr auto; column-gap:10px; align-items:baseline; cursor:pointer; }}
.card input {{ accent-color:var(--ink); transform:translateY(2px); width:16px; height:16px; }}
.card .t {{ font-weight:700; }}
.card .cat {{ font-size:11px; border:2px solid var(--ink); border-radius:99px; padding:1px 8px; white-space:nowrap; }}
.card p {{ margin:8px 0 0; }}
.card .fix {{ background:var(--paper2); padding:8px 10px; border-radius:10px; }}
.card-recomendado .fix {{ background:var(--paper); }}
.card ul {{ margin:8px 0 0; padding-left:18px; }}
.card code {{ font:12.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; color:var(--soft); word-break:break-all; }}
footer {{ margin-top:40px; padding-top:12px; border-top:2px solid var(--ink); color:var(--soft); font-size:12px; }}
@media (max-width:560px) {{ .sum {{ grid-template-columns:repeat(2,1fr); }}
  .card label {{ grid-template-columns:auto 1fr; }} .card .cat {{ grid-column:2; justify-self:start; margin-top:4px; }} }}
</style></head><body><div class="wrap">
<header><h1>OwlCheck</h1>
<p>{e(checker.project_name)} &middot; {e(checker.engine_name)} &middot; {e(now)} &middot; {e(tr(L, 'version'))} {VERSION}</p></header>
<div class="priv">{e(tr(L, 'html_priv'))}</div>
<div class="sum">
{sums}
</div>
{''.join(cards)}
<footer>{e(tr(L, 'footer'))}</footer>
</div></body></html>"""


# Command line

REPORT_FILES = {"html": "owlcheck-report.html", "md": "owlcheck-report.md",
                "json": "owlcheck-result.json", "manifest": "owlcheck-manifest.json"}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="owlcheck",
        description="Pre-release checklist for Unity, Godot 4 and GameMaker projects (plus general checks for any "
                    "other folder). Runs locally, no network.")
    ap.add_argument("project", help="project root folder (with ProjectSettings/, project.godot or the .yyp file)")
    ap.add_argument("--lang", default=DEFAULT_LANG, choices=LANGS, help="report language: en, es or pt (default: en)")
    ap.add_argument("--out", default=".", help="folder to save the reports in (default: current folder)")
    ap.add_argument("--no-html", action="store_true", help="don't write the HTML report")
    ap.add_argument("--md", action="store_true", help="also write a Markdown report")
    ap.add_argument("--json", action="store_true", help="also write the results as JSON")
    ap.add_argument("--manifest", action="store_true",
                    help="write a manifest with the SHA-256 hash of every file (proof of authorship)")
    ap.add_argument("--no-color", action="store_true", help="plain output without colors")
    ap.add_argument("--version", action="version", version=f"OwlCheck {VERSION}")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    L = norm_lang(args.lang)

    root = resolve_root(args.project)
    if root is None:
        print(tr(L, "cli_not_found", path=Path(args.project).expanduser()), file=sys.stderr)
        return 2
    if detect_engine(root) == "generic":
        inside = find_projects(root)
        if inside:
            print(tr(L, "cli_projects_inside"), file=sys.stderr)
            for p, eng in inside:
                print(f"  {p}  ({eng})", file=sys.stderr)
            return 2
    out = Path(args.out).expanduser().resolve()
    if out == root or root in out.parents:
        print(tr(L, "cli_inside"), file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)

    checker = Checker(root, lang=L)
    findings = checker.run()
    color = not args.no_color and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    print(render_terminal(checker, findings, color=color))

    written = []
    if not args.no_html:
        p = out / REPORT_FILES["html"]
        p.write_text(render_html(checker, findings), encoding="utf-8")
        written.append(p)
    if args.md:
        p = out / REPORT_FILES["md"]
        p.write_text(render_markdown(checker, findings), encoding="utf-8")
        written.append(p)
    if args.json:
        p = out / REPORT_FILES["json"]
        p.write_text(json.dumps({"tool": f"OwlCheck {VERSION}", "project": checker.project_name, "lang": L,
                                 "engine": checker.engine, "engine_version": checker.engine_version,
                                 "counts": counts(findings),
                                 "findings": [f.__dict__ for f in findings]},
                                ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(p)
    if args.manifest:
        p = out / REPORT_FILES["manifest"]
        p.write_text(json.dumps(build_manifest(root, checker.files, L), ensure_ascii=False, indent=2),
                     encoding="utf-8")
        written.append(p)
    for p in written:
        print(tr(L, "cli_saved", path=p))
    return 1 if any(f.severity == "CRITICAL" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
