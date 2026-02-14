"""FastAPI 應用入口

CORS 設定、路由掛載、靜態檔案伺服（production 模式）。
"""

import sys
from pathlib import Path

# 確保專案根目錄在 sys.path，讓 from analysis.xxx import 正常運作
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.routers import stocks, analysis, backtest, report, recommend, screener, watchlist, system, configs

app = FastAPI(title="台股技術分析系統 API", version="2.0")

# CORS — 開發模式允許 Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 掛載路由
app.include_router(stocks.router, prefix="/api/stocks", tags=["stocks"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"])
app.include_router(report.router, prefix="/api/report", tags=["report"])
app.include_router(recommend.router, prefix="/api/recommend", tags=["recommend"])
app.include_router(screener.router, prefix="/api/screener", tags=["screener"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(configs.router, prefix="/api/configs", tags=["configs"])

# Production: 伺服 Vue build 靜態檔
DIST_DIR = PROJECT_ROOT / "frontend" / "dist"
if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="static")
