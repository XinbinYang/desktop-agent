@echo off
chcp 65001 >nul
cd /d "%~dp0"
PowerShell -ExecutionPolicy Bypass -File "start-all.ps1"
pause