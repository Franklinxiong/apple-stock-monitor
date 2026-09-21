"""解析 Apple pickup-message 接口返回的库存状态。"""

from typing import List

from models import StockResult, StoreStock


class ParseError(Exception):
    """响应结构异常，无法解析。"""


def parse_stock_json(data: dict, region: str, models: List[str]) -> List[StockResult]:
    """从原始 JSON 提取店铺 + 型号库存状态。

    新接口结构: body.stores[]，每个 store 含 partsAvailability.{partNumber}.pickupDisplay。
    partsAvailability 缺失某型号视为该店未上架（无货）。
    """
    try:
        stores_raw = data["body"]["stores"]
    except (KeyError, TypeError) as exc:
        raise ParseError("响应缺少 body.stores 结构，可能接口已变更") from exc

    if stores_raw is None:
        stores_raw = []

    results = {model: StockResult(region=region, model=model) for model in models}
    for store in stores_raw:
        try:
            store_number = store["storeNumber"]
            store_name = store.get("storeName", store_number)
            parts = store.get("partsAvailability", {}) or {}
        except (KeyError, TypeError):
            continue
        for model in models:
            part = parts.get(model)
            if part is None:
                results[model].stores.append(
                    StoreStock(
                        store_id=store_number,
                        store_name=store_name,
                        region=region,
                        model=model,
                        available=False,
                        pickup_display="not_listed",
                    )
                )
                continue
            pickup_display = str(part.get("pickupDisplay", ""))
            available = pickup_display.lower() == "available"
            results[model].stores.append(
                StoreStock(
                    store_id=store_number,
                    store_name=store_name,
                    region=region,
                    model=model,
                    available=available,
                    pickup_display=pickup_display,
                )
            )
    return list(results.values())
