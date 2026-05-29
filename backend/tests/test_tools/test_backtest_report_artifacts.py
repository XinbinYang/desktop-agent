import base64
from pathlib import Path
from unittest.mock import patch

import pytest

from app.runtime_paths import runtime_dir
from app.tools.backtest_tool import BacktestReportTool


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


@pytest.mark.asyncio
async def test_backtest_report_returns_chart_artifact():
    def fake_generate_report(_result, output_path):
        md_path = Path(output_path)
        chart_path = md_path.with_suffix(".png")
        csv_path = md_path.with_suffix(".csv")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text("# report", encoding="utf-8")
        chart_path.write_bytes(PNG_BYTES)
        csv_path.write_text("date,value\n2024-01-01,1\n", encoding="utf-8")
        return {
            "md_path": str(md_path),
            "chart_path": str(chart_path),
            "csv_path": str(csv_path),
        }

    with patch("app.tools.backtest_tool._load_result", return_value={"final_value": 1}), \
         patch("app.tools.backtest_tool.generate_report", fake_generate_report):
        result = await BacktestReportTool().execute(
            strategy_name="sma_cross",
            codes="600519.SH",
            start_date="2024-01-01",
            session_id="report-session",
            agent_type="personal",
        )

    assert result.error == ""
    artifacts = result.metadata["artifacts"]
    image = next(item for item in artifacts if item["type"] == "image")
    assert image["url"].startswith("/preview/report-session/")
    assert image["mime_type"] == "image/png"
    assert any(item["type"] == "data" for item in artifacts)
    assert any(item["type"] == "code" for item in artifacts)
    assert Path(image["path"]).is_relative_to(runtime_dir("preview"))
