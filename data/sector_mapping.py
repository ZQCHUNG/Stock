"""產業標籤精確化 — 自定義二級產業分類（Gemini R22 P0）

yfinance 的 sector 標籤在台股非常粗糙（例如將 PCB、封測、IC 設計
全部歸類為 Electronic Components）。這裡手動定義 108 檔標的的精確
二級產業分類，確保 Sector Heat 與 Sector Momentum 有實戰意義。

更新頻率：每季（配合 0050/0051 成分股調整）
"""

from collections import defaultdict
import logging
logger = logging.getLogger(__name__)


# 股票代碼 → 二級產業
SECTOR_MAPPING: dict[str, str] = {
    # ===== 半導體 =====
    # IC 設計
    "2454": "IC設計",
    "2379": "IC設計",
    "3034": "IC設計",
    "6415": "IC設計",
    # IP 設計
    "3661": "IP設計",
    "3443": "IP設計",
    "5274": "IP設計",
    "6442": "IP設計",
    # 晶圓代工
    "2330": "晶圓代工",
    "2303": "晶圓代工",
    "6770": "晶圓代工",
    # 封測 / 半導體設備
    "3711": "封測",
    "2449": "封測",
    "6239": "封測",
    "2360": "封測/設備",
    "6515": "封測/設備",
    # 記憶體
    "2408": "記憶體",
    "2344": "記憶體",
    "8299": "記憶體",
    # 矽晶圓
    "6488": "矽晶圓",

    # ===== AI 伺服器供應鏈 =====
    # ODM / EMS
    "2317": "ODM/EMS",
    "2382": "ODM/EMS",
    "6669": "ODM/EMS",
    "3231": "ODM/EMS",
    "2357": "ODM/EMS",
    "2324": "ODM/EMS",
    "2356": "ODM/EMS",
    "4938": "ODM/EMS",
    "2353": "ODM/EMS",
    "3706": "ODM/EMS",
    "2376": "ODM/EMS",
    "2377": "ODM/EMS",
    # 散熱
    "3017": "散熱",
    "3653": "散熱",
    # 機殼 / 機構件
    "2059": "機殼",
    "6805": "機殼/軸承",
    "2474": "機殼/零件",
    # 光通訊 / 網通
    "2345": "光通訊/網通",
    "6139": "光通訊/設備",

    # ===== 電子零組件 =====
    # PCB / 載板
    "2383": "PCB/載板",
    "3037": "PCB/載板",
    "2368": "PCB/載板",
    "3044": "PCB/載板",
    "4958": "PCB/載板",
    "2313": "PCB/載板",
    # 被動元件
    "2327": "被動元件",
    # 連接器
    "3533": "連接器",
    "3665": "連接器",
    # 電源供應器
    "2385": "電源供應器",
    "2301": "電源供應器",
    "6409": "電源供應器",

    # ===== 光電 =====
    "3008": "鏡頭",
    "2409": "面板",

    # ===== 電子通路 =====
    "2347": "電子通路",
    "3036": "電子通路",
    "3702": "電子通路",

    # ===== 金融 =====
    # 金控
    "2881": "金控",
    "2882": "金控",
    "2886": "金控",
    "2891": "金控",
    "2884": "金控",
    "2885": "金控",
    "2880": "金控",
    "2887": "金控",
    "2890": "金控",
    "2892": "金控",
    "2883": "金控",
    # 銀行
    "5880": "銀行",
    "2801": "銀行",
    "2834": "銀行",
    "2812": "銀行",
    "5876": "銀行",
    # 租賃
    "5871": "租賃",

    # ===== 傳產 =====
    # 石化
    "1303": "石化",
    "1301": "石化",
    "1326": "石化",
    "6505": "石化",
    # 鋼鐵
    "2002": "鋼鐵",
    "2027": "鋼鐵",
    "1605": "鋼鐵",
    # 水泥
    "1101": "水泥",
    "1102": "水泥",
    # 紡織 / 成衣
    "1402": "紡織",
    "1476": "紡織/成衣",
    "1477": "紡織/成衣",
    "9904": "鞋業",

    # ===== 內需 =====
    # 食品 / 通路
    "1216": "食品/通路",
    "2912": "食品/通路",
    # 電信
    "2412": "電信",
    "3045": "電信",
    "4904": "電信",
    # 汽車 / 機械
    "2207": "汽車/機械",
    "1590": "汽車/機械",
    "1504": "汽車/機械",

    # ===== 重電 / 綠能 =====
    "2308": "重電/綠能",
    "1519": "重電/綠能",
    "1513": "重電/綠能",
    "1503": "重電/綠能",

    # ===== 生技醫療 =====
    "6446": "生技醫療",
    "6919": "生技醫療",
    "4743": "生技醫療",
    "6472": "生技醫療",

    # ===== 航運 / 運輸 =====
    "2603": "航運/運輸",
    "2615": "航運/運輸",
    "2618": "航運/運輸",
    "2609": "航運/運輸",

    # ===== 其他 =====
    "2395": "工業電腦",
    "2404": "廠務工程",
}

# 一級產業聚合（用於 Sector Heat 計算）
SECTOR_L1_MAP: dict[str, str] = {
    "IC設計": "半導體",
    "IP設計": "半導體",
    "晶圓代工": "半導體",
    "封測": "半導體",
    "封測/設備": "半導體",
    "記憶體": "半導體",
    "矽晶圓": "半導體",
    "ODM/EMS": "AI伺服器",
    "散熱": "AI伺服器",
    "機殼": "AI伺服器",
    "機殼/軸承": "AI伺服器",
    "機殼/零件": "AI伺服器",
    "光通訊/網通": "AI伺服器",
    "光通訊/設備": "AI伺服器",
    "PCB/載板": "電子零組件",
    "被動元件": "電子零組件",
    "連接器": "電子零組件",
    "電源供應器": "電子零組件",
    "鏡頭": "光電",
    "面板": "光電",
    "電子通路": "電子通路",
    "金控": "金融",
    "銀行": "金融",
    "租賃": "金融",
    "石化": "傳產",
    "鋼鐵": "傳產",
    "水泥": "傳產",
    "紡織": "傳產",
    "紡織/成衣": "傳產",
    "鞋業": "傳產",
    "食品/通路": "內需消費",
    "電信": "電信",
    "汽車/機械": "汽車/機械",
    "重電/綠能": "重電/綠能",
    "生技醫療": "生技醫療",
    "航運/運輸": "航運/運輸",
    "工業電腦": "其他電子",
    "廠務工程": "其他電子",
}


def _build_sector_groups() -> dict[str, list[str]]:
    """建立 二級產業 → [股票代碼] 的反向索引"""
    groups: dict[str, list[str]] = defaultdict(list)
    for code, sector in SECTOR_MAPPING.items():
        groups[sector].append(code)
    return dict(groups)


def _build_l1_groups() -> dict[str, list[str]]:
    """建立 一級產業 → [股票代碼] 的反向索引"""
    groups: dict[str, list[str]] = defaultdict(list)
    for code, sector_l2 in SECTOR_MAPPING.items():
        sector_l1 = SECTOR_L1_MAP.get(sector_l2, "其他")
        groups[sector_l1].append(code)
    return dict(groups)


# 預建索引（模組載入時建立，O(1) 查詢）
SECTOR_GROUPS: dict[str, list[str]] = _build_sector_groups()
SECTOR_L1_GROUPS: dict[str, list[str]] = _build_l1_groups()


def get_stock_sector(code: str, level: int = 2) -> str:
    """查詢股票的產業分類

    Args:
        code: 股票代碼
        level: 1=一級產業（半導體、金融...）, 2=二級產業（IC設計、金控...）

    Returns:
        產業名稱，若未找到則回傳 "未分類"
    """
    sector_l2 = SECTOR_MAPPING.get(code)
    if sector_l2 is None:
        return "未分類"
    if level == 1:
        return SECTOR_L1_MAP.get(sector_l2, "其他")
    return sector_l2


def get_stock_sector_with_fallback(code: str) -> str:
    """查詢股票的產業分類（帶 yfinance fallback）

    先查本地 mapping，不存在時嘗試 yfinance，並標記 (Unmapped)。
    """
    sector = SECTOR_MAPPING.get(code)
    if sector is not None:
        return sector
    # yfinance fallback
    try:
        from data.fetcher import get_stock_info

        info = get_stock_info(code)
        yf_sector = info.get("sector", "") or info.get("industry", "")
        if yf_sector:
            return f"{yf_sector} (Unmapped)"
    except Exception as e:
        logger.debug(f"Optional data fetch failed: {e}")
    return "未分類"
