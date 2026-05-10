import pytest
import pandas as pd
from unittest.mock import MagicMock, patch, AsyncMock

from app.tools.wind_tool import _wind_data_to_csv, WindWsdTool, WindWssTool, WindWsetTool, WindEdbTool, WindTdaysTool


class TestWindDataToCsv:
    def test_error_code_raises(self):
        mock_data = MagicMock()
        mock_data.ErrorCode = -1
        mock_data.Data = [["some error"]]
        mock_data.Fields = []
        mock_data.Codes = []
        mock_data.Times = []
        with pytest.raises(RuntimeError, match="Wind API 错误"):
            _wind_data_to_csv(mock_data)

    def test_empty_data_returns_message(self):
        mock_data = MagicMock()
        mock_data.ErrorCode = 0
        mock_data.Data = []
        mock_data.Fields = []
        mock_data.Codes = []
        mock_data.Times = []
        assert _wind_data_to_csv(mock_data) == "(无数据)"

    def test_time_series_format(self):
        mock_data = MagicMock()
        mock_data.ErrorCode = 0
        mock_data.Fields = ["close", "volume"]
        mock_data.Codes = ["000001.SZ"]
        mock_data.Times = ["2024-01-01", "2024-01-02"]
        mock_data.Data = [[100, 101], [1000, 2000]]
        csv = _wind_data_to_csv(mock_data)
        assert "Date" in csv
        assert "close" in csv
        assert "volume" in csv

    def test_cross_section_format(self):
        mock_data = MagicMock()
        mock_data.ErrorCode = 0
        mock_data.Fields = ["pe_ttm"]
        mock_data.Codes = ["000001.SZ", "600519.SH"]
        mock_data.Times = ["2024-01-01"]
        mock_data.Data = [[10, 20]]
        csv = _wind_data_to_csv(mock_data)
        assert "Code" in csv
        assert "pe_ttm" in csv


class MockWind:
    """模拟 WindPy.w 对象"""
    def __init__(self):
        self.wsd = MagicMock()
        self.wss = MagicMock()
        self.wset = MagicMock()
        self.edb = MagicMock()
        self.tdays = MagicMock()


class TestWindWsdTool:
    @pytest.fixture
    def tool(self):
        return WindWsdTool()

    @pytest.mark.asyncio
    async def test_successful_call(self, tool):
        mock_w = MockWind()
        mock_result = MagicMock()
        mock_result.ErrorCode = 0
        mock_result.Fields = ["close"]
        mock_result.Codes = ["000001.SZ"]
        mock_result.Times = ["2024-01-01"]
        mock_result.Data = [[100]]
        mock_w.wsd.return_value = mock_result

        with patch('app.tools.wind_tool._get_wind', return_value=mock_w):
            with patch('app.tools.wind_tool._run_sync', new_callable=AsyncMock, return_value=mock_result):
                result = await tool.execute(
                    codes="000001.SZ",
                    fields="close",
                    begin_date="2024-01-01",
                    end_date="2024-01-01",
                )
                assert result.error == ""
                assert "close" in result.output

    @pytest.mark.asyncio
    async def test_quota_exceeded(self, tool):
        with patch('app.tools.wind_tool._get_wind', side_effect=RuntimeError("quota exceeded")):
            result = await tool.execute(
                codes="000001.SZ",
                fields="close",
                begin_date="2024-01-01",
                end_date="2024-01-01",
            )
            assert "配额" in result.error


class TestWindWssTool:
    @pytest.fixture
    def tool(self):
        return WindWssTool()

    @pytest.mark.asyncio
    async def test_successful_call(self, tool):
        mock_w = MockWind()
        mock_result = MagicMock()
        mock_result.ErrorCode = 0
        mock_result.Fields = ["pe_ttm"]
        mock_result.Codes = ["000001.SZ", "600519.SH"]
        mock_result.Times = ["2024-01-01"]
        mock_result.Data = [[10, 20]]
        mock_w.wss.return_value = mock_result

        with patch('app.tools.wind_tool._get_wind', return_value=mock_w):
            with patch('app.tools.wind_tool._run_sync', new_callable=AsyncMock, return_value=mock_result):
                result = await tool.execute(
                    codes="000001.SZ,600519.SH",
                    fields="pe_ttm",
                )
                assert result.error == ""
                assert "pe_ttm" in result.output


class TestWindWsetTool:
    @pytest.fixture
    def tool(self):
        return WindWsetTool()

    @pytest.mark.asyncio
    async def test_successful_call(self, tool):
        mock_w = MockWind()
        mock_result = MagicMock()
        mock_result.ErrorCode = 0
        mock_result.Fields = ["wind_code", "sec_name"]
        mock_result.Codes = []
        mock_result.Times = []
        mock_result.Data = [[["000001.SZ", "600519.SH"], ["平安银行", "贵州茅台"]]]
        mock_w.wset.return_value = mock_result

        with patch('app.tools.wind_tool._get_wind', return_value=mock_w):
            with patch('app.tools.wind_tool._run_sync', new_callable=AsyncMock, return_value=mock_result):
                result = await tool.execute(
                    table_name="indexconstituent",
                    options="date=20240101;windcode=000300.SH",
                )
                assert result.error == ""
                assert "wind_code" in result.output


class TestWindEdbTool:
    @pytest.fixture
    def tool(self):
        return WindEdbTool()

    @pytest.mark.asyncio
    async def test_successful_call(self, tool):
        mock_w = MockWind()
        mock_result = MagicMock()
        mock_result.ErrorCode = 0
        mock_result.Fields = ["close"]
        mock_result.Codes = ["M0000138"]
        mock_result.Times = ["2024-01-01", "2024-01-02"]
        mock_result.Data = [[5.2, 5.3]]
        mock_w.edb.return_value = mock_result

        with patch('app.tools.wind_tool._get_wind', return_value=mock_w):
            with patch('app.tools.wind_tool._run_sync', new_callable=AsyncMock, return_value=mock_result):
                result = await tool.execute(
                    codes="M0000138",
                    begin_date="2024-01-01",
                    end_date="2024-01-02",
                )
                assert result.error == ""
                assert "close" in result.output


class TestWindTdaysTool:
    @pytest.fixture
    def tool(self):
        return WindTdaysTool()

    @pytest.mark.asyncio
    async def test_successful_call(self, tool):
        mock_w = MockWind()
        mock_result = MagicMock()
        mock_result.ErrorCode = 0
        mock_result.Fields = []
        mock_result.Codes = []
        mock_result.Times = ["2024-01-01", "2024-01-02"]
        mock_result.Data = []
        mock_w.tdays.return_value = mock_result

        with patch('app.tools.wind_tool._get_wind', return_value=mock_w):
            with patch('app.tools.wind_tool._run_sync', new_callable=AsyncMock, return_value=mock_result):
                result = await tool.execute(
                    begin_date="2024-01-01",
                    end_date="2024-01-02",
                )
                assert result.error == ""
