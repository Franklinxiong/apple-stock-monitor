"""Apple 商店库存监控 GUI（PySide6 科技感 Dashboard，方案 B）。

用法:
  cd ~/Desktop/apple-stock-monitor
  python gui.py

复用现有数据层模块（fetcher / parser / catalog / models / notifier / state），
CLI（monitor.py）行为完全不变。

模块顶层纯逻辑函数（classify_status / count_stats / sort_stores /
current_item_for_region / apply_model_selection / collect_available_changes）
不依赖 Qt，可独立单测（见 tests/test_gui_logic.py）。
"""

import json
import os
import shutil
import sys
from datetime import datetime
from typing import List, Optional, Tuple

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import catalog
import fetcher
import notifier
import parser
from models import REGION_CN, REGION_HK, REGION_NAMES, StoreStock
from state import StateStore

import apppath

APP_BASE = apppath.base_dir()
APP_DATA = apppath.writable_dir()
DEFAULT_CONFIG_FILE = os.path.join(APP_DATA, "config.json")
DEFAULT_STATE_FILE = os.path.join(APP_DATA, "state.json")
DEFAULT_POLL_INTERVAL_MINUTES = 10

# ---------- 纯逻辑（不依赖 Qt，可单测） ----------

STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"
STATUS_UPCOMING = "upcoming"

_STATUS_ORDER = {STATUS_AVAILABLE: 0, STATUS_UPCOMING: 1, STATUS_UNAVAILABLE: 2}
_STATUS_LABELS = {
    STATUS_AVAILABLE: "有货",
    STATUS_UNAVAILABLE: "无货",
    STATUS_UPCOMING: "即将到货",
}


def classify_status(store: StoreStock) -> str:
    """将单个店铺库存归为 available / upcoming / unavailable 三类。

    - 可自提（available=True）→ available
    - unavailable / not_listed / 空显示 → unavailable（无货/未上架）
    - 其他显示值（coming soon 等）→ upcoming（即将到货）
    """
    if store.available:
        return STATUS_AVAILABLE
    disp = (store.pickup_display or "").strip().lower()
    if disp in ("", "unavailable", "not_listed"):
        return STATUS_UNAVAILABLE
    return STATUS_UPCOMING


def count_stats(stores: List[StoreStock]) -> Tuple[int, int, int]:
    """统计 (有货, 无货, 即将到货) 数量。"""
    available = unavailable = upcoming = 0
    for s in stores:
        status = classify_status(s)
        if status == STATUS_AVAILABLE:
            available += 1
        elif status == STATUS_UNAVAILABLE:
            unavailable += 1
        else:
            upcoming += 1
    return available, unavailable, upcoming


def sort_stores(stores: List[StoreStock]) -> List[StoreStock]:
    """按 有货 → 即将到货 → 无货 稳定排序（组内保持原顺序）。"""
    return sorted(stores, key=lambda s: _STATUS_ORDER[classify_status(s)])


def current_item_for_region(cfg: dict, region: str) -> Optional[dict]:
    """取某地区当前监控型号（watchlist 中该地区第一条记录）。"""
    for w in cfg.get("watchlist", []):
        if w.get("region") == region:
            return w
    return None


def apply_model_selection(cfg: dict, region: str, entry: dict) -> dict:
    """选中 catalog 型号（{pn, name}）后更新 watchlist。

    - 该地区已配置该型号 → 保留原记录（stores 等），移到首位完成切换；
    - 否则 → 新增一条记录到首位。
    返回更新后的 cfg。
    """
    pn = entry["pn"]
    label = entry.get("name") or pn
    watchlist = cfg.setdefault("watchlist", [])
    for i, w in enumerate(watchlist):
        if w.get("region") == region and w.get("model") == pn:
            item = watchlist.pop(i)
            if label:
                item["label"] = label
            watchlist.insert(0, item)
            return cfg
    watchlist.insert(0, {"region": region, "model": pn, "label": label, "stores": []})
    return cfg


def collect_available_changes(results, state_store: StateStore, item_key: str) -> List[StoreStock]:
    """记录本次库存状态，返回「无货→有货」的店铺列表（不在此处发通知）。"""
    changes: List[StoreStock] = []
    for result in results:
        for store in result.stores:
            was = state_store.was_available(item_key, store.store_id)
            state_store.set_store_name(item_key, store.store_id, store.store_name)
            state_store.set_available(item_key, store.store_id, store.available)
            if store.available and not was:
                changes.append(store)
    return changes


# ---------- 配置读写 ----------


def load_config() -> dict:
    """读取 config.json，缺失字段按默认值兜底（gui.notify_enabled 默认 true）。"""
    default = {
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
        "bark": {"enabled": False, "key": ""},
        "gui": {"notify_enabled": True},
        "watchlist": [],
    }
    if not os.path.exists(DEFAULT_CONFIG_FILE) and APP_BASE != APP_DATA:
        _template = os.path.join(APP_BASE, "config.json")
        if os.path.exists(_template):
            try:
                shutil.copy(_template, DEFAULT_CONFIG_FILE)
            except OSError:
                pass
    try:
        with open(DEFAULT_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            return default
        cfg.setdefault("poll_interval_minutes", DEFAULT_POLL_INTERVAL_MINUTES)
        cfg.setdefault("bark", {"enabled": False, "key": ""})
        cfg.setdefault("gui", {})
        cfg["gui"].setdefault("notify_enabled", True)
        cfg.setdefault("watchlist", [])
        return cfg
    except (OSError, json.JSONDecodeError):
        return default


def save_config(cfg: dict) -> None:
    try:
        with open(DEFAULT_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---------- QSS 样式（方案 B · 科技感 Dashboard） ----------

QSS = """
QWidget {
    color: #e8eaf0;
    font-family: "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}
QMainWindow {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0d0f1a, stop:1 #1a1f2e);
}
QDialog {
    background: #12151f;
}
QLabel#titleNeon {
    color: #4cc2ff;
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 2px;
}
QLabel#titleMono {
    color: #e8eaf0;
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 2px;
}
QPushButton {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 13px;
    padding: 6px 16px;
    color: #e8eaf0;
    font-size: 13px;
}
QPushButton:hover {
    background: rgba(255,255,255,0.11);
}
QPushButton:pressed {
    background: rgba(255,255,255,0.04);
}
QPushButton#regionBtn {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px;
    padding: 5px 18px;
    color: #8b90a3;
    font-size: 13px;
}
QPushButton#regionBtn:hover {
    color: #e8eaf0;
    border-color: rgba(76,194,255,0.5);
}
QPushButton#regionBtn:checked {
    color: #4cc2ff;
    border: 1px solid #4cc2ff;
    background: rgba(76,194,255,0.12);
}
QPushButton#ghostBtn {
    background: transparent;
    border: 1px solid rgba(76,194,255,0.45);
    border-radius: 13px;
    color: #4cc2ff;
    padding: 5px 16px;
}
QPushButton#ghostBtn:hover {
    background: rgba(76,194,255,0.12);
    border-color: #4cc2ff;
}
QPushButton#refreshBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4cc2ff, stop:1 #2a7fff);
    border: none;
    border-radius: 13px;
    color: #0d0f1a;
    font-weight: 700;
    padding: 6px 22px;
}
QPushButton#refreshBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6bd0ff, stop:1 #4a95ff);
}
QPushButton#refreshBtn:disabled {
    background: rgba(255,255,255,0.10);
    color: #8b90a3;
}
QPushButton#switchBtn {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 13px;
    color: #8b90a3;
    padding: 5px 18px;
    font-size: 12px;
}
QPushButton#switchBtn:checked {
    background: rgba(48,209,88,0.15);
    border: 1px solid #30d158;
    color: #30d158;
}
QFrame#card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 10px;
}
QFrame#statCard {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 10px;
}
QLabel#statAvail {
    color: #30d158;
    font-size: 30px;
    font-weight: 800;
}
QLabel#statUnavail {
    color: #ff453a;
    font-size: 30px;
    font-weight: 800;
}
QLabel#statUpcoming {
    color: #ffd60a;
    font-size: 30px;
    font-weight: 800;
}
QLabel#statCaption {
    color: #8b90a3;
    font-size: 12px;
}
QLabel#statusRunning {
    color: #30d158;
    font-size: 13px;
    font-weight: 600;
}
QLabel#statusQuery {
    color: #ffd60a;
    font-size: 13px;
    font-weight: 600;
}
QLabel#statusStopped {
    color: #8b90a3;
    font-size: 13px;
    font-weight: 600;
}
QListWidget#storeList {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget#storeList::item {
    background: transparent;
    border: none;
}
QFrame#storeRow {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
}
QFrame#storeRow QLabel {
    color: #e8eaf0;
    font-size: 13px;
    background: transparent;
    border: none;
}
QLabel#statusAvailable {
    color: #30d158;
    font-weight: 600;
    font-size: 13px;
}
QLabel#statusUnavailable {
    color: #ff453a;
    font-weight: 600;
    font-size: 13px;
}
QLabel#statusUpcoming {
    color: #ffd60a;
    font-weight: 600;
    font-size: 13px;
}
QLabel#errorBanner {
    background: rgba(255,69,58,0.15);
    border: 1px solid rgba(255,69,58,0.5);
    color: #ff6961;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
}
QLabel#warnBanner {
    background: rgba(255,214,10,0.12);
    border: 1px solid rgba(255,214,10,0.4);
    color: #ffd60a;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
}
QLineEdit {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px;
    padding: 6px 10px;
    color: #e8eaf0;
}
QLineEdit:focus {
    border-color: #4cc2ff;
}
QLineEdit#searchBox {
    font-size: 14px;
    padding: 8px 12px;
}
QListWidget#candidateList {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    color: #e8eaf0;
    font-size: 13px;
}
QListWidget#candidateList::item {
    padding: 8px 12px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}
QListWidget#candidateList::item:selected {
    background: rgba(76,194,255,0.18);
    color: #4cc2ff;
}
QListWidget#candidateList::item:hover {
    background: rgba(76,194,255,0.08);
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: rgba(255,255,255,0.15);
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
"""


# ---------- 库存查询线程 ----------


class StockQueryWorker(QObject):
    """后台查询线程：复用 fetcher.fetch_stock_json + parser.parse_stock_json。"""

    finished = Signal(object)   # List[StockResult]
    failed = Signal(str)        # 错误消息
    store_cache_used = Signal()  # 店铺列表拉取失败，已改用本地缓存

    def __init__(self, region: str, model: str, store_ids: List[str]):
        super().__init__()
        self.region = region
        self.model = model
        self.store_ids = list(store_ids)

    def _load_cached_stores(self, region: str) -> Optional[List[dict]]:
        path = os.path.join(APP_DATA, f"stores_cache_{region}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stores = data.get("stores") if isinstance(data, dict) else None
            return stores if isinstance(stores, list) else None
        except (OSError, json.JSONDecodeError):
            return None

    def run(self) -> None:
        try:
            if self.store_ids:
                store_ids = self.store_ids
            else:
                try:
                    store_ids = [s["storeNumber"] for s in fetcher.fetch_stores(self.region)]
                except fetcher.FetchError:
                    cached = self._load_cached_stores(self.region)
                    if not cached:
                        raise
                    store_ids = [s["storeNumber"] for s in cached]
                    self.store_cache_used.emit()
            results = []
            for i, sid in enumerate(store_ids):
                if i:
                    fetcher.polite_sleep()
                data = fetcher.fetch_stock_json(self.region, [self.model], sid)
                parsed = parser.parse_stock_json(data, self.region, [self.model])
                if parsed:
                    results.append(parsed[0])
            self.finished.emit(results)
        except fetcher.FetchError as exc:
            self.failed.emit(str(exc))
        except parser.ParseError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - 后台线程兜底，避免线程静默退出
            self.failed.emit(str(exc))


# ---------- 型号选择对话框 ----------


class ModelSelectDialog(QDialog):
    """型号选择器：搜索框调用 catalog 模糊搜索，候选列表单击选中。"""

    def __init__(self, region: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"更换监控型号 · {REGION_NAMES[region]}")
        self.setModal(True)
        self.resize(520, 560)
        self.region = region
        self._entry: Optional[dict] = None
        self._catalog = catalog.load_catalog()

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("搜索型号")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #e8eaf0;")
        root.addWidget(title)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText("输入型号名 / 颜色容量 / Part Number，如 iPhone 18 Pro 512GB、MJYH4CH/A")
        root.addWidget(self.search_box)

        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #8b90a3; font-size: 12px;")
        root.addWidget(self.hint_label)

        self.candidate_list = QListWidget()
        self.candidate_list.setObjectName("candidateList")
        root.addWidget(self.candidate_list, 1)

        self.search_box.textChanged.connect(self._on_search)
        self.candidate_list.itemClicked.connect(self._on_item_clicked)
        self._on_search("")

    def selected_entry(self) -> Optional[dict]:
        return self._entry

    def _on_search(self, text: str) -> None:
        query = text.strip()
        self.candidate_list.clear()
        self._entry = None
        if not query:
            self.hint_label.setText("输入型号名或 Part Number 搜索，如 iPhone 18 Pro / MJYH4CH/A")
            self.hint_label.setStyleSheet("color: #8b90a3; font-size: 12px;")
            return
        hits = catalog.search_models(self.region, query, self._catalog)
        if not hits:
            self.hint_label.setText("未找到匹配型号，可尝试更精确的名称（含容量/颜色）或完整 Part Number")
            self.hint_label.setStyleSheet("color: #ff6961; font-size: 12px;")
            return
        self.hint_label.setText(f"找到 {len(hits)} 个候选，点击选中" if len(hits) <= 30 else f"找到 {len(hits)} 个候选，显示前 30 条")
        self.hint_label.setStyleSheet("color: #8b90a3; font-size: 12px;")
        for e in hits[:30]:
            item = QListWidgetItem(f"{e['name']}　{e['pn']}")
            item.setData(Qt.UserRole, e)
            self.candidate_list.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self._entry = item.data(Qt.UserRole)
        self.accept()


# ---------- 主窗口 ----------


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Apple Stock Monitor")
        self.resize(880, 660)
        self.cfg = load_config()
        self.region = self._initial_region()
        self.current_item = current_item_for_region(self.cfg, self.region)
        self.state_store = StateStore(DEFAULT_STATE_FILE)
        self.last_data: List[StoreStock] = []
        self.data_stale = False
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[StockQueryWorker] = None
        self._query_ctx: Tuple[str, str] = (self.region, "")
        self._pending_refresh = False

        self._build_ui()
        self._apply_region_ui()
        self._setup_timer()
        self._start_query()

    # ---------- 初始化 ----------

    def _initial_region(self) -> str:
        for w in self.cfg.get("watchlist", []):
            if w.get("region") in (REGION_CN, REGION_HK):
                return w["region"]
        return REGION_CN

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)

        # 顶部栏
        top = QHBoxLayout()
        top.setSpacing(8)
        title_neon = QLabel("STOCK")
        title_neon.setObjectName("titleNeon")
        title_monitor = QLabel("MONITOR")
        title_monitor.setObjectName("titleMono")
        top.addWidget(title_neon)
        top.addWidget(title_monitor)
        top.addStretch(1)
        self.cn_btn = QPushButton("中国区")
        self.hk_btn = QPushButton("香港区")
        for b in (self.cn_btn, self.hk_btn):
            b.setObjectName("regionBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            top.addWidget(b)
        self.region_group = QButtonGroup(self)
        self.region_group.addButton(self.cn_btn)
        self.region_group.addButton(self.hk_btn)
        self.cn_btn.clicked.connect(lambda: self._switch_region(REGION_CN))
        self.hk_btn.clicked.connect(lambda: self._switch_region(REGION_HK))
        top.addSpacing(16)
        self.status_label = QLabel("● 运行中")
        self.status_label.setObjectName("statusRunning")
        top.addWidget(self.status_label)
        root.addLayout(top)

        # 监控型号卡片
        model_card = QFrame()
        model_card.setObjectName("card")
        mc = QHBoxLayout(model_card)
        mc.setContentsMargins(16, 12, 16, 12)
        mc_cap = QLabel("当前监控型号")
        mc_cap.setStyleSheet("color: #8b90a3; font-size: 12px;")
        mc.addWidget(mc_cap)
        self.model_label = QLabel("—")
        self.model_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #e8eaf0;")
        mc.addWidget(self.model_label)
        mc.addStretch(1)
        self.change_btn = QPushButton("更换")
        self.change_btn.setObjectName("ghostBtn")
        self.change_btn.setCursor(Qt.PointingHandCursor)
        self.change_btn.clicked.connect(self._on_change_model)
        mc.addWidget(self.change_btn)
        root.addWidget(model_card)

        # 统计条
        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.stat_avail_num = self._make_stat_card(stats, "statAvail", "有货")
        self.stat_unavail_num = self._make_stat_card(stats, "statUnavail", "无货")
        self.stat_upcoming_num = self._make_stat_card(stats, "statUpcoming", "即将到货")
        root.addLayout(stats)

        # 门店库存列表
        list_header = QLabel("门店库存")
        list_header.setStyleSheet("color: #8b90a3; font-size: 12px; font-weight: 600;")
        root.addWidget(list_header)
        self.store_list = QListWidget()
        self.store_list.setObjectName("storeList")
        self.store_list.setSpacing(4)
        root.addWidget(self.store_list, 1)

        # 错误/提示横幅
        self.error_banner = QLabel("")
        self.error_banner.setObjectName("errorBanner")
        self.error_banner.setWordWrap(True)
        self.error_banner.hide()
        root.addWidget(self.error_banner)
        self.warn_banner = QLabel("")
        self.warn_banner.setObjectName("warnBanner")
        self.warn_banner.setWordWrap(True)
        self.warn_banner.hide()
        root.addWidget(self.warn_banner)

        # 底部栏
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        push_cap = QLabel("到货推送")
        push_cap.setStyleSheet("color: #8b90a3; font-size: 13px;")
        bottom.addWidget(push_cap)
        self.notify_switch = QPushButton()
        self.notify_switch.setObjectName("switchBtn")
        self.notify_switch.setCheckable(True)
        self.notify_switch.setCursor(Qt.PointingHandCursor)
        self.notify_switch.toggled.connect(self._on_notify_toggled)
        bottom.addWidget(self.notify_switch)
        self.bark_btn = QPushButton("Bark")
        self.bark_btn.setObjectName("ghostBtn")
        self.bark_btn.setCursor(Qt.PointingHandCursor)
        self.bark_btn.clicked.connect(self._on_bark_toggle)
        bottom.addWidget(self.bark_btn)
        self.bark_edit = QLineEdit()
        self.bark_edit.setObjectName("barkEdit")
        self.bark_edit.setPlaceholderText("Bark Key（回车保存）")
        self.bark_edit.setFixedWidth(220)
        self.bark_edit.hide()
        self.bark_edit.returnPressed.connect(self._on_bark_saved)
        bottom.addWidget(self.bark_edit)
        bottom.addStretch(1)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setObjectName("refreshBtn")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(self._start_query)
        bottom.addWidget(self.refresh_btn)
        self.last_refresh_label = QLabel("上次 —")
        self.last_refresh_label.setStyleSheet("color: #8b90a3; font-size: 12px;")
        bottom.addWidget(self.last_refresh_label)
        root.addLayout(bottom)

    def _make_stat_card(self, layout: QHBoxLayout, num_obj: str, caption: str) -> QLabel:
        card = QFrame()
        card.setObjectName("statCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(2)
        num = QLabel("0")
        num.setObjectName(num_obj)
        num.setAlignment(Qt.AlignCenter)
        v.addWidget(num)
        cap = QLabel(caption)
        cap.setObjectName("statCaption")
        cap.setAlignment(Qt.AlignCenter)
        v.addWidget(cap)
        layout.addWidget(card, 1)
        return num

    def _apply_region_ui(self) -> None:
        if self.region == REGION_CN:
            self.cn_btn.setChecked(True)
        else:
            self.hk_btn.setChecked(True)
        self.current_item = current_item_for_region(self.cfg, self.region)
        if self.current_item:
            self.model_label.setText(self.current_item.get("label") or self.current_item.get("model", ""))
        else:
            self.model_label.setText("未设置 — 点击「更换」选择监控型号")
        self.notify_switch.setChecked(bool(self.cfg.get("gui", {}).get("notify_enabled", True)))
        self.notify_switch.setText("已开启" if self.notify_switch.isChecked() else "已关闭")
        self.bark_edit.setText(self.cfg.get("bark", {}).get("key", ""))

    def _setup_timer(self) -> None:
        interval_min = int(self.cfg.get("poll_interval_minutes", DEFAULT_POLL_INTERVAL_MINUTES)) or DEFAULT_POLL_INTERVAL_MINUTES
        self.timer = QTimer(self)
        self.timer.setInterval(interval_min * 60 * 1000)
        self.timer.timeout.connect(self._start_query)
        self.timer.start()

    # ---------- 地区切换 ----------

    def _switch_region(self, region: str) -> None:
        if region == self.region:
            return
        self.region = region
        self._apply_region_ui()
        if self._worker_thread is not None:
            self._pending_refresh = True
        else:
            self._start_query()

    # ---------- 查询调度 ----------

    def _start_query(self) -> None:
        if self._worker_thread is not None:
            return
        self._pending_refresh = False
        if not self.current_item:
            self._render_empty("当前地区未配置监控型号，点击「更换」选择")
            return
        self.refresh_btn.setEnabled(False)
        self.change_btn.setEnabled(False)
        self.status_label.setText("● 查询中")
        self.status_label.setObjectName("statusQuery")
        self.status_label.setStyleSheet("")
        self._query_ctx = (self.region, self.current_item["model"])

        thread = QThread(self)
        worker = StockQueryWorker(self.region, self.current_item["model"], self.current_item.get("stores") or [])
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_query_finished)
        worker.failed.connect(self._on_query_failed)
        worker.store_cache_used.connect(self._on_store_cache_used)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        self._worker_thread = thread
        self._worker = worker
        thread.start()

    def _on_query_finished(self, results) -> None:
        merged: List[StoreStock] = []
        for r in results:
            merged.extend(r.stores)
        self.last_data = merged
        self.data_stale = False

        item_key = f"{self._query_ctx[0]}|{self._query_ctx[1]}"
        changes = collect_available_changes(results, self.state_store, item_key)
        if changes:
            self.state_store.save()
            if self.cfg.get("gui", {}).get("notify_enabled", True):
                self._notify_changes(changes)

        self._render_results()
        self.last_refresh_label.setText("上次 " + datetime.now().strftime("%H:%M"))
        self.error_banner.hide()
        self.warn_banner.hide()

    def _notify_changes(self, changes: List[StoreStock]) -> None:
        region = self._query_ctx[0]
        label = self.current_item.get("label") or self.current_item.get("model", "")
        bark_key = self.cfg.get("bark", {}).get("key", "") if self.cfg.get("bark", {}).get("enabled") else ""
        title = f"🎉 {REGION_NAMES[region]} {label} 有货了"
        for store in changes:
            notifier.notify_all(title, f"{store.store_name}（{store.store_id}）可自提，快去下单", bark_key)

    def _on_query_failed(self, msg: str) -> None:
        self.data_stale = True
        self.error_banner.setText(f"刷新失败：{msg}（保留上次数据，可能过期）")
        self.error_banner.show()
        self.last_refresh_label.setText("刷新失败")
        if not self.last_data:
            self._render_empty("暂无数据 — 刷新失败")

    def _on_store_cache_used(self) -> None:
        self.warn_banner.setText("提示：店铺列表拉取失败，已使用本地缓存（可能过期）")
        self.warn_banner.show()

    def _on_thread_finished(self) -> None:
        self._worker_thread = None
        self._worker = None
        self.refresh_btn.setEnabled(True)
        self.change_btn.setEnabled(True)
        self.status_label.setText("● 运行中")
        self.status_label.setObjectName("statusRunning")
        self.status_label.setStyleSheet("")
        if self._pending_refresh:
            self._pending_refresh = False
            self._start_query()

    def closeEvent(self, event) -> None:
        if self._worker_thread is not None:
            self._worker_thread.quit()
            self._worker_thread.wait(3000)
        super().closeEvent(event)

    # ---------- 交互 ----------

    def _on_change_model(self) -> None:
        dlg = ModelSelectDialog(self.region, self)
        if dlg.exec() == QDialog.Accepted:
            entry = dlg.selected_entry()
            if not entry:
                return
            apply_model_selection(self.cfg, self.region, entry)
            save_config(self.cfg)
            self.current_item = current_item_for_region(self.cfg, self.region)
            self._apply_region_ui()
            self._start_query()

    def _on_notify_toggled(self, checked: bool) -> None:
        self.cfg.setdefault("gui", {})["notify_enabled"] = bool(checked)
        save_config(self.cfg)
        self.notify_switch.setText("已开启" if checked else "已关闭")

    def _on_bark_toggle(self) -> None:
        self.bark_edit.setVisible(not self.bark_edit.isVisible())
        if self.bark_edit.isVisible():
            self.bark_edit.setFocus()

    def _on_bark_saved(self) -> None:
        key = self.bark_edit.text().strip()
        self.cfg.setdefault("bark", {})["key"] = key
        self.cfg["bark"]["enabled"] = bool(key)
        save_config(self.cfg)

    # ---------- 渲染 ----------

    def _render_results(self) -> None:
        self.store_list.clear()
        if not self.last_data:
            self._render_empty("暂无数据")
            return
        a, u, up = count_stats(self.last_data)
        self.stat_avail_num.setText(str(a))
        self.stat_unavail_num.setText(str(u))
        self.stat_upcoming_num.setText(str(up))
        for store in sort_stores(self.last_data):
            self._append_store_row(store)

    def _append_store_row(self, store: StoreStock) -> None:
        row = QFrame()
        row.setObjectName("storeRow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 9, 14, 9)
        lay.addWidget(QLabel(store.store_name or store.store_id))
        lay.addStretch(1)
        status = classify_status(store)
        status_label = QLabel(f"● {_STATUS_LABELS[status]}")
        status_label.setObjectName(f"status{status.capitalize()}")
        lay.addWidget(status_label)
        item = QListWidgetItem()
        item.setSizeHint(row.sizeHint())
        self.store_list.addItem(item)
        self.store_list.setItemWidget(item, row)

    def _render_empty(self, text: str) -> None:
        self.store_list.clear()
        item = QListWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        self.store_list.addItem(item)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
