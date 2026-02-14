"""風險管理模組 — 組合相關性 + VaR + 產業集中度

- 相關性：60 天日對數報酬率的 Pearson Correlation
- VaR：Historical VaR (95% 信心水準)
- 產業集中度：偵測單一產業過度暴露 + Beta 曝險
- 警報：高相關、VaR 超限、產業集中
"""

import numpy as np
import pandas as pd


def calculate_correlation_matrix(
    stock_data: dict[str, pd.DataFrame],
    days: int = 60,
) -> pd.DataFrame:
    """計算股票組合的相關性矩陣

    使用日對數報酬率 (log returns) 的 Pearson 相關係數。
    對數報酬率比簡單報酬率更適合統計分析（具有可加性、近似常態分佈）。

    Args:
        stock_data: {stock_code: DataFrame} 包含 close 欄位
        days: 計算天數（預設 60 天）

    Returns:
        相關性矩陣 DataFrame（codes x codes）
    """
    returns = {}
    for code, df in stock_data.items():
        if df is None or len(df) < days // 2:
            continue
        close = df["close"].tail(days + 1)
        log_ret = np.log(close / close.shift(1)).dropna()
        if len(log_ret) >= 10:  # 至少 10 個數據點
            returns[code] = log_ret

    if len(returns) < 2:
        return pd.DataFrame()

    # 對齊日期索引
    df_returns = pd.DataFrame(returns)
    df_returns = df_returns.dropna()

    if len(df_returns) < 10:
        return pd.DataFrame()

    return df_returns.corr()


def calculate_portfolio_var(
    stock_data: dict[str, pd.DataFrame],
    confidence: float = 0.95,
    days: int = 250,
    portfolio_value: float = 1_000_000,
) -> dict:
    """計算組合 Historical VaR

    使用歷史模擬法：假設等權重組合，取過去 N 天的每日組合報酬率，
    以第 (1-confidence) 百分位數作為 VaR。

    Args:
        stock_data: {stock_code: DataFrame} 包含 close 欄位
        confidence: 信心水準（預設 95%）
        days: 計算視窗天數（預設 250 天，約一年交易日）
        portfolio_value: 組合總值（用於計算金額 VaR）

    Returns:
        dict: var_pct, var_amount, daily_returns, stocks_used
    """
    returns_dict = {}
    for code, df in stock_data.items():
        if df is None or len(df) < 30:
            continue
        close = df["close"].tail(days + 1)
        daily_ret = close.pct_change().dropna()
        if len(daily_ret) >= 20:
            returns_dict[code] = daily_ret

    if not returns_dict:
        return {"var_pct": 0, "var_amount": 0, "daily_returns": [], "stocks_used": 0}

    # 對齊日期並計算等權重組合報酬
    df_returns = pd.DataFrame(returns_dict).dropna()
    if len(df_returns) < 20:
        return {"var_pct": 0, "var_amount": 0, "daily_returns": [], "stocks_used": 0}

    portfolio_returns = df_returns.mean(axis=1)  # 等權重

    # Historical VaR
    var_pct = float(np.percentile(portfolio_returns, (1 - confidence) * 100))

    return {
        "var_pct": var_pct,
        "var_amount": var_pct * portfolio_value,
        "daily_returns": portfolio_returns.tolist(),
        "stocks_used": len(returns_dict),
    }


def check_risk_alerts(
    corr_matrix: pd.DataFrame,
    var_info: dict,
    corr_threshold: float = 0.75,
    max_daily_loss: float = -30_000,
) -> list[str]:
    """檢查風險警報

    Args:
        corr_matrix: 相關性矩陣
        var_info: VaR 計算結果
        corr_threshold: 相關性警報閾值（預設 0.75）
        max_daily_loss: 單日最大可承受虧損（元，預設 -3 萬）

    Returns:
        警報訊息列表
    """
    alerts = []

    # 高相關性警報
    if not corr_matrix.empty:
        codes = corr_matrix.index.tolist()
        for i in range(len(codes)):
            for j in range(i + 1, len(codes)):
                corr_val = corr_matrix.iloc[i, j]
                if not np.isnan(corr_val) and corr_val > corr_threshold:
                    alerts.append(
                        f"高相關性：{codes[i]} 與 {codes[j]} "
                        f"相關係數 {corr_val:.2f}（>{corr_threshold}），"
                        f"持有兩檔無法有效分散風險"
                    )

    # VaR 警報
    var_amount = var_info.get("var_amount", 0)
    if var_amount < max_daily_loss:
        alerts.append(
            f"VaR 警告：95% 信心水準下，單日最大虧損 "
            f"${abs(var_amount):,.0f}（超過閾值 ${abs(max_daily_loss):,.0f}）"
        )

    return alerts


def analyze_industry_concentration(
    sector_data: dict[str, str],
    concentration_threshold: float = 0.35,
) -> dict:
    """分析產業集中度

    Args:
        sector_data: {stock_code: sector_name} 對照表
        concentration_threshold: 單一產業佔比警報閾值（預設 35%）

    Returns:
        dict with keys:
        - sectors: {sector: [codes]} 產業分組
        - sector_pcts: {sector: pct} 各產業佔比
        - concentrated: list of (sector, pct) 超過閾值的產業
        - total_stocks: 總股數
        - alerts: 警報訊息列表
    """
    if not sector_data:
        return {"sectors": {}, "sector_pcts": {}, "concentrated": [],
                "total_stocks": 0, "alerts": []}

    # 分組
    sectors: dict[str, list[str]] = {}
    for code, sector in sector_data.items():
        if not sector or sector == "N/A":
            sector = "未分類"
        sectors.setdefault(sector, []).append(code)

    total = len(sector_data)
    sector_pcts = {s: len(codes) / total for s, codes in sectors.items()}

    # 超過閾值的產業
    concentrated = [(s, pct) for s, pct in sector_pcts.items()
                    if pct >= concentration_threshold and s != "未分類"]
    concentrated.sort(key=lambda x: x[1], reverse=True)

    # 警報
    alerts = []
    for sector, pct in concentrated:
        codes = sectors[sector]
        alerts.append(
            f"產業集中：{sector} 佔比 {pct:.0%}（{len(codes)} 檔：{', '.join(codes)}），"
            f"超過 {concentration_threshold:.0%} 閾值。若該產業基本面轉向，損失將集中爆發。"
        )

    return {
        "sectors": sectors,
        "sector_pcts": sector_pcts,
        "concentrated": concentrated,
        "total_stocks": total,
        "alerts": alerts,
    }


def calculate_portfolio_beta(
    stock_data: dict[str, pd.DataFrame],
    market_df: pd.DataFrame,
    days: int = 120,
) -> dict[str, float]:
    """計算各股票對大盤的 Beta 值

    Beta = Cov(Ri, Rm) / Var(Rm)

    Args:
        stock_data: {stock_code: DataFrame} 包含 close
        market_df: 大盤（TAIEX）DataFrame 包含 close
        days: 計算天數

    Returns:
        {stock_code: beta} 對照表
    """
    if market_df is None or len(market_df) < 30:
        return {}

    market_ret = market_df["close"].tail(days + 1).pct_change().dropna()

    betas = {}
    for code, df in stock_data.items():
        if df is None or len(df) < 30:
            continue
        stock_ret = df["close"].tail(days + 1).pct_change().dropna()

        # 對齊日期
        aligned = pd.DataFrame({"stock": stock_ret, "market": market_ret}).dropna()
        if len(aligned) < 20:
            continue

        cov = aligned["stock"].cov(aligned["market"])
        var_m = aligned["market"].var()
        if var_m > 0:
            betas[code] = round(float(cov / var_m), 2)

    return betas
