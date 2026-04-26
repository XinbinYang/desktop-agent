@echo off
chcp 65001 >nul
cd /d "%~dp0"
PowerShell -ExecutionPolicy Bypass -File "install.ps1"
pause