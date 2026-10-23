"""Local application data: where the inventory database and remembered file paths live.

Never inside Google Drive, the project folder or PyInstaller's temporary runtime folder."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

APP_DIR = Path("Auraplex") / "MaterialStockChecker"
ROLES = ("stock", "bom")


def default_data_dir() -> Path:
    """%LOCALAPPDATA%\\Auraplex\\MaterialStockChecker (per user, not roamed, not synced)."""
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / "AppData" / "Local") / APP_DIR


class Settings:
    """Remembered Storage / BOM paths as the user selected them (drive letters are never assumed)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}  # first run, or an unreadable file: the user simply selects the files again
        paths = data.get("paths") if isinstance(data, dict) else None
        return {role: paths[role] for role in ROLES
                if isinstance(paths, dict) and isinstance(paths.get(role), str) and paths[role]}

    def remember(self, role: str, path: str) -> bool:
        """Store one selected path. Returns True if the file changed. Atomic: a crash leaves the old file intact."""
        if role not in ROLES:
            raise ValueError("Unknown workbook role")
        paths = self.load()
        if paths.get(role) == path:
            return False
        paths[role] = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".settings-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "paths": paths}, stream, ensure_ascii=False, indent=2)
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.remove(temporary)
            except OSError:
                pass
            raise
        return True


class InterfacePreferences:
    """The interface language, in its own file beside settings.json (never inside it, never the database).

    Reading never fails: a missing, unreadable or invalid file gives the default. Saving is atomic (temporary file in
    the same folder, fsync, os.replace); a failure raises OSError and leaves any earlier file intact."""

    VERSION = 1

    def __init__(self, path: str | Path, languages=("en", "zh", "ms"), default="en"):
        self.path, self.languages, self.default = Path(path), tuple(languages), default

    def load(self) -> tuple[str, str | None]:
        """(language, problem): problem is None for a valid file or no file, else why the default is used."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self.default, None
        except (OSError, UnicodeDecodeError) as exc:
            return self.default, f"{type(exc).__name__}: {exc}"
        try:
            data = json.loads(text)
        except ValueError as exc:
            return self.default, f"invalid JSON: {exc}"
        language = data.get("language") if isinstance(data, dict) else None
        if language not in self.languages:
            return self.default, f"unsupported language value: {language!r}"
        return language, None

    def save(self, language: str) -> None:
        if language not in self.languages:
            raise ValueError("Unsupported interface language")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".interface-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"version": self.VERSION, "language": language}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.remove(temporary)
            except OSError:
                pass
            raise
