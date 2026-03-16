@echo off
REM ============================================================
REM  Corridor Video Maker – Dependency Installer
REM  Installs opencv-python using the QGIS bundled Python.
REM ============================================================

SET QGIS_PYTHON="C:\Program Files\QGIS 3.40.5\bin\python3.exe"

echo Installing opencv-python into the QGIS Python environment …
%QGIS_PYTHON% -m pip install --upgrade pip
%QGIS_PYTHON% -m pip install opencv-python numpy

echo.
echo Done!  You can now use the Corridor Video Maker plugin.
pause
