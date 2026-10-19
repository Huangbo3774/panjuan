# 磐卷 PaperForge · 一键安装并启动
# 用法：右键"用 PowerShell 运行"，或在 PowerShell 里执行  .\scripts\setup.ps1
#
# 为什么需要这个脚本：本机可能同时装着多个 Python，且默认 `python` 可能是 3.6
# （实测这台机器默认 python 是 3.6.8，装不了本项目任何依赖）。
# 所以脚本【显式挑 3.11+】，不依赖 PATH 顺序。

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Say($m) { Write-Host "  $m" }
function Head($m) { Write-Host "`n[$m]" -ForegroundColor Cyan }

Head "1/4  找 Python 3.11+"
$cands = @()
try {
    $listed = py --list-paths 2>$null
    if ($listed) {
        foreach ($line in $listed) {
            if ($line -match '^\s*-V:(\d)\.(\d+)\S*\s+\*?\s*(\S.*?\.exe)\s*$') {
                $maj = [int]$Matches[1]; $min = [int]$Matches[2]
                if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 11)) { if (Test-Path $Matches[3]) { $cands += $Matches[3] } }
            }
        }
    }
} catch { Say "py 启动器不可用，改用 PATH 探测" }

foreach ($exe in @("python", "python3")) {
    try {
        $v = & $exe -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($v -match '^(\d+)\.(\d+)$') {
            if ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11)) {
                $p = (Get-Command $exe).Source
                if ($cands -notcontains $p) { $cands += $p }
            }
        }
    } catch { }
}

if ($cands.Count -eq 0) {
    Write-Host "`n✗ 没找到 Python 3.11+。" -ForegroundColor Red
    Write-Host "  请到 https://www.python.org/downloads/ 安装（勾选 Add to PATH），重装后再跑本脚本。"
    exit 1
}
$PY = $cands[0]
Say "使用 $PY"
Say (& $PY --version)

Head "2/4  建虚拟环境"
if (-not (Test-Path "$root\.venv")) {
    & $PY -m venv "$root\.venv"
    Say "已创建 .venv"
} else { Say ".venv 已存在，跳过" }
$VPY = if (Test-Path "$root\.venv\Scripts\python.exe") { "$root\.venv\Scripts\python.exe" } else { "$root\.venv/bin/python" }

Head "3/4  装依赖（首次约 1–3 分钟）"
& $VPY -m pip install --upgrade pip --quiet | Out-Null
& $VPY -m pip install -r "$root\requirements.txt"
if ($LASTEXITCODE -ne 0) { Write-Host "✗ 依赖安装失败，检查网络或代理" -ForegroundColor Red; exit 1 }

Head "4/4  启动"
$port = if ($env:PORT) { $env:PORT } else { 8000 }
$url = "http://127.0.0.1:$port/"
Write-Host ""
Write-Host "  磐卷已就绪 → $url" -ForegroundColor Green
Write-Host "  局域网内手机/平板也能打开做题页（把 127.0.0.1 换成本机 IP）"
Write-Host "  Ctrl+C 停止服务" -ForegroundColor DarkGray
Write-Host ""
Start-Process $url
& $VPY -m uvicorn app.main:app --host 0.0.0.0 --port $port
