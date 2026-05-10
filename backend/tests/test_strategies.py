import pytest
from app.strategies import list_strategies, get_strategy, get_strategy_info


class TestStrategyRegistry:
    def test_list_strategies_returns_non_empty_list(self):
        names = list_strategies()
        assert isinstance(names, list)
        assert len(names) > 0
        assert all(isinstance(n, str) for n in names)

    def test_list_strategies_contains_known_strategies(self):
        names = list_strategies()
        expected = ['sma_cross', 'macd', 'rsi', 'momentum', 'bollinger', 'turtle', 'dual_thrust']
        for name in expected:
            assert name in names, f"策略 {name} 未在注册表中"

    def test_get_strategy_returns_class_for_valid_name(self):
        cls = get_strategy('sma_cross')
        assert cls is not None
        assert hasattr(cls, 'params')

    def test_get_strategy_returns_none_for_invalid_name(self):
        assert get_strategy('nonexistent_strategy') is None

    def test_get_strategy_info_returns_dict(self):
        info = get_strategy_info('sma_cross')
        assert isinstance(info, dict)
        assert info['name'] == 'sma_cross'
        assert 'params' in info
        assert isinstance(info['params'], list)

    def test_get_strategy_info_contains_defaults(self):
        info = get_strategy_info('sma_cross')
        param_names = [p['name'] for p in info['params']]
        assert 'fast' in param_names
        assert 'slow' in param_names

    def test_get_strategy_info_empty_for_invalid(self):
        info = get_strategy_info('invalid')
        assert info == {}
