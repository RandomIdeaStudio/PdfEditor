"""Windows 10 & 11 HKCU context menu installer and uninstaller (zero admin rights)."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .. import APP_NAME, PUBLISHER, VERSION
from .converter import CONVERTIBLE_EXTENSIONS
from .i18n import t
from .presets import PRESETS

EDIT_MENU_KEY = rf"Software\Classes\SystemFileAssociations\.pdf\shell\{APP_NAME}Edit"
DOWNSIZE_MENU_KEY = rf"Software\Classes\SystemFileAssociations\.pdf\shell\{APP_NAME}Downsize"
CONVERT_SUBKEY_NAME = f"{APP_NAME}Convert"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"


@dataclass(frozen=True)
class InstallStatus:
    installed: bool
    registered_command: str | None
    install_dir: Path
    installed_exe: Path


def get_install_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_NAME
    return Path.home() / "AppData" / "Local" / APP_NAME


def get_installed_exe_path() -> Path:
    return get_install_dir() / f"{APP_NAME}.exe"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _convert_key_for_ext(ext: str) -> str:
    return rf"Software\Classes\SystemFileAssociations\{ext}\shell\{CONVERT_SUBKEY_NAME}"


def _notify_shell() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except Exception:
        pass


def _delete_tree_hkcu(subkey: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_tree_hkcu(rf"{subkey}\{child}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
    except FileNotFoundError:
        pass


def get_install_status() -> InstallStatus:
    install_dir = get_install_dir()
    installed_exe = get_installed_exe_path()

    if sys.platform != "win32":
        return InstallStatus(False, None, install_dir, installed_exe)

    import winreg

    try:
        cmd_key = rf"{EDIT_MENU_KEY}\command"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cmd_key, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, "")
            return InstallStatus(True, str(value), install_dir, installed_exe)
    except OSError:
        return InstallStatus(False, None, install_dir, installed_exe)


def _resolve_command_prefix(target_exe: Path) -> tuple[str, str]:
    if is_frozen():
        exe_str = str(target_exe)
        return f'"{exe_str}"', f'"{exe_str}",0'

    python_exe = Path(sys.executable)
    pythonw = python_exe.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else python_exe
    project_root = Path(__file__).resolve().parents[3]
    entry_script = project_root / "run_app.py"
    icon_file = project_root / "assets" / "app.ico"
    icon_value = str(icon_file) if icon_file.exists() else f'"{runner}",0'
    return f'"{runner}" "{entry_script}"', icon_value


def install_app() -> InstallStatus:
    """Copy executable into `%LOCALAPPDATA%\\PdfEditor` and register HKCU context menus."""
    if sys.platform != "win32":
        raise RuntimeError(t("error.windows_only"))

    import winreg

    install_dir = get_install_dir()
    target_exe = get_installed_exe_path()

    if is_frozen():
        current_exe = Path(sys.executable).resolve()
        install_dir.mkdir(parents=True, exist_ok=True)
        if current_exe != target_exe.resolve():
            shutil.copy2(current_exe, target_exe)

    cmd_prefix, icon_value = _resolve_command_prefix(target_exe)

    # 1) Direct "Edit in PdfEditor" item on .pdf files
    _delete_tree_hkcu(EDIT_MENU_KEY)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, EDIT_MENU_KEY) as edit_key:
        winreg.SetValueEx(edit_key, "MUIVerb", 0, winreg.REG_SZ, t("context_menu.edit"))
        winreg.SetValueEx(edit_key, "Icon", 0, winreg.REG_SZ, icon_value)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{EDIT_MENU_KEY}\command") as cmd_key:
        winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, f'{cmd_prefix} "%1"')

    # 2) Cascading "Downsize PDF" submenu on .pdf files
    _delete_tree_hkcu(DOWNSIZE_MENU_KEY)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, DOWNSIZE_MENU_KEY) as root_key:
        winreg.SetValueEx(root_key, "MUIVerb", 0, winreg.REG_SZ, t("context_menu.downsize"))
        winreg.SetValueEx(root_key, "SubCommands", 0, winreg.REG_SZ, "")
        winreg.SetValueEx(root_key, "Icon", 0, winreg.REG_SZ, icon_value)

    for preset in PRESETS:
        item_key_path = rf"{DOWNSIZE_MENU_KEY}\shell\{preset.registry_id}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, item_key_path) as item_key:
            winreg.SetValueEx(item_key, "MUIVerb", 0, winreg.REG_SZ, preset.label)
            winreg.SetValueEx(item_key, "Icon", 0, winreg.REG_SZ, icon_value)

        cmd_key_path = rf"{item_key_path}\command"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_key_path) as cmd_key:
            winreg.SetValueEx(
                cmd_key,
                "",
                0,
                winreg.REG_SZ,
                f'{cmd_prefix} --preset {preset.key} "%1"',
            )

    # 3) "Convert to PDF" on all supported non-PDF extensions
    for ext in CONVERTIBLE_EXTENSIONS:
        conv_key_path = _convert_key_for_ext(ext)
        _delete_tree_hkcu(conv_key_path)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, conv_key_path) as conv_key:
            winreg.SetValueEx(conv_key, "MUIVerb", 0, winreg.REG_SZ, t("context_menu.convert"))
            winreg.SetValueEx(conv_key, "Icon", 0, winreg.REG_SZ, icon_value)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{conv_key_path}\command") as cmd_key:
            winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, f'{cmd_prefix} --convert "%1"')

    # 4) Windows Installed Apps uninstall entry
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as uninst_key:
        winreg.SetValueEx(uninst_key, "DisplayName", 0, winreg.REG_SZ, t("app.display_name"))
        winreg.SetValueEx(uninst_key, "DisplayVersion", 0, winreg.REG_SZ, VERSION)
        winreg.SetValueEx(uninst_key, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
        winreg.SetValueEx(
            uninst_key, "UninstallString", 0, winreg.REG_SZ, f"{cmd_prefix} --uninstall"
        )
        winreg.SetValueEx(uninst_key, "DisplayIcon", 0, winreg.REG_SZ, icon_value)
        winreg.SetValueEx(uninst_key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(uninst_key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(uninst_key, "NoRepair", 0, winreg.REG_DWORD, 1)

    _notify_shell()
    return get_install_status()


def uninstall_app() -> bool:
    """Remove all context menu entries, Uninstall record, and installed executable."""
    if sys.platform != "win32":
        raise RuntimeError(t("error.windows_only"))

    _delete_tree_hkcu(EDIT_MENU_KEY)
    _delete_tree_hkcu(DOWNSIZE_MENU_KEY)
    for ext in CONVERTIBLE_EXTENSIONS:
        _delete_tree_hkcu(_convert_key_for_ext(ext))
    _delete_tree_hkcu(UNINSTALL_KEY)
    _notify_shell()

    install_dir = get_install_dir()
    if install_dir.exists():
        current_exe = Path(sys.executable).resolve()
        running_from_install_dir = is_frozen() and (
            install_dir.resolve() in current_exe.parents
        )
        if running_from_install_dir:
            cleanup_cmd = f'ping 127.0.0.1 -n 3 > nul & rmdir /s /q "{install_dir}"'
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            subprocess.Popen(
                ["cmd.exe", "/c", cleanup_cmd],
                creationflags=creation_flags,
                close_fds=True,
            )
        else:
            shutil.rmtree(install_dir, ignore_errors=True)

    return True
