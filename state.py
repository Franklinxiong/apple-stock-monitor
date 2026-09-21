"""状态持久化：记录每个监控项（region+model+store）的上次库存状态，用于去重提醒。"""

import json
import logging
import os
from typing import Dict, Set

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = "state.json"


class StateStore:
    """读写 state.json，管理库存状态转换记忆。"""

    def __init__(self, path: str = DEFAULT_STATE_FILE):
        self.path = path
        self._data: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._data = loaded
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("状态文件读取失败，忽略并以空状态启动: %s", exc)

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.error("状态文件写入失败: %s", exc)

    def was_available(self, item_key: str, store_id: str) -> bool:
        return bool(self._data.get(item_key, {}).get(store_id, {}).get("available", False))

    def set_available(self, item_key: str, store_id: str, available: bool) -> None:
        store_state = self._data.setdefault(item_key, {}).setdefault(store_id, {})
        store_state["available"] = available

    def store_name(self, item_key: str, store_id: str) -> str:
        return str(self._data.get(item_key, {}).get(store_id, {}).get("name", ""))

    def set_store_name(self, item_key: str, store_id: str, name: str) -> None:
        store_state = self._data.setdefault(item_key, {}).setdefault(store_id, {})
        store_state["name"] = name

    def all_item_keys(self) -> Set[str]:
        return set(self._data.keys())
