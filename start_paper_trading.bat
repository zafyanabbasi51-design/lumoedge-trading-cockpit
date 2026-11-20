@echo off
title LumoEdge 30-Day Paper Trading Engine
color 0B
echo =======================================================================
echo          LUMOEDGE 30-DAY AUTONOMOUS PAPER TRADING SERVICE
echo        ZERO REAL-MONEY RISK GUARD -- SIMULATED EXECUTION ONLY
echo =======================================================================
echo.
cd /d "%~dp0"
C:\Python314\python.exe -m paper_trading.run_paper_trader
pause
