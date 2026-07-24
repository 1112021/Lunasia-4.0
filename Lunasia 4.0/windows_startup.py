# -*- coding: utf-8 -*-
"""
Windows 开机自启动：当前用户「启动」文件夹中的 Lunasia.lnk（无 pywin32，用 PowerShell + WScript.Shell）。
"""
import os
import subprocess
import sys

STARTUP_LNK_NAME = "Lunasia.lnk"


def _startup_folder():
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return ""
    return os.path.join(
        appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
    )


def shortcut_path():
    return os.path.join(_startup_folder(), STARTUP_LNK_NAME)


def get_shortcut_icon_path():
    """快捷方式图标：优先 .ico，其次 png（与 app_icon 资源一致）。"""
    root = os.path.dirname(os.path.abspath(__file__))
    for name in ("icon.ico", "icon_2048.png", os.path.join("assets", "icon_2048.png")):
        p = os.path.join(root, name) if not os.path.isabs(name) else name
        if os.path.isfile(p):
            return os.path.normpath(p)
    return ""


def _resolve_launcher_exe(hide_console):
    """hide_console 时优先同目录 pythonw.exe。"""
    exe = sys.executable
    if not hide_console or sys.platform != "win32":
        return exe
    d = os.path.dirname(exe)
    base = os.path.basename(exe).lower()
    if base == "python.exe":
        w = os.path.join(d, "pythonw.exe")
        if os.path.isfile(w):
            return w
    return exe


def resolve_launch_command(hide_console, startup_mode):
    """startup_mode: 'normal' | 'tray'；hide_console 仅对 python 启动有效。"""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        work = os.path.dirname(exe)
        if startup_mode == "tray":
            return exe, "--startup-tray", work
        return exe, "", work

    main_py = os.path.abspath(sys.argv[0])
    work = os.path.dirname(main_py)
    launcher = _resolve_launcher_exe(hide_console)
    main_q = '"' + main_py.replace('"', '\\"') + '"'
    if startup_mode == "tray":
        return launcher, f"{main_q} --startup-tray", work
    return launcher, main_q, work


def _create_shortcut_via_powershell(lnk_path, target, arguments, work_dir, icon_path):
    env = os.environ.copy()
    env["LU_LNK"] = lnk_path
    env["LU_TARGET"] = target
    env["LU_ARGS"] = arguments or ""
    env["LU_WORK"] = work_dir or ""
    env["LU_ICON"] = icon_path or ""
    ps = r"""
$ErrorActionPreference = 'Stop'
$W = New-Object -ComObject WScript.Shell
$L = $W.CreateShortcut($env:LU_LNK)
$L.TargetPath = $env:LU_TARGET
$L.Arguments = $env:LU_ARGS
$L.WorkingDirectory = $env:LU_WORK
if ($env:LU_ICON -ne '') { $L.IconLocation = $env:LU_ICON + ',0' }
$L.Save()
"""
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps,
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        err = (r.stderr or "").strip() + (r.stdout or "").strip()
        return r.returncode == 0, err or None
    except Exception as e:
        return False, str(e)


def apply_windows_startup(config):
    """
    根据 config 创建或删除启动快捷方式。
    返回 dict: ok, missing_when_disabling (bool), error (str|None)
    """
    result = {"ok": True, "missing_when_disabling": False, "error": None}
    if sys.platform != "win32":
        return result

    mode = (config or {}).get("startup_mode", "off")
    if mode not in ("off", "normal", "tray"):
        mode = "off"

    folder = _startup_folder()
    lnk = shortcut_path()
    if not folder:
        result["ok"] = False
        result["error"] = "无法解析 APPDATA 启动文件夹路径"
        return result

    os.makedirs(folder, exist_ok=True)

    if mode == "off":
        if os.path.isfile(lnk):
            try:
                os.remove(lnk)
            except OSError as e:
                result["ok"] = False
                result["error"] = str(e)
        else:
            result["missing_when_disabling"] = True
        return result

    hide = bool((config or {}).get("startup_hide_console", False))
    target, args, work = resolve_launch_command(hide, mode)
    icon = get_shortcut_icon_path()
    ok, err = _create_shortcut_via_powershell(lnk, target, args, work, icon)
    if not ok:
        result["ok"] = False
        result["error"] = err or "创建快捷方式失败"
    return result
