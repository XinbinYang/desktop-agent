import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from app.backtest_engine import run_backtest, generate_report
from app.strategies import get_strategy


class TestRunBacktest:
    @pytest.fixture
    def sample_df(self):
        """构造一个有效的 OHLCV DataFrame（50 个交易日）"""
        dates = pd.date_range('2024-01-01', periods=50, freq='B')
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(50) * 0.5)
        df = pd.DataFrame({
            'open': close - 0.5,
            'high': close + 1.0,
            'low': close - 1.0,
            'close': close,
            'volume': np.random.randint(1000, 10000, 50),
        }, index=dates)
        return df

    def test_run_backtest_sma_cross(self, sample_df):
        result = run_backtest('sma_cross', sample_df, initial_cash=100000, commission=0.0003)
        assert result['strategy'] == 'sma_cross'
        assert 'final_value' in result
        assert 'total_return_pct' in result
        assert 'sharpe_ratio' in result
        assert 'max_drawdown_pct' in result
        assert 'trades' in result
        assert 'nav_df' in result
        assert result['n_days'] == 50

    def test_run_backtest_with_params(self, sample_df):
        result = run_backtest('sma_cross', sample_df, fast=3, slow=10)
        assert result['strategy'] == 'sma_cross'
        assert result['params'] == {'fast': 3, 'slow': 10}

    def test_run_backtest_unknown_strategy(self, sample_df):
        with pytest.raises(ValueError, match="未知策略"):
            run_backtest('unknown_strategy', sample_df)

    def test_run_backtest_missing_columns(self):
        bad_df = pd.DataFrame({'a': [1, 2, 3]})
        with pytest.raises(ValueError, match="缺少必要列"):
            run_backtest('sma_cross', bad_df)

    def test_run_backtest_various_strategies(self, sample_df):
        strategies = ['sma_cross', 'macd', 'rsi', 'momentum', 'bollinger']
        for name in strategies:
            if get_strategy(name):
                result = run_backtest(name, sample_df)
                assert result['n_days'] == 50
                assert isinstance(result['nav_df'], pd.DataFrame)


class TestGenerateReport:
    @pytest.fixture
    def sample_result(self):
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        nav_df = pd.DataFrame({
            'date': dates.date,
            'value': [100000 + i * 100 for i in range(10)],
        })
        nav_df['return_pct'] = nav_df['value'].pct_change().fillna(0) * 100
        nav_df['cumulative_return'] = (nav_df['value'] / 100000 - 1) * 100
        nav_df['drawdown'] = 0.0
        return {
            'strategy': 'sma_cross',
            'params': {'fast': 5, 'slow': 20},
            'initial_cash': 100000,
            'final_value': 100900,
            'total_return_pct': 0.9,
            'annual_return_pct': 2.3,
            'sharpe_ratio': 1.5,
            'max_drawdown_pct': 0.5,
            'max_drawdown_days': 0,
            'trades': {'total': 2, 'won': 1, 'lost': 1, 'win_rate': 50.0},
            'nav_df': nav_df,
            'n_days': 10,
        }

    def test_generate_report_creates_files(self, sample_result, tmp_path):
        output_path = str(tmp_path / "report.md")
        paths = generate_report(sample_result, output_path)
        assert Path(paths['md_path']).exists()
        assert Path(paths['chart_path']).exists()
        assert Path(paths['csv_path']).exists()

    def test_generate_report_markdown_content(self, sample_result, tmp_path):
        output_path = str(tmp_path / "report.md")
        generate_report(sample_result, output_path)
        content = Path(output_path).read_text(encoding='utf-8')
        assert "策略回测报告" in content
        assert "sma_cross" in content
        assert "100,000" in content
