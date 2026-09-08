@echo off
title Magic S-RIM Valuation Dashboard
echo =======================================================
echo   Starting Magic S-RIM Web Dashboard...
echo   Open your browser at http://localhost:8501
echo =======================================================
echo.

cd /d "%~dp0"
streamlit run app.py

pause
