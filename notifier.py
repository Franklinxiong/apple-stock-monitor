"""通知模块：macOS 桌面通知（默认，经 iCloud 镜像同步到 iPhone）+ 可选 Bark 推送。"""

import logging
import shutil
import subprocess

import requests

logger = logging.getLogger(__name__)

BARK_API_BASE = "https://api.day.app"


def _run_osascript(script: str) -> bool:
    if shutil.which("osascript") is None:
        logger.warning("未找到 osascript，跳过桌面通知")
        return False
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return True
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("桌面通知执行失败: %s", exc)
        return False


def notify_desktop(title: str, message: str) -> bool:
    """macOS 原生通知。需要终端 App 具备通知权限（首次会弹授权）。"""
    safe_title = title.replace('"', "'")
    safe_message = message.replace('"', "'")
    script = f'display notification "{safe_message}" with title "{safe_title}"'
    return _run_osascript(script)


def notify_bark(key: str, title: str, message: str, timeout: int = 10) -> bool:
    """通过 Bark 推送手机通知。key 为空或推送失败返回 False。"""
    if not key:
        return False
    url = f"{BARK_API_BASE}/{key}/{requests.utils.quote(title)}/{requests.utils.quote(message)}"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return True
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Bark 推送失败: %s", exc)
        return False


def notify_all(title: str, message: str, bark_key: str = "") -> None:
    """桌面通知 + 可选 Bark。任一失败均不影响另一路。"""
    ok_desktop = notify_desktop(title, message)
    ok_bark = True
    if bark_key:
        ok_bark = notify_bark(bark_key, title, message)
    if ok_desktop and ok_bark:
        logger.info("通知已发送: %s - %s", title, message)
    else:
        logger.warning("部分通知发送失败: desktop=%s bark=%s", ok_desktop, ok_bark)
