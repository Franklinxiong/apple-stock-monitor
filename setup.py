"""py2app 打包配置：将 GUI 封装为 macOS .app（AppleStockMonitor）。

用法:
  .venv/bin/python setup.py py2app

产物: dist/AppleStockMonitor.app
"""

import sys

from setuptools import setup

if sys.platform != "darwin":
    raise SystemExit("py2app 仅支持 macOS 打包")

APP = ["gui.py"]
APP_NAME = "AppleStockMonitor"

# 运行所需的静态数据文件（打包进 Contents/Resources）
DATA_FILES = [
    "config.json",
    "models_catalog.json",
    "stores_cache_cn.json",
    "stores_cache_hk.json",
]

OPTIONS = {
    "argv_emulation": False,
    "packages": ["PySide6"],
    "plist": {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": "AppleStockMonitor",
        "CFBundleIdentifier": "com.franklinxiong.applestockmonitor",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    },
}

setup(
    name=APP_NAME,
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
