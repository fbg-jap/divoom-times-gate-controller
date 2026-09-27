import os
from pathlib import Path
import subprocess
import sys


def set_startup(enabled, config_root):
    if os.name != "nt":
        from .platform_support import linux_startup
        linux_startup(enabled, config_root)
        return
    import winreg
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        args = [str(exe)]
    else:
        pythonw = exe.with_name("pythonw.exe")
        args = [str(pythonw if pythonw.exists() else exe), str(Path(__file__).resolve().parents[1] / "app.py")]
    args.extend(["--minimized", "--config-dir", str(config_root)])
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            winreg.SetValueEx(key, "DivoomKeeperStudio", 0, winreg.REG_SZ, subprocess.list2cmdline(args))
        else:
            try:
                winreg.DeleteValue(key, "DivoomKeeperStudio")
            except FileNotFoundError:
                pass
