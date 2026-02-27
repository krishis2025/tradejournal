@echo off
REM ═══════════════════════════════════════════════════════════════
REM  Trade Journal — Git Setup Script (Windows)
REM  Run this ONCE to initialize the repo and push to GitHub.
REM ═══════════════════════════════════════════════════════════════

echo.
echo ═══════════════════════════════════════════════════
echo   Trade Journal — Git Setup
echo ═══════════════════════════════════════════════════
echo.

REM Check git is installed
where git >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: git is not installed.
    echo    Install it from: https://git-scm.com/downloads
    pause
    exit /b 1
)

REM Initialize repo if needed
if not exist ".git" (
    echo Initializing git repository...
    git init
    git branch -M main
    echo    Done.
) else (
    echo Git repo already exists.
)

REM Stage all files
echo.
echo Staging files...
git add -A
echo    Done.

REM Commit
set /p VERSION=<VERSION
echo.
echo Creating commit v%VERSION%...
git commit -m "v%VERSION% — Trade Journal release"
echo    Done.

REM Tag
git tag -a "v%VERSION%" -m "v%VERSION%"
echo    Tagged as v%VERSION%.

echo.
echo ═══════════════════════════════════════════════════
echo   Ready to push!
echo ═══════════════════════════════════════════════════
echo.
echo   1. Create a NEW repo on GitHub:
echo      https://github.com/new
echo.
echo   2. Then run:
echo      git remote add origin https://github.com/YOUR_USERNAME/tradejournal.git
echo      git push -u origin main
echo      git push --tags
echo.
pause
