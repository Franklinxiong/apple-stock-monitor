"""数据模型定义。"""

from dataclasses import dataclass, field
from typing import List, Optional

REGION_CN = "cn"
REGION_HK = "hk"

REGION_NAMES = {
    REGION_CN: "中国大陆",
    REGION_HK: "中国香港",
}

# 各地区库存查询接口（pickup-message，需指定 store）
REGION_API_URLS = {
    REGION_CN: "https://www.apple.com.cn/shop/retail/pickup-message",
    REGION_HK: "https://www.apple.com/hk/shop/retail/pickup-message",
}

# 各地区零售店列表页面（内嵌 storeList JSON）
REGION_STORELIST_URLS = {
    REGION_CN: "https://www.apple.com.cn/retail/storelist/",
    REGION_HK: "https://www.apple.com/hk/retail/storelist/",
}

# 店铺列表 JSON 中对应的 locale 字段
REGION_LOCALES = {
    REGION_CN: "zh_CN",
    REGION_HK: "zh_HK",
}


@dataclass
class WatchItem:
    """一条监控配置：地区 + 型号 + 关注店铺列表（空=全部店铺）。"""

    region: str
    model: str
    label: str = ""
    stores: List[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.region}|{self.model}"

    def to_dict(self) -> dict:
        return {
            "region": self.region,
            "model": self.model,
            "label": self.label,
            "stores": list(self.stores),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WatchItem":
        return cls(
            region=data.get("region", ""),
            model=data.get("model", ""),
            label=data.get("label", ""),
            stores=list(data.get("stores", [])),
        )


@dataclass
class StoreStock:
    """单个店铺对某个型号的库存状态。"""

    store_id: str
    store_name: str
    region: str
    model: str
    available: bool
    pickup_display: str = ""


@dataclass
class StockResult:
    """一次查询的结果汇总。"""

    region: str
    model: str
    stores: List[StoreStock] = field(default_factory=list)

    def available_stores(self) -> List[StoreStock]:
        return [s for s in self.stores if s.available]


def is_valid_part_number(model: str) -> bool:
    """校验 Part Number 格式，形如 MQ0X3CH/A。"""
    if not model or "/" not in model:
        return False
    head, tail = model.rsplit("/", 1)
    return bool(head) and bool(tail)
