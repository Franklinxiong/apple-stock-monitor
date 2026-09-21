"""Apple 商店库存监控 CLI 入口。

用法:
  python monitor.py list-stores --region cn
  python monitor.py add --region cn --name "iPhone 17 512GB 黑色" [--store "三里屯"]
  python monitor.py add --region cn --model MG724CH/A [--store R320]   # 旧用法仍兼容
  python monitor.py add --region hk                                     # 交互式引导
  python monitor.py remove --region cn --model MG724CH/A
  python monitor.py list
  python monitor.py run

型号名与店名支持模糊搜索：不知道 Part Number / R 编号也能直接添加。
"""

import argparse
import json
import logging
import os
import random
import sys
import time
from typing import Dict, List, Optional, Tuple

import catalog
import fetcher
import parser
from models import (
    REGION_CN,
    REGION_HK,
    REGION_NAMES,
    WatchItem,
    is_valid_part_number,
)
from notifier import notify_all
from state import StateStore

DEFAULT_CONFIG_FILE = "config.json"
DEFAULT_STATE_FILE = "state.json"
DEFAULT_POLL_INTERVAL_MINUTES = 10

logger = logging.getLogger("monitor")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def config_path() -> str:
    return os.path.join(BASE_DIR, DEFAULT_CONFIG_FILE)


def state_path() -> str:
    return os.path.join(BASE_DIR, DEFAULT_STATE_FILE)


# ---------- 配置读写 ----------


def load_config(path: str = "") -> dict:
    path = path or config_path()
    if not os.path.exists(path):
        return {"poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES, "bark": {"enabled": False, "key": ""}, "watchlist": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("配置读取失败: %s", exc)
        sys.exit(1)


def save_config(cfg: dict, path: str = "") -> None:
    path = path or config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.error("配置写入失败: %s", exc)
        sys.exit(1)


def get_watchlist(cfg: dict) -> List[WatchItem]:
    return [WatchItem.from_dict(d) for d in cfg.get("watchlist", [])]


# ---------- CLI 命令 ----------


def cmd_list_stores(args) -> int:
    region = args.region
    if region not in REGION_NAMES:
        logger.error("不支持的地区: %s（可选 %s / %s）", region, REGION_CN, REGION_HK)
        return 1
    try:
        stores = fetcher.fetch_stores(region)
    except fetcher.FetchError as exc:
        logger.error("获取店铺列表失败: %s", exc)
        return 1
    print(f"=== {REGION_NAMES[region]} 直营店列表（{len(stores)} 家）===")
    for s in sorted(stores, key=lambda x: x["storeNumber"]):
        print(f"  {s['storeNumber']}  {s['storeName']}")
    print("\n添加监控时可用 --store <ID> 限定店铺（可多个，不传则监控全部店铺）")
    return 0


def _resolve_model(args, region: str) -> Optional[Tuple[str, str]]:
    """解析型号，返回 (part_number, label)。找不到返回 None。"""
    catalog_data = catalog.load_catalog()

    # 1) --model 直传 Part Number（兼容旧用法）
    if args.model:
        model = args.model.strip()
        if not is_valid_part_number(model):
            logger.error("型号格式不正确，应为 Part Number 形式（如 MG724CH/A），或用 --name 输入型号名")
            return None
        # 尝试从速查表补全中文 label
        for e in catalog_data.get(region, []):
            if e["pn"].lower() == model.lower():
                return model, e["name"]
        return model, args.label or ""

    # 2) --name 或交互输入型号名
    query = (args.name or "").strip()
    if not query:
        query = input(f"请输入要监控的型号名（如 iPhone 17 512GB 黑色，留空退出）: ").strip()
        if not query:
            return None
    hits = catalog.search_models(region, query, catalog_data)
    if not hits:
        logger.error(
            "在 %s 速查表中未找到与「%s」匹配的型号。"
            "可尝试更精确的名称（如包含容量/颜色），或直接 --model <Part Number>。",
            REGION_NAMES[region], query,
        )
        return None
    chosen = catalog.pick_one(hits, "型号")
    if chosen is None:
        return None
    return chosen["pn"], chosen["name"]


def _resolve_stores(args, region: str) -> List[str]:
    """解析店铺 ID 列表（R 编号）。空列表 = 全部店铺。"""
    raw_stores = list(args.store or [])
    if not raw_stores:
        return []
    # 已直接给出 R 编号的保留
    r_ids = [s.strip() for s in raw_stores if s.strip().upper().startswith("R")]
    # 其余按店名模糊搜索
    name_queries = [s.strip() for s in raw_stores if not s.strip().upper().startswith("R")]
    if not name_queries:
        return r_ids
    try:
        stores = fetcher.fetch_stores(region)
    except fetcher.FetchError as exc:
        logger.error("获取店铺列表失败: %s", exc)
        return r_ids
    for q in name_queries:
        hits = catalog.search_stores(stores, q)
        if not hits:
            logger.warning("未找到店名包含「%s」的店铺，已跳过", q)
            continue
        chosen = catalog.pick_one(hits, "店铺")
        if chosen is not None and chosen["storeNumber"] not in r_ids:
            r_ids.append(chosen["storeNumber"])
    return r_ids


def cmd_add(args) -> int:
    region = args.region
    if region not in REGION_NAMES:
        logger.error("不支持的地区: %s（可选 %s / %s）", region, REGION_CN, REGION_HK)
        return 1

    resolved = _resolve_model(args, region)
    if resolved is None:
        return 1
    model, auto_label = resolved
    label = args.label or auto_label

    cfg = load_config()
    watchlist = get_watchlist(cfg)
    if any(w.region == region and w.model == model for w in watchlist):
        logger.error("该型号已存在监控列表: %s %s", region, model)
        return 1

    store_ids = _resolve_stores(args, region)

    # 校验型号有效：用指定店铺或该地区第一个店铺试查一次
    try:
        sid = store_ids[0] if store_ids else fetcher.default_store(region)
        if not sid:
            logger.error("无法获取 %s 店铺信息，校验失败", REGION_NAMES[region])
            return 1
        data = fetcher.fetch_stock_json(region, [model], sid)
        parser.parse_stock_json(data, region, [model])
    except fetcher.FetchError as exc:
        logger.error("型号校验失败（网络或型号无效）: %s", exc)
        return 1

    item = WatchItem(region=region, model=model, label=label, stores=store_ids)
    watchlist.append(item)
    cfg["watchlist"] = [w.to_dict() for w in watchlist]
    save_config(cfg)
    scope = "全部店铺" if not item.stores else f"{len(item.stores)} 家店铺: {', '.join(item.stores)}"
    print(f"已添加监控: [{REGION_NAMES[region]}] {label}（{model}，{scope}）")
    print("运行 `python monitor.py run` 开始监控")
    return 0


def cmd_remove(args) -> int:
    region = args.region
    cfg = load_config()
    watchlist = get_watchlist(cfg)
    if args.model:
        model = args.model.strip()
        targets = [w for w in watchlist if w.region == region and w.model == model]
    elif args.name:
        model = args.name.strip()
        targets = [w for w in watchlist if w.region == region and model in (w.label or w.model)]
    else:
        logger.error("请指定要移除的型号：--model <Part Number> 或 --name <型号名>")
        return 1
    if not targets:
        logger.error("未找到该监控项: %s %s", region, model)
        return 1
    keys = {(w.region, w.model) for w in targets}
    watchlist = [w for w in watchlist if (w.region, w.model) not in keys]
    cfg["watchlist"] = [w.to_dict() for w in watchlist]
    save_config(cfg)
    for w in targets:
        label = w.label or w.model
        print(f"已移除监控: [{REGION_NAMES[w.region]}] {label}（{w.model}）")
    return 0


def cmd_list(args) -> int:
    cfg = load_config()
    watchlist = get_watchlist(cfg)
    if not watchlist:
        print("当前监控列表为空。可用 `add` 添加型号。")
        return 0
    print(f"=== 监控列表（{len(watchlist)} 项，轮询间隔 {cfg.get('poll_interval_minutes', DEFAULT_POLL_INTERVAL_MINUTES)} 分钟）===")
    for w in watchlist:
        scope = "全部店铺" if not w.stores else ", ".join(w.stores)
        label = f"（{w.label}）" if w.label else ""
        print(f"  [{REGION_NAMES[w.region]}] {w.model} {label} -> {scope}")
    return 0


def cmd_run(args) -> int:
    cfg = load_config()
    watchlist = get_watchlist(cfg)
    if not watchlist:
        logger.error("监控列表为空，请先用 add 添加型号")
        return 1
    interval_min = int(cfg.get("poll_interval_minutes", DEFAULT_POLL_INTERVAL_MINUTES))
    bark_key = cfg.get("bark", {}).get("key", "") if cfg.get("bark", {}).get("enabled") else ""
    state = StateStore(state_path())
    logger.info(
        "启动监控: %d 个型号，每 %d 分钟轮询一次，Bark=%s",
        len(watchlist),
        interval_min,
        "开启" if bark_key else "关闭（仅桌面通知）",
    )
    consecutive_failures = 0
    while True:
        try:
            changed = run_once(watchlist, state, bark_key)
            if changed:
                state.save()
            consecutive_failures = 0
        except fetcher.FetchError as exc:
            consecutive_failures += 1
            delay = fetcher.backoff_delay(consecutive_failures)
            logger.error("本轮拉取失败（第 %d 次）: %s，%d 秒后重试", consecutive_failures, exc, int(delay))
            time.sleep(delay)
            continue
        logger.info("本轮完成，%d 秒后下一轮", interval_min * 60)
        time.sleep(interval_min * 60 + random.uniform(0, 30))


def run_once(watchlist: List[WatchItem], state: StateStore, bark_key: str = "") -> bool:
    """执行一轮检查。返回是否有状态变化（触发过通知）。"""
    # 1. 展开监控范围: (region, store) -> {model: item}
    groups: Dict[Tuple[str, str], Dict[str, WatchItem]] = {}
    for item in watchlist:
        if item.stores:
            store_ids = list(item.stores)
        else:
            try:
                store_ids = [s["storeNumber"] for s in fetcher.fetch_stores(item.region)]
            except fetcher.FetchError as exc:
                logger.warning("[%s] 获取全部店铺失败: %s", item.region, exc)
                continue
        for sid in store_ids:
            groups.setdefault((item.region, sid), {})[item.model] = item

    if not groups:
        logger.warning("本轮没有可查询的监控目标")
        return False

    changed = False
    first = True
    for (region, store_id), models_map in groups.items():
        if not first:
            fetcher.polite_sleep()
        first = False
        models = list(models_map.keys())
        try:
            data = fetcher.fetch_stock_json(region, models, store_id)
            results = parser.parse_stock_json(data, region, models)
        except fetcher.FetchError as exc:
            logger.warning("[%s/%s] 拉取失败: %s", region, store_id, exc)
            continue
        except parser.ParseError as exc:
            logger.error("[%s/%s] 解析失败: %s", region, store_id, exc)
            continue
        by_model = {r.model: r for r in results}
        for model, result in by_model.items():
            item = models_map[model]
            for store in result.stores:
                if store.store_id != store_id:
                    continue
                item_key = item.key
                was = state.was_available(item_key, store.store_id)
                state.set_store_name(item_key, store.store_id, store.store_name)
                state.set_available(item_key, store.store_id, store.available)
                if store.available and not was:
                    changed = True
                    label = item.label or item.model
                    title = f"🎉 {REGION_NAMES[item.region]} {label} 有货了"
                    message = f"{store.store_name}（{store.store_id}）可自提，快去下单"
                    logger.info("检测到有货: %s %s %s", item.region, item.model, store.store_name)
                    notify_all(title, message, bark_key)
                elif not store.available and was:
                    logger.info("状态回落为无货: %s %s %s", item.region, item.model, store.store_name)
    return changed


# ---------- 入口 ----------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Apple 商店库存监控")
    p.add_argument("--verbose", action="store_true", help="输出调试日志")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("list-stores", help="列出地区直营店")
    sp.add_argument("--region", required=True, choices=[REGION_CN, REGION_HK])
    sp.set_defaults(func=cmd_list_stores)

    sp = sub.add_parser("add", help="添加监控型号（支持型号名/店名模糊搜索）")
    sp.add_argument("--region", required=True, choices=[REGION_CN, REGION_HK])
    sp.add_argument("--model", default="", help="Part Number（可选），如 MG724CH/A；不传则按 --name 搜索")
    sp.add_argument("--name", default="", help="型号名关键词（可选），如 \"iPhone 17 512GB 黑色\"")
    sp.add_argument("--label", default="", help="备注名称（覆盖自动生成的名称，用于通知文案）")
    sp.add_argument("--store", action="append", default=[], help="店铺 ID 或店名关键词，可多次传，如 R320 或 三里屯")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("remove", help="移除监控型号")
    sp.add_argument("--region", required=True, choices=[REGION_CN, REGION_HK])
    sp.add_argument("--model", default="", help="Part Number")
    sp.add_argument("--name", default="", help="型号名关键词（匹配 label 或 Part Number）")
    sp.set_defaults(func=cmd_remove)

    sp = sub.add_parser("list", help="查看监控列表")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("run", help="启动监控（前台常驻）")
    sp.set_defaults(func=cmd_run)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
