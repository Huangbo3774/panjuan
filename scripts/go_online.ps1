# 磐远试卷打印助手 · 一键上线
# 前提：这台机器已登录过 GitHub（没登录也没关系，脚本会弹浏览器让你授权一次）。
# 凭据由 Git Credential Manager 保管，不写进文件、不经过任何第三方。
#
# 用法：在 paper-forge 文件夹的地址栏输入 powershell 回车，然后执行
#   .\scripts\go_online.ps1 -Owner Huangbo3774 -Repo panjuan
# 加 -Private 可先建成私有仓库，确认无误后再转公开。

param(
    [Parameter(Mandatory = $true)][string]$Owner,
    [string]$Repo = "panjuan",
    [switch]$Private
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Head($m) { Write-Host "`n[$m]" -ForegroundColor Cyan }

# ---- 1. 取 GitHub API 令牌（GCM 弹浏览器授权，绝不读你的密码） ----
Head "1/5  取得 GitHub 授权"
$raw = "protocol=https`nhost=github.com`n" | git credential fill
$token = ($raw | Select-String -Pattern '^password=').Line.Substring(9)
if (-not $token) { Write-Host "✗ 没拿到令牌，请先在浏览器登录一次 github.com"; exit 1 }
Write-Host "  已取得授权（令牌只显示长度：$($token.Length) 位，不打印内容）"

$H = @{ Authorization = "Bearer $token"; Accept = "application/vnd.github+json";
       "X-GitHub-Api-Version" = "2022-11-28"; "User-Agent" = "panjuan-release" }

# ⚠️ PS 5.1 的 Invoke-RestMethod 传字符串 body 时按系统 ANSI（中文机=GBK）编码，
#    非 ASCII 会被替换成 '?'。GitHub 收到的仓库描述就变成 "?????"。
#    所有带中文的写操作必须走这个函数：显式转 UTF-8 字节。
#    注意别再给 Content-Type 加 charset=utf-8 —— 加了 PS 会拒绝 byte[] body。
function Put-JsonUtf8($uri, $obj, $method = "Post") {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes(($obj | ConvertTo-Json -Depth 6))
    Invoke-RestMethod -Uri $uri -Headers $H -Method $method -Body $bytes -ContentType "application/json"
}

# ---- 2. 建仓库 ----
Head "2/5  创建仓库 $Owner/$Repo"
try {
    $exist = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo" -Headers $H -Method Get
    Write-Host "  仓库已存在，跳过创建（id=$($exist.id)）"
} catch {
    $body = @{ name = $Repo; description = "把老师发的 PDF/图片/Word 作业一键变成标准 A4 试卷：自动清洗、去灰底、省墨、2合1。本地运行不上传，MIT 开源免费。"; private = [bool]$Private }
    Put-JsonUtf8 "https://api.github.com/user/repos" $body | Out-Null
    Write-Host "  已创建"
}

# ---- 3. 推代码 ----
Head "3/5  推送"
# ⚠️ 这里不能用 `git ... 2>$null`：在 $ErrorActionPreference='Stop' 下，
#    git 往 stderr 写的正常提示会被 PowerShell 当成终止错误抛出来，
#    导致脚本在"远端还不存在"这个最常见的情况下直接崩掉（实测踩过）。
$ErrorActionPreference = "Continue"
$has = ((git remote get-url origin 2>&1) | Out-String)
$ErrorActionPreference = "Stop"
$url = "https://github.com/$Owner/$Repo.git"
if ($has -match 'github\.com') { git remote set-url origin $url } else { git remote add origin $url }
git branch -M main
git push -u origin main --quiet
if ($LASTEXITCODE -ne 0) { Write-Host "✗ 推送失败（多半是授权没通过），后面几步已跳过"; exit 1 }
Write-Host "  推送完成"

# ---- 4. Topics（GitHub 搜索/Explore 的入口） ----
Head "4/5  设置 Topics"
# 不用 'paper'：GitHub 上大量指向论文，会把项目埋掉；worksheet 才是家长搜的词
$topics = @("education","homework","exam","pdf","printing","ocr","selfhosted",
            "local-first","privacy","chinese","k12","teacher","worksheet","fastapi","python")
Put-JsonUtf8 "https://api.github.com/repos/$Owner/$Repo/topics" @{ names = $topics } "Put" | Out-Null
Write-Host "  已设 $($topics.Count) 个标签"

# ---- 5. Release + 发行包 ----
Head "5/5  发 Release v1.0.0"
$zip = Join-Path $root "..\panjuan-v1.0.zip"
git archive --format=zip -o $zip HEAD
$size = [math]::Round((Get-Item $zip).Length / 1KB)
Write-Host "  发行包 $size KB"

$notes = @"
## V1.0 打印引擎

任意 PDF / 图片 / Word -> 一张标准 A4 试卷 PDF。

**它解决的事**：老师深夜发来三张糊照片，打印店关门，家里没墨。1-2 秒出一张干净 A4，不用去打印店。

**下载即用**：解压 -> 双击 start.bat -> 自动装依赖并启动 -> 浏览器自动打开。需要 Python 3.11+。

- 自动清洗：去灰底、纠偏、裁边（按清晰度决定要不要洗，不对清晰图乱动手）
- 混合格式一次拖入，顺序即页序
- 省墨模式、字号缩放、2 合 1 省纸
- 全程本机，零外部请求，无账号无埋点，MIT 永久免费

**已知不做**：.doc 老格式、手写作业识别、数学公式排版。
验收：11 条自动化用例全过。
"@

$rel = @{ tag_name = "v1.0.0"; name = "V1.0 打印引擎：任意文档 → 一张干净 A4";
          body = $notes; draft = $false; prerelease = $false }
$ErrorActionPreference = "Continue"
try {
    $r = Put-JsonUtf8 "https://api.github.com/repos/$Owner/$Repo/releases" $rel
} catch {
    # 重跑时标签已存在：改查已有 release，别把整个脚本崩在最后一步
    Write-Host "  创建 Release 报错（可能已存在），改为查找既有 Release"
    $r = (Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo/releases/tags/v1.0.0" -Headers $H)
}
$ErrorActionPreference = "Stop"
if (-not $r) { Write-Host "✗ 拿不到 Release，后续上传跳过"; exit 1 }

# 上传 zip：先取 upload_url，把 {name} 替换掉
$up = ($r.upload_url -replace '\{\?name,label\}', '') + "?name=panjuan-v1.0.zip"
$bytes = [System.IO.File]::ReadAllBytes($zip)
Invoke-RestMethod -Uri $up -Headers $H -Method Post -Body $bytes `
    -ContentType "application/zip" | Out-Null

Write-Host "`n===== 上线完成 =====" -ForegroundColor Green
Write-Host "  https://github.com/$Owner/$Repo"
Write-Host "  Release: $($r.html_url)"
if ($Private) { Write-Host "  ⚠️ 当前是私有仓库，公开后才会被搜到：Settings → Danger Zone → Change visibility" }
