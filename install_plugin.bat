@echo off
REM ============================================================
REM  Corridor Video Maker – Plugin Installer
REM  Copies the plugin folder to the QGIS user plugins directory.
REM ============================================================

SET SOURCE=%~dp0corridor_video_maker
SET DEST=%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\corridor_video_maker

echo Source : %SOURCE%
echo Dest   : %DEST%
echo.

IF NOT EXIST "%DEST%" (
    mkdir "%DEST%"
    echo Created plugin directory.
)

xcopy /E /Y /I "%SOURCE%" "%DEST%"

IF %ERRORLEVEL% EQU 0 (
    echo.
    echo Plugin installed successfully!
    echo Restart QGIS and enable "Corridor Video Maker" in Plugin Manager.
) ELSE (
    echo.
    echo ERROR: Copy failed. Check that the source path exists.
)
pause
