import os
import sys
from datetime import datetime, timedelta
from typing import Optional, Any, Callable, Union
from pathlib import Path

import pandas as pd

from app.tools.base import BaseTool, ToolResult

# 项目根目录与数据库路径 (wind_sync_tool.py 位于 backend/app/tools/，项目根目录需再向上两级)
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_QUANT_DB_PATH = _PROJECT_ROOT / "data" / "quant_db.sqlite"
_MARKET_DB_PATH = _PROJECT_ROOT / "data" / "market_data.db"

# WIND 字段映射
DAILY_PRICE_FIELDS = "open,high,low,close,volume,amt,vwap,pct_chg"
DAILY_PRICE_COLS = ["open", "high", "low", "close", "volume", "amount", "vwap", "pct_chg"]

DAILY_INDICATOR_FIELDS = "pe_ttm,pb_lf,ps_ttm,pcf_ncf_ttm,dividendyield,mkt_cap_ard,float_mkt_cap_ard,turn,free_turn"
DAILY_INDICATOR_COLS = ["pe_ttm", "pb", "ps_ttm", "pcf_ncf_ttm", "dividend_yield", "mkt_cap", "float_mkt_cap", "turn", "free_turn"]
# WIND→DB 字段映射
WIND_TO_DB_INDICATOR = {
    "pe_ttm": "pe_ttm",
    "pb_lf": "pb",
    "ps_ttm": "ps_ttm",
    "pcf_ncf_ttm": "pcf_ncf_ttm",
    "dividendyield": "dividend_yield",
    "mkt_cap_ard": "mkt_cap",
    "float_mkt_cap_ard": "float_mkt_cap",
    "turn": "turn",
    "free_turn": "free_turn",
}


def _ensure_wind():
    """确保 WindPy 已连接。"""
    windpy_path = os.environ.get("WINDPY_PATH", r"C:\Wind\Wind.NET.Client\WindNET\x64")
    if windpy_path not in sys.path:
        sys.path.insert(0, windpy_path)
    from WindPy import w
    if not w.isconnected():
        w.start()
    return w


def _yesterday() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def _get_local_latest_date_quant(stock_code: str, table: str) -> Optional[str]:
    """查询 quant_db 中某只股票在某表里的最新日期。"""
    if not _QUANT_DB_PATH.exists():
        return None
    import sqlite3
    conn = sqlite3.connect(str(_QUANT_DB_PATH))
    try:
        c = conn.cursor()
        c.execute(f"SELECT MAX(trade_date) FROM {table} WHERE stock_code = ?", (stock_code,))
        row = c.fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


def _get_local_latest_date_market(index_code: str, table: str = "china_equity_historical") -> Optional[str]:
    """查询 market_data.db 中某指数的最新日期。"""
    if not _MARKET_DB_PATH.exists():
        return None
    import sqlite3
    conn = sqlite3.connect(str(_MARKET_DB_PATH))
    try:
        c = conn.cursor()
        c.execute(f"SELECT MAX(date) FROM {table} WHERE index_code = ?", (index_code,))
        row = c.fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


def _parse_wsd_result(result) -> Optional[pd.DataFrame]:
    """将 WindPy wsd 结果解析为 DataFrame，index 为日期，columns 为字段。"""
    if result.ErrorCode != 0:
        return None
    # result.Data: list of lists, 每个内层列表是一个字段的时间序列
    # result.Times: list of datetime/date
    # result.Fields: list of field names
    data = {f: result.Data[i] for i, f in enumerate(result.Fields)}
    df = pd.DataFrame(data, index=pd.to_datetime(result.Times))
    df.index.name = "date"
    return df


# ---------------------------------------------------------------------------
# Shared helper — eliminates duplicated boilerplate across the three sync
# functions below.
# ---------------------------------------------------------------------------

# Type alias: a single item in an insert_specs list.
# Each tuple is (db_column_name, source), where source may be:
#   str              -> Wind field name to extract from the DataFrame row
#   list / tuple     -> fallback list of Wind field names (tried in order)
#   Any other value  -> constant to insert for every row
#   callable         -> zero-arg callable whose return value is inserted
InsertSpec = tuple[str, Any]


def _run_wsd_sync(
    db_path: Path,
    table_name: str,
    codes: list[str],
    fields: str,
    wsd_options: Optional[str],
    insert_specs: list[InsertSpec],
    latest_date_fn: Callable[[str, str], Optional[str]],
    date_col: str,
    code_col: str,
    start_date: Optional[str],
    end_date: str,
    *,
    quota_label: str = "WIND wsd",
) -> dict:
    """Generic WSD incremental-sync helper.

    Parameters
    ----------
    db_path : Path
        Path to the target SQLite database file.
    table_name : str
        Name of the table to upsert into.
    codes : list[str]
        Security / index codes to iterate over.
    fields : str
        Comma-separated WIND field names passed to ``w.wsd()``.
    wsd_options : str or None
        Optional trailing option string for ``w.wsd()`` (e.g. ``"PriceAdj=F"``).
    insert_specs : list[InsertSpec]
        Ordered list of ``(db_column, source)`` pairs that define every
        column in the INSERT statement *after* the mandatory date + code
        columns.  See the module-level docstring for the meaning of each
        source type.
    latest_date_fn : callable
        ``(code, table_name) -> str | None`` — returns the most recent date
        already present locally for this code, or ``None``.
    date_col : str
        Name of the date column in the target table (e.g. ``"trade_date"``).
    code_col : str
        Name of the code column in the target table (e.g. ``"stock_code"``).
    start_date : str or None
        Earliest date to request from WIND (``"YYYY-MM-DD"``).
    end_date : str
        Latest date to request from WIND (``"YYYY-MM-DD"``).
    quota_label : str
        Label used in the quota-exceeded error message.

    Returns
    -------
    dict
        Summary with keys ``"synced"``, ``"skipped"``, ``"errors"``.
    """
    w = _ensure_wind()
    summary: dict[str, list[str]] = {"synced": [], "skipped": [], "errors": []}

    for code in codes:
        # ---- determine actual start ----------------------------------------
        local_latest = latest_date_fn(code, table_name)
        if local_latest:
            next_day = (datetime.strptime(local_latest, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            actual_start = max(start_date, next_day) if start_date else next_day
        else:
            actual_start = start_date

        if not actual_start or actual_start > end_date:
            summary["skipped"].append(f"{code}: 本地已最新 ({local_latest})")
            continue

        # ---- fetch from WIND -----------------------------------------------
        if wsd_options:
            result = w.wsd(code, fields, actual_start, end_date, wsd_options)
        else:
            result = w.wsd(code, fields, actual_start, end_date)

        if result.ErrorCode != 0:
            err_msg = str(result.Data)
            if "quota exceeded" in err_msg.lower():
                summary["errors"].append(f"{code}: {quota_label} 配额已用完，无法同步。")
                break  # 配额用完，停止后续同步
            summary["errors"].append(f"{code}: WIND 错误 {result.ErrorCode} - {err_msg}")
            continue

        df = _parse_wsd_result(result)
        if df is None or df.empty:
            summary["skipped"].append(f"{code}: 无新数据 ({actual_start} ~ {end_date})")
            continue

        # ---- upsert to SQLite ----------------------------------------------
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        try:
            c = conn.cursor()
            inserted = 0

            spec_cols = [col for col, _ in insert_specs]
            all_cols = [date_col, code_col] + spec_cols
            col_names = ", ".join(all_cols)
            placeholders = ", ".join(["?"] * len(all_cols))

            for dt, row in df.iterrows():
                date_str = dt.strftime("%Y-%m-%d")

                c.execute(
                    f"SELECT 1 FROM {table_name} WHERE {code_col} = ? AND {date_col} = ?",
                    (code, date_str),
                )
                if c.fetchone():
                    continue

                values: list[Any] = [date_str, code]
                for _, source in insert_specs:
                    if isinstance(source, str):
                        # Wind field name — extract from DataFrame row
                        val = row.get(source)
                        values.append(float(val) if pd.notna(val) else None)
                    elif isinstance(source, (list, tuple)):
                        # Fallback list of field names — try each in order
                        val = None
                        for f in source:
                            val = row.get(f)
                            if pd.notna(val):
                                break
                        values.append(float(val) if pd.notna(val) else None)
                    elif callable(source):
                        values.append(source())
                    else:
                        values.append(source)

                c.execute(
                    f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})",
                    values,
                )
                inserted += 1

            conn.commit()
            summary["synced"].append(f"{code}: {actual_start}~{end_date} 插入 {inserted} 条")
        finally:
            conn.close()

    return summary


# ---------------------------------------------------------------------------
# Thin wrappers — each is now a one-liner delegating to _run_wsd_sync().
# ---------------------------------------------------------------------------

def _sync_a_stock_daily(codes: list[str], start_date: Optional[str], end_date: str) -> dict:
    """同步 A 股日线数据到 quant_db.daily_prices。"""
    return _run_wsd_sync(
        db_path=_QUANT_DB_PATH,
        table_name="daily_prices",
        codes=codes,
        fields=DAILY_PRICE_FIELDS,
        wsd_options="PriceAdj=F",
        insert_specs=[
            ("open", "open"),
            ("high", "high"),
            ("low", "low"),
            ("close", "close"),
            ("volume", "volume"),
            ("amount", ["amount", "amt"]),
            ("vwap", "vwap"),
            ("pct_chg", "pct_chg"),
            ("adj_factor", None),
            ("created_at", lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ],
        latest_date_fn=_get_local_latest_date_quant,
        date_col="trade_date",
        code_col="stock_code",
        start_date=start_date,
        end_date=end_date,
    )


def _sync_a_stock_indicators(codes: list[str], start_date: Optional[str], end_date: str) -> dict:
    """同步 A 股技术指标到 quant_db.daily_indicators。"""
    return _run_wsd_sync(
        db_path=_QUANT_DB_PATH,
        table_name="daily_indicators",
        codes=codes,
        fields=DAILY_INDICATOR_FIELDS,
        wsd_options=None,
        insert_specs=[
            ("pe_ttm", "pe_ttm"),
            ("pb", "pb_lf"),
            ("ps_ttm", "ps_ttm"),
            ("pcf_ncf_ttm", "pcf_ncf_ttm"),
            ("dividend_yield", "dividendyield"),
            ("mkt_cap", "mkt_cap_ard"),
            ("float_mkt_cap", "float_mkt_cap_ard"),
            ("turn", "turn"),
            ("free_turn", "free_turn"),
            ("created_at", lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ],
        latest_date_fn=_get_local_latest_date_quant,
        date_col="trade_date",
        code_col="stock_code",
        start_date=start_date,
        end_date=end_date,
    )


def _sync_china_index(codes: list[str], start_date: Optional[str], end_date: str) -> dict:
    """同步中国指数数据到 market_data.db.china_equity_historical。"""
    return _run_wsd_sync(
        db_path=_MARKET_DB_PATH,
        table_name="china_equity_historical",
        codes=codes,
        fields="close",
        wsd_options=None,
        insert_specs=[
            ("index_name", None),
            ("close_price", "close"),
            ("source_file", "wind_sync"),
        ],
        latest_date_fn=_get_local_latest_date_market,
        date_col="date",
        code_col="index_code",
        start_date=start_date,
        end_date=end_date,
    )


class WindSyncTool(BaseTool):
    name = "wind_sync"
    description = (
        "从 WIND 抓取最新数据并增量同步到本地数据库。支持 A 股日线、A 股技术指标、中国指数。"
        "自动检测本地缺失的日期范围，只同步新数据，避免重复和浪费 WIND 配额。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "sync_type": {
                "type": "string",
                "description": "同步类型: a_stock_daily(A股日线→quant_db.daily_prices), a_stock_indicators(A股技术指标→quant_db.daily_indicators), china_index(中国指数→market_data.db.china_equity_historical)",
                "enum": ["a_stock_daily", "a_stock_indicators", "china_index"],
            },
            "codes": {
                "type": "string",
                "description": "代码列表，逗号分隔。A股如 000001.SZ,600519.SH；指数如 000300.SH,000905.SH",
            },
            "start_date": {
                "type": "string",
                "description": "开始日期 YYYY-MM-DD，可选。默认从本地最新日期的下一天开始（即只同步缺失数据）。",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期 YYYY-MM-DD，可选。默认昨天。",
            },
        },
        "required": ["sync_type", "codes"],
    }

    async def execute(
        self,
        sync_type: str,
        codes: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> ToolResult:
        try:
            code_list = [c.strip() for c in codes.split(",") if c.strip()]
            if not code_list:
                return ToolResult(error="codes 参数为空")

            end = end_date or _yesterday()

            if sync_type == "a_stock_daily":
                summary = _sync_a_stock_daily(code_list, start_date, end)
            elif sync_type == "a_stock_indicators":
                summary = _sync_a_stock_indicators(code_list, start_date, end)
            elif sync_type == "china_index":
                summary = _sync_china_index(code_list, start_date, end)
            else:
                return ToolResult(error=f"未知的 sync_type: {sync_type}")

            lines = []
            if summary["synced"]:
                lines.append("【同步成功】")
                lines.extend(summary["synced"])
            if summary["skipped"]:
                lines.append("【跳过（已最新或无数据）】")
                lines.extend(summary["skipped"])
            if summary["errors"]:
                lines.append("【错误】")
                lines.extend(summary["errors"])

            if not lines:
                return ToolResult(output="无数据需要同步。")
            return ToolResult(output="\n".join(lines))

        except Exception as e:
            return ToolResult(error=f"同步异常: {e}")
