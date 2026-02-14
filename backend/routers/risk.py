"""風險監控儀表板路由（Gemini R46-2, R48-1）

整合 analysis/risk.py 的核心風險計算，提供:
1. 組合風險摘要（VaR + Beta + 集中度）
2. 相關性矩陣
3. 風險警報
4. VaR 動態倉位建議（R48-1）
5. 情境壓力測試（R48-1）
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger(__name__)


class PositionSizeRequest(BaseModel):
    code: str
    entry_price: float
    confidence: float = 0.7
    account_value: float = 1_000_000
    var_limit_pct: float = 0.02


class ScenarioRequest(BaseModel):
    account_value: float = 1_000_000


@router.get("/summary")
def risk_summary():
    """取得組合風險摘要

    基於模擬倉位的持股計算：VaR、組合 Beta、產業集中度、風險警報。
    """
    from backend import db
    from backend.dependencies import make_serializable
    from data.fetcher import get_stock_data, get_taiex_data
    from analysis.risk import (
        calculate_correlation_matrix,
        calculate_portfolio_var,
        calculate_portfolio_beta,
        analyze_industry_concentration,
        check_risk_alerts,
    )
    import numpy as np

    positions = db.get_open_positions()
    if not positions:
        return make_serializable({
            "has_data": False,
            "message": "無持倉資料。請先在模擬倉位中建立部位。",
        })

    codes = list({p["code"] for p in positions})

    # Calculate total portfolio value
    total_value = sum(
        p.get("entry_price", 0) * p.get("lots", 0) * 1000
        for p in positions
    )

    # Parallel fetch stock data
    stock_data = {}
    def _fetch(code):
        try:
            return code, get_stock_data(code, period_days=300)
        except Exception:
            return code, None

    with ThreadPoolExecutor(max_workers=6) as ex:
        for code, df in ex.map(_fetch, codes):
            if df is not None and len(df) >= 30:
                stock_data[code] = df

    if not stock_data:
        return make_serializable({
            "has_data": False,
            "message": "無法取得股價資料",
        })

    # 1. Correlation matrix
    corr_matrix = calculate_correlation_matrix(stock_data, days=60)
    corr_data = None
    high_corr_pairs = []
    if not corr_matrix.empty:
        corr_data = {
            "codes": corr_matrix.index.tolist(),
            "matrix": corr_matrix.values.tolist(),
        }
        # Extract high-correlation pairs
        for i in range(len(corr_matrix)):
            for j in range(i + 1, len(corr_matrix)):
                val = float(corr_matrix.iloc[i, j])
                if not np.isnan(val) and abs(val) > 0.6:
                    high_corr_pairs.append({
                        "stock_a": corr_matrix.index[i],
                        "stock_b": corr_matrix.columns[j],
                        "correlation": round(val, 3),
                    })
        high_corr_pairs.sort(key=lambda x: abs(x["correlation"]), reverse=True)

    # 2. VaR (95% confidence, 1-day and 5-day)
    var_1d = calculate_portfolio_var(stock_data, confidence=0.95, days=250, portfolio_value=total_value)
    var_5d = calculate_portfolio_var(stock_data, confidence=0.95, days=250, portfolio_value=total_value)
    # 5-day VaR approximation: VaR_1d * sqrt(5)
    var_5d_pct = var_1d["var_pct"] * (5 ** 0.5) if var_1d["var_pct"] else 0
    var_5d_amt = var_5d_pct * total_value

    # 3. Portfolio Beta
    taiex_df = None
    try:
        taiex_df = get_taiex_data(period_days=300)
    except Exception:
        pass

    betas = {}
    portfolio_beta = None
    if taiex_df is not None:
        betas = calculate_portfolio_beta(stock_data, taiex_df, days=120)
        if betas:
            portfolio_beta = round(sum(betas.values()) / len(betas), 2)

    # 4. Industry concentration
    sector_data = {}
    for p in positions:
        sector_data[p["code"]] = p.get("sector", "") or "未分類"
    concentration = analyze_industry_concentration(sector_data)

    # 5. Position concentration (by value)
    position_concentration = []
    for p in positions:
        pos_value = p.get("entry_price", 0) * p.get("lots", 0) * 1000
        pct = pos_value / total_value if total_value > 0 else 0
        position_concentration.append({
            "code": p["code"],
            "name": p.get("name", ""),
            "value": round(pos_value),
            "pct": round(pct * 100, 1),
            "beta": betas.get(p["code"]),
        })
    position_concentration.sort(key=lambda x: x["value"], reverse=True)

    # 6. Risk alerts
    alerts = check_risk_alerts(corr_matrix, var_1d)
    alerts.extend(concentration.get("alerts", []))
    # Add beta alert
    if portfolio_beta is not None and portfolio_beta > 1.3:
        alerts.append(f"高 Beta 警告：組合 Beta {portfolio_beta}（>1.3），波動風險高於大盤 30%+")

    return make_serializable({
        "has_data": True,
        "portfolio": {
            "total_value": round(total_value),
            "stock_count": len(codes),
            "portfolio_beta": portfolio_beta,
        },
        "var": {
            "var_1d_pct": round(var_1d["var_pct"] * 100, 2) if var_1d["var_pct"] else 0,
            "var_1d_amount": round(var_1d["var_amount"]) if var_1d["var_amount"] else 0,
            "var_5d_pct": round(var_5d_pct * 100, 2),
            "var_5d_amount": round(var_5d_amt),
            "stocks_used": var_1d["stocks_used"],
        },
        "correlation": corr_data,
        "high_corr_pairs": high_corr_pairs[:10],
        "betas": betas,
        "concentration": {
            "by_position": position_concentration,
            "by_sector": {
                "sectors": concentration["sector_pcts"],
                "concentrated": concentration["concentrated"],
            },
        },
        "alerts": alerts,
    })


@router.post("/position-size")
def suggest_position_size(req: PositionSizeRequest):
    """VaR 動態倉位建議（R48-1）

    根據當前持倉的 VaR 預算、相關性、Beta 等因素，
    計算建議的開倉張數。
    """
    from backend import db
    from backend.dependencies import make_serializable
    from backend.position_sizer import calculate_position_size
    from data.fetcher import get_stock_data, get_taiex_data

    positions = db.get_open_positions()
    codes = list({p["code"] for p in positions})

    # Fetch stock data for existing positions
    existing_stock_data = {}
    def _fetch(code):
        try:
            return code, get_stock_data(code, period_days=300)
        except Exception:
            return code, None

    if codes:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for code, df in ex.map(_fetch, codes):
                if df is not None and len(df) >= 30:
                    existing_stock_data[code] = df

    # Fetch target stock data
    try:
        stock_df = get_stock_data(req.code, period_days=300)
    except Exception:
        stock_df = None

    if stock_df is None or stock_df.empty:
        return {"error": f"無法取得 {req.code} 的股價資料"}

    # Fetch market data for beta
    market_df = None
    try:
        market_df = get_taiex_data(period_days=300)
    except Exception:
        pass

    result = calculate_position_size(
        stock_code=req.code,
        entry_price=req.entry_price,
        stock_df=stock_df,
        existing_positions=positions,
        existing_stock_data=existing_stock_data,
        account_value=req.account_value,
        var_limit_pct=req.var_limit_pct,
        confidence_score=req.confidence,
        market_df=market_df,
    )

    return make_serializable(result)


@router.post("/scenario")
def run_scenario(req: ScenarioRequest):
    """情境壓力測試（R48-1）

    模擬不同市場下跌情境對投資組合的影響。
    """
    from backend import db
    from backend.dependencies import make_serializable
    from backend.position_sizer import run_scenario_analysis
    from data.fetcher import get_stock_data

    positions = db.get_open_positions()
    codes = list({p["code"] for p in positions})

    stock_data = {}
    def _fetch(code):
        try:
            return code, get_stock_data(code, period_days=300)
        except Exception:
            return code, None

    if codes:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for code, df in ex.map(_fetch, codes):
                if df is not None and len(df) >= 30:
                    stock_data[code] = df

    results = run_scenario_analysis(
        positions=positions,
        stock_data=stock_data,
        account_value=req.account_value,
    )

    return make_serializable({"scenarios": results})
