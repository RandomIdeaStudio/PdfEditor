"""Multilingual localization service backed by JSON locale files."""

from __future__ import annotations

import json
import locale
import os
import sys
from pathlib import Path
from typing import Any

from .. import APP_NAME

SUPPORTED_LANGUAGES: tuple[str, ...] = ("cs", "en")
FALLBACK_LANGUAGE = "en"


def _resolve_locales_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "locales"
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[3] / "locales"


def _get_settings_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else (Path.home() / "AppData" / "Local")
    return base / APP_NAME / "settings.json"


def detect_system_language() -> str:
    """Detect OS language; fall back to English if unsupported."""
    try:
        lang_code, _ = locale.getlocale()
        if lang_code:
            short = lang_code.split("_")[0].split("-")[0].lower()
            if short in SUPPORTED_LANGUAGES:
                return short
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            import ctypes

            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            # 0x0405 = cs-CZ
            if (lcid & 0x3FF) == 0x05:
                return "cs"
    except Exception:
        pass
    return FALLBACK_LANGUAGE


def load_saved_language() -> str | None:
    settings_path = _get_settings_path()
    if not settings_path.exists():
        return None
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        lang = data.get("language")
        if lang in SUPPORTED_LANGUAGES:
            return str(lang)
    except Exception:
        pass
    return None


def save_language_preference(lang: str) -> None:
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {lang}")
    settings_path = _get_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["language"] = lang
    settings_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


class LocalizationManager:
    """Loads locale dictionaries and formats translated strings by key."""

    def __init__(self, locales_dir: Path | None = None) -> None:
        self._locales_dir = locales_dir or _resolve_locales_dir()
        self._catalogs: dict[str, dict[str, str]] = {}
        self._current_language: str = FALLBACK_LANGUAGE
        self._load_all()
        initial = load_saved_language() or detect_system_language()
        self.set_language(initial, persist=False)

    def _load_all(self) -> None:
        for lang in SUPPORTED_LANGUAGES:
            path = self._locales_dir / f"{lang}.json"
            if not path.exists():
                raise FileNotFoundError(f"Missing locale file: {path}")
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._catalogs[lang] = {str(k): str(v) for k, v in raw.items()}

    @property
    def language(self) -> str:
        return self._current_language

    def set_language(self, lang: str, persist: bool = True) -> None:
        if lang not in self._catalogs:
            lang = FALLBACK_LANGUAGE
        self._current_language = lang
        if persist:
            try:
                save_language_preference(lang)
            except Exception:
                pass

    def catalog(self, lang: str) -> dict[str, str]:
        return dict(self._catalogs[lang])

    def t(self, key: str, **kwargs: Any) -> str:
        table = self._catalogs.get(self._current_language, {})
        template = table.get(key)
        if template is None:
            template = self._catalogs[FALLBACK_LANGUAGE].get(key, key)
        if kwargs:
            return template.format(**kwargs)
        return template


_MANAGER: LocalizationManager | None = None


def get_i18n() -> LocalizationManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = LocalizationManager()
    return _MANAGER


def t(key: str, **kwargs: Any) -> str:
    return get_i18n().t(key, **kwargs)
