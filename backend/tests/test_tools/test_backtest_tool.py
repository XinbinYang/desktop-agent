import pytest
import pandas as pd
import sqlite3
from pathlib import Path
from unittest.mock import patch

from app.tools.backtest_tool import (
    _query_ohlcv,
    _query_close_only,
    _get_data_from_quant_db,
    _get_data_from_market_db,
    StrategyListTool,
    BacktestRunTool,
    BacktestReportTool,
    _save_result,
    _load_result,
)


class TestQueryHelpers:
    @pytest.fixture
    def conn(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE test_ohlcv (
                date TEXT, ticker TEXT, open_price REAL, high_price REAL, low_price REAL, close_price REAL, volume REAL
            )
        """)
        conn.execute("""
            CREATE TABLE test_close (
                date TEXT, ticker TEXT, close_price REAL
            )
        """)
        dates = ['2024-01-01', '2024-01-02', '2024-01-03']
        for d in dates:
            conn.execute("INSERT INTO test_ohlcv VALUES (?, 'TEST', 100, 101, 99, 100.5, 1000)", (d,))
            conn.execute("INSERT INTO test_close VALUES (?, 'TEST', 100.5)", (d,))
        conn.commit()
        yield conn
        conn.close()

    def test_query_ohlcv_returns_dataframe(self, conn):
        df = _query_ohlcv(conn, "test_ohlcv", "ticker", "TEST", "2024-01-01", "2024-01-03")
        assert df is not None
        assert list(df.columns) == ['open', 'high', 'low', 'close', 'volume']
        assert len(df) == 3

    def test_query_ohlcv_returns_none_for_empty(self, conn):
        df = _query_ohlcv(conn, "test_ohlcv", "ticker", "NONE", "2024-01-01", "2024-01-03")
        assert df is None

    def test_query_close_only_returns_dataframe(self, conn):
        df = _query_close_only(conn, "test_close", "ticker", "TEST", "2024-01-01", "2024-01-03")
        assert df is not None
        assert list(df.columns) == ['open', 'high', 'low', 'close', 'volume']
        assert len(df) == 3
        # close-only 表会填充 open/high/low/volume
        assert (df['open'] == df['close']).all()

    def test_query_close_only_returns_none_for_empty(self, conn):
        df = _query_close_only(conn, "test_close", "ticker", "NONE", "2024-01-01", "2024-01-03")
        assert df is None


class TestGetDataFromQuantDb:
    def test_returns_none_when_db_missing(self):
        with patch('app.tools.backtest_tool._QUANT_DB_PATH') as mock_path:
            mock_path.exists.return_value = False
            result = _get_data_from_quant_db('600519.SH', '2024-01-01', '2024-01-03')
            assert result is None


class TestGetDataFromMarketDb:
    def test_returns_none_when_db_missing(self):
        with patch('app.tools.backtest_tool._MARKET_DB_PATH') as mock_path:
            mock_path.exists.return_value = False
            result = _get_data_from_market_db('^GSPC', '2024-01-01', '2024-01-03')
            assert result is None


class TestCacheHelpers:
    def test_save_and_load_roundtrip(self, tmp_path):
        with patch('app.tools.backtest_tool._BACKTEST_CACHE_DIR', tmp_path):
            data = {
                'strategy': 'sma_cross',
                'final_value': 101000,
                'nav_df': pd.DataFrame({'a': [1, 2]}),
            }
            _save_result('sess_1', 'sma_cross', '600519.SH', '2024-01-01', data)
            loaded = _load_result('sess_1', 'sma_cross', '600519.SH', '2024-01-01')
            assert loaded is not None
            assert loaded['strategy'] == 'sma_cross'
            assert loaded['final_value'] == 101000
            assert isinstance(loaded['nav_df'], pd.DataFrame)

    def test_load_nonexistent_returns_none(self, tmp_path):
        with patch('app.tools.backtest_tool._BACKTEST_CACHE_DIR', tmp_path):
            result = _load_result('sess_x', 'none', 'NONE', '2024-01-01')
            assert result is None


class TestStrategyListTool:
    @pytest.fixture
    def tool(self):
        return StrategyListTool()

    @pytest.mark.asyncio
    async def test_returns_list_of_strategies(self, tool):
        result = await tool.execute()
        assert result.error == ""
        assert "sma_cross" in result.output
        assert "macd" in result.output


class TestBacktestRunTool:
    @pytest.fixture
    def tool(self):
        return BacktestRunTool()

    @pytest.mark.asyncio
    async def test_error_on_unknown_strategy(self, tool):
        with patch('app.tools.backtest_tool._get_data') as mock_get:
            mock_get.return_value = pd.DataFrame({
                'open': [100 + i for i in range(15)],
                'high': [101 + i for i in range(15)],
                'low': [99 + i for i in range(15)],
                'close': [100 + i for i in range(15)],
                'volume': [1000 + i * 100 for i in range(15)],
            }, index=pd.date_range('2024-01-01', periods=15))
            result = await tool.execute(
                strategy_name='unknown',
                codes='600519.SH',
                start_date='2024-01-01',
                end_date='2024-01-03',
            )
            assert "参数错误" in result.error or "未知策略" in result.error

    @pytest.mark.asyncio
    async def test_error_on_insufficient_data(self, tool):
        # 没有本地数据、且 Wind 不可用时，会数据量不足
        with patch('app.tools.backtest_tool._get_data') as mock_get:
            mock_get.return_value = pd.DataFrame({'close': [100]})
            result = await tool.execute(
                strategy_name='sma_cross',
                codes='FAKE.CODE',
                start_date='2024-01-01',
                end_date='2024-01-03',
            )
            assert "数据量不足" in result.error


class TestGetDataFallback:
    """Verify that _get_data prefers local data and only calls WIND when local is truly empty."""

    @pytest.mark.asyncio
    async def test_uses_local_when_sufficient(self):
        from app.tools import backtest_tool

        df = pd.DataFrame({
            'open': [1.0] * 12, 'high': [1.0] * 12, 'low': [1.0] * 12, 'close': [1.0] * 12, 'volume': [0] * 12
        }, index=pd.date_range('2024-01-01', periods=12))
        with patch.object(backtest_tool, '_get_data_from_quant_db', return_value=df), \
             patch.object(backtest_tool, '_get_wind_data') as wind:
            result = backtest_tool._get_data('600519.SH', '2024-01-01', '2024-01-12')
            assert len(result) == 12
            wind.assert_not_called()

    @pytest.mark.asyncio
    async def test_sparse_local_raises_instead_of_wind_fallback(self):
        """1..MIN-1 rows locally must error explicitly, not silently call WIND."""
        from app.tools import backtest_tool

        sparse = pd.DataFrame({
            'open': [1.0, 1.0], 'high': [1.0, 1.0], 'low': [1.0, 1.0],
            'close': [1.0, 1.0], 'volume': [0, 0]
        }, index=pd.date_range('2024-01-01', periods=2))
        with patch.object(backtest_tool, '_get_data_from_quant_db', return_value=sparse), \
             patch.object(backtest_tool, '_get_data_from_market_db', return_value=None), \
             patch.object(backtest_tool, '_get_wind_data') as wind:
            with pytest.raises(ValueError, match="wind_sync"):
                backtest_tool._get_data('600519.SH', '2024-01-01', '2024-01-12')
            wind.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_local_falls_back_to_wind(self):
        """Truly empty local data does fall back to WIND (preserves original intent)."""
        from app.tools import backtest_tool

        wind_df = pd.DataFrame({
            'open': [1.0] * 12, 'high': [1.0] * 12, 'low': [1.0] * 12, 'close': [1.0] * 12, 'volume': [0] * 12
        }, index=pd.date_range('2024-01-01', periods=12))
        with patch.object(backtest_tool, '_get_data_from_quant_db', return_value=None), \
             patch.object(backtest_tool, '_get_data_from_market_db', return_value=None), \
             patch.object(backtest_tool, '_get_wind_data', return_value=wind_df) as wind:
            result = backtest_tool._get_data('600519.SH', '2024-01-01', '2024-01-12')
            assert len(result) == 12
            wind.assert_called_once()


class TestBacktestReportTool:
    @pytest.fixture
    def tool(self):
        return BacktestReportTool()

    @pytest.mark.asyncio
    async def test_error_when_no_cached_result(self, tool):
        result = await tool.execute(
            strategy_name='none',
            codes='NONE',
            start_date='2024-01-01',
        )
        assert "未找到回测结果" in result.error
