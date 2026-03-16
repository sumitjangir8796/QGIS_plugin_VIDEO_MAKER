@echo off
REM ============================================================
REM  Corridor Video Maker – Quick Sync to GitHub
REM  Commits all workspace changes and pushes to GitHub.
REM  Double-click this after editing any plugin file.
REM ============================================================

SET REPO=C:\Users\sumitj\Desktop\Code\QGIS_Plugin_Video_Maker

cd /d "%REPO%"

echo === Corridor Video Maker  — GitHub Sync ===
echo.

REM Stage everything
git add -A
echo Staged changes:
git status --short

REM Check if there is anything to commit
git diff --cached --quiet
IF %ERRORLEVEL% EQU 0 (
    echo.
    echo Nothing to commit – workspace is already up to date on GitHub.
    pause
    EXIT /B 0
)

REM Auto-commit with timestamp
FOR /F "tokens=2 delims==" %%I IN ('wmic os get localdatetime /value 2^>nul') DO SET DT=%%I
SET TIMESTAMP=%DT:~0,4%-%DT:~4,2%-%DT:~6,2% %DT:~8,2%:%DT:~10,2%
git commit -m "Update %TIMESTAMP%: plugin changes"

echo.
echo Pushing to GitHub ...
git push origin master

echo.
IF %ERRORLEVEL% EQU 0 (
    echo SUCCESS – changes are live on GitHub.
) ELSE (
    echo Push failed. Check your internet connection or GitHub credentials.
)
pause
