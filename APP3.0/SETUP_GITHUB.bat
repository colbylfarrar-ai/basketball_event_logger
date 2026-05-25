@echo off
:: ============================================================
::  SETUP_GITHUB.bat
::  Run this ONCE after creating your GitHub repository.
::  Steps:
::  1. Go to https://github.com/new
::  2. Name it "analytics-hub" (or anything you like)
::  3. Keep it PRIVATE (your data stays yours)
::  4. Do NOT add README, .gitignore, or license
::  5. Copy the repo URL (https://github.com/YOURNAME/analytics-hub.git)
::  6. Paste it when prompted below, then press Enter
:: ============================================================

echo.
echo  Analytics Hub - GitHub Setup
echo  ============================================================
echo.
set /p REPO_URL="Paste your GitHub repo URL and press Enter: "

cd /d "%~dp0"
git remote add origin %REPO_URL%
git branch -M main
git push -u origin main

echo.
echo  Done! Your code is now on GitHub.
echo  Database files and credentials are excluded (see .gitignore).
echo.
pause
