@echo off
echo Stopping Stock News App...
taskkill /FI "WINDOWTITLE eq StockNews Backend" /T /F
taskkill /FI "WINDOWTITLE eq StockNews Frontend" /T /F
echo.
echo Servers stopped.
pause
