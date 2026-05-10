import backtrader as bt


# ====== 1. 双均线交叉策略 ======
class SmaCrossStrategy(bt.Strategy):
    params = (
        ('fast', 5),
        ('slow', 20),
    )

    def __init__(self):
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)

    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.sell()


# ====== 2. MACD 策略 ======
class MacdStrategy(bt.Strategy):
    params = (
        ('fast', 12),
        ('slow', 26),
        ('signal', 9),
    )

    def __init__(self):
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.fast,
            period_me2=self.p.slow,
            period_signal=self.p.signal
        )
        self.crossover = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)

    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.sell()


# ====== 3. RSI 策略 ======
class RsiStrategy(bt.Strategy):
    params = (
        ('period', 14),
        ('upper', 70),
        ('lower', 30),
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.period)

    def next(self):
        if not self.position:
            if self.rsi < self.p.lower:
                self.buy()
        elif self.rsi > self.p.upper:
            self.sell()


# ====== 4. 动量策略 ======
class MomentumStrategy(bt.Strategy):
    params = (
        ('period', 20),
    )

    def __init__(self):
        self.returns = bt.indicators.PercentChange(self.data.close, period=self.p.period)

    def next(self):
        if not self.position:
            if self.returns > 0:
                self.buy()
        elif self.returns < 0:
            self.sell()


# ====== 5. 布林带策略 ======
class BollingerStrategy(bt.Strategy):
    params = (
        ('period', 20),
        ('devfactor', 2.0),
    )

    def __init__(self):
        self.boll = bt.indicators.BollingerBands(
            self.data.close,
            period=self.p.period,
            devfactor=self.p.devfactor
        )

    def next(self):
        if not self.position:
            if self.data.close < self.boll.lines.bot:
                self.buy()
        elif self.data.close > self.boll.lines.top:
            self.sell()


# ====== 6. 海龟交易（唐奇安通道突破）======
class TurtleStrategy(bt.Strategy):
    params = (
        ('entry_period', 20),
        ('exit_period', 10),
    )

    def __init__(self):
        self.donchian_entry = bt.indicators.Highest(self.data.high, period=self.p.entry_period)
        self.donchian_exit = bt.indicators.Lowest(self.data.low, period=self.p.exit_period)

    def next(self):
        if not self.position:
            if self.data.close > self.donchian_entry[-1]:
                self.buy()
        elif self.data.close < self.donchian_exit[-1]:
            self.sell()


# ====== 7. Dual Thrust 策略 ======
class DualThrustStrategy(bt.Strategy):
    params = (
        ('n', 4),
        ('k1', 0.5),
        ('k2', 0.5),
    )

    def __init__(self):
        self.hh = bt.indicators.Highest(self.data.high, period=self.p.n)
        self.ll = bt.indicators.Lowest(self.data.low, period=self.p.n)
        self.hc = bt.indicators.Highest(self.data.close, period=self.p.n)
        self.lc = bt.indicators.Lowest(self.data.close, period=self.p.n)
        self.range_ = None

    def next(self):
        if len(self.data) < self.p.n + 1:
            return
        self.range_ = max(self.hh[0] - self.lc[0], self.hc[0] - self.ll[0])
        upper = self.data.close[0] + self.p.k1 * self.range_
        lower = self.data.close[0] - self.p.k2 * self.range_

        if not self.position:
            if self.data.close > upper:
                self.buy()
            elif self.data.close < lower:
                self.sell()
        elif self.position.size > 0 and self.data.close < lower:
            self.sell()
        elif self.position.size < 0 and self.data.close > upper:
            self.buy()


# 策略注册表
STRATEGIES = {
    'sma_cross': SmaCrossStrategy,
    'macd': MacdStrategy,
    'rsi': RsiStrategy,
    'momentum': MomentumStrategy,
    'bollinger': BollingerStrategy,
    'turtle': TurtleStrategy,
    'dual_thrust': DualThrustStrategy,
}


def list_strategies() -> list[str]:
    return list(STRATEGIES.keys())


def get_strategy(name: str):
    return STRATEGIES.get(name)


def get_strategy_info(name: str) -> dict:
    cls = STRATEGIES.get(name)
    if not cls:
        return {}
    params = []
    raw_params = getattr(cls, 'params', ())
    # backtrader 会将 params 处理为 Params 类
    if hasattr(raw_params, '_getpairs'):
        pairs = raw_params._getpairs()
        if isinstance(pairs, dict):
            for pname, pdef in pairs.items():
                params.append({'name': pname, 'default': pdef})
        else:
            for pname, pdef in pairs:
                params.append({'name': pname, 'default': pdef})
    elif hasattr(raw_params, '_fields'):
        for field in raw_params._fields:
            default = getattr(raw_params, field, None)
            params.append({'name': field, 'default': default})
    else:
        for item in raw_params:
            if isinstance(item, tuple) and len(item) == 2:
                pname, pdef = item
                params.append({'name': pname, 'default': pdef})
    return {
        'name': name,
        'description': cls.__doc__ or '',
        'params': params,
    }
