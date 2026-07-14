import copy
from unittest import mock

import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import NoMarketDataError


def setup_function():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def teardown_function():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def test_strict_mode_raises_instead_of_returning_no_data_sentinel():
    set_config(
        {
            "strict_data_mode": True,
            "data_vendors": {"core_stock_apis": "akshare"},
        }
    )

    def unavailable(*_args, **_kwargs):
        raise NoMarketDataError("300496.SZ", detail="test gap")

    with (
        mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": {"akshare": unavailable}},
            clear=False,
        ),
        pytest.raises(NoMarketDataError, match="test gap"),
    ):
        interface.route_to_vendor(
            "get_stock_data", "300496.SZ", "2026-01-01", "2026-07-14"
        )


def test_strict_mode_raises_optional_vendor_failure():
    set_config(
        {
            "strict_data_mode": True,
            "data_vendors": {"macro_data": "fred"},
        }
    )

    def broken(*_args, **_kwargs):
        raise RuntimeError("macro broken")

    with (
        mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_macro_indicators": {"fred": broken}},
            clear=False,
        ),
        pytest.raises(RuntimeError, match="macro broken"),
    ):
        interface.route_to_vendor("get_macro_indicators", "cpi", "2026-07-14", 90)
