import pandas as pd
import requests

from tradingagents.dataflows import akshare_cn


class _FakeAkshare:
    def __init__(self):
        self.requested_symbol = None

    def stock_info_a_code_name(self):
        return pd.DataFrame([{"code": "300496", "name": "中科创达"}])

    def stock_news_em(self, symbol):
        self.requested_symbol = symbol
        return pd.DataFrame(
            [
                {
                    "新闻标题": "中科创达测试新闻",
                    "新闻内容": "用于验证公司简称解析。",
                    "文章来源": "测试源",
                    "发布时间": "2026-07-14 10:30:00",
                    "新闻链接": "https://example.test/news",
                }
            ]
        )


def test_get_news_resolves_exact_a_share_company_name(monkeypatch):
    fake = _FakeAkshare()
    monkeypatch.setattr(akshare_cn, "_ak", lambda: fake)
    report = akshare_cn.get_news_akshare("中科创达", "2026-07-07", "2026-07-14")
    assert fake.requested_symbol == "300496"
    assert "300496.SZ" in report


def test_tencent_quote_maps_total_and_float_market_cap(monkeypatch):
    values = [""] * 53
    values[1] = "中科创达"
    values[3] = "53.72"
    values[44] = "198.53"
    values[45] = "248.03"

    class _Response:
        content = f'v_sz300496="{"~".join(values)}";'.encode("gbk")

        def raise_for_status(self):
            return None

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _Response())
    quote = akshare_cn._tencent_quote("300496")
    assert quote["mcap_yi"] == 248.03
    assert quote["float_mcap_yi"] == 198.53
