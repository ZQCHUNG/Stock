"""回測引擎

模擬歷史交易績效，包含：
- 台股手續費與交易稅
- 逐筆交易紀錄
- 績效指標計算（報酬率、最大回撤、Sharpe Ratio 等）
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from config import BACKTEST_PARAMS, RISK_PARAMS, TRADE_UNIT, STRATEGY_V4_PARAMS, StrategyV4Config
from analysis.strategy import generate_signals
from analysis.strategy_v4 import generate_v4_signals


@dataclass
class Trade:
    """單筆交易紀錄"""
    date_open: pd.Timestamp
    date_close: pd.Timestamp | None = None
    side: str = "BUY"  # BUY or SELL
    shares: int = 0
    price_open: float = 0.0
    price_close: float = 0.0
    commission: float = 0.0
    tax: float = 0.0
    pnl: float = 0.0
    return_pct: float = 0.0
    exit_reason: str = ""  # "signal" / "stop_loss" / "trailing_stop" / "take_profit"
    liquidity_warning: str = ""  # 流動性警告（交易金額佔當日成交額比重過高）


@dataclass
class BacktestResult:
    """回測結果"""
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)
    daily_returns: pd.Series = field(default_factory=pd.Series)

    # 績效指標
    total_return: float = 0.0
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    total_trades: int = 0
    avg_holding_days: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    dividend_income: float = 0.0
    params_description: str = ""  # 策略參數快照（由 StrategyV4Config.describe() 產生）


class BacktestEngine:
    """回測引擎

    使用方式：
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run(df)
    """

    def __init__(
        self,
        initial_capital: float | None = None,
        commission_rate: float | None = None,
        tax_rate: float | None = None,
        slippage: float | None = None,
    ):
        self.initial_capital = initial_capital or BACKTEST_PARAMS["initial_capital"]
        self.commission_rate = commission_rate or BACKTEST_PARAMS["commission_rate"]
        self.tax_rate = tax_rate or BACKTEST_PARAMS["tax_rate"]
        self.slippage = slippage if slippage is not None else BACKTEST_PARAMS.get("slippage", 0.001)

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """執行回測（v3：ATR 動態停損停利 + 部位管理 + 最短持有期）

        Args:
            df: 原始股價 DataFrame

        Returns:
            BacktestResult 回測結果
        """
        signals_df = generate_signals(df)

        # 風控參數
        use_atr = RISK_PARAMS.get("use_atr_stops", False)
        stop_loss_pct = RISK_PARAMS.get("stop_loss", 0.07)
        trailing_stop_pct = RISK_PARAMS.get("trailing_stop", 0.05)
        atr_sl_mult = RISK_PARAMS.get("atr_stop_loss_mult", 3.0)
        atr_ts_mult = RISK_PARAMS.get("atr_trailing_mult", 2.5)
        max_position_pct = RISK_PARAMS.get("max_position_pct", 0.5)
        min_hold_days = RISK_PARAMS.get("min_hold_days", 0)

        cash = self.initial_capital
        position = 0  # 持有股數
        trades: list[Trade] = []
        current_trade: Trade | None = None
        equity_history = []
        highest_since_entry = 0.0  # 進場後最高價（用於移動停利）
        entry_atr = 0.0  # 進場時的 ATR（v3）
        hold_day_count = 0  # 持有天數計數（v3）

        _has_high = "high" in signals_df.columns
        _has_atr = "atr" in signals_df.columns
        _has_volume = "volume" in signals_df.columns
        for row in signals_df.itertuples():
            date = row.Index
            price = row.close
            high = row.high if _has_high else price
            signal = row.signal
            current_atr = row.atr if _has_atr else 0.0

            # 更新持倉期間最高價（用當日最高價）
            if position > 0:
                highest_since_entry = max(highest_since_entry, high)
                hold_day_count += 1

            # ===== 風控檢查（優先於訊號） =====
            force_sell = False
            exit_reason = ""

            if position > 0 and current_trade is not None:
                entry_price = current_trade.price_open

                # v3: 最短持有期檢查
                if hold_day_count <= min_hold_days:
                    pass  # 持有天數不足，不觸發停損停利
                elif use_atr and entry_atr > 0:
                    # v3: ATR 動態停損停利
                    sl_distance = entry_atr * atr_sl_mult
                    ts_distance = entry_atr * atr_ts_mult

                    if price <= entry_price - sl_distance:
                        force_sell = True
                        exit_reason = "stop_loss"
                    elif highest_since_entry > entry_price and \
                         price <= highest_since_entry - ts_distance:
                        force_sell = True
                        exit_reason = "trailing_stop"
                else:
                    # v2 fallback: 固定百分比
                    if price <= entry_price * (1 - stop_loss_pct):
                        force_sell = True
                        exit_reason = "stop_loss"
                    elif highest_since_entry > entry_price and \
                         price <= highest_since_entry * (1 - trailing_stop_pct):
                        force_sell = True
                        exit_reason = "trailing_stop"

            # 執行強制賣出（停損/停利）
            if force_sell and position > 0 and current_trade is not None:
                sell_price = price * (1 - self.slippage)  # 滑價
                revenue = position * sell_price
                commission = revenue * self.commission_rate
                tax = revenue * self.tax_rate
                cash += revenue - commission - tax

                current_trade.date_close = date
                current_trade.price_close = sell_price
                current_trade.commission += commission
                current_trade.tax = tax
                current_trade.pnl = (
                    (sell_price - current_trade.price_open) * position
                    - current_trade.commission
                    - current_trade.tax
                )
                current_trade.return_pct = (
                    current_trade.pnl / (current_trade.price_open * position)
                )
                current_trade.exit_reason = exit_reason

                trades.append(current_trade)
                position = 0
                current_trade = None
                highest_since_entry = 0.0
                entry_atr = 0.0
                hold_day_count = 0

            # 計算當前權益
            equity = cash + position * price
            equity_history.append({"date": date, "equity": equity})

            # ===== 正常訊號交易 =====
            if signal == "BUY" and position == 0:
                buy_price = price * (1 + self.slippage)  # 滑價
                # v2 部位管理：最多用 max_position_pct 的資金
                available = cash * max_position_pct
                max_shares = int(available / (buy_price * TRADE_UNIT * (1 + self.commission_rate))) * TRADE_UNIT
                if max_shares >= TRADE_UNIT:
                    shares = max_shares
                    cost = shares * buy_price
                    commission = cost * self.commission_rate
                    cash -= cost + commission
                    position = shares
                    highest_since_entry = high
                    entry_atr = current_atr  # v3: 記錄進場 ATR
                    hold_day_count = 0       # v3: 重置持有天數

                    current_trade = Trade(
                        date_open=date,
                        side="BUY",
                        shares=shares,
                        price_open=buy_price,
                        commission=commission,
                    )
                    # 流動性警告：交易金額佔當日成交額 > 5%
                    if _has_volume:
                        _daily_amount = row.volume * price
                        _trade_amount = shares * buy_price
                        if _daily_amount > 0 and _trade_amount > _daily_amount * 0.05:
                            _pct = _trade_amount / _daily_amount
                            current_trade.liquidity_warning = f"佔當日成交額 {_pct:.1%}"

            elif signal == "SELL" and position > 0 and current_trade is not None:
                sell_price = price * (1 - self.slippage)  # 滑價
                # 賣出：全部出清
                revenue = position * sell_price
                commission = revenue * self.commission_rate
                tax = revenue * self.tax_rate
                cash += revenue - commission - tax

                current_trade.date_close = date
                current_trade.price_close = sell_price
                current_trade.commission += commission
                current_trade.tax = tax
                current_trade.pnl = (
                    (sell_price - current_trade.price_open) * position
                    - current_trade.commission
                    - current_trade.tax
                )
                current_trade.return_pct = (
                    current_trade.pnl / (current_trade.price_open * position)
                )
                current_trade.exit_reason = "signal"

                trades.append(current_trade)
                position = 0
                current_trade = None
                highest_since_entry = 0.0
                entry_atr = 0.0
                hold_day_count = 0

        # 如果最後還有持倉，以最後收盤價平倉
        if position > 0 and current_trade is not None:
            last_date = signals_df.index[-1]
            last_price = signals_df.iloc[-1]["close"] * (1 - self.slippage)  # 滑價
            revenue = position * last_price
            commission = revenue * self.commission_rate
            tax = revenue * self.tax_rate
            cash += revenue - commission - tax

            current_trade.date_close = last_date
            current_trade.price_close = last_price
            current_trade.commission += commission
            current_trade.tax = tax
            current_trade.pnl = (
                (last_price - current_trade.price_open) * position
                - current_trade.commission
                - current_trade.tax
            )
            current_trade.return_pct = (
                current_trade.pnl / (current_trade.price_open * position)
            )
            current_trade.exit_reason = "end_of_period"
            trades.append(current_trade)

        # 建立權益曲線
        equity_df = pd.DataFrame(equity_history)
        if not equity_df.empty:
            equity_df.set_index("date", inplace=True)
            equity_curve = equity_df["equity"]
        else:
            equity_curve = pd.Series(dtype=float)

        # 計算績效指標
        result = BacktestResult(trades=trades, equity_curve=equity_curve)
        self._calculate_metrics(result)

        return result

    def run_v4(self, df: pd.DataFrame, params: dict | None = None,
              dividends: pd.Series | None = None) -> BacktestResult:
        """執行 v4 回測（趨勢動量 + 支撐進場 + 移動停利停損）

        v4 使用完全不同的進出場邏輯：
        - 進場：v4_signal == "BUY" 時買入
        - 出場：固定停利 / 固定停損 / 移動停利（trailing stop）
        - 用當日最高最低價偵測 TP/SL（更貼近真實盤中行為）
        - 最短持有天數：避免正常波動觸發假停損

        報酬率已透過 yfinance auto_adjust=True 的調整後股價包含除權息。
        若提供 dividends 參數，僅追蹤估計股利收入供報表顯示，不影響 P&L 計算。

        Args:
            df: 調整後股價 DataFrame（auto_adjust=True，含除權息調整）
            params: 覆蓋 STRATEGY_V4_PARAMS 的參數
            dividends: 歷史除息資料（僅供估算顯示，不影響報酬計算）

        Returns:
            BacktestResult 回測結果
        """
        p = dict(STRATEGY_V4_PARAMS)
        if params:
            p.update(params)

        # 記錄參數快照
        _params_desc = StrategyV4Config.from_dict(p).describe()

        signals_df = generate_v4_signals(df, params=p)

        tp_pct = p.get("take_profit_pct", 0.10)
        sl_pct = p.get("stop_loss_pct", 0.07)
        trailing_pct = p.get("trailing_stop_pct", 0.02)
        max_pos_pct = p.get("max_position_pct", 0.9)
        min_hold = p.get("min_hold_days", 5)

        # 建立除息日查詢集合（僅供估算，不影響 P&L）
        # 注意：auto_adjust=True 的調整後股價已包含除權息，
        # 此處僅追蹤持倉期間的估計股利收入供報表顯示
        div_map = {}
        if dividends is not None and not dividends.empty:
            for d, v in dividends.items():
                div_map[pd.Timestamp(d).normalize()] = v

        cash = self.initial_capital
        position = 0
        trades: list[Trade] = []
        current_trade: Trade | None = None
        equity_history = []
        hold_days = 0
        highest_since_entry = 0.0
        tp_price = 0.0
        sl_price = 0.0
        original_sl_price = 0.0
        total_dividend_income = 0.0

        _has_high = "high" in signals_df.columns
        _has_low = "low" in signals_df.columns
        _has_v4_signal = "v4_signal" in signals_df.columns
        _has_volume = "volume" in signals_df.columns
        for row in signals_df.itertuples():
            date = row.Index
            # 估算除息收入（僅追蹤，不加入 cash）
            # 報酬率已透過 yfinance auto_adjust=True 的調整後股價包含除權息
            if position > 0 and div_map:
                _norm_date = pd.Timestamp(date).normalize()
                if _norm_date in div_map:
                    _div_per_share = div_map[_norm_date]
                    _div_income = position * _div_per_share
                    total_dividend_income += _div_income
            price = row.close
            high = row.high if _has_high else price
            low = row.low if _has_low else price
            signal = row.v4_signal if _has_v4_signal else "HOLD"

            if position > 0:
                highest_since_entry = max(highest_since_entry, high)
                hold_days += 1

                # 移動停利：從最高價回落 trailing_pct 時出場
                if trailing_pct > 0:
                    new_sl = highest_since_entry * (1 - trailing_pct)
                    if new_sl > sl_price:
                        sl_price = new_sl

            # ===== 出場檢查（用 high/low 偵測盤中觸及） =====
            force_sell = False
            exit_reason = ""
            exit_price = 0.0

            if position > 0 and current_trade is not None and hold_days >= min_hold:
                # 當日同時觸及 TP 和 SL：以收盤方向判斷
                if tp_pct > 0 and high >= tp_price and low <= sl_price:
                    if price >= current_trade.price_open:
                        force_sell = True
                        exit_reason = "take_profit"
                        exit_price = tp_price
                    else:
                        force_sell = True
                        exit_reason = "trailing_stop" if sl_price > original_sl_price else "stop_loss"
                        exit_price = sl_price
                elif tp_pct > 0 and high >= tp_price:
                    force_sell = True
                    exit_reason = "take_profit"
                    exit_price = tp_price
                elif low <= sl_price:
                    force_sell = True
                    exit_reason = "trailing_stop" if sl_price > original_sl_price else "stop_loss"
                    exit_price = sl_price

            if force_sell and position > 0 and current_trade is not None:
                actual_exit = exit_price * (1 - self.slippage)  # 滑價
                revenue = position * actual_exit
                commission = revenue * self.commission_rate
                tax = revenue * self.tax_rate
                cash += revenue - commission - tax

                current_trade.date_close = date
                current_trade.price_close = actual_exit
                current_trade.commission += commission
                current_trade.tax = tax
                current_trade.pnl = (
                    (actual_exit - current_trade.price_open) * position
                    - current_trade.commission
                    - current_trade.tax
                )
                current_trade.return_pct = (
                    current_trade.pnl / (current_trade.price_open * position)
                )
                current_trade.exit_reason = exit_reason

                trades.append(current_trade)
                position = 0
                current_trade = None
                hold_days = 0

            # 當前權益
            equity = cash + position * price
            equity_history.append({"date": date, "equity": equity})

            # ===== 進場 =====
            if signal == "BUY" and position == 0:
                buy_price = price * (1 + self.slippage)  # 滑價
                available = cash * max_pos_pct
                max_shares = int(available / (buy_price * TRADE_UNIT * (1 + self.commission_rate))) * TRADE_UNIT
                if max_shares >= TRADE_UNIT:
                    shares = max_shares
                    cost = shares * buy_price
                    commission = cost * self.commission_rate
                    cash -= cost + commission
                    position = shares
                    highest_since_entry = high
                    hold_days = 0
                    tp_price = buy_price * (1 + tp_pct) if tp_pct > 0 else float("inf")
                    sl_price = buy_price * (1 - sl_pct)
                    original_sl_price = sl_price

                    current_trade = Trade(
                        date_open=date,
                        side="BUY",
                        shares=shares,
                        price_open=buy_price,
                        commission=commission,
                    )
                    # 流動性警告：交易金額佔當日成交額 > 5%
                    if _has_volume:
                        _daily_amount = row.volume * price
                        _trade_amount = shares * buy_price
                        if _daily_amount > 0 and _trade_amount > _daily_amount * 0.05:
                            _pct = _trade_amount / _daily_amount
                            current_trade.liquidity_warning = f"佔當日成交額 {_pct:.1%}"

        # 期末平倉
        if position > 0 and current_trade is not None:
            last_date = signals_df.index[-1]
            last_price = signals_df.iloc[-1]["close"] * (1 - self.slippage)  # 滑價
            revenue = position * last_price
            commission = revenue * self.commission_rate
            tax = revenue * self.tax_rate
            cash += revenue - commission - tax

            current_trade.date_close = last_date
            current_trade.price_close = last_price
            current_trade.commission += commission
            current_trade.tax = tax
            current_trade.pnl = (
                (last_price - current_trade.price_open) * position
                - current_trade.commission
                - current_trade.tax
            )
            current_trade.return_pct = (
                current_trade.pnl / (current_trade.price_open * position)
            )
            current_trade.exit_reason = "end_of_period"
            trades.append(current_trade)

        # 權益曲線
        equity_df = pd.DataFrame(equity_history)
        if not equity_df.empty:
            equity_df.set_index("date", inplace=True)
            equity_curve = equity_df["equity"]
        else:
            equity_curve = pd.Series(dtype=float)

        result = BacktestResult(trades=trades, equity_curve=equity_curve,
                                dividend_income=total_dividend_income,
                                params_description=_params_desc)
        self._calculate_metrics(result)

        return result

    def _calculate_metrics(self, result: BacktestResult) -> None:
        """計算績效指標"""
        if result.equity_curve.empty:
            return

        equity = result.equity_curve

        # 日報酬率
        result.daily_returns = equity.pct_change().dropna()

        # 總報酬率
        result.total_return = (equity.iloc[-1] - self.initial_capital) / self.initial_capital

        # 年化報酬率
        trading_days = len(equity)
        if trading_days > 1:
            result.annual_return = (1 + result.total_return) ** (252 / trading_days) - 1
        else:
            result.annual_return = 0.0

        # 最大回撤
        peak = equity.expanding().max()
        drawdown = (equity - peak) / peak
        result.max_drawdown = drawdown.min()

        # 交易統計
        result.total_trades = len(result.trades)
        if result.total_trades > 0:
            winning_trades = [t for t in result.trades if t.pnl > 0]
            losing_trades = [t for t in result.trades if t.pnl <= 0]

            result.win_rate = len(winning_trades) / result.total_trades

            total_profit = sum(t.pnl for t in winning_trades) if winning_trades else 0
            total_loss = abs(sum(t.pnl for t in losing_trades)) if losing_trades else 1
            result.profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")

            # 平均持有天數
            holding_days = []
            for t in result.trades:
                if t.date_close is not None:
                    days = (t.date_close - t.date_open).days
                    holding_days.append(days)
            result.avg_holding_days = np.mean(holding_days) if holding_days else 0

            # 平均獲利 / 平均虧損
            result.avg_win = np.mean([t.return_pct for t in winning_trades]) if winning_trades else 0
            result.avg_loss = np.mean([t.return_pct for t in losing_trades]) if losing_trades else 0

            # 最大連勝 / 連敗
            streak_w = streak_l = max_w = max_l = 0
            for t in result.trades:
                if t.pnl > 0:
                    streak_w += 1
                    streak_l = 0
                    max_w = max(max_w, streak_w)
                else:
                    streak_l += 1
                    streak_w = 0
                    max_l = max(max_l, streak_l)
            result.max_consecutive_wins = max_w
            result.max_consecutive_losses = max_l

        # Sharpe Ratio (假設無風險利率 1.5%)
        if len(result.daily_returns) > 1 and result.daily_returns.std() > 0:
            risk_free_daily = 0.015 / 252
            excess_returns = result.daily_returns - risk_free_daily
            result.sharpe_ratio = (
                excess_returns.mean() / excess_returns.std() * np.sqrt(252)
            )

            # Sortino Ratio (只計算下行風險)
            downside = excess_returns[excess_returns < 0]
            if len(downside) > 0 and downside.std() > 0:
                result.sortino_ratio = (
                    excess_returns.mean() / downside.std() * np.sqrt(252)
                )

        # Calmar Ratio (年化報酬 / 最大回撤)
        if result.max_drawdown < 0:
            result.calmar_ratio = result.annual_return / abs(result.max_drawdown)


def run_backtest(
    df: pd.DataFrame,
    initial_capital: float | None = None,
) -> BacktestResult:
    """便捷函式：執行回測

    Args:
        df: 原始股價 DataFrame
        initial_capital: 初始資金

    Returns:
        BacktestResult
    """
    engine = BacktestEngine(initial_capital=initial_capital)
    return engine.run(df)


def run_backtest_v4(
    df: pd.DataFrame,
    initial_capital: float | None = None,
    params: dict | None = None,
    dividends: pd.Series | None = None,
) -> BacktestResult:
    """便捷函式：執行 v4 回測

    報酬率已透過調整後股價包含除權息（yfinance auto_adjust=True）。

    Args:
        df: 調整後股價 DataFrame
        initial_capital: 初始資金
        params: v4 策略參數覆蓋
        dividends: 歷史除息資料（僅供估算顯示，不影響報酬計算）

    Returns:
        BacktestResult
    """
    engine = BacktestEngine(initial_capital=initial_capital)
    return engine.run_v4(df, params=params, dividends=dividends)


@dataclass
class PortfolioBacktestResult:
    """組合回測結果"""
    # 組合層級
    equity_curve: pd.Series = field(default_factory=pd.Series)
    daily_returns: pd.Series = field(default_factory=pd.Series)
    total_return: float = 0.0
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0

    # 個股層級
    stock_results: dict[str, BacktestResult] = field(default_factory=dict)
    stock_equity_curves: dict[str, pd.Series] = field(default_factory=dict)
    stock_codes: list[str] = field(default_factory=list)
    stock_names: dict[str, str] = field(default_factory=dict)

    # 組合統計
    initial_capital: float = 0.0
    per_stock_capital: float = 0.0
    total_trades: int = 0
    winning_stocks: int = 0
    losing_stocks: int = 0
    correlation_matrix: pd.DataFrame = field(default_factory=pd.DataFrame)


def run_portfolio_backtest_v4(
    stock_data: dict[str, pd.DataFrame],
    stock_names: dict[str, str] | None = None,
    initial_capital: float | None = None,
    params: dict | None = None,
) -> PortfolioBacktestResult:
    """等權重組合回測（v4 策略）

    將資金等分給每檔股票，獨立執行 v4 回測，再合併權益曲線。

    Args:
        stock_data: {stock_code: DataFrame} 各股票歷史資料
        stock_names: {stock_code: name} 股票名稱（可選）
        initial_capital: 總初始資金
        params: v4 策略參數覆寫

    Returns:
        PortfolioBacktestResult
    """
    from config import BACKTEST_PARAMS

    total_capital = initial_capital or BACKTEST_PARAMS["initial_capital"]
    n_stocks = len(stock_data)
    if n_stocks == 0:
        return PortfolioBacktestResult(initial_capital=total_capital)

    per_stock = total_capital / n_stocks

    result = PortfolioBacktestResult(
        initial_capital=total_capital,
        per_stock_capital=per_stock,
        stock_codes=list(stock_data.keys()),
        stock_names=stock_names or {},
    )

    # 個股回測
    for code, df in stock_data.items():
        try:
            engine = BacktestEngine(initial_capital=per_stock)
            bt = engine.run_v4(df, params=params)
            result.stock_results[code] = bt
            if not bt.equity_curve.empty:
                result.stock_equity_curves[code] = bt.equity_curve
            result.total_trades += bt.total_trades
            if bt.total_return > 0:
                result.winning_stocks += 1
            elif bt.total_return < 0:
                result.losing_stocks += 1
        except Exception:
            continue

    if not result.stock_equity_curves:
        return result

    # 合併權益曲線（日期對齊後加總）
    eq_df = pd.DataFrame(result.stock_equity_curves)
    eq_df = eq_df.ffill().bfill()
    result.equity_curve = eq_df.sum(axis=1)

    # 日報酬
    if len(result.equity_curve) > 1:
        result.daily_returns = result.equity_curve.pct_change().dropna()

    # 總報酬
    result.total_return = (result.equity_curve.iloc[-1] - total_capital) / total_capital

    # 年化報酬
    trading_days = len(result.equity_curve)
    if trading_days > 1:
        result.annual_return = (1 + result.total_return) ** (252 / trading_days) - 1

    # 最大回撤
    peak = result.equity_curve.expanding().max()
    drawdown = (result.equity_curve - peak) / peak
    result.max_drawdown = drawdown.min()

    # Sharpe / Sortino
    if len(result.daily_returns) > 1 and result.daily_returns.std() > 0:
        risk_free_daily = 0.015 / 252
        excess = result.daily_returns - risk_free_daily
        result.sharpe_ratio = excess.mean() / excess.std() * np.sqrt(252)

        downside = excess[excess < 0]
        if len(downside) > 0 and downside.std() > 0:
            result.sortino_ratio = excess.mean() / downside.std() * np.sqrt(252)

    # Calmar
    if result.max_drawdown < 0:
        result.calmar_ratio = result.annual_return / abs(result.max_drawdown)

    # 相關性矩陣（個股日報酬）
    if len(result.stock_equity_curves) >= 2:
        returns_df = pd.DataFrame({
            code: curve.pct_change().dropna()
            for code, curve in result.stock_equity_curves.items()
        })
        if len(returns_df) > 5:
            result.correlation_matrix = returns_df.corr()

    return result


def format_backtest_summary(result: BacktestResult) -> str:
    """格式化回測摘要為文字"""
    lines = [
        "=" * 50,
        "回測績效摘要",
        "=" * 50,
        f"總報酬率:     {result.total_return:>10.2%}",
        f"年化報酬率:   {result.annual_return:>10.2%}",
        f"最大回撤:     {result.max_drawdown:>10.2%}",
        f"Sharpe Ratio: {result.sharpe_ratio:>10.2f}",
        f"總交易次數:   {result.total_trades:>10d}",
        f"勝率:         {result.win_rate:>10.2%}",
        f"盈虧比:       {result.profit_factor:>10.2f}",
        f"平均持有天數: {result.avg_holding_days:>10.1f}",
        "=" * 50,
    ]
    return "\n".join(lines)
