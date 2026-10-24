# 磐远试卷打印助手 · 注册「网页上一键启动服务」
#
# 浏览器里的网页【不能】自己启动本地进程（安全沙箱，任何网站都做不到）。
# 唯一合规的做法是注册一个 Windows 自定义协议（panjuan://），
# 网页上的按钮点一下 = 让系统去跑我们注册好的那条命令。
#
# 全部写在 HKCU（当前用户），不需要管理员权限；随时 -Remove 干净撤掉。
# 注册表读写一律用 .NET Registry API：PowerShell 的 Set-ItemProperty 对
# "(Default)"（未命名值）的行为在不同版本上不一致，写没写进去不能靠猜 —— 
# 本脚本写完立刻读回来核对，读不到就报错退出。
#
# 用法：
#   .\scripts\install_startup.ps1              注册协议（start.bat 会自动跑这个）
#   .\scripts\install_startup.ps1 -AutoStart   再额外加"登录时自动启动"
#   .\scripts\install_startup.ps1 -Remove      撤销全部
#   .\scripts\install_startup.ps1 -Check       只查现在注册成什么样

param(
    [switch]$Remove,
    [switch]$AutoStart,
    [switch]$Check,
    [switch]$CheckThis,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
# 让 -Check 的输出在任何代码页下都是 UTF-8：调用方（测试脚本）用 utf-8 解码才不会把
# 中文路径读成乱码，从而把"指向本检出"误判成"指向别处"。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$root    = Split-Path -Parent $PSScriptRoot
$vbs     = Join-Path $root "scripts\start_hidden.vbs"
$subkey  = "Software\Classes\panjuan"
$cmdSub  = "$subkey\shell\open\command"
$startupDir = [Environment]::GetFolderPath("Startup")
$lnkPath = Join-Path $startupDir "磐远磐远试卷打印助手.lnk"

function Say($m) { if (-not $Quiet) { Write-Host "  $m" } }

# ── 读写辅助：默认值(未命名)用 $null 当名字，这是 .NET 的正规写法 ──
function Get-RegValue([string]$path, [string]$name) {
    $k = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($path)
    if (-not $k) { return $null }
    try { return $k.GetValue($name) } finally { $k.Close() }
}
function Set-RegValue([string]$path, [string]$name, $value) {
    $k = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($path)
    try { $k.SetValue($name, $value) } finally { $k.Close() }
}

if ($Check) {
    $c = Get-RegValue $cmdSub $null
    if ($c) { Write-Host "REGISTERED panjuan:// → $c"; exit 0 }
    Write-Host "NOT-REGISTERED"; exit 2
}

# 给测试用的"判决式"检查：把结论放进退出码，而不是让调用方去比对输出文本。
#   0 = 已注册且指向【当前这份检出】；2 = 没注册；3 = 注册了但指向别处（文件夹挪过了）
# 为什么不用 -Check 的文本：中文路径经不同代码页转手会变乱码，比对结果就成了假判决
# （尺文同源的老毛病，只不过这次同源的是编码）。
if ($CheckThis) {
    $c = Get-RegValue $cmdSub $null
    if (-not $c) { Write-Host "NOT-REGISTERED"; exit 2 }
    # 用 Contains 而不是 -like：路径里出现 [ ] * ? 时 -like 的通配语义会误判
    if ($c.ToLower().Contains($vbs.ToLower())) { Write-Host "HERE $c"; exit 0 }
    Write-Host "ELSEWHERE $c"; Write-Host "expected $vbs"; exit 3
}

if ($Remove) {
    Write-Host "`n[撤销]"
    if ([Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($subkey)) {
        [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($subkey, $false)
        Say "已删除协议 panjuan://"
    } else { Say "协议本来就没注册" }
    if (Test-Path $lnkPath) { Remove-Item -Force $lnkPath; Say "已删除开机启动项" }
    else { Say "开机启动项本来就没有" }
    exit 0
}

if (-not (Test-Path $vbs)) {
    Write-Host "✗ 找不到 $vbs" -ForegroundColor Red
    exit 1
}

# 命令行：用 wscript 跑 vbs → 不会闪控制台窗口；"%1" 是浏览器传来的 URI，vbs 里忽略
$command = 'wscript.exe "{0}" "%1"' -f $vbs

Say "注册 panjuan:// ..."
Set-RegValue $subkey       $null        "URL:磐远试卷打印助手"
Set-RegValue $subkey       "URL Protocol" ""
Set-RegValue $cmdSub       $null        $command

# 写完必须读回来核对：注册表写失败一般是安全软件拦截，不能只当成功
$back = Get-RegValue $cmdSub $null
if ($back -ne $command) {
    Write-Host "✗ 协议命令没写对。期望：$command`n  实际：$back" -ForegroundColor Red
    Write-Host "  可能被安全软件拦了注册表写入。不影响手动启动：双击 start.bat 一样能用。"
    exit 1
}
if ((Get-RegValue $subkey "URL Protocol") -eq $null) {
    Write-Host "✗ URL Protocol 标记缺失，浏览器不会把它当协议处理" -ForegroundColor Red
    exit 1
}
Say "HKCU\$subkey → $back"

if ($AutoStart) {
    Write-Host "`n[登录时自动启动]" -ForegroundColor Cyan
    $sh  = New-Object -ComObject WScript.Shell
    $lnk = $sh.CreateShortcut($lnkPath)
    $lnk.TargetPath       = "wscript.exe"
    $lnk.Arguments        = "`"$vbs`""
    $lnk.WorkingDirectory = $root
    $lnk.Description      = "磐远试卷打印助手 本机服务"
    $lnk.Save()
    if (Test-Path $lnkPath) { Say "已加入启动文件夹：$lnkPath" }
    else { Write-Host "✗ 启动项没创建成功" -ForegroundColor Red; exit 1 }
}

if (-not $Quiet) {
    Write-Host "`n✓ 完成。以后在网页上看到「启动服务」按钮，点一下就会拉起本机服务。" -ForegroundColor Green
    Write-Host "  浏览器会弹一次确认框（Windows 对自定义协议的规定动作），勾选「总是允许」后就不再问。"
    Write-Host "  想撤销：.\scripts\install_startup.ps1 -Remove"
}
exit 0
