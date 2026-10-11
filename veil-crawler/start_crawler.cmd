@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3.12 -X utf8 run_crawler.py --no-pause
if errorlevel 1 pause
