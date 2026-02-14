@echo off
echo === 台股技術分析系統 ===
echo.
echo 啟動 Worker 背景掃描...
start "Stock Worker" cmd /k "python worker.py"
echo.
echo 啟動 Streamlit Web UI...
start "Stock UI" cmd /k "python -m streamlit run app.py"
echo.
echo 兩個程序已啟動：
echo   - Worker: 背景掃描（每 15 分鐘）
echo   - UI: http://localhost:8501
echo.
pause
