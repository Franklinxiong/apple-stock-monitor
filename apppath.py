"""打包感知的路径解析：兼容源码运行 / py2app / PyInstaller。

- base_dir(): 只读数据目录（源码运行=项目根目录；.app 内=Resources/_MEIPASS）
- writable_dir(): 可写数据目录（源码运行=项目根目录；.app 内=~/Library/Application Support/AppleStockMonitor）
"""

import os
import sys

_APP_SUPPORT_DIR = "AppleStockMonitor"


def base_dir() -> str:
    """只读数据目录。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)  # PyInstaller
        if meipass:
            return meipass
        exe_dir = os.path.dirname(sys.executable)
        resources = os.path.join(os.path.dirname(exe_dir), "Resources")  # py2app
        if os.path.isdir(resources):
            return resources
        return exe_dir
    return os.path.dirname(os.path.abspath(__file__))


def writable_dir() -> str:
    """可写数据目录（自动创建）。"""
    if getattr(sys, "frozen", False):
        home = os.path.expanduser("~")
        path = os.path.join(home, "Library", "Application Support", _APP_SUPPORT_DIR)
        os.makedirs(path, exist_ok=True)
        return path
    return os.path.dirname(os.path.abspath(__file__))
