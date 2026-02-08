"""條件選股 worker — 獨立進程執行，避免 Streamlit 執行緒問題

用法: python screener_worker.py <json_input_file> <json_output_file>
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from data.fetcher import populate_ticker_cache, get_stock_fundamentals_safe, get_stock_data
from analysis.indicators import calculate_all_indicators


def run_screener(input_path: str, output_path: str):
    with open(input_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    scan_pool = cfg["scan_pool"]  # {code: {name, market}}
    filter_cfg = cfg["filter_cfg"]  # {field: [op, threshold]}
    need_rsi = cfg.get("need_rsi", False)
    rsi_lo = cfg.get("rsi_lo", 30)
    rsi_hi = cfg.get("rsi_hi", 70)
    need_adx = cfg.get("need_adx", False)
    adx_val = cfg.get("adx_val", 20)

    populate_ticker_cache(scan_pool)
    need_tech = need_rsi or need_adx

    def passes_filters(fund, tech):
        for field, (op, threshold) in filter_cfg.items():
            val = fund.get(field)
            if val is None:
                return False
            if op == ">" and val <= threshold:
                return False
            if op == "<" and val >= threshold:
                return False
        if need_rsi:
            rsi = tech.get("RSI") if tech else None
            if rsi is None:
                return False
            if rsi < rsi_lo or rsi > rsi_hi:
                return False
        if need_adx:
            adx = tech.get("ADX") if tech else None
            if adx is None:
                return False
            if adx <= adx_val:
                return False
        return True

    def fetch_one(item):
        code, info = item
        display_name = info.get("name", info) if isinstance(info, dict) else info
        fund = get_stock_fundamentals_safe(code)
        if fund is None:
            return None

        tech = None
        close_price = fund.get("current_price")
        if need_tech:
            try:
                df = get_stock_data(code, period_days=120)
                if df is not None and len(df) >= 60:
                    indicators_df = calculate_all_indicators(df)
                    last = indicators_df.iloc[-1]
                    tech = {"RSI": float(last.get("rsi", 0) or 0), "ADX": float(last.get("adx", 0) or 0)}
                    close_price = float(last["close"])
            except Exception:
                pass

        if not passes_filters(fund, tech):
            return None

        def safe_float(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        return {
            "代碼": code,
            "名稱": display_name,
            "收盤價": safe_float(close_price),
            "PE": safe_float(fund.get("trailing_pe")),
            "Forward PE": safe_float(fund.get("forward_pe")),
            "PB": safe_float(fund.get("price_to_book")),
            "ROE": safe_float(fund.get("return_on_equity")),
            "ROA": safe_float(fund.get("return_on_assets")),
            "毛利率": safe_float(fund.get("gross_margins")),
            "營利率": safe_float(fund.get("operating_margins")),
            "淨利率": safe_float(fund.get("profit_margins")),
            "EPS": safe_float(fund.get("trailing_eps")),
            "營收成長": safe_float(fund.get("revenue_growth")),
            "獲利成長": safe_float(fund.get("earnings_growth")),
            "殖利率": safe_float(fund.get("dividend_yield")),
            "負債比": safe_float(fund.get("debt_to_equity")),
            "流動比": safe_float(fund.get("current_ratio")),
            "Beta": safe_float(fund.get("beta")),
            "市值(億)": round(fund.get("market_cap") / 1e8, 1) if fund.get("market_cap") else None,
            "自由現金流(億)": round(fund.get("free_cashflow") / 1e8, 1) if fund.get("free_cashflow") else None,
            "營業現金流(億)": round(fund.get("operating_cashflow") / 1e8, 1) if fund.get("operating_cashflow") else None,
            "目標價": safe_float(fund.get("target_mean_price")),
            "分析師數": fund.get("number_of_analysts"),
            "RSI": safe_float(tech.get("RSI")) if tech else None,
            "ADX": safe_float(tech.get("ADX")) if tech else None,
        }

    with ThreadPoolExecutor(max_workers=5) as executor:
        raw = list(executor.map(fetch_one, scan_pool.items()))

    results = [r for r in raw if r is not None]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False)


if __name__ == "__main__":
    run_screener(sys.argv[1], sys.argv[2])
