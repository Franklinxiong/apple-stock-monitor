"""GUI 纯逻辑单测：不依赖 Qt 窗口，只测数据层逻辑。

覆盖：统计计数、型号选择状态逻辑、门店排序、无货→有货变化检测。
"""

from collections import namedtuple

from models import StoreStock
from state import StateStore

from gui import (
    STATUS_AVAILABLE,
    STATUS_UNAVAILABLE,
    STATUS_UPCOMING,
    apply_model_selection,
    classify_status,
    collect_available_changes,
    count_stats,
    current_item_for_region,
    sort_stores,
)

_Result = namedtuple("_Result", ["stores"])


def _stock(store_id, name, available, display):
    return StoreStock(
        store_id=store_id,
        store_name=name,
        region="cn",
        model="MQ0X3CH/A",
        available=available,
        pickup_display=display,
    )


# ---------- 状态分类 ----------


def test_classify_status():
    assert classify_status(_stock("R1", "A", True, "available")) == STATUS_AVAILABLE
    assert classify_status(_stock("R2", "B", False, "unavailable")) == STATUS_UNAVAILABLE
    assert classify_status(_stock("R3", "C", False, "not_listed")) == STATUS_UNAVAILABLE
    assert classify_status(_stock("R4", "D", False, "")) == STATUS_UNAVAILABLE
    assert classify_status(_stock("R5", "E", False, "coming soon")) == STATUS_UPCOMING
    assert classify_status(_stock("R6", "F", False, "UNKNOWN")) == STATUS_UPCOMING


# ---------- 统计计数 ----------


def test_count_stats():
    stores = [
        _stock("R1", "A", True, "available"),
        _stock("R2", "B", False, "unavailable"),
        _stock("R3", "C", False, "not_listed"),
        _stock("R4", "D", False, "coming soon"),
        _stock("R5", "E", True, "available"),
    ]
    assert count_stats(stores) == (2, 2, 1)


def test_count_stats_empty():
    assert count_stats([]) == (0, 0, 0)


# ---------- 门店排序（有货 → 即将到货 → 无货） ----------


def test_sort_stores_order():
    stores = [
        _stock("R1", "无货A", False, "unavailable"),
        _stock("R2", "即将B", False, "coming soon"),
        _stock("R3", "有货C", True, "available"),
        _stock("R4", "无货D", False, "not_listed"),
        _stock("R5", "有货E", True, "available"),
    ]
    sorted_stores = sort_stores(stores)
    assert [classify_status(s) for s in sorted_stores] == [
        STATUS_AVAILABLE,
        STATUS_AVAILABLE,
        STATUS_UPCOMING,
        STATUS_UNAVAILABLE,
        STATUS_UNAVAILABLE,
    ]
    # 组内保持原顺序（稳定排序）
    assert [s.store_name for s in sorted_stores] == ["有货C", "有货E", "即将B", "无货A", "无货D"]


def test_sort_stores_empty():
    assert sort_stores([]) == []


# ---------- 型号选择状态逻辑 ----------


def test_apply_model_selection_new_region():
    cfg = {"watchlist": [{"region": "hk", "model": "MJRX4ZA/A", "label": "旧", "stores": []}]}
    cfg = apply_model_selection(cfg, "cn", {"pn": "MJYH4CH/A", "name": "iPhone 18 Pro Max 1TB 勃艮第酒红色"})
    watchlist = cfg["watchlist"]
    assert len(watchlist) == 2
    assert watchlist[0]["region"] == "cn"
    assert watchlist[0]["model"] == "MJYH4CH/A"
    assert watchlist[0]["label"] == "iPhone 18 Pro Max 1TB 勃艮第酒红色"
    assert watchlist[0]["stores"] == []


def test_apply_model_selection_existing_moves_to_front():
    cfg = {
        "watchlist": [
            {"region": "cn", "model": "AAA", "label": "A", "stores": []},
            {"region": "cn", "model": "MJYH4CH/A", "label": "旧备注", "stores": ["R320"]},
        ]
    }
    cfg = apply_model_selection(cfg, "cn", {"pn": "MJYH4CH/A", "name": "新备注"})
    watchlist = cfg["watchlist"]
    assert len(watchlist) == 2  # 已存在则不新增重复项
    assert watchlist[0]["model"] == "MJYH4CH/A"
    assert watchlist[0]["label"] == "新备注"
    assert watchlist[0]["stores"] == ["R320"]  # 原 stores 保留


def test_apply_model_selection_empty_watchlist():
    cfg = {"watchlist": []}
    cfg = apply_model_selection(cfg, "hk", {"pn": "MJRX4ZA/A", "name": "iPhone 18 Pro 512GB 冰川色"})
    assert len(cfg["watchlist"]) == 1
    assert cfg["watchlist"][0]["region"] == "hk"
    assert cfg["watchlist"][0]["model"] == "MJRX4ZA/A"


def test_current_item_for_region():
    cfg = {"watchlist": [{"region": "hk", "model": "H1"}, {"region": "cn", "model": "C1"}]}
    assert current_item_for_region(cfg, "cn")["model"] == "C1"
    assert current_item_for_region(cfg, "hk")["model"] == "H1"
    assert current_item_for_region(cfg, "jp") is None
    assert current_item_for_region({"watchlist": []}, "cn") is None


# ---------- 无货→有货变化检测（通知触发依据） ----------


def test_collect_available_changes(tmp_path):
    state = StateStore(str(tmp_path / "state.json"))
    item_key = "cn|MQ0X3CH/A"

    # 首次：无历史记录，按"无货"基线判断，有货店触发变化
    results = [_Result(stores=[_stock("R1", "A", True, "available"), _stock("R2", "B", False, "unavailable")])]
    changes = collect_available_changes(results, state, item_key)
    assert [s.store_id for s in changes] == ["R1"]

    # 第二次：状态未变，无变化
    results2 = [_Result(stores=[_stock("R1", "A", True, "available"), _stock("R2", "B", False, "unavailable")])]
    assert collect_available_changes(results2, state, item_key) == []

    # 回落无货后再变有货 → 再次触发
    collect_available_changes([_Result(stores=[_stock("R1", "A", False, "unavailable")])], state, item_key)
    changes4 = collect_available_changes([_Result(stores=[_stock("R1", "A", True, "available")])], state, item_key)
    assert [s.store_id for s in changes4] == ["R1"]
