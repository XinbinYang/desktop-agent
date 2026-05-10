from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from app.tools.backtest_tool import BacktestReportTool, _save_result


@pytest.mark.asyncio
async def test_backtest_report_is_written_to_mounted_preview_dir(tmp_path):
    cache_dir = tmp_path / "sessions" / "backtest"
    preview_dir = tmp_path / "preview"
    cache_dir.mkdir(parents=True)
    preview_dir.mkdir()
    result_data = {
        "strategy": "sma_cross",
        "final_value": 101000,
        "nav_df": pd.DataFrame({"value": [100000, 101000]}),
    }

    with patch("app.tools.backtest_tool._BACKTEST_CACHE_DIR", cache_dir), \
         patch("app.tools.backtest_tool._PREVIEW_DIR", preview_dir), \
         patch("app.tools.backtest_tool.generate_report") as mock_generate:
        mock_generate.return_value = {
            "md_path": str(preview_dir / "report.md"),
            "chart_path": str(preview_dir / "report.png"),
            "csv_path": str(preview_dir / "report.csv"),
        }
        _save_result("sess_1", "sma_cross", "600519.SH", "2024-01-01", result_data)
        result = await BacktestReportTool().execute(
            "sma_cross",
            "600519.SH",
            "2024-01-01",
            session_id="sess_1",
        )

    assert result.error == ""
    output_path = Path(mock_generate.call_args.args[1])
    assert output_path.parent == preview_dir
