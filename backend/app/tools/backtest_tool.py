import json
import sqlite3
from typing import Any, Dict, Optional

import pandas as pd

from app.backtest_engine import generate_report, run_backtest
from app.runtime_paths import runtime_dir
from app.strategies import get_strategy_info, list_strategies
from app.tools.base import BaseTool, ToolResult
from app.tools.wind_runtime import get_wind_client

_BACKTEST_CACHE_DIR = runtime_dir("sessions") / "backtest"
_BACKTEST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_PREVIEW_DIR = runtime_dir("preview")

# 本地数据库路径 (backtest_tool.py 位于 backend/app/tools/，项目根目录需再向上两级)
_LOCAL_DATA_DIR = runtime_dir("data")
_QUANT_DB_PATH = _LOCAL_DATA_DIR / "quant_db.sqlite"
_MARKET_DB_PATH = _LOCAL_DATA_DIR / "market_data.db"


def _cache_key(session_id: str, strategy_name: str, codes: str, start_date: str) -> str:
    return f"{session_id}_{strategy_name}_{codes.replace('.', '_')}_{start_date}"


def _save_result(session_id: str, strategy_name: str, codes: str, start_date: str, result: dict):
    key = _cache_key(session_id, strategy_name, codes, start_date)
    path = _BACKTEST_CACHE_DIR / f"{key}.json"
    # nav_df 不能直接序列化，需要转换
    save_data = dict(result)
    if 'nav_df' in save_data:
        save_data['nav_df'] = save_data['nav_df'].to_dict(orient='records')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(save_data, f, ensure_ascii=False, default=str, indent=2)


def _load_result(session_id: str, strategy_name: str, codes: str, start_date: str) -> dict | None:
    key = _cache_key(session_id, strategy_name, codes, start_date)
    path = _BACKTEST_CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'nav_df' in data:
        data['nav_df'] = pd.DataFrame(data['nav_df'])
    return data


def _get_data_from_quant_db(code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """从 quant_db.sqlite 读取 A 股日线数据 (OHLCV)。"""
    if not _QUANT_DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(_QUANT_DB_PATH))
    try:
        df = pd.read_sql(
            """SELECT trade_date as date, open, high, low, close, volume
               FROM daily_prices
               WHERE stock_code = ? AND trade_date >= ? AND trade_date <= ?
               ORDER BY trade_date""",
            conn, params=(code, start_date, end_date)
        )
        if df.empty:
            return None
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        df = df.dropna()
        return df
    finally:
        conn.close()


def _query_ohlcv(conn, table: str, code_col: str, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """查询带有完整 OHLCV 的表。"""
    df = pd.read_sql(
        f"""SELECT date, open_price as open, high_price as high, low_price as low, close_price as close, volume
           FROM {table}
           WHERE {code_col} = ? AND date >= ? AND date <= ?
           ORDER BY date""",
        conn, params=(code, start_date, end_date)
    )
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').dropna()
        return df
    return None


def _query_close_only(conn, table: str, code_col: str, code: str, start_date: str, end_date: str,
                      close_col: str = "close_price") -> Optional[pd.DataFrame]:
    """查询只有 close 价格的表，自动填充 open/high/low/volume。"""
    df = pd.read_sql(
        f"""SELECT date, {close_col} as close
           FROM {table}
           WHERE {code_col} = ? AND date >= ? AND date <= ?
           ORDER BY date""",
        conn, params=(code, start_date, end_date)
    )
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        df['open'] = df['close']
        df['high'] = df['close']
        df['low'] = df['close']
        df['volume'] = 0
        df = df[['open', 'high', 'low', 'close', 'volume']].dropna()
        return df
    return None


def _get_data_from_market_db(code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """从 market_data.db 读取全球/中国大类资产数据。"""
    if not _MARKET_DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(_MARKET_DB_PATH))
    try:
        # 1. 完整 OHLCV 表
        df = _query_ohlcv(conn, "index_historical_prices", "ticker", code, start_date, end_date)
        if df is not None:
            return df

        # 2-13. close-only 表统一查询
        close_only_tables = [
            ("china_equity_historical", "index_code", "close_price"),
            ("global_equity_indices", "ticker", "close_price"),
            ("global_commodity_futures", "ticker", "close_price"),
            ("global_fx_rates", "pair", "close_price"),
            ("global_bond_yields", "bond_code", "yield"),
            ("etf_historical_prices", "ticker", "close_price"),
            ("bond_futures_daily", "asset_code", "close"),
            ("bond_etfs_daily", "asset_code", "close"),
            ("low_corr_bonds", "asset_code", "yield"),
            ("china_bond_index", "symbol", "close_price"),
            ("commodity_index_historical", "index_code", "close_price"),
            ("unified_asset_prices", "asset_code", "price"),
        ]
        for table, code_col, close_col in close_only_tables:
            df = _query_close_only(conn, table, code_col, code, start_date, end_date, close_col)
            if df is not None:
                return df

        return None
    finally:
        conn.close()


def _get_wind_data(codes: str, start_date: str, end_date: str) -> pd.DataFrame:
    """通过 WIND 获取历史数据，构造 backtrader 可用的 DataFrame。"""
    w = get_wind_client()

    fields = "open,high,low,close,volume"
    result = w.wsd(codes, fields, start_date, end_date, "PriceAdj=F")

    if result.ErrorCode != 0:
        raise RuntimeError(f"WIND 数据获取失败: {result.Data}")

    # 构造 DataFrame
    # result.Data: [[open1, open2, ...], [high1, high2, ...], ...]
    # result.Times: [date1, date2, ...]
    data_dict = {
        'open': result.Data[0],
        'high': result.Data[1],
        'low': result.Data[2],
        'close': result.Data[3],
        'volume': result.Data[4],
    }
    df = pd.DataFrame(data_dict, index=pd.to_datetime(result.Times))
    df = df.dropna()
    return df


_MIN_BACKTEST_ROWS = 10


def _get_data(codes: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Resolve backtest data: prefer local DBs, only fall back to WIND when
    no local rows exist at all. Sparse local data (1..MIN-1 rows) is reported
    as a hard error so we don't silently spend WIND quota on the same code
    we already partially have locally — the user should sync first.
    """
    df = _get_data_from_quant_db(codes, start_date, end_date)
    if df is not None and len(df) >= _MIN_BACKTEST_ROWS:
        return df
    if df is not None and len(df) > 0:
        raise ValueError(
            f"本地 quant_db 仅有 {len(df)} 条 {codes} 数据（< {_MIN_BACKTEST_ROWS}）。"
            f"请先用 wind_sync 工具补齐本地数据，避免重复消耗 WIND 配额。"
        )

    df = _get_data_from_market_db(codes, start_date, end_date)
    if df is not None and len(df) >= _MIN_BACKTEST_ROWS:
        return df
    if df is not None and len(df) > 0:
        raise ValueError(
            f"本地 market_data.db 仅有 {len(df)} 条 {codes} 数据（< {_MIN_BACKTEST_ROWS}）。"
            f"请先用 wind_sync 工具补齐本地数据，避免重复消耗 WIND 配额。"
        )

    return _get_wind_data(codes, start_date, end_date)


class StrategyListTool(BaseTool):
    name = "strategy_list"
    description = "列出所有可用的策略模板及其默认参数。"
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self) -> ToolResult:
        strategies = []
        for name in list_strategies():
            info = get_strategy_info(name)
            params_str = ", ".join([f"{p['name']}={p['default']}" for p in info.get('params', [])])
            strategies.append(f"- {name}: {params_str}")
        return ToolResult(output="可用策略模板:\n" + "\n".join(strategies))


class BacktestRunTool(BaseTool):
    name = "backtest_run"
    description = (
        "运行策略回测。优先从本地量化数据库获取历史数据，本地无数据时回退到 WIND。"
        "常用策略: sma_cross(双均线), macd(MACD), rsi(RSI), momentum(动量), "
        "bollinger(布林带), turtle(海龟交易), dual_thrust(Dual Thrust)。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "strategy_name": {"type": "string", "description": "策略名称，如 sma_cross"},
            "codes": {"type": "string", "description": "资产代码，如 600519.SH(A股), ^GSPC(美股指数), HSI(港股), WTI_Crude(商品), EURUSD(外汇), US_Bond_10Y(债券)"},
            "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
            "initial_cash": {"type": "number", "description": "初始资金，默认 100000", "default": 100000},
            "commission": {"type": "number", "description": "佣金率，默认 0.0003（万3）", "default": 0.0003},
            "params": {"type": "object", "description": "策略参数字典，如 {\"fast\": 5, \"slow\": 20}", "default": {}}
        },
        "required": ["strategy_name", "codes", "start_date", "end_date"]
    }

    async def execute(self, strategy_name: str, codes: str, start_date: str, end_date: str,
                      initial_cash: float = 100000, commission: float = 0.0003, params: dict = None,
                      session_id: str = "default") -> ToolResult:
        try:
            params = params or {}
            df = _get_data(codes, start_date, end_date)
            if len(df) < 10:
                return ToolResult(error=f"数据量不足 ({len(df)} 条)，无法回测")

            result = run_backtest(
                strategy_name=strategy_name,
                df=df,
                initial_cash=initial_cash,
                commission=commission,
                **params
            )

            # 保存结果供 report 工具使用（持久化）
            _save_result(session_id or 'default', strategy_name, codes, start_date, result)

            # 生成简要文本输出
            trades = result['trades']
            summary = (
                f"策略: {strategy_name} | 标的: {codes} | 周期: {start_date} ~ {end_date}\n"
                f"初始资金: {result['initial_cash']:,.0f} → 最终: {result['final_value']:,.2f}\n"
                f"总收益率: {result['total_return_pct']}% | 年化: {result['annual_return_pct']}%\n"
                f"夏普比率: {result['sharpe_ratio']} | 最大回撤: {result['max_drawdown_pct']}%\n"
                f"交易次数: {trades['total']} (盈 {trades['won']} / 亏 {trades['lost']}) | 胜率: {trades['win_rate']:.1f}%\n"
                f"回测天数: {result['n_days']}\n"
                f"---\n"
                f"使用 backtest_report 工具可生成详细报告（含收益曲线图、回撤图、CSV数据）"
            )
            return ToolResult(output=summary)
        except ValueError as e:
            return ToolResult(error=f"回测参数错误: {e}")
        except RuntimeError as e:
            err_str = str(e)
            if "quota exceeded" in err_str.lower():
                return ToolResult(error="WIND wsd 每日配额已用完，无法获取历史数据进行回测。建议明日再试或联系管理员增加配额。")
            return ToolResult(error=f"回测运行错误: {err_str}")
        except Exception as e:
            return ToolResult(error=f"回测异常: {e}")


class BacktestReportTool(BaseTool):
    name = "backtest_report"
    description = "为最近一次回测生成详细报告（Markdown + 收益曲线图 + 净值CSV），保存到 preview/ 目录。"
    parameters = {
        "type": "object",
        "properties": {
            "strategy_name": {"type": "string", "description": "策略名称"},
            "codes": {"type": "string", "description": "资产代码"},
            "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD"}
        },
        "required": ["strategy_name", "codes", "start_date"]
    }

    async def execute(self, strategy_name: str, codes: str, start_date: str, session_id: str = "default") -> ToolResult:
        result = _load_result(session_id, strategy_name, codes, start_date)
        if not result:
            return ToolResult(error="未找到回测结果，请先运行 backtest_run")

        preview_dir = _PREVIEW_DIR
        preview_dir.mkdir(exist_ok=True)
        safe_name = f"{strategy_name}_{codes.replace('.', '_')}".replace('^', '')
        output_path = str(preview_dir / f"{safe_name}_report.md")

        try:
            paths = generate_report(result, output_path)
            return ToolResult(
                output=f"报告已生成:\n- Markdown: {paths['md_path']}\n- 图表: {paths['chart_path']}\n- 数据: {paths['csv_path']}",
                base64_image=None  # 如有需要可以读取图表返回
            )
        except Exception as e:
            return ToolResult(error=f"报告生成失败: {e}")
