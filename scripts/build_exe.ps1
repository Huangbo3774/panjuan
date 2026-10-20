# 磐卷 PaperForge · 一键打成「免安装包」
#
# 产物：dist\PaperForge\（exe + _internal）与 dist\panjuan-v<版本>-windows.zip
# 家长侧的使用方式：下载 zip → 解压 → 双击 PaperForge.exe → 浏览器自动打开。
# 不需要 Python、不需要 PowerShell、不需要命令行。
#
# 为什么在【干净 venv】里构建，而不是直接用这台机的 Python：
#   本机全局 3.11 的 site-packages 里有 1.8GB 无关包（polars / playwright / gradio /
#   streamlit / scipy…）。PyInstaller 顺着 import 抓，环境越脏越容易把不该带的拽进来，
#   而且"这台机能打包"和"clone 下来也能打包"会是两回事。
#
# 用法：
#   .\scripts\build_exe.ps1              建 venv（首次）+ 装依赖 + 打包 + 压 zip
#   .\scripts\build_exe.ps1 -SkipVenv    用当前已就绪的 .venv-build
#   .\scripts\build_exe.ps1 -NoZip       只打包，不压缩（调试用）

param(
    [switch]$SkipVenv,
    [switch]$NoZip,
    [switch]$Clean,
    [string]$Version = "1.2.2"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$t0 = Get-Date
$venv = Join-Path $root ".venv-build"
$VPY = Join-Path $venv "Scripts\python.exe"
$dist = Join-Path $root "dist"
$appdir = Join-Path $dist "PaperForge"
$zipname = "panjuan-v$Version-windows.zip"   # GitHub 的资产名不吃中文，中文只能放 label
$zip = Join-Path $dist $zipname

function Say($m) { Write-Host "  $m" }
function Head($m) { Write-Host "`n[$m]" -ForegroundColor Cyan }
function Fail($m) { Write-Host "`n✗ $m" -ForegroundColor Red; exit 1 }
function SizeMB($p) {
    if (Test-Path -PathType Container $p) {
        $n = (Get-ChildItem -Recurse -File -Force $p | Measure-Object Length -Sum).Sum
    } elseif (Test-Path $p) { $n = (Get-Item $p).Length } else { return 0 }
    return [math]::Round($n / 1MB, 1)
}

# ── 1) 干净 venv ────────────────────────────────────────────
Head "构建环境 .venv-build"
if (-not $SkipVenv) {
    if (-not (Test-Path $VPY)) {
        $py = Get-Command "py" -ErrorAction SilentlyContinue
        if ($py) { & py -3.11 -m venv $venv } else { & python -m venv $venv }
        if (-not (Test-Path $VPY)) { Fail "虚拟环境没建起来：$VPY" }
    }
    Say "python = $VPY"
    & $VPY -c "import sys; print('  版本', sys.version.split()[0])"
    if ($Clean) {
        Say "清掉旧的构建缓存 build/ dist/"
        foreach ($d in @((Join-Path $root "build"), $dist)) { if (Test-Path $d) { Remove-Item -Recurse -Force $d } }
    }
    Say "装依赖（requirements.txt + pyinstaller，首次要几分钟）…"
    & $VPY -m pip install --upgrade pip --quiet | Out-Null
    & $VPY -m pip install -r (Join-Path $root "requirements.txt") --quiet
    if ($LASTEXITCODE -ne 0) { Fail "依赖装失败，看上面的 pip 报错" }
    & $VPY -m pip install "pyinstaller>=6.0" --quiet
    if ($LASTEXITCODE -ne 0) { Fail "pyinstaller 装失败" }
    # 打包用的依赖必须自己也在清单上：以前 python-multipart 是从别处蹭来的，
    # 干净环境一装就暴露（上传接口 500）。这里当一次哨兵。
    & $VPY -c "import multipart, fitz, cv2, onnxruntime, rapidocr_onnxruntime, reportlab, docx; print('  依赖齐')"
    if ($LASTEXITCODE -ne 0) { Fail "干净 venv 里缺依赖 —— requirements.txt 漏写了东西" }
} else {
    if (-not (Test-Path $VPY)) { Fail "-SkipVenv 但 .venv-build 不存在" }
    Say "沿用现有 .venv-build"
}

# ── 2) 打包 ─────────────────────────────────────────────────
Head "PyInstaller（onedir）"
if (Test-Path $appdir) { Remove-Item -Recurse -Force $appdir }
& $VPY -m PyInstaller --noconfirm --clean `
    --distpath $dist --workpath (Join-Path $root "build") `
    (Join-Path $root "packaging\paperforge.spec")
if ($LASTEXITCODE -ne 0) { Fail "打包失败" }
if (-not (Test-Path (Join-Path $appdir "PaperForge.exe"))) { Fail "产物里没有 PaperForge.exe" }

# ── 3) 装配：把用户看得见的数据目录先建好 ───────────────────
Head "装配产物"
foreach ($d in @("data", "var")) {
    $p = Join-Path $appdir $d
    New-Item -ItemType Directory -Force -Path $p | Out-Null
    # 空目录压进 zip 后会丢，放一个说明文件既占位又解释
    Set-Content -Path (Join-Path $p "README.txt") -Encoding UTF8 `
        -Value $(if ($d -eq "data") { "试卷、题目、标准答案、作答记录都在这里。删掉这个文件夹等于清空全部卷子。" }
                 else { "临时工作目录：每次启动程序会清空，不放任何长期数据。" })
}
$readme = Join-Path $appdir "使用说明.txt"
@"
磐卷 PaperForge · 免安装版
--------------------------------------------------
怎么用
  1. 把整个文件夹解压到任意位置（【不要】在压缩包里直接双击运行）
  2. 双击 PaperForge.exe
  3. 浏览器会自动打开 http://127.0.0.1:8000/ ，把老师发的作业拖进去

那个黑色窗口是什么
  就是程序本身。关掉它 = 停止磐卷；数据不会丢，下次双击 exe 继续用。

东西存在哪
  data\   试卷、题目、标准答案、作答记录（要备份就拷这个文件夹）
  var\    临时文件，每次启动自动清空

隐私
  全程只在你这台电脑上运行，不联网、不上传、无账号、无广告。
  代码开源：GitHub 搜 paper-forge（磐卷 PaperForge），MIT 协议。

常见问题
  · 浏览器没自动打开 → 自己访问 http://127.0.0.1:8000/
  · 提示"端口被占用/已在跑" → 说明已经有一个磐卷在运行，直接用那个窗口
  · Windows 已保护你的电脑 / SmartScreen → 点「更多信息」→「仍要运行」；
    这是未做付费代码签名的正常现象，不是病毒（签名是可选增强，见仓库 docs）
  · 换电脑 → 把整个文件夹拷过去即可，data\ 里的卷子会跟着走
"@ | Set-Content -Path $readme -Encoding UTF8
Say "PaperForge.exe + _internal + data/ + var/ + 使用说明.txt"

# ── 4) 压缩 ─────────────────────────────────────────────────
Head "体积与耗时"
$exeSize = SizeMB (Join-Path $appdir "PaperForge.exe")
Say ("exe            {0} MB" -f $exeSize)
Say ("_internal      {0} MB" -f (SizeMB (Join-Path $appdir "_internal")))
Say ("整个文件夹      {0} MB" -f (SizeMB $appdir))
Say ("文件数         {0}" -f (Get-ChildItem -Recurse -File -Force $appdir).Count)

if (-not $NoZip) {
    if (Test-Path $zip) { Remove-Item -Force $zip }
    Head "压缩 zip"
    Compress-Archive -Path $appdir -DestinationPath $zip -CompressionLevel Optimal
    Say ("{0}  {1} MB" -f $zipname, (SizeMB $zip))
}

$dt = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
Write-Host "`n✓ 打包完成，用时 $dt 秒" -ForegroundColor Green
Say "产物：$appdir"
if (-not $NoZip) { Say "下载包：$zip" }
Say "下一步（必做）：对这份 exe 跑一遍验收，别只看它能双击"
Say "  1) 双击 dist\PaperForge\PaperForge.exe  （或 .\dist\PaperForge\PaperForge.exe --port 8000）"
Say  "  2) `$env:PJ_BASE='http://127.0.0.1:8000'; py -3.11 tests\acceptance_v11.py"
exit 0
