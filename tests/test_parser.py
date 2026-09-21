"""parser 模块单元测试。"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from parser import ParseError, parse_stock_json
from models import StockResult


def _sample_data(part_state=None):
    part_state = part_state if part_state is not None else {"pickupDisplay": "available"}
    stores = [
        {
            "storeNumber": "R428",
            "storeName": "ifc mall",
            "partsAvailability": {"MG2L4ZA/A": part_state},
        },
        {
            "storeNumber": "R673",
            "storeName": "apm Hong Kong",
            "partsAvailability": {"MG2L4ZA/A": {"pickupDisplay": "unavailable"}},
        },
    ]
    return {"body": {"stores": stores}}


def test_parse_available():
    results = parse_stock_json(_sample_data({"pickupDisplay": "available"}), "hk", ["MG2L4ZA/A"])
    assert isinstance(results, list) and len(results) == 1
    result = results[0]
    assert isinstance(result, StockResult)
    assert len(result.stores) == 2
    available = result.available_stores()
    assert len(available) == 1
    assert available[0].store_id == "R428"
    assert available[0].store_name == "ifc mall"
    assert available[0].available is True


def test_parse_multiple_models():
    data = {
        "body": {
            "stores": [
                {
                    "storeNumber": "R683",
                    "storeName": "环球港",
                    "partsAvailability": {
                        "MG314CH/A": {"pickupDisplay": "available"},
                        "MG334CH/A": {"pickupDisplay": "unavailable"},
                    },
                }
            ]
        }
    }
    results = parse_stock_json(data, "cn", ["MG314CH/A", "MG334CH/A"])
    assert len(results) == 2
    by_model = {r.model: r for r in results}
    assert by_model["MG314CH/A"].stores[0].available is True
    assert by_model["MG334CH/A"].stores[0].available is False
    assert by_model["MG334CH/A"].stores[0].pickup_display == "unavailable"


def test_parse_unavailable():
    results = parse_stock_json(_sample_data({"pickupDisplay": "unavailable"}), "hk", ["MG2L4ZA/A"])
    assert results[0].available_stores() == []


def test_parse_no_stores():
    data = {"body": {"stores": []}}
    results = parse_stock_json(data, "hk", ["MG2L4ZA/A"])
    assert results[0].stores == []


def test_parse_model_not_listed():
    data = {
        "body": {
            "stores": [
                {
                    "storeNumber": "R428",
                    "storeName": "ifc mall",
                    "partsAvailability": {},
                }
            ]
        }
    }
    results = parse_stock_json(data, "hk", ["MG2L4ZA/A"])
    assert len(results[0].stores) == 1
    assert results[0].stores[0].available is False
    assert results[0].stores[0].pickup_display == "not_listed"


def test_parse_bad_structure():
    with pytest.raises(ParseError):
        parse_stock_json({"foo": "bar"}, "hk", ["MG2L4ZA/A"])
