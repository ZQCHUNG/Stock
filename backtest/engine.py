"""回測引擎

模擬歷史交易績效，包含：
- 台股手續費與交易稅
- 逐筆交易紀錄
- 績效指標計算（報酬率、最大回撤、Sharpe Ratio 等）
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from config import BACKTEST_PARAMS, RISK_PARAMS, TRADE_UNIT, STRATEGY_V4_PARAMS
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
    total_trades: int = 0
    avg_holding_days: float = 0.0


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
    ):
        self.initial_capital = initial_capital or BACKTEST_PARAMS["initial_capital"]
        self.commission_rate = commission_rate or BACKTEST_PARAMS["commission_rate"]
        self.tax_rate = tax_rate or BACKTEST_PARAMS["tax_rate"]

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

        for date, row in signals_df.iterrows():
            price = row["close"]
            high = row.get("high", price)
            signal = row["signal"]
            current_atr = row.get("atr", 0.0)

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
                revenue = position * price
                commission = revenue * self.commission_rate
                tax = revenue * self.tax_rate
                cash += revenue - commission - tax

                current_trade.date_close = date
                current_trade.price_close = price
                current_trade.commission += commission
                current_trade.tax = tax
                current_trade.pnl = (
                    (price - current_trade.price_open) * position
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
                # v2 部位管理：最多用 max_position_pct 的資金
                available = cash * max_position_pct
                max_shares = int(available / (price * TRADE_UNIT * (1 + self.commission_rate))) * TRADE_UNIT
                if max_shares >= TRADE_UNIT:
                    shares = max_shares
                    cost = shares * price
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
                        price_open=price,
                        commission=commission,
                    )

            elif signal == "SELL" and position > 0 and current_trade is not None:
                # 賣出：全部出清
                revenue = position * price
                commission = revenue * self.commission_rate
                tax = revenue * self.tax_rate
                cash += revenue - commission - tax

                current_trade.date_close = date
                current_trade.price_close = price
                current_trade.commission += commission
                current_trade.tax = tax
                current_trade.pnl = (
                    (price - current_trade.price_open) * position
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
            last_price = signals_df.iloc[-1]["close"]
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

    def run_v4(self, df: pd.DataFrame, params: dict | None = None) -> BacktestResult:
        """執行 v4 回測（趨勢動量 + 支撐進場 + 移動停利停損）

        v4 使用完全不同的進出場邏輯：
        - 進場：v4_signal == "BUY" 時買入
        - 出場：固定停利 / 固定停損 / 移動停利（trailing stop）
        - 用當日最高最低價偵測 TP/SL（更貼近真實盤中行為）
        - 最短持有天數：避免正常波動觸發假停損

        Args:
            df: 原始股價 DataFrame
            params: 覆蓋 STRATEGY_V4_PARAMS 的參數

        Returns:
            BacktestResult 回測結果
        """
        p = dict(STRATEGY_V4_PARAMS)
        if params:
            p.update(params)

        signals_df = generate_v4_signals(df, params=p)

        tp_pct = p.get("take_profit_pct", 0.10)
        sl_pct = p.get("stop_loss_pct", 0.07)
        trailing_pct = p.get("trailing_stop_pct", 0.02)
        max_pos_pct = p.get("max_position_pct", 0.9)
        min_hold = p.get("min_hold_days", 5)

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

        for date, row in signals_df.iterrows():
            price = row["close"]
            high = row.get("high", price)
            low = row.get("low", price)
            signal = row.get("v4_signal", "HOLD")

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
                revenue = position * exit_price
                commission = revenue * self.commission_rate
                tax = revenue * self.tax_rate
                cash += revenue - commission - tax

                current_trade.date_close = date
                current_trade.price_close = exit_price
                current_trade.commission += commission
                current_trade.tax = tax
                current_trade.pnl = (
                    (exit_price - current_trade.price_open) * position
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
                available = cash * max_pos_pct
                max_shares = int(available / (price * TRADE_UNIT * (1 + self.commission_rate))) * TRADE_UNIT
                if max_shares >= TRADE_UNIT:
                    shares = max_shares
                    cost = shares * price
                    commission = cost * self.commission_rate
                    cash -= cost + commission
                    position = shares
                    highest_since_entry = high
                    hold_days = 0
                    tp_price = price * (1 + tp_pct) if tp_pct > 0 else float("inf")
                    sl_price = price * (1 - sl_pct)
                    original_sl_price = sl_price

                    current_trade = Trade(
                        date_open=date,
                        side="BUY",
                        shares=shares,
                        price_open=price,
                        commission=commission,
                    )

        # 期末平倉
        if position > 0 and current_trade is not None:
            last_date = signals_df.index[-1]
            last_price = signals_df.iloc[-1]["close"]
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

        result = BacktestResult(trades=trades, equity_curve=equity_curve)
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

        # Sharpe Ratio (假設無風險利率 1.5%)
        if len(result.daily_returns) > 1 and result.daily_returns.std() > 0:
            risk_free_daily = 0.015 / 252
            excess_returns = result.daily_returns - risk_free_daily
            result.sharpe_ratio = (
                excess_returns.mean() / excess_returns.std() * np.sqrt(252)
            )


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
) -> BacktestResult:
    """便捷函式：執行 v4 回測

    Args:
        df: 原始股價 DataFrame
        initial_capital: 初始資金
        params: v4 策略參數覆蓋

    Returns:
        BacktestResult
    """
    engine = BacktestEngine(initial_capital=initial_capital)
    return engine.run_v4(df, params=params)


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
