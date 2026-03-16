@echo off
REM ============================================================
REM  Corridor Video Maker – Dependency Installer
REM  Uses the QGIS OSGeo4W Python environment to install packages.
REM ============================================================

SET O4W_ENV=C:\Program Files\QGIS 3.40.5\bin\o4w_env.bat

echo Setting up OSGeo4W environment ...
CALL "%O4W_ENV%"

echo.
echo Installing opencv-python and numpy into QGIS Python ...
python -m pip install opencv-python numpy

echo.
echo Done!  You can now use the Corridor Video Maker plugin.
echo Restart QGIS if it is already running.
pause
