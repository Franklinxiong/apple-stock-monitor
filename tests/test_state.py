"""state 模块单元测试。"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from state import StateStore


def _make_store():
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)
    return StateStore(tmp.name)


def test_initial_state_empty():
    store = _make_store()
    assert store.was_available("cn|MQ0X3CH/A", "R428") is False


def test_set_and_get():
    store = _make_store()
    store.set_available("cn|MQ0X3CH/A", "R428", True)
    assert store.was_available("cn|MQ0X3CH/A", "R428") is True
    assert store.was_available("cn|MQ0X3CH/A", "R388") is False


def test_persistence_roundtrip():
    store = _make_store()
    store.set_available("hk|MQ0X3CH/A", "R428", True)
    store.set_store_name("hk|MQ0X3CH/A", "R428", "香港ifc mall")
    store.save()

    reloaded = StateStore(store.path)
    assert reloaded.was_available("hk|MQ0X3CH/A", "R428") is True
    assert reloaded.store_name("hk|MQ0X3CH/A", "R428") == "香港ifc mall"


def test_transition_reset():
    store = _make_store()
    store.set_available("cn|M", "R1", True)
    store.set_available("cn|M", "R1", False)
    assert store.was_available("cn|M", "R1") is False
