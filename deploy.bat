@echo off
REM 雙擊呢個檔案就會用 PowerShell 執行 deploy.ps1
REM (繞過 PowerShell 預設禁止執行未簽署 script 嘅限制)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1"
pause
