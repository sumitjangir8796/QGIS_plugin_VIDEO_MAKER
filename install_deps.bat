@echo off
REM ============================================================
REM  Corridor Video Maker – Dependency Installer
REM  Auto-detects QGIS Python (works for regular and LTR installs)
REM ============================================================

SET QGIS_PYTHON=

REM Try common install locations (newest version first)
FOR %%P IN (
    "C:\Program Files\QGIS 3.40.11\apps\Python312\python.exe"
    "C:\Program Files\QGIS 3.40.5\apps\Python312\python.exe"
    "C:\Program Files\QGIS 3.38\apps\Python312\python.exe"
    "C:\Program Files\QGIS 3.36\apps\Python312\python.exe"
    "C:\Program Files (x86)\QGIS 3.40.11\apps\Python312\python.exe"
    "C:\Program Files (x86)\QGIS 3.40.5\apps\Python312\python.exe"
) DO (
    IF EXIST %%P (
        IF NOT DEFINED QGIS_PYTHON SET QGIS_PYTHON=%%P
    )
)

REM Also search dynamically under Program Files
IF NOT DEFINED QGIS_PYTHON (
    FOR /D %%D IN ("C:\Program Files\QGIS*") DO (
        FOR /D %%P IN ("%%D\apps\Python3*") DO (
            IF EXIST "%%P\python.exe" (
                IF NOT DEFINED QGIS_PYTHON SET QGIS_PYTHON=%%P\python.exe
            )
        )
    )
)

IF NOT DEFINED QGIS_PYTHON (
    echo ERROR: Could not find QGIS Python. Please edit this script and set QGIS_PYTHON manually.
    pause
    exit /b 1
)

echo === Corridor Video Maker - Installing Dependencies ===
echo.
echo Using Python: %QGIS_PYTHON%
echo.

"%QGIS_PYTHON%" -m pip install --user --no-warn-script-location opencv-python

echo.
IF %ERRORLEVEL% EQU 0 (
    echo SUCCESS - opencv-python is installed.
    echo Restart QGIS and reload the plugin.
) ELSE (
    echo FAILED - try running this script as Administrator.
)
pause
