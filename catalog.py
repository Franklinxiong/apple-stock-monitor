"""型号速查表：把用户友好的型号名/店名解析为 Part Number / R 编号。

数据来源：models_catalog.json（由脚本从 Apple 官网购买页抓取生成，
涵盖中国大陆/香港直营店在售的 iPhone、MacBook、iPad 型号）。
"""

import json
import os
import re
from typing import List, Optional

import apppath

BASE_DIR = apppath.base_dir()
CATALOG_FILE = os.path.join(BASE_DIR, "models_catalog.json")


def norm(s: str) -> str:
    """归一化：小写、去符号/连字符，词间保留一个空格。"""
    return " ".join(t for t in re.split(r"[\s\-–—·/\\.,()（）\u2011]+", (s or "").lower()) if t)


def _tokens(s: str):
    return [t for t in re.split(r"[\s\-–—·/\\.,()（）\u2011]+", (s or "").lower()) if t]


def _match_level(query: str, kw: str) -> int:
    """返回匹配级别（0=不命中；越大越精确）。

    4: 整体归一化串是关键词子串
    3: 用户词序列按顺序精确命中关键词词序列（可跳跃）
    2: 数字/中文词允许前缀放宽（如 512 -> 512gb、黑 -> 黑色）
    1: 降级切词（无空格输入，把 512gb 拆 512+gb）
    """
    qn = norm(query)
    kn = norm(kw)
    if not qn:
        return 0
    if qn in kn:
        return 4
    q_toks = _tokens(query)
    k_toks = _tokens(kn)
    if len(q_toks) > 1 and _subseq(q_toks, k_toks, allow_prefix=False):
        return 3
    if len(q_toks) > 1 and _subseq(q_toks, k_toks, allow_prefix=True):
        return 2
    # 无空格输入降级：整串切词
    flat = re.sub(r"\s+", "", qn)
    big = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", flat)
    if big and all(t in re.sub(r"\s+", "", kn) for t in big):
        return 1
    small = re.findall(r"[a-z]+|[0-9]+|[\u4e00-\u9fff]+", flat)
    if small and all(t in re.sub(r"\s+", "", kn) for t in small):
        return 1
    return 0


def _subseq(q_toks, k_toks, allow_prefix: bool) -> bool:
    """q_toks 是否按顺序出现在 k_toks 中（可跳跃）。"""
    it = iter(k_toks)
    for t in q_toks:
        for k in it:
            if k == t:
                break
            if allow_prefix and t != k and k.startswith(t) and len(k) > len(t):
                if t.isdigit() or all("\u4e00" <= c <= "\u9fff" for c in t):
                    break
        else:
            return False
    return True


def load_catalog() -> dict:
    """加载型号速查表。文件缺失或损坏时返回空表。"""
    try:
        with open(CATALOG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "cn" in data and "hk" in data:
            return data
        return {"cn": [], "hk": []}
    except (OSError, json.JSONDecodeError):
        return {"cn": [], "hk": []}


def search_models(region: str, query: str, catalog: Optional[dict] = None) -> List[dict]:
    """按型号名模糊搜索，返回按匹配度排序的候选列表。

    支持：完整 Part Number（如 MG724CH/A）、型号名关键词
    （如 "iPhone 17 512GB 黑色"、"macbook air 13 午夜"、"iPad Pro 1TB"）。
    """
    catalog = catalog or load_catalog()
    entries = catalog.get(region, [])
    q = norm(query)
    if not q:
        return []

    # 直接命中 Part Number
    for e in entries:
        if norm(e["pn"]) == q or e["pn"].lower() == query.strip().lower():
            return [e]

    # 关键词匹配（按匹配级别 + 词长排序）
    scored = []
    for e in entries:
        lvl = _match_level(query, e["keywords"])
        if lvl == 0:
            continue
        tokens = _tokens(query)
        score = lvl * 10000 + sum(len(t) for t in tokens)
        if tokens and tokens[0] in norm(e["keywords"]):
            score += 500
        scored.append((score, e))
    scored.sort(key=lambda x: (-x[0], x[1]["pn"]))
    return [e for _, e in scored]


def search_stores(stores: List[dict], query: str) -> List[dict]:
    """按店名模糊搜索店铺，返回按匹配度排序的候选列表。

    stores 为 [{storeNumber, storeName}, ...]，如 "三里屯"、"ifc"、"金沙"。
    """
    q = norm(query)
    if not q:
        return []
    scored = []
    for s in stores:
        name = norm(s.get("storeName", ""))
        if q in name:
            scored.append((len(name), s))
            continue
        tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]+", q)
        if tokens and all(t in name for t in tokens):
            scored.append((sum(len(t) for t in tokens), s))
    scored.sort(key=lambda x: (-x[0], x[1]["storeNumber"]))
    return [s for _, s in scored]


def pick_one(candidates: List[dict], kind: str, prompt: str = "") -> Optional[dict]:
    """打印候选并让用户输入编号选择；只有一个时直接返回。"""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    print(f"找到 {len(candidates)} 个匹配的{kind}：")
    for i, c in enumerate(candidates, 1):
        if kind == "型号":
            desc = f"{c['name']}（{c['pn']}）"
        else:
            desc = f"{c['storeName']}（{c['storeNumber']}）"
        print(f"  [{i}] {desc}")
    while True:
        raw = input(prompt or f"请输入编号 1-{len(candidates)}（0 取消）: ").strip()
        if raw == "0":
            return None
        try:
            idx = int(raw)
            if 1 <= idx <= len(candidates):
                return candidates[idx - 1]
        except ValueError:
            pass
        print("输入无效，请重试")
