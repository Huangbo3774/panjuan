# 磐卷 PaperForge · 一键启动（双击 start.bat 即可，不用手动开服务）
#
# 它做四件事：
#   1) 先看 8000 端口有没有服务在跑 —— 有就直接开浏览器，不再起第二个
#      （重复启动会端口冲突、uvicorn 静默绑定失败，然后你测的是旧进程，这个坑踩过）
#   2) 没有就挑一个 Python 3.11+（优先 .venv），后台把服务拉起来
#   3) 等 /api/health 真的能通，再打开浏览器 —— 不是"睡两秒就打开"那种假等待
#   4) 依赖没装齐时，明确告诉你去跑一次 setup.ps1，而不是黑框一闪而过
#
# 停止：双击 stop.bat（或 scripts\start.ps1 -Stop）

param(
    [int]$Port = 8000,
    [switch]$Stop,
    [switch]$NoBrowser,
    [switch]$Status
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$url = "http://127.0.0.1:$Port/"
$pidFile = Join-Path $root "var\server.pid"
$logFile = Join-Path $root "var\server.log"

function Say($m) { Write-Host "  $m" }
function Head($m) { Write-Host "`n[$m]" -ForegroundColor Cyan }
function Fail($m) { Write-Host "`n✗ $m" -ForegroundColor Red; exit 1 }

function Test-Alive([int]$p) {
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:$p/api/health" -TimeoutSec 2
        return $r
    } catch { return $null }
}

function Get-PortOwner([int]$p) {
    try {
        $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        if ($c) { return [int]($c | Select-Object -First 1).OwningProcess }
    } catch { }
    return $null
}

# ── 停止 ────────────────────────────────────────────────
if ($Stop) {
    Head "停止磐卷服务"
    $killed = @()
    $owner = Get-PortOwner $Port
    if ($owner) { Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue; $killed += $owner }
    if (Test-Path $pidFile) {
        $old = (Get-Content $pidFile -Raw).Trim()
        if ($old -match '^\d+$') { Stop-Process -Id ([int]$old) -Force -ErrorAction SilentlyContinue; $killed += [int]$old }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
    if ($killed.Count) { Say "已结束进程：$($killed -join ', ')" } else { Say "没有正在运行的服务" }
    exit 0
}

if ($Status) {
    $h = Test-Alive $Port
    if ($h) { Write-Host "RUNNING $url (pid=$($h.pid))"; exit 0 }
    Write-Host "STOPPED"; exit 2
}

# ── 注册 panjuan://（网页上的「启动服务」按钮靠它）────────────
# 放在最前面、且在"已在跑就退出"之前：不管这次有没有真的起服务，
# 用户都该拿到可用的按钮。每次都注册是幂等的、几十毫秒，
# 项目文件夹挪位置后注册表里那条命令也会自动跟着更新。
# 这一步失败不影响启动，所以只提示、不退出。
Head "注册网页一键启动"
$installer = Join-Path $root "scripts\install_startup.ps1"
if (Test-Path $installer) {
    & $installer -Quiet
    if ($LASTEXITCODE -eq 0) { Say "panjuan:// 就绪：以后双击 HTML 也能在网页上点「启动服务」" }
    else { Say "协议没注册上（多半是安全软件拦注册表）。不影响使用，照常双击 start.bat 即可。" }
} else { Say "找不到 install_startup.ps1，跳过（网页上只能手动启动）" }

# ── 已在跑就别再起第二个 ─────────────────────────────────
Head "检查服务"
$h = Test-Alive $Port
if ($h) {
    Say "服务已经在跑了（pid=$($h.pid)），直接打开页面"
    if (-not $NoBrowser) { Start-Process $url }
    Say $url
    exit 0
}

# ── 挑 Python：优先 .venv，其次显式找 3.11+ ──────────────
Head "选择 Python 3.11+"
$PY = $null
foreach ($cand in @((Join-Path $root ".venv\Scripts\python.exe"), (Join-Path $root ".venv\bin\python"))) {
    if (Test-Path $cand) { $PY = $cand; Say "虚拟环境 $cand"; break }
}
if (-not $PY) {
    try {
        foreach ($line in (py --list-paths 2>$null)) {
            if ($line -match '^\s*-V:(\d)\.(\d+)\S*\s+\*?\s*(\S.*?\.exe)\s*$') {
                if ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11)) {
                    $PY = $Matches[3]; if (Test-Path $PY) { Say "系统 Python $PY"; break } else { $PY = $null }
                }
            }
        }
    } catch { }
}
if (-not $PY) {
    Fail "没找到 Python 3.11+。请先跑一次 scripts\setup.ps1（它会自动安装并建虚拟环境）。"
}

# ── 依赖是否齐（首次没装就直接告诉用户去跑 setup） ────────
Head "检查依赖"
& $PY -c "import fastapi, uvicorn, pymupdf, reportlab, cv2, numpy" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Say "依赖还没装好，正在调用安装脚本（首次约 1–3 分钟）…"
    & (Join-Path $root "scripts\setup.ps1")
    exit $LASTEXITCODE
}
Say "依赖齐全"

# ── 后台拉起服务 ─────────────────────────────────────────
Head "启动服务"
New-Item -ItemType Directory -Force -Path (Join-Path $root "var") | Out-Null
# 用 cmd /c 包一层再隐藏窗口：
#   · Start-Process 直接带 -RedirectStandardOutput 会让 python 继承启动脚本的控制台句柄，
#     双击 .bat 的那个黑框会一直挂着不返回（实测卡住 200s+），用户以为没启动。
#   · 重定向交给 cmd 做（>> 日志 2>&1），父进程 80ms 就返回，日志照样有。
$errLog = Join-Path $root "var\server.err.log"
$inner = "cd /d `"$root`" && `"$PY`" -m uvicorn app.main:app --host 127.0.0.1 --port $Port " +
         "--log-level warning >> `"$logFile`" 2>&1"
$proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $inner -WindowStyle Hidden -PassThru
if (-not $proc -or -not $proc.Id) {
    Fail "后台进程没拉起来。请在 PowerShell 里手动跑一次看报错：.\scripts\start.ps1"
}
$proc.Id | Out-File -FilePath $pidFile -Encoding ascii -NoNewline
Say "进程 $($proc.Id)，日志 var\server.log"

# ── 等健康检查真通过，再开浏览器 ──────────────────────────
Head "等待就绪"
$ready = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    $ready = Test-Alive $Port
    if ($ready) { break }
    if ($proc.HasExited -and -not (Test-Alive $Port)) {
        # cmd 退出而服务没起来 = 启动失败，把日志尾巴直接给用户看
        if (Test-Path $errLog) { Get-Content $errLog -Tail 10 | ForEach-Object { Say $_ } }
        break
    }
}
if (-not $ready) {
    Write-Host "`n✗ 服务没起来。看一下 var\server.err.log 的最后几行：" -ForegroundColor Red
    if (Test-Path (Join-Path $root "var\server.err.log")) {
        Get-Content (Join-Path $root "var\server.err.log") -Tail 12 | ForEach-Object { Say $_ }
    }
    Fail "启动失败"
}

Say "就绪，pid=$($ready.pid) · 字体 $($ready.font)"
Write-Host "`n  磐卷已打开 → $url" -ForegroundColor Green
Say "关掉这个窗口不影响服务；要停止请双击 stop.bat"
if (-not $NoBrowser) { Start-Process $url }
exit 0
