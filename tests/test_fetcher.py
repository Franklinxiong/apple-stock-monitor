"""fetcher 店铺列表解析单元测试。"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetcher


SAMPLE_HTML = (
    "<html><script>"
    '{"pageProps":{"id":"page-store-list","storeList":['
    '{"locale":"zh_CN","calledLocale":"zh_CN","__typename":"RmdLocale","hasStates":true,'
    '"state":[{"__typename":"RgdsState","name":"上海","store":['
    '{"id":"R683","name":"环球港","slug":"globalharbor","__typename":"RgdsStore"},'
    '{"id":"R389","name":"浦东","slug":"pudong","__typename":"RgdsStore"}'
    ']}]},'
    '{"locale":"en_US","calledLocale":"en_US","__typename":"RmdLocale","hasStates":true,'
    '"state":[{"__typename":"RgdsState","name":"New York","store":['
    '{"id":"R001","name":"Fifth Avenue","slug":"fifthavenue","__typename":"RgdsStore"}'
    ']}]}'
    ']}}'
    "</script></html>"
)


def test_extract_zh_cn_stores():
    stores = fetcher._extract_stores_from_html(SAMPLE_HTML, "zh_CN")
    assert len(stores) == 2
    assert stores[0] == {"storeNumber": "R683", "storeName": "环球港"}
    assert stores[1] == {"storeNumber": "R389", "storeName": "浦东"}


def test_extract_wrong_locale():
    stores = fetcher._extract_stores_from_html(SAMPLE_HTML, "zh_HK")
    assert stores == []


def test_extract_no_storelist():
    stores = fetcher._extract_stores_from_html("<html>no data</html>", "zh_CN")
    assert stores == []


def test_extract_no_states_direct_stores():
    html = (
        "<script>"
        '{"pageProps":{"storeList":[{"locale":"zh_HK","calledLocale":"zh_HK",'
        '"__typename":"RmdLocale","hasStates":false,'
        '"states":[{"id":"R428","name":"ifc mall","__typename":"RgdsStore"},'
        '{"id":"R673","name":"apm Hong Kong","__typename":"RgdsStore"}]}]}}'
        "</script>"
    )
    stores = fetcher._extract_stores_from_html(html, "zh_HK")
    assert len(stores) == 2
    assert stores[0] == {"storeNumber": "R428", "storeName": "ifc mall"}
