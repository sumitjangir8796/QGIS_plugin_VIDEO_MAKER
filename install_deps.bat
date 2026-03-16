@echo off
REM ============================================================
REM  Corridor Video Maker – Dependency Installer
REM  Installs opencv-python and numpy into QGIS Python 3.12
REM ============================================================

SET QGIS_PYTHON=C:\Program Files\QGIS 3.40.5\apps\Python312\python.exe

echo === Corridor Video Maker – Installing Dependencies ===
echo.
echo Using Python: %QGIS_PYTHON%
echo.

"%QGIS_PYTHON%" -m pip install --user opencv-python numpy

echo.
IF %ERRORLEVEL% EQU 0 (
    echo SUCCESS – opencv-python and numpy are installed.
    echo Restart QGIS and reload the plugin.
) ELSE (
    echo FAILED – try running this script as Administrator.
)
pause
