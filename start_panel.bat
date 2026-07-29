@echo off
cd /d "%~dp0"
title XJTU Seat Monitor Panel
echo.
echo  ========================================
echo   XJTU Seat Monitor - Web Panel
echo   Keep this window OPEN.
echo   Browser: http://127.0.0.1:18730/
echo   Closing this window stops the panel
echo   (page will show Failed to fetch).
echo   Running monitor process can keep going.
echo  ========================================
echo.
python -c "import flask" 2>nul
if errorlevel 1 (
  echo Installing dependencies...
  pip install -r requirements.txt
  if errorlevel 1 (
    echo ERROR: pip install failed
    pause
    exit /b 1
  )
)
echo Starting panel...
python -u panel_app.py
echo.
echo Panel exited. Run this bat again if the page cannot connect.
pause
