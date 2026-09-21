"""调用 Apple 官网 pickup-message 接口拉取库存原始数据。"""

import json
import logging
import os
import random
import re
import time
from typing import List, Optional

import requests

import apppath

from models import REGION_API_URLS, REGION_STORELIST_URLS, REGION_LOCALES

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
STORES_CACHE_TTL = 24 * 3600  # 店铺列表缓存 24 小时


class FetchError(Exception):
    """拉取失败。"""


class FetchRetryableError(FetchError):
    """可重试的网络/临时错误。"""


def _build_url(region: str, models: List[str], store_id: str) -> str:
    base = REGION_API_URLS[region]
    params = ["pl=true", "mts.0=regular"]
    for i, m in enumerate(models):
        params.append(f"parts.{i}={requests.utils.quote(m)}")
    params.append(f"store={requests.utils.quote(store_id)}")
    return f"{base}?{'&'.join(params)}"


def fetch_stock_json(
    region: str,
    models: List[str],
    store_id: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """拉取指定地区 + 型号列表在指定店铺的库存 JSON。失败抛 FetchError。"""
    url = _build_url(region, models, store_id)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout as exc:
        raise FetchRetryableError(f"请求超时: {url}") from exc
    except requests.exceptions.ConnectionError as exc:
        raise FetchRetryableError(f"网络连接失败: {url}") from exc
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        raise FetchError(f"HTTP {status}: {url}") from exc
    except ValueError as exc:
        raise FetchError(f"返回非 JSON 数据: {url}") from exc


# ---------- 店铺列表 ----------


def _stores_cache_path(region: str) -> str:
    return os.path.join(apppath.writable_dir(), f"stores_cache_{region}.json")


def _load_stores_cache(region: str) -> Optional[List[dict]]:
    path = _stores_cache_path(region)
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("region") != region:
            return None
        if time.time() - data.get("fetched_at", 0) > STORES_CACHE_TTL:
            return None
        return data.get("stores")
    except (OSError, json.JSONDecodeError):
        return None


def _save_stores_cache(region: str, stores: List[dict]) -> None:
    path = _stores_cache_path(region)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"region": region, "fetched_at": time.time(), "stores": stores},
                f,
                ensure_ascii=False,
                indent=2,
            )
    except OSError as exc:
        logger.warning("店铺缓存写入失败: %s", exc)


def fetch_stores(region: str, use_cache: bool = True, timeout: int = DEFAULT_TIMEOUT) -> List[dict]:
    """获取某地区全部直营店列表（带 24h 缓存）。

    从 Apple 零售店列表页面内嵌的 storeList JSON 解析。
    返回 [{storeNumber, storeName}, ...]；失败抛 FetchError。
    """
    if use_cache:
        cached = _load_stores_cache(region)
        if cached is not None:
            return cached

    url = REGION_STORELIST_URLS[region]
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        html = resp.text
    except requests.exceptions.Timeout as exc:
        raise FetchRetryableError(f"店铺列表请求超时: {url}") from exc
    except requests.exceptions.ConnectionError as exc:
        raise FetchRetryableError(f"店铺列表网络失败: {url}") from exc
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        raise FetchError(f"店铺列表 HTTP {status}: {url}") from exc

    stores = _extract_stores_from_html(html, REGION_LOCALES[region])
    if not stores:
        raise FetchError(f"未能在 {region} 零售店页面中解析到店铺列表")
    _save_stores_cache(region, stores)
    return stores


def _extract_stores_from_html(html: str, locale: str) -> List[dict]:
    """从零售店列表页内嵌 JSON 提取指定 locale 的店铺。"""
    m = re.search(r'"storeList"\s*:\s*\[', html)
    if not m:
        return []
    start = m.end() - 1  # '[' 位置
    try:
        decoder = json.JSONDecoder()
        store_list, _ = decoder.raw_decode(html[start:])
    except json.JSONDecodeError:
        return []

    stores = []
    for entry in store_list:
        if not isinstance(entry, dict):
            continue
        if entry.get("locale") != locale and entry.get("calledLocale") != locale:
            continue
        states = entry.get("states") or entry.get("state") or []
        for st in states:
            if not isinstance(st, dict):
                continue
            if "store" in st:  # hasStates=true 时 state 元素含 store 数组
                for s in st["store"]:
                    if isinstance(s, dict) and s.get("id"):
                        stores.append({"storeNumber": s["id"], "storeName": s.get("name", "")})
            elif st.get("id"):  # hasStates=false 时 states 直接是 store
                stores.append({"storeNumber": st["id"], "storeName": st.get("name", "")})
    # 去重
    seen = set()
    result = []
    for s in stores:
        if s["storeNumber"] not in seen:
            seen.add(s["storeNumber"])
            result.append(s)
    return result


def default_store(region: str) -> Optional[str]:
    """取该地区第一个店铺 ID，用于型号校验。"""
    try:
        stores = fetch_stores(region)
        return stores[0]["storeNumber"] if stores else None
    except FetchError:
        return None


def backoff_delay(attempt: int) -> float:
    """指数退避：30s -> 1min -> 2min -> 4min（上限 4min）。"""
    return min(30 * (2 ** (attempt - 1)), 240)


def polite_sleep() -> None:
    """请求间随机小延迟，降低限流风险。"""
    time.sleep(random.uniform(0.8, 1.5))
