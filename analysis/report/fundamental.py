"""基本面分析模組 — 基本面評估、產業風險、產業對照"""

_SECTOR_PROFILES = {
    "biotech": {
        "sectors": {"Healthcare"},
        "industries": {"Biotechnology", "Drug Manufacturers", "Diagnostics & Research"},
        "skip_pe": True,
        "skip_roe": True,
        "skip_margin": True,
        "skip_de": False,
        "label": "生技新藥業，獲利指標適用性較低",
    },
    "financial": {
        "sectors": {"Financial Services", "Real Estate"},
        "industries": set(),
        "skip_pe": False,
        "skip_roe": False,
        "skip_margin": False,
        "skip_de": True,
        "label": "金融/營建業，高槓桿為常態",
    },
    "traditional": {
        "sectors": {"Utilities", "Consumer Defensive", "Basic Materials"},
        "industries": set(),
        "skip_pe": False,
        "skip_roe": False,
        "skip_margin": False,
        "skip_de": False,
        "label": "",
    },
    "default": {
        "skip_pe": False,
        "skip_roe": False,
        "skip_margin": False,
        "skip_de": False,
        "label": "",
    },
}


def _get_sector_profile(sector: str, industry: str) -> dict:
    """根據 yfinance sector/industry 判斷產業類別"""
    for profile_name, profile in _SECTOR_PROFILES.items():
        if profile_name == "default":
            continue
        if sector in profile.get("sectors", set()):
            # Healthcare 需要再看 industry 才決定是不是 biotech
            if profile_name == "biotech":
                if industry in profile["industries"]:
                    return profile
                continue  # Healthcare 但不是 biotech → 繼續找或 default
            return profile
    return _SECTOR_PROFILES["default"]


def _assess_fundamentals(fundamentals: dict, current_price: float,
                         sector: str = "", industry: str = "") -> dict:
    """評估基本面，回傳分數與解讀（依產業調整評分邏輯）"""
    profile = _get_sector_profile(sector, industry)
    score = 0.0
    parts = []
    available = 0

    def _val(key):
        v = fundamentals.get(key)
        if v is not None:
            return v
        return None

    # --- 估值 ---
    pe = _val("trailing_pe")
    fwd_pe = _val("forward_pe")
    if pe is not None and not profile["skip_pe"]:
        available += 1
        if pe < 10:
            score += 1.0
            parts.append(f"本益比 {pe:.1f} 倍，估值偏低")
        elif pe < 15:
            score += 0.5
            parts.append(f"本益比 {pe:.1f} 倍，估值合理")
        elif pe > 40:
            score -= 1.0
            parts.append(f"本益比 {pe:.1f} 倍，估值偏高")
        else:
            parts.append(f"本益比 {pe:.1f} 倍")

    if pe is not None and fwd_pe is not None and pe > 0 and not profile["skip_pe"]:
        available += 1
        if fwd_pe < pe * 0.8:
            score += 0.5
            parts.append(f"預估本益比 {fwd_pe:.1f} 倍，獲利預期成長")

    # --- 獲利成長 ---
    eg = _val("earnings_growth")
    if eg is not None:
        available += 1
        if eg > 0.30:
            score += 1.5
            parts.append(f"獲利成長率 {eg:.0%}，成長強勁")
        elif eg > 0.10:
            score += 0.5
            parts.append(f"獲利成長率 {eg:.0%}，穩健成長")
        elif eg < -0.10:
            score -= 1.0
            parts.append(f"獲利成長率 {eg:.0%}，獲利衰退")
        elif eg < 0:
            score -= 0.5
            parts.append(f"獲利成長率 {eg:.0%}，小幅衰退")

    # --- 營收成長 ---
    rg = _val("revenue_growth")
    if rg is not None:
        available += 1
        if rg > 0.20:
            score += 1.0
            parts.append(f"營收成長率 {rg:.0%}，營收動能強")
        elif rg > 0.05:
            score += 0.3
        elif rg < -0.05:
            score -= 0.5
            parts.append(f"營收成長率 {rg:.0%}，營收下滑")

    # --- ROE ---
    roe = _val("return_on_equity")
    if roe is not None:
        available += 1
        if roe > 0.25:
            score += 1.0
            parts.append(f"ROE {roe:.0%}，股東權益報酬率優秀")
        elif roe > 0.15:
            score += 0.5
        elif roe < 0.08 and not profile["skip_roe"]:
            score -= 0.5
            parts.append(f"ROE {roe:.0%}，獲利效率偏低")

    # --- 淨利率 ---
    pm = _val("profit_margins")
    if pm is not None:
        available += 1
        if pm > 0.30:
            score += 0.5
        elif pm < 0.05 and not profile["skip_margin"]:
            score -= 0.5
            parts.append(f"淨利率 {pm:.0%}，利潤率偏低")

    # --- 負債 ---
    de = _val("debt_to_equity")
    if de is not None:
        available += 1
        if de < 30:
            score += 0.3
        elif de > 100 and not profile["skip_de"]:
            score -= 0.5
            parts.append(f"負債權益比 {de:.0f}%，財務槓桿偏高")

    # --- 殖利率 ---
    dy = _val("dividend_yield")
    is_traditional = (sector in _SECTOR_PROFILES["traditional"].get("sectors", set()))
    if dy is not None:
        # yfinance 台股有時回傳百分比形式 (e.g. 1.15 表示 1.15%)，需正規化為小數
        if dy > 1:
            dy = dy / 100
        available += 1
        # 傳產/公用事業殖利率加權提高
        dy_bonus = 0.3 if is_traditional else 0.0
        if dy > 0.05:
            score += 0.5 + dy_bonus
            parts.append(f"殖利率 {dy:.1%}，配息豐厚")
        elif dy > 0.03:
            score += 0.2 + dy_bonus

    # --- 法人目標價 ---
    target_mean = _val("target_mean_price")
    num_analysts = _val("number_of_analysts") or 0
    analyst_data = {}
    if target_mean is not None and current_price > 0:
        available += 1
        upside = (target_mean / current_price - 1)
        analyst_data = {
            "target_mean": target_mean,
            "target_median": _val("target_median_price"),
            "target_high": _val("target_high_price"),
            "target_low": _val("target_low_price"),
            "num_analysts": num_analysts,
            "rating": fundamentals.get("analyst_rating", "N/A"),
            "upside": upside,
        }
        # 只有 >= 2 位分析師且偏離 < 200% 才納入評分
        if num_analysts >= 2 and abs(upside) < 2.0:
            if upside > 0.20:
                score += 1.0
                parts.append(f"法人目標均價 {target_mean:.0f} 元，上檔空間 {upside:.0%}")
            elif upside > 0.05:
                score += 0.3
            elif upside < -0.10:
                score -= 0.5
                parts.append(f"法人目標均價 {target_mean:.0f} 元，低於現價 {abs(upside):.0%}")

    # Clamp
    score = max(-5.0, min(5.0, score))

    # 格式化指標
    def _fmt(val, fmt_str, suffix=""):
        if val is None:
            return "N/A"
        return f"{val:{fmt_str}}{suffix}"

    metrics = {
        "trailing_pe": _fmt(pe, ".1f", " 倍"),
        "forward_pe": _fmt(fwd_pe, ".1f", " 倍"),
        "price_to_book": _fmt(_val("price_to_book"), ".2f", " 倍"),
        "trailing_eps": _fmt(_val("trailing_eps"), ".2f", " 元"),
        "forward_eps": _fmt(_val("forward_eps"), ".2f", " 元"),
        "earnings_growth": _fmt(eg, ".1%") if eg is not None else "N/A",
        "revenue_growth": _fmt(rg, ".1%") if rg is not None else "N/A",
        "roe": _fmt(roe, ".1%") if roe is not None else "N/A",
        "roa": _fmt(_val("return_on_assets"), ".1%") if _val("return_on_assets") is not None else "N/A",
        "gross_margins": _fmt(_val("gross_margins"), ".1%") if _val("gross_margins") is not None else "N/A",
        "operating_margins": _fmt(_val("operating_margins"), ".1%") if _val("operating_margins") is not None else "N/A",
        "profit_margins": _fmt(pm, ".1%") if pm is not None else "N/A",
        "debt_to_equity": _fmt(de, ".0f", "%") if de is not None else "N/A",
        "current_ratio": _fmt(_val("current_ratio"), ".2f") if _val("current_ratio") is not None else "N/A",
        "dividend_yield": _fmt(dy, ".2%") if dy is not None else "N/A",
        "dividend_rate": _fmt(_val("dividend_rate"), ".2f", " 元") if _val("dividend_rate") is not None else "N/A",
        "beta": _fmt(_val("beta"), ".2f") if _val("beta") is not None else "N/A",
    }

    # 綜合解讀
    sector_label = profile.get("label", "")
    sector_note = f"（{sector_label}）" if sector_label else ""
    if score >= 3:
        interpretation = f"基本面表現優異{sector_note}。" + "；".join(parts[:4]) + "。"
    elif score >= 1:
        interpretation = f"基本面表現穩健{sector_note}。" + "；".join(parts[:4]) + "。"
    elif score >= -1:
        interpretation = f"基本面表現中性{sector_note}。" + ("；".join(parts[:4]) + "。" if parts else "")
    else:
        interpretation = f"基本面表現偏弱{sector_note}。" + "；".join(parts[:4]) + "。"

    return {
        "fundamental_score": score,
        "fundamental_interpretation": interpretation,
        "metrics": metrics,
        "analyst_data": analyst_data,
        "available_count": available,
    }


def _assess_industry_risks(sector: str, industry: str,
                           fundamentals: dict, volatility_data: dict,
                           volume_data: dict, current_price: float,
                           company_info: dict) -> list:
    """依產業別評估特定風險（Gemini 項目 3: 風險識別深度）"""
    risks = []
    market_cap = company_info.get("market_cap", 0) or 0
    vol_ratio = volume_data.get("volume_ratio", 1.0)
    atr_pct = volatility_data.get("atr_pct", 0)

    # --- 生技風險 ---
    profile = _get_sector_profile(sector, industry)
    is_biotech = profile.get("skip_pe", False) and profile.get("skip_roe", False)

    if is_biotech:
        # 臨床試驗 / 法規審批風險（生技業固有）
        risks.append({
            "risk": "臨床試驗與法規審批風險",
            "severity": "high",
            "detail": "生技新藥業核心風險：產品需通過臨床試驗與主管機關審批，時程長且結果不確定，任何階段失敗都可能導致股價大幅修正",
        })

        # 現金燃燒率（用 operating_margins 作為代理指標）
        op_margin = fundamentals.get("operating_margins")
        pm = fundamentals.get("profit_margins")
        if op_margin is not None and op_margin < -1.0:
            risks.append({
                "risk": "高現金燃燒率",
                "severity": "high",
                "detail": f"營業利益率 {op_margin:.0%}，顯示公司目前大量燒錢，需密切關注現金水位與未來募資計畫",
            })
        elif pm is not None and pm < -0.5:
            risks.append({
                "risk": "持續虧損",
                "severity": "medium",
                "detail": f"淨利率 {pm:.0%}，公司尚未實現穩定獲利，營運仰賴資本市場融資",
            })

        # 營收規模
        rg = fundamentals.get("revenue_growth")
        if rg is not None and rg < -0.20:
            risks.append({
                "risk": "營收大幅衰退",
                "severity": "high",
                "detail": f"營收成長率 {rg:.0%}，營收下滑幅度大，商業化進度可能不如預期",
            })

    # --- 金融業風險 ---
    is_financial = sector in _SECTOR_PROFILES["financial"]["sectors"]
    if is_financial:
        risks.append({
            "risk": "利率敏感度風險",
            "severity": "medium",
            "detail": "金融業獲利高度受利率政策影響，升息有利利差但可能增加信用風險",
        })
        de = fundamentals.get("debt_to_equity")
        if de is not None and de > 500:
            risks.append({
                "risk": "高槓桿經營",
                "severity": "medium",
                "detail": f"負債權益比 {de:.0f}%，雖為金融業常態但仍需關注資本適足率",
            })

    # --- 科技業風險 ---
    if sector in ("Technology", "Communication Services"):
        risks.append({
            "risk": "技術競爭週期風險",
            "severity": "medium",
            "detail": "科技業技術迭代快速，需持續關注公司研發投入與產品競爭力變化",
        })
        # 半導體特定風險
        semi_keywords = ("Semiconductor", "半導體", "Chip", "Foundry", "IC Design")
        if any(kw.lower() in (industry or "").lower() for kw in semi_keywords):
            risks.append({
                "risk": "地緣政治與供應鏈風險",
                "severity": "medium",
                "detail": "半導體產業受地緣政治（出口管制、關稅）影響大，供應鏈中斷可能衝擊營收與訂單",
            })
            risks.append({
                "risk": "資本支出循環風險",
                "severity": "medium",
                "detail": "半導體為高度資本密集產業，大規模擴產可能壓縮短期獲利率，且產能開出時間點若遇景氣下行將造成利用率下降",
            })
        # 高估值風險
        pe = fundamentals.get("pe_ratio")
        if pe is not None and pe > 30:
            risks.append({
                "risk": "估值偏高風險",
                "severity": "medium",
                "detail": f"本益比 {pe:.1f}x 高於科技業平均，若獲利成長不如預期將面臨估值修正壓力",
            })
        elif pe is not None and pe > 25:
            risks.append({
                "risk": "估值溢價",
                "severity": "low",
                "detail": f"本益比 {pe:.1f}x 略高於平均，需持續確認成長動能支撐",
            })

    # --- 傳產/原物料風險 ---
    if sector in _SECTOR_PROFILES["traditional"]["sectors"]:
        risks.append({
            "risk": "景氣循環與原物料風險",
            "severity": "medium",
            "detail": "傳統產業受總體經濟與原物料價格波動影響大，需關注景氣指標",
        })

    # --- 通用風險 ---
    # 流動性風險
    if vol_ratio < 0.5:
        risks.append({
            "risk": "流動性不足",
            "severity": "medium",
            "detail": f"近期量能比僅 {vol_ratio:.1f}x，成交量偏低可能導致買賣價差大、出場困難",
        })
    if market_cap > 0 and market_cap < 5e9:  # 50 億以下
        risks.append({
            "risk": "小型股風險",
            "severity": "medium",
            "detail": f"市值約 {market_cap/1e8:.0f} 億元，小型股波動大、籌碼集中度高",
        })

    # 高槓桿（非金融）
    de = fundamentals.get("debt_to_equity")
    if de is not None and de > 100 and not is_financial:
        risks.append({
            "risk": "財務槓桿偏高",
            "severity": "medium",
            "detail": f"負債權益比 {de:.0f}%，財務壓力較大",
        })

    # 高波動
    if atr_pct > 0.05:
        risks.append({
            "risk": "極高波動度",
            "severity": "high",
            "detail": f"ATR 佔股價 {atr_pct:.1%}，日均波動幅度極大，不適合低風險偏好投資人",
        })
    elif atr_pct > 0.03:
        risks.append({
            "risk": "波動度偏高",
            "severity": "medium",
            "detail": f"ATR 佔股價 {atr_pct:.1%}，波動幅度高於一般水準",
        })

    # 依 severity 排序（high > medium > low）
    severity_order = {"high": 0, "medium": 1, "low": 2}
    risks.sort(key=lambda r: severity_order.get(r["severity"], 2))
    return risks


def _get_peer_context(sector: str, industry: str, fundamentals: dict,
                      current_price: float, perf_data: dict) -> dict:
    """產業基準對照（Gemini 項目 7: 同業比較）

    不額外抓取 peer 資料，而是提供產業通用基準值和相對定位，
    讓投資人了解該股在產業中的相對位置。
    """
    # 台股各產業通用基準（概略值，供對照）
    _INDUSTRY_BENCHMARKS = {
        "biotech": {
            "label": "台灣生技業",
            "avg_pb": 4.0,
            "avg_gross_margin": 0.50,
            "typical_volatility": "高（年化 40-80%）",
            "key_metrics": ["毛利率", "營收成長率", "現金水位", "研發管線進度"],
            "notes": "生技業虧損為常態，重點看研發管線、法規進度、現金燃燒率；P/E 不適用，改看 P/B 和 P/S",
            "peers": ["4147 中裕", "6547 高端疫苗", "4743 合一", "4726 永昕", "6472 保瑞"],
        },
        "financial": {
            "label": "台灣金融業",
            "avg_pe": 12.0,
            "avg_roe": 0.10,
            "avg_dy": 0.05,
            "typical_volatility": "低至中（年化 15-25%）",
            "key_metrics": ["ROE", "殖利率", "資本適足率", "淨利差"],
            "notes": "金融業看 ROE 和殖利率穩定性，高槓桿為常態，不適用一般 D/E 標準",
            "peers": ["2882 國泰金", "2881 富邦金", "2886 兆豐金", "2884 玉山金"],
        },
        "semiconductor": {
            "label": "台灣半導體業",
            "avg_pe": 18.0,
            "avg_roe": 0.20,
            "avg_gross_margin": 0.45,
            "typical_volatility": "中至高（年化 25-45%）",
            "key_metrics": ["毛利率", "營收成長率", "資本支出", "產能利用率"],
            "notes": "半導體為資本密集產業，需關注週期位置、庫存水位與下游需求變化",
            "peers": ["2330 台積電", "2454 聯發科", "3711 日月光", "2379 瑞昱"],
        },
        "traditional": {
            "label": "台灣傳統產業",
            "avg_pe": 10.0,
            "avg_roe": 0.08,
            "avg_dy": 0.04,
            "typical_volatility": "低（年化 15-25%）",
            "key_metrics": ["殖利率", "本益比", "負債比", "原物料敏感度"],
            "notes": "傳產看殖利率與景氣循環位置，獲利穩定但成長性有限",
            "peers": ["1301 台塑", "1303 南亞", "1326 台化", "2002 中鋼"],
        },
        "default": {
            "label": "台股一般企業",
            "avg_pe": 15.0,
            "avg_roe": 0.12,
            "typical_volatility": "中（年化 20-35%）",
            "key_metrics": ["本益比", "ROE", "營收成長率"],
            "notes": "",
            "peers": [],
        },
    }

    # 判斷產業
    profile = _get_sector_profile(sector, industry)
    is_biotech = profile.get("skip_pe", False) and profile.get("skip_roe", False)
    is_financial = sector in _SECTOR_PROFILES["financial"]["sectors"]
    is_traditional = sector in _SECTOR_PROFILES["traditional"]["sectors"]
    is_semi = industry in ("Semiconductors", "Semiconductor Equipment")

    if is_biotech:
        bench = _INDUSTRY_BENCHMARKS["biotech"]
    elif is_financial:
        bench = _INDUSTRY_BENCHMARKS["financial"]
    elif is_semi:
        bench = _INDUSTRY_BENCHMARKS["semiconductor"]
    elif is_traditional:
        bench = _INDUSTRY_BENCHMARKS["traditional"]
    else:
        bench = _INDUSTRY_BENCHMARKS["default"]

    # 相對定位分析
    positioning = []
    pb = fundamentals.get("price_to_book")
    pe = fundamentals.get("trailing_pe")
    roe = fundamentals.get("return_on_equity")
    dy = fundamentals.get("dividend_yield")
    gm = fundamentals.get("gross_margins")

    if pb is not None and "avg_pb" in bench:
        diff = (pb / bench["avg_pb"] - 1)
        if diff > 0.3:
            positioning.append(f"P/B {pb:.1f}x 高於產業均值 {bench['avg_pb']:.1f}x（溢價 {diff:.0%}），估值偏貴")
        elif diff < -0.3:
            positioning.append(f"P/B {pb:.1f}x 低於產業均值 {bench['avg_pb']:.1f}x（折價 {abs(diff):.0%}），估值偏低")
        else:
            positioning.append(f"P/B {pb:.1f}x 接近產業均值 {bench['avg_pb']:.1f}x")

    if pe is not None and "avg_pe" in bench:
        diff = (pe / bench["avg_pe"] - 1)
        if diff > 0.5:
            positioning.append(f"P/E {pe:.1f}x 遠高於產業均值 {bench['avg_pe']:.0f}x")
        elif diff < -0.3:
            positioning.append(f"P/E {pe:.1f}x 低於產業均值 {bench['avg_pe']:.0f}x，可能被低估")

    if roe is not None and "avg_roe" in bench:
        if roe > bench["avg_roe"] * 1.5:
            positioning.append(f"ROE {roe:.0%} 顯著優於產業水準 {bench['avg_roe']:.0%}")
        elif roe < bench["avg_roe"] * 0.5 and roe > 0:
            positioning.append(f"ROE {roe:.0%} 低於產業水準 {bench['avg_roe']:.0%}")

    if gm is not None and "avg_gross_margin" in bench:
        if gm > bench["avg_gross_margin"] * 1.2:
            positioning.append(f"毛利率 {gm:.0%} 優於產業均值，具定價能力")
        elif gm < bench["avg_gross_margin"] * 0.6:
            positioning.append(f"毛利率 {gm:.0%} 低於產業水準，競爭力堪慮")

    return {
        "industry_label": bench["label"],
        "key_metrics": bench["key_metrics"],
        "typical_volatility": bench["typical_volatility"],
        "industry_notes": bench["notes"],
        "positioning": positioning,
        "peers": bench.get("peers", []),
    }
