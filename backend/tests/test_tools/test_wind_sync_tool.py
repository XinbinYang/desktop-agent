"""
Tests for wind_sync_tool.py —— WIND 数据增量同步工具。

由于 WIND wsd 接口有每日配额限制，所有涉及真实 WIND 调用的测试
均使用 Mock 对象模拟 WindPy 返回结果，确保测试可重复执行。
"""

import pytest
import sqlite3
import pandas as pd
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

# 被测模块
from app.tools.wind_sync_tool import (
    WindSyncTool,
    _parse_wsd_result,
    _get_local_latest_date_quant,
    _get_local_latest_date_market,
    _QUANT_DB_PATH,
    _MARKET_DB_PATH,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture(scope="function")
def temp_quant_db(tmp_path):
    """创建临时 quant_db.sqlite，初始化 daily_prices / daily_indicators 表。"""
    db_path = tmp_path / "quant_db.sqlite"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute(
        """CREATE TABLE daily_prices (
            id INTEGER PRIMARY KEY,
            trade_date DATE,
            stock_code VARCHAR(20),
            open FLOAT, high FLOAT, low FLOAT, close FLOAT,
            volume FLOAT, amount FLOAT, vwap FLOAT, pct_chg FLOAT,
            adj_factor FLOAT, created_at DATETIME
        )"""
    )
    c.execute(
        """CREATE TABLE daily_indicators (
            id INTEGER PRIMARY KEY,
            trade_date DATE,
            stock_code VARCHAR(20),
            pe_ttm FLOAT, pb FLOAT, ps_ttm FLOAT, pcf_ncf_ttm FLOAT,
            dividend_yield FLOAT, mkt_cap FLOAT, float_mkt_cap FLOAT,
            turn FLOAT, free_turn FLOAT, created_at DATETIME
        )"""
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(scope="function")
def temp_market_db(tmp_path):
    """创建临时 market_data.db，初始化 china_equity_historical 表。"""
    db_path = tmp_path / "market_data.db"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute(
        """CREATE TABLE china_equity_historical (
            date DATE,
            index_code TEXT,
            index_name TEXT,
            close_price REAL,
            source_file TEXT
        )"""
    )
    conn.commit()
    conn.close()
    return db_path


# ------------------------------------------------------------------
# Helper: 构造 Mock WindPy 结果
# ------------------------------------------------------------------

def make_wsd_result(error_code: int = 0, fields=None, times=None, data=None):
    """构造一个模拟的 WindPy wsd 返回对象。"""
    result = MagicMock()
    result.ErrorCode = error_code
    result.Fields = fields or []
    result.Times = times or []
    result.Data = data or []
    return result


# ------------------------------------------------------------------
# 单元测试
# ------------------------------------------------------------------

class TestParseWsdResult:
    def test_parse_normal(self):
        result = make_wsd_result(
            error_code=0,
            fields=["open", "high", "low", "close", "volume"],
            times=[datetime(2024, 1, 2), datetime(2024, 1, 3)],
            data=[
                [10.0, 10.5],   # open
                [11.0, 11.2],   # high
                [9.5, 10.3],    # low
                [10.8, 10.9],   # close
                [100000, 120000],  # volume
            ],
        )
        df = _parse_wsd_result(result)
        assert df is not None
        assert len(df) == 2
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df.loc[df.index[0], "close"] == 10.8

    def test_parse_error(self):
        result = make_wsd_result(error_code=-40522017)
        df = _parse_wsd_result(result)
        assert df is None

    def test_parse_empty(self):
        result = make_wsd_result(error_code=0, fields=[], times=[], data=[])
        df = _parse_wsd_result(result)
        assert df is None or df.empty


class TestLocalLatestDate:
    def test_quant_db_latest(self, temp_quant_db, monkeypatch):
        # Patch 数据库路径到临时文件
        monkeypatch.setattr(
            "app.tools.wind_sync_tool._QUANT_DB_PATH", temp_quant_db
        )
        conn = sqlite3.connect(str(temp_quant_db))
        c = conn.cursor()
        c.execute(
            "INSERT INTO daily_prices (trade_date, stock_code, close) VALUES (?, ?, ?)",
            ("2024-06-28", "000001.SZ", 10.0),
        )
        c.execute(
            "INSERT INTO daily_prices (trade_date, stock_code, close) VALUES (?, ?, ?)",
            ("2024-06-30", "000001.SZ", 10.5),
        )
        conn.commit()
        conn.close()

        latest = _get_local_latest_date_quant("000001.SZ", "daily_prices")
        assert latest == "2024-06-30"

    def test_quant_db_no_data(self, temp_quant_db, monkeypatch):
        monkeypatch.setattr(
            "app.tools.wind_sync_tool._QUANT_DB_PATH", temp_quant_db
        )
        latest = _get_local_latest_date_quant("999999.XY", "daily_prices")
        assert latest is None

    def test_market_db_latest(self, temp_market_db, monkeypatch):
        monkeypatch.setattr(
            "app.tools.wind_sync_tool._MARKET_DB_PATH", temp_market_db
        )
        conn = sqlite3.connect(str(temp_market_db))
        c = conn.cursor()
        c.execute(
            "INSERT INTO china_equity_historical (date, index_code, close_price) VALUES (?, ?, ?)",
            ("2024-05-20", "000300.SH", 3500.0),
        )
        conn.commit()
        conn.close()

        latest = _get_local_latest_date_market("000300.SH")
        assert latest == "2024-05-20"


class TestWindSyncToolExecution:
    @pytest.mark.asyncio
    async def test_skip_when_already_up_to_date(self, temp_quant_db, monkeypatch):
        """本地已是最新日期，应直接跳过，不调用 wsd。"""
        monkeypatch.setattr(
            "app.tools.wind_sync_tool._QUANT_DB_PATH", temp_quant_db
        )
        # 插入一条数据到 2024-06-28
        conn = sqlite3.connect(str(temp_quant_db))
        c = conn.cursor()
        c.execute(
            "INSERT INTO daily_prices (trade_date, stock_code, close) VALUES (?, ?, ?)",
            ("2024-06-28", "000001.SZ", 10.0),
        )
        conn.commit()
        conn.close()

        tool = WindSyncTool()
        result = await tool.execute(
            sync_type="a_stock_daily",
            codes="000001.SZ",
            start_date=None,
            end_date="2024-06-28",
        )
        assert not result.error
        assert "跳过" in result.output or "已最新" in result.output

    @pytest.mark.asyncio
    @patch("app.tools.wind_sync_tool._ensure_wind")
    async def test_sync_a_stock_daily_success(self, mock_ensure_wind, temp_quant_db, monkeypatch):
        """模拟 wsd 返回数据，验证能正确写入 daily_prices。"""
        monkeypatch.setattr(
            "app.tools.wind_sync_tool._QUANT_DB_PATH", temp_quant_db
        )

        # Mock WindPy
        mock_w = MagicMock()
        mock_ensure_wind.return_value = mock_w
        mock_w.wsd.return_value = make_wsd_result(
            error_code=0,
            fields=["open", "high", "low", "close", "volume", "amt", "vwap", "pct_chg"],
            times=[datetime(2024, 6, 29), datetime(2024, 6, 30)],
            data=[
                [10.0, 10.2],   # open
                [11.0, 11.1],   # high
                [9.5, 10.0],    # low
                [10.5, 10.8],   # close
                [100000, 110000],  # volume
                [1050000, 1100000],  # amt
                [10.3, 10.6],   # vwap
                [0.5, 2.86],    # pct_chg
            ],
        )

        tool = WindSyncTool()
        result = await tool.execute(
            sync_type="a_stock_daily",
            codes="000001.SZ",
            start_date="2024-06-29",
            end_date="2024-06-30",
        )
        assert not result.error, f"Unexpected error: {result.error}"
        assert "同步成功" in result.output or "插入" in result.output

        # 验证数据库写入
        conn = sqlite3.connect(str(temp_quant_db))
        c = conn.cursor()
        c.execute(
            "SELECT trade_date, open, high, low, close, volume FROM daily_prices WHERE stock_code = ? ORDER BY trade_date",
            ("000001.SZ",),
        )
        rows = c.fetchall()
        conn.close()
        assert len(rows) == 2
        assert rows[0][0] == "2024-06-29"
        assert rows[0][4] == 10.5  # close
        assert rows[1][0] == "2024-06-30"

    @pytest.mark.asyncio
    @patch("app.tools.wind_sync_tool._ensure_wind")
    async def test_sync_quota_exceeded(self, mock_ensure_wind, temp_quant_db, monkeypatch):
        """模拟 WIND 配额耗尽，应返回错误提示并停止同步。"""
        monkeypatch.setattr(
            "app.tools.wind_sync_tool._QUANT_DB_PATH", temp_quant_db
        )

        mock_w = MagicMock()
        mock_ensure_wind.return_value = mock_w
        mock_w.wsd.return_value = make_wsd_result(
            error_code=-40522017,
            data=[["CWSDService:: quota exceeded."]],
        )

        tool = WindSyncTool()
        result = await tool.execute(
            sync_type="a_stock_daily",
            codes="000001.SZ",
            start_date="2024-06-29",
            end_date="2024-06-30",
        )
        assert not result.error  # 错误信息放在 output 中
        assert "配额" in result.output

    @pytest.mark.asyncio
    @patch("app.tools.wind_sync_tool._ensure_wind")
    async def test_sync_china_index_success(self, mock_ensure_wind, temp_market_db, monkeypatch):
        """模拟中国指数同步写入 market_data.db。"""
        monkeypatch.setattr(
            "app.tools.wind_sync_tool._MARKET_DB_PATH", temp_market_db
        )

        mock_w = MagicMock()
        mock_ensure_wind.return_value = mock_w
        mock_w.wsd.return_value = make_wsd_result(
            error_code=0,
            fields=["close"],
            times=[datetime(2024, 7, 1), datetime(2024, 7, 2)],
            data=[[3500.0, 3510.5]],
        )

        tool = WindSyncTool()
        result = await tool.execute(
            sync_type="china_index",
            codes="000300.SH",
            start_date="2024-07-01",
            end_date="2024-07-02",
        )
        assert not result.error
        assert "同步成功" in result.output or "插入" in result.output

        conn = sqlite3.connect(str(temp_market_db))
        c = conn.cursor()
        c.execute(
            "SELECT date, close_price FROM china_equity_historical WHERE index_code = ? ORDER BY date",
            ("000300.SH",),
        )
        rows = c.fetchall()
        conn.close()
        assert len(rows) == 2
        assert rows[0] == ("2024-07-01", 3500.0)
        assert rows[1] == ("2024-07-02", 3510.5)

    @pytest.mark.asyncio
    async def test_empty_codes(self):
        tool = WindSyncTool()
        result = await tool.execute(sync_type="a_stock_daily", codes="")
        assert result.error is not None
        assert "为空" in result.error
