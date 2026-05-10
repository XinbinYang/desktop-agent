import backtrader as bt
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from app.strategies import get_strategy, list_strategies


class PortfolioValueAnalyzer(bt.Analyzer):
    """记录每日净值曲线"""
    def __init__(self):
        self.dates = []
        self.values = []
        self.cash = []

    def next(self):
        self.dates.append(self.datas[0].datetime.date(0))
        self.values.append(self.strategy.broker.getvalue())
        self.cash.append(self.strategy.broker.getcash())

    def get_analysis(self):
        return {
            'dates': self.dates,
            'values': self.values,
            'cash': self.cash,
        }


def run_backtest(
    strategy_name: str,
    df: pd.DataFrame,
    initial_cash: float = 100000.0,
    commission: float = 0.0003,
    slippage: float = 0.0,
    **strategy_params
) -> Dict[str, Any]:
    """
    运行 backtrader 回测。

    Args:
        strategy_name: 策略名称，如 'sma_cross'
        df: 包含开高低收量的 DataFrame，index 为 datetime
        initial_cash: 初始资金
        commission: 佣金率（默认万3）
        slippage: 滑点（按价格百分比）
        **strategy_params: 策略参数，如 fast=5, slow=20

    Returns:
        回测结果字典
    """
    strategy_cls = get_strategy(strategy_name)
    if not strategy_cls:
        raise ValueError(f"未知策略: {strategy_name}，可用策略: {list_strategies()}")

    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_cls, **strategy_params)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)

    if slippage > 0:
        cerebro.broker.set_slippage_perc(perc=slippage)

    # 数据校验
    required_cols = {'open', 'high', 'low', 'close', 'volume'}
    df_cols_lower = {c.lower() for c in df.columns}
    if not required_cols.issubset(df_cols_lower):
        missing = required_cols - df_cols_lower
        raise ValueError(f"DataFrame 缺少必要列: {missing}")

    # 标准化列名
    col_map = {c.lower(): c for c in df.columns}
    df = df.rename(columns={col_map[c]: c for c in required_cols if c in col_map})

    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.02)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(PortfolioValueAnalyzer, _name='portfolio')

    results = cerebro.run()
    strat = results[0]

    # 收集结果
    portfolio = strat.analyzers.portfolio.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    returns = strat.analyzers.returns.get_analysis()

    final_value = strat.broker.getvalue()
    total_return_pct = (final_value / initial_cash - 1) * 100

    # 计算年化收益
    n_days = len(portfolio['dates'])
    if n_days > 1:
        annual_return = ((1 + total_return_pct / 100) ** (252 / n_days) - 1) * 100
    else:
        annual_return = 0

    # 计算胜率
    trade_stats = {}
    if trades and 'total' in trades:
        total = trades['total'].get('total', 0)
        won = trades.get('won', {}).get('total', 0)
        lost = trades.get('lost', {}).get('total', 0)
        trade_stats = {
            'total': total,
            'won': won,
            'lost': lost,
            'win_rate': (won / total * 100) if total > 0 else 0,
        }
    else:
        trade_stats = {'total': 0, 'won': 0, 'lost': 0, 'win_rate': 0}

    # 净值曲线 DataFrame
    nav_df = pd.DataFrame({
        'date': portfolio['dates'],
        'value': portfolio['values'],
    })
    nav_df['return_pct'] = nav_df['value'].pct_change().fillna(0) * 100
    nav_df['cumulative_return'] = (nav_df['value'] / initial_cash - 1) * 100

    # 计算最大回撤序列
    peak = nav_df['value'].cummax()
    drawdown_series = (nav_df['value'] - peak) / peak * 100
    nav_df['drawdown'] = drawdown_series

    return {
        'strategy': strategy_name,
        'params': strategy_params,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'total_return_pct': round(total_return_pct, 2),
        'annual_return_pct': round(annual_return, 2),
        'sharpe_ratio': round(sharpe.get('sharperatio', 0) or 0, 3),
        'max_drawdown_pct': round(drawdown.get('max', {}).get('drawdown', 0) or 0, 2),
        'max_drawdown_days': drawdown.get('max', {}).get('len', 0) or 0,
        'trades': trade_stats,
        'nav_df': nav_df,
        'n_days': n_days,
    }


def generate_report(result: Dict[str, Any], output_path: str):
    """生成 Markdown + CSV 报告"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    nav_df = result['nav_df']
    strategy = result['strategy']

    # 保存净值曲线 CSV
    csv_path = output_path.replace('.md', '_nav.csv')
    nav_df.to_csv(csv_path, index=False, encoding='utf-8')

    # 画图
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 1]})

    # 收益曲线
    ax1 = axes[0]
    ax1.plot(nav_df['date'], nav_df['cumulative_return'], linewidth=1.5, color='#1f77b4')
    ax1.fill_between(nav_df['date'], nav_df['cumulative_return'], 0, alpha=0.2, color='#1f77b4')
    ax1.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax1.set_title(f'Strategy: {strategy} | Total Return: {result["total_return_pct"]}%', fontsize=12)
    ax1.set_ylabel('Cumulative Return (%)')
    ax1.grid(True, alpha=0.3)

    # 回撤曲线
    ax2 = axes[1]
    ax2.fill_between(nav_df['date'], nav_df['drawdown'], 0, alpha=0.4, color='red')
    ax2.set_title(f'Max Drawdown: {result["max_drawdown_pct"]}%')
    ax2.set_ylabel('Drawdown (%)')
    ax2.set_xlabel('Date')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    chart_path = output_path.replace('.md', '_chart.png')
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close()

    # Markdown 报告
    trades = result['trades']
    md = f"""# 策略回测报告

## 基本信息

| 指标 | 数值 |
|------|------|
| 策略名称 | {strategy} |
| 策略参数 | {result['params']} |
| 初始资金 | {result['initial_cash']:,.0f} |
| 最终资金 | {result['final_value']:,.2f} |
| 总收益率 | {result['total_return_pct']}% |
| 年化收益率 | {result['annual_return_pct']}% |
| 夏普比率 | {result['sharpe_ratio']} |
| 最大回撤 | {result['max_drawdown_pct']}% |
| 回撤天数 | {result['max_drawdown_days']} |
| 交易次数 | {trades['total']} |
| 盈利次数 | {trades['won']} |
| 亏损次数 | {trades['lost']} |
| 胜率 | {trades['win_rate']:.1f}% |
| 回测天数 | {result['n_days']} |

## 收益曲线

![收益曲线]({chart_path.split('/')[-1]})

## 数据下载

- [净值曲线 CSV]({csv_path.split('/')[-1]})

---
*Generated by Desktop Agent Backtest Engine*
"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(md)

    return {
        'md_path': output_path,
        'chart_path': chart_path,
        'csv_path': csv_path,
    }
