"""台股技術分析系統 - 設定檔"""

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class StrategyV4Config:
    """v4 策略參數 — frozen dataclass 確保回測可復現性

    每次回測結果都可精確對應到一組參數，避免參數散落在 UI 和邏輯層之間。
    """
    # 進場過濾
    adx_min: int = 18
    rsi_low: int = 30
    rsi_high: int = 80
    min_uptrend_days: int = 10
    support_max_dist: float = 0.05
    min_volume_ratio: float = 0.7
    min_volume_lots: int = 500  # 最低成交量（張），過濾殭屍股/低流動性標的
    # 出場
    take_profit_pct: float = 0.10
    stop_loss_pct: float = 0.07
    trailing_stop_pct: float = 0.02
    min_hold_days: int = 5
    # 部位
    max_position_pct: float = 0.9

    def to_dict(self) -> dict:
        """轉成 dict（與現有 API 相容）"""
        return asdict(self)

    def with_overrides(self, **kwargs) -> "StrategyV4Config":
        """建立新的 config（因為 frozen 不能直接改）"""
        d = asdict(self)
        d.update(kwargs)
        return StrategyV4Config(**d)

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyV4Config":
        """從 dict 建立（忽略不認識的 key）"""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)

    def describe(self) -> str:
        """人類可讀的參數摘要（用於回測報告紀錄）"""
        return (f"ADX≥{self.adx_min} | RSI {self.rsi_low}-{self.rsi_high} | "
                f"上升趨勢≥{self.min_uptrend_days}天 | "
                f"TP {self.take_profit_pct:.0%} SL {self.stop_loss_pct:.0%} "
                f"Trail {self.trailing_stop_pct:.0%} | 最短持有 {self.min_hold_days}天 | "
                f"最低量 {self.min_volume_lots}張")


# 預設 v4 config 實例
DEFAULT_V4_CONFIG = StrategyV4Config()


# 預設股票清單（台股熱門股，含上市與上櫃）
DEFAULT_STOCKS = {
    "2330": "台積電",
    "2317": "鴻海",
    "2454": "聯發科",
    "2881": "富邦金",
    "2882": "國泰金",
    "2891": "中信金",
    "0050": "元大台灣50",
    "0056": "元大高股息",
    "2603": "長榮",
    "3008": "大立光",
    "6748": "亞果生醫",
    "6547": "高端疫苗",
    "3293": "鉅祥",
    "5876": "上海商銀",
}

# 推薦掃描用的股票池（0050 + 0051 成分股 + 補強，共 108 檔）
# 來源：臺灣 50 指數 + 臺灣中型 100 指數（2025Q4 調整後）
SCAN_STOCKS = {
    # ===== 臺灣 50 成分股（50 檔） =====
    "2330": "台積電",
    "2317": "鴻海",
    "2454": "聯發科",
    "2308": "台達電",
    "2891": "中信金",
    "3711": "日月光投控",
    "2881": "富邦金",
    "2382": "廣達",
    "2882": "國泰金",
    "2345": "智邦",
    "2303": "聯電",
    "2884": "玉山金",
    "2412": "中華電",
    "3017": "奇鋐",
    "2886": "兆豐金",
    "6669": "緯穎",
    "2383": "台光電",
    "3231": "緯創",
    "2887": "台新新光金",
    "2885": "元大金",
    "1216": "統一",
    "2357": "華碩",
    "2327": "國巨",
    "2890": "永豐金",
    "2892": "第一金",
    "2301": "光寶科",
    "1303": "南亞",
    "2880": "華南金",
    "2360": "致茂",
    "3661": "世芯-KY",
    "2883": "凱基金",
    "3665": "貿聯-KY",
    "5880": "合庫金",
    "2379": "瑞昱",
    "3008": "大立光",
    "3653": "健策",
    "2002": "中鋼",
    "2408": "南亞科",
    "3034": "聯詠",
    "2059": "川湖",
    "2603": "長榮",
    "1301": "台塑",
    "2207": "和泰車",
    "6919": "康霈",
    "3045": "台灣大",
    "4904": "遠傳",
    "2395": "研華",
    "2912": "統一超",
    "2615": "萬海",
    "6505": "台塑化",
    # ===== 臺灣中型 100 成分股（前 52 檔，依市值排序） =====
    "3037": "欣興",
    "2449": "京元電子",
    "2344": "華邦電",
    "2368": "金像電",
    "3443": "創意",
    "1101": "台泥",
    "5871": "中租-KY",
    "5876": "上海商銀",
    "2404": "漢唐",
    "2801": "彰銀",
    "3044": "健鼎",
    "2376": "技嘉",
    "6446": "藥華藥",
    "4938": "和碩",
    "1590": "亞德客-KY",
    "2324": "仁寶",
    "6770": "力積電",
    "6239": "力成",
    "1504": "東元",
    "2834": "臺企銀",
    "1519": "華城",
    "2356": "英業達",
    "2474": "可成",
    "3533": "嘉澤",
    "1326": "台化",
    "4958": "臻鼎-KY",
    "2618": "長榮航",
    "1605": "華新",
    "2609": "陽明",
    "3036": "文曄",
    "2313": "華通",
    "1402": "遠東新",
    "1102": "亞泥",
    "3702": "大聯大",
    "6139": "亞翔",
    "6805": "富世達",
    "2812": "台中銀",
    "2353": "宏碁",
    "3706": "神達",
    "6515": "穎崴",
    "2409": "友達",
    "1476": "儒鴻",
    "2385": "群光",
    "2347": "聯強",
    "6442": "光聖",
    "9904": "寶成",
    "2027": "大成鋼",
    "2377": "微星",
    "6409": "旭隼",
    "6415": "矽力-KY",
    "1477": "聚陽",
    "1513": "中興電",
    # ===== Gemini R22 審核補強（6 檔） =====
    # 生技深度
    "4743": "合一",
    "6472": "保瑞",
    # OTC 指標股
    "5274": "信驊",
    "8299": "群聯",
    # 半導體上游
    "6488": "環球晶",
    # 重電/綠能
    "1503": "士電",
}

# 技術指標參數
INDICATOR_PARAMS = {
    "ma_short": 5,
    "ma_mid": 20,
    "ma_long": 60,
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "kd_period": 9,
    "bb_period": 20,
    "bb_std": 2,
}

# 策略參數
STRATEGY_PARAMS = {
    "buy_threshold": 0.3,
    "sell_threshold": -0.3,
    "weights": {
        "ma": 0.20,
        "rsi": 0.20,
        "macd": 0.20,
        "kd": 0.20,
        "bb": 0.10,
        "volume": 0.10,
    },
    # v2 新增
    "confirm_days": 2,          # 訊號需連續 N 天確認才進場
    "trend_filter": True,       # 趨勢過濾：MA20 > MA60 才做多
    "volume_confirm": True,     # 買入當天量 > 5日均量
    # v3 新增
    "score_rising": False,      # 評分需上升中才進場（預設關閉，過嚴）
}

# 風控參數（v2 新增，v3 改為 ATR 動態）
RISK_PARAMS = {
    "stop_loss": 0.07,          # 停損：固定百分比（v2 fallback）
    "trailing_stop": 0.05,      # 移動停利：固定百分比（v2 fallback）
    "max_position_pct": 0.5,    # 單筆最多用 50% 資金
    # v3 新增（ATR 預設關閉，可在 UI 手動開啟）
    "use_atr_stops": False,     # ATR 動態停損停利（預設關，大盤測試固定%更穩）
    "atr_stop_loss_mult": 3.0,  # 停損 = 買入價 - 3x ATR
    "atr_trailing_mult": 2.5,   # 移動停利 = 最高價 - 2.5x ATR
    "min_hold_days": 2,         # 最短持有天數（防止正常波動踢出場）
}

# 回測參數
BACKTEST_PARAMS = {
    "initial_capital": 1_000_000,  # 初始資金 100 萬
    "commission_rate": 0.001425,   # 手續費 0.1425%
    "tax_rate": 0.003,             # 交易稅 0.3%
    "slippage": 0.001,             # 滑價 0.1%
}

# v4 策略參數（趨勢動量 + 支撐進場 + 移動停利停損）
STRATEGY_V4_PARAMS = {
    # 進場過濾
    "adx_min": 18,              # ADX 最低要求（趨勢存在）
    "rsi_low": 30,              # RSI 下限
    "rsi_high": 80,             # RSI 上限
    "min_uptrend_days": 10,     # MA20>MA60 最少持續天數
    "support_max_dist": 0.05,   # 支撐進場：價格距 MA20 最大百分比
    "min_volume_ratio": 0.7,    # 最低量能比（相對 5 日均量）
    "min_volume_lots": 500,     # 最低成交量（張），過濾殭屍股/低流動性標的
    # 出場
    "take_profit_pct": 0.10,    # 停利 +10%
    "stop_loss_pct": 0.07,      # 停損 -7%
    "trailing_stop_pct": 0.02,  # 移動停利 2%（從最高價回落 2% 出場）— 非動態模式的 fallback
    "min_hold_days": 5,         # 最短持有天數（避免正常波動假停損）
    # R73: Dynamic Trail — 動態移動停利（依獲利幅度調整寬度）
    # REJECTED as default: flat 2% trail outperforms on avg (Sharpe 0.87 vs 0.72)
    # Dynamic trail helps large-caps (2330: 0.74→1.44) but hurts momentum stocks (6139: 2.13→1.18)
    "dynamic_trail_enabled": False,  # VALIDATED: baseline wins for general use
    "dynamic_trail_tiers": [
        # (profit_threshold, trail_pct) — 獲利越多 trail 越緊
        # 從最高的 tier 往下匹配（第一個 >= 的 threshold）
        (0.50, 0.08),   # >50% profit → 8% trail (tight lock)
        (0.20, 0.10),   # 20-50% profit → 10% trail
        (0.00, 0.15),   # 0-20% profit → 15% trail (wide, let it run)
    ],
    # 部位
    "max_position_pct": 0.9,    # 單筆最大部位 90%
}

# 台股交易單位
TRADE_UNIT = 1000  # 一張 = 1000 股
