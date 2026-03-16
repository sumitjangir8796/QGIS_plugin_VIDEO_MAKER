@echo off
REM ============================================================
REM  Corridor Video Maker – Build Plugin ZIP for QGIS Repository
REM  Output: corridor_video_maker.zip  (ready to upload)
REM ============================================================

SET ROOT=%~dp0
SET PLUGIN_DIR=%ROOT%corridor_video_maker
SET OUT_ZIP=%ROOT%corridor_video_maker.zip

echo === Building plugin ZIP ===
echo.

REM Remove old zip if present
IF EXIST "%OUT_ZIP%" DEL /F "%OUT_ZIP%"

REM Use PowerShell to create the zip with the folder inside
powershell -NoProfile -Command ^
  "Compress-Archive -Path '%PLUGIN_DIR%' -DestinationPath '%OUT_ZIP%' -Force"

IF EXIST "%OUT_ZIP%" (
    echo.
    echo SUCCESS: %OUT_ZIP%
    echo.
    echo Upload this file at:
    echo   https://plugins.qgis.org/plugins/add/
) ELSE (
    echo ERROR: ZIP was not created.
)
pause
