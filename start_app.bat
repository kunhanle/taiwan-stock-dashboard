@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
echo ============================================================
echo   全球連動 App 啟動中...
echo   啟動完成後，用瀏覽器開:  http://127.0.0.1:8137/
echo   (關閉視窗即停止 server)
echo ============================================================
python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8137
pause
