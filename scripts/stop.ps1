# 磐远试卷打印助手 · 停止本机服务
# 用法：双击 stop.bat，或在 PowerShell 里执行 .\scripts\stop.ps1
param([int]$Port = 8000)
$ErrorActionPreference = "Continue"
& (Join-Path $PSScriptRoot "start.ps1") -Stop -Port $Port
