"""Localization integrity tests: key parity, placeholder parity, and code references."""

from __future__ import annotations

import re
import string
from pathlib import Path

from pdf_editor.core.i18n import LocalizationManager, SUPPORTED_LANGUAGES

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "pdf_editor"
T_CALL_PATTERN = re.compile(r'\bt\(\s*"([a-z0-9_.]+)"')


def _extract_placeholders(template: str) -> set[str]:
    formatter = string.Formatter()
    return {
        field_name
        for _lit, field_name, _spec, _conv in formatter.parse(template)
        if field_name is not None
    }


def test_all_locales_have_identical_keys_and_placeholders() -> None:
    mgr = LocalizationManager()
    en_catalog = mgr.catalog("en")
    assert en_catalog, "English catalog must not be empty"

    for lang in SUPPORTED_LANGUAGES:
        cat = mgr.catalog(lang)
        missing = set(en_catalog) - set(cat)
        extra = set(cat) - set(en_catalog)
        assert not missing, f"Locale '{lang}' is missing keys: {sorted(missing)}"
        assert not extra, f"Locale '{lang}' has extra keys not in 'en': {sorted(extra)}"

        for key, value in cat.items():
            assert value.strip(), f"Locale '{lang}' has empty value for key '{key}'"
            assert _extract_placeholders(value) == _extract_placeholders(en_catalog[key]), (
                f"Placeholder mismatch for key '{key}' in locale '{lang}'"
            )


def test_all_code_i18n_keys_exist_in_catalogs() -> None:
    mgr = LocalizationManager()
    en_catalog = mgr.catalog("en")

    referenced_keys: set[str] = set()
    for py_file in SRC_DIR.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        referenced_keys.update(T_CALL_PATTERN.findall(content))

    assert referenced_keys, "Expected i18n key references in source code"
    missing = referenced_keys - set(en_catalog)
    assert not missing, f"Source code references undefined i18n keys: {sorted(missing)}"


def test_core_layer_has_no_pyside6_imports() -> None:
    core_dir = SRC_DIR / "core"
    for py_file in core_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        assert "PySide6" not in text, f"Core module {py_file.name} must not import PySide6"
