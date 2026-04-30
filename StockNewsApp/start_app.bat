@echo off
echo ==========================================
echo Starting Stock News App
echo ==========================================

echo Starting Backend Server...
start "StockNews Backend" cmd /k "cd backend && python -m uvicorn main:app --reload --port 8000"

echo Starting Frontend Server...
start "StockNews Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo Both servers are starting up in new windows.
echo Backend: http://localhost:8000/docs
echo Frontend: http://localhost:5173
echo.
pause
