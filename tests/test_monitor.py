"""monitor.run_once 去重触发逻辑测试（mock 网络与通知）。"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import monitor
import state as state_mod
from models import StoreStock, StockResult


def _tmp_state_path():
    tmpdir = tempfile.mkdtemp()
    return os.path.join(tmpdir, "state.json")


class _FakeState:
    def __init__(self, path):
        self.store = state_mod.StateStore(path)

    def was_available(self, item_key, store_id):
        return self.store.was_available(item_key, store_id)

    def set_available(self, item_key, store_id, available):
        self.store.set_available(item_key, store_id, available)

    def set_store_name(self, item_key, store_id, name):
        self.store.set_store_name(item_key, store_id, name)

    def save(self):
        self.store.save()


def _make_result(region, model, stores):
    return StockResult(region=region, model=model, stores=stores)


def _store(sid, name, available):
    return StoreStock(store_id=sid, store_name=name, region="hk", model="MG2L4ZA/A",
                      available=available, pickup_display="available" if available else "unavailable")


def _fake_fetch(region, models, store_id):
    return {"body": {"stores": []}}


def _fake_parse(data, region, models):
    return [_make_result(region, m, [_store("R428", "ifc mall", True)]) for m in models]


def _fake_notify(title, message, bark_key=""):
    _fake_notify.calls.append((title, message, bark_key))


def test_no_notify_when_already_available(monkeypatch):
    _fake_notify.calls = []
    st = _FakeState(_tmp_state_path())
    item = monitor.WatchItem(region="hk", model="MG2L4ZA/A", stores=["R428"])
    st.store.set_available(item.key, "R428", True)  # 上次已有货

    monkeypatch.setattr(monitor.fetcher, "fetch_stock_json", _fake_fetch)
    monkeypatch.setattr(monitor.parser, "parse_stock_json", _fake_parse)
    monkeypatch.setattr(monitor, "notify_all", _fake_notify)

    changed = monitor.run_once([item], st)
    assert changed is False
    assert _fake_notify.calls == []


def test_notify_when_transition_to_available(monkeypatch):
    _fake_notify.calls = []
    st = _FakeState(_tmp_state_path())
    item = monitor.WatchItem(region="hk", model="MG2L4ZA/A", stores=["R428"])

    monkeypatch.setattr(monitor.fetcher, "fetch_stock_json", _fake_fetch)
    monkeypatch.setattr(monitor.parser, "parse_stock_json", _fake_parse)
    monkeypatch.setattr(monitor, "notify_all", _fake_notify)

    changed = monitor.run_once([item], st)
    assert changed is True
    assert len(_fake_notify.calls) == 1
    assert "有货" in _fake_notify.calls[0][0]


def test_no_notify_when_still_out_of_stock(monkeypatch):
    _fake_notify.calls = []
    st = _FakeState(_tmp_state_path())
    item = monitor.WatchItem(region="hk", model="MG2L4ZA/A", stores=["R428"])

    def _parse_out(data, region, models):
        return [_make_result(region, m, [_store("R428", "ifc mall", False)]) for m in models]

    monkeypatch.setattr(monitor.fetcher, "fetch_stock_json", _fake_fetch)
    monkeypatch.setattr(monitor.parser, "parse_stock_json", _parse_out)
    monkeypatch.setattr(monitor, "notify_all", _fake_notify)

    changed = monitor.run_once([item], st)
    assert changed is False
    assert _fake_notify.calls == []
