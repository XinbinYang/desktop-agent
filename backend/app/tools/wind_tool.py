import asyncio
import io
from typing import Any, Dict, Optional
from app.tools.base import BaseTool, ToolResult
from app.tools.wind_runtime import get_wind_client

# 全局单例
_wind_client = None
_wind_connected = False


def _ensure_windpy_path():
    """确保 WindPy 所在目录在 Python 路径中。"""
    # Kept for compatibility with tests/older imports. Discovery now lives in
    # wind_runtime so all Wind callers share the same path and CWD handling.
    return None


def _get_wind():
    """获取已连接的 WindPy 实例（懒启动）。"""
    global _wind_client, _wind_connected
    if _wind_client is not None and _wind_connected:
        return _wind_client
    _wind_client = get_wind_client()
    _wind_connected = True
    return _wind_client


def _wind_data_to_csv(wind_data, default_index_name: str = "") -> str:
    """将 WindData 对象转为 CSV 字符串。"""
    import pandas as pd

    if wind_data.ErrorCode != 0:
        err_msg = ""
        if wind_data.Data and isinstance(wind_data.Data, list) and len(wind_data.Data) > 0:
            try:
                err_msg = str(wind_data.Data[0][0]) if wind_data.Data[0] else ""
            except Exception:
                err_msg = str(wind_data.Data)
        raise RuntimeError(f"Wind API 错误 (ErrorCode={wind_data.ErrorCode}): {err_msg}")

    data = wind_data.Data
    fields = wind_data.Fields or []
    codes = wind_data.Codes or []
    times = wind_data.Times or []

    if not data:
        return "(无数据)"

    # 判断数据维度构造 DataFrame
    if times and len(times) > 1:
        # 时间序列数据（wsd / edb / wsi）
        # data 外层是字段，内层是时间
        df = pd.DataFrame({fields[i]: data[i] for i in range(min(len(fields), len(data)))}, index=times)
        df.index.name = "Date"
    elif codes and len(codes) > 1 and len(times) <= 1:
        # 多代码截面数据（wss）
        # data 外层是字段，内层是代码
        df = pd.DataFrame({fields[i]: data[i] for i in range(min(len(fields), len(data)))}, index=codes)
        df.index.name = "Code"
    else:
        # 单代码截面 或 数据集（wset）
        # 尝试按行优先构造
        if len(data) == len(fields):
            # 行=字段，需要转置为 列=字段
            df = pd.DataFrame({fields[i]: data[i] for i in range(len(fields))})
        elif len(data) > 0 and len(data[0]) == len(fields):
            # 行=记录，列=字段
            df = pd.DataFrame(data, columns=fields)
        else:
            df = pd.DataFrame(data)
            if len(df.columns) == len(fields):
                df.columns = fields

        if codes and len(codes) == 1 and "code" not in [str(c).lower() for c in df.columns]:
            df.insert(0, "code", codes[0])

    buf = io.StringIO()
    df.to_csv(buf, encoding="utf-8")
    return buf.getvalue()


def _run_sync(func, *args, **kwargs):
    """在线程池中运行同步的 WindPy 调用。"""
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, func, *args, **kwargs)


# ====== 工具实现 ======

class WindWsdTool(BaseTool):
    name = "wind_wsd"
    description = (
        "获取 WIND 历史序列数据（日线/周线/月线等）。"
        "常用字段: close(收盘价), open(开盘价), high(最高价), low(最低价), volume(成交量), "
        "amt(成交额), pe_ttm(滚动市盈率), pb_lf(市净率), mkt_cap_ard(总市值), turn(换手率)。"
        "注意: 该接口有每日调用配额限制，超出配额会报错。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "codes": {"type": "string", "description": "股票/债券/期货代码，如 000001.SZ 或 000001.SZ,600519.SH"},
            "fields": {"type": "string", "description": "字段名，多个用逗号分隔，如 close,volume,pe_ttm"},
            "begin_date": {"type": "string", "description": "开始日期，格式 YYYY-MM-DD，如 2024-01-01"},
            "end_date": {"type": "string", "description": "结束日期，格式 YYYY-MM-DD，如 2024-06-01"},
            "options": {"type": "string", "description": "可选参数，如 Period=M;PriceAdj=F，默认空字符串", "default": ""}
        },
        "required": ["codes", "fields", "begin_date", "end_date"]
    }

    async def execute(self, codes: str, fields: str, begin_date: str, end_date: str, options: str = "") -> ToolResult:
        try:
            w = _get_wind()
            result = await _run_sync(w.wsd, codes, fields, begin_date, end_date, options)
            csv_text = _wind_data_to_csv(result)
            return ToolResult(output=csv_text)
        except RuntimeError as e:
            err_str = str(e)
            if "quota exceeded" in err_str.lower() or "-40522017" in err_str:
                return ToolResult(
                    error=f"WIND 每日 wsd 调用配额已用完。建议改用 wind_wss 获取截面数据，或缩小日期范围后重试。原始错误: {err_str}"
                )
            return ToolResult(error=err_str)
        except Exception as e:
            return ToolResult(error=f"Wind 调用异常: {e}")


class WindWssTool(BaseTool):
    name = "wind_wss"
    description = (
        "获取 WIND 截面快照数据（某一时间点的多股多字段指标）。"
        "无配额限制，推荐优先使用。"
        "常用字段: pe_ttm(滚动市盈率), pb_lf(市净率), ps_ttm(市销率), mkt_cap_ard(总市值), "
        "ev(企业价值), dividendyield(股息率), roe_avg(净资产收益率), eps_ttm(每股收益), "
        "total_shares(总股本), free_float_shares(流通股本), industry_citic(中信行业)。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "codes": {"type": "string", "description": "股票/债券/期货代码，支持多代码逗号分隔，如 000001.SZ,000858.SZ,600519.SH"},
            "fields": {"type": "string", "description": "字段名，多个用逗号分隔，如 pe_ttm,pb_lf,mkt_cap_ard"},
            "options": {"type": "string", "description": "可选参数，如 tradeDate=20240105;PriceAdj=F，默认空字符串", "default": ""}
        },
        "required": ["codes", "fields"]
    }

    async def execute(self, codes: str, fields: str, options: str = "") -> ToolResult:
        try:
            w = _get_wind()
            result = await _run_sync(w.wss, codes, fields, options)
            csv_text = _wind_data_to_csv(result)
            return ToolResult(output=csv_text)
        except Exception as e:
            return ToolResult(error=f"Wind 调用异常: {e}")


class WindWsetTool(BaseTool):
    name = "wind_wset"
    description = (
        "获取 WIND 数据集（如指数成分股、行业分类、基金列表、A股列表等）。"
        "常用 tableName: indexconstituent(指数成分股), sectorconstituent(行业成分股), "
        "date=20240105;windcode=000300.SH 可查询沪深300成分股。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "table_name": {"type": "string", "description": "数据集名称，如 indexconstituent, sectorconstituent"},
            "options": {"type": "string", "description": "查询参数，如 date=20240105;windcode=000300.SH", "default": ""}
        },
        "required": ["table_name"]
    }

    async def execute(self, table_name: str, options: str = "") -> ToolResult:
        try:
            w = _get_wind()
            result = await _run_sync(w.wset, table_name, options)
            csv_text = _wind_data_to_csv(result)
            return ToolResult(output=csv_text)
        except Exception as e:
            return ToolResult(error=f"Wind 调用异常: {e}")


class WindEdbTool(BaseTool):
    name = "wind_edb"
    description = (
        "获取 WIND 经济数据库（EDB）宏观指标时间序列。"
        "常用指标代码: M0000138(中国GDP同比), M0001227(CPI同比), M0001388(PMI), "
        "M0004271(社会融资规模), M0004273(M2同比), M0024274(十年期国债收益率), "
        "M0061355(美元兑人民币中间价), M0000185(工业增加值同比)。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "codes": {"type": "string", "description": "宏观指标代码，支持多代码逗号分隔，如 M0000138,M0001227"},
            "begin_date": {"type": "string", "description": "开始日期，格式 YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "结束日期，格式 YYYY-MM-DD"},
            "options": {"type": "string", "description": "可选参数，默认空字符串", "default": ""}
        },
        "required": ["codes", "begin_date", "end_date"]
    }

    async def execute(self, codes: str, begin_date: str, end_date: str, options: str = "") -> ToolResult:
        try:
            w = _get_wind()
            result = await _run_sync(w.edb, codes, begin_date, end_date, options)
            csv_text = _wind_data_to_csv(result)
            return ToolResult(output=csv_text)
        except Exception as e:
            return ToolResult(error=f"Wind 调用异常: {e}")


class WindTdaysTool(BaseTool):
    name = "wind_tdays"
    description = "获取指定日期范围内的交易日历。"
    parameters = {
        "type": "object",
        "properties": {
            "begin_date": {"type": "string", "description": "开始日期，格式 YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "结束日期，格式 YYYY-MM-DD"},
            "options": {"type": "string", "description": "可选参数，如 Days=Alldays 返回所有日期，默认空字符串", "default": ""}
        },
        "required": ["begin_date", "end_date"]
    }

    async def execute(self, begin_date: str, end_date: str, options: str = "") -> ToolResult:
        try:
            w = _get_wind()
            result = await _run_sync(w.tdays, begin_date, end_date, options)
            csv_text = _wind_data_to_csv(result)
            return ToolResult(output=csv_text)
        except Exception as e:
            return ToolResult(error=f"Wind 调用异常: {e}")
