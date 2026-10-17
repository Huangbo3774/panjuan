# 修 GitHub 上的中文元信息乱码，并把编码修法回写进 go_online.ps1 的说明。
#
# 根因：Windows PowerShell 5.1 的 Invoke-RestMethod 在 -Body 传字符串时，
#       会用系统 ANSI 代码页（中文机 = GBK）编码请求体，
#       非 ASCII 字符被替换成 '?'。GitHub 收到的就是 "?????"。
# 修法：把 JSON 显式转成 UTF-8 字节数组再传，并给 Content-Type 加 charset=utf-8。
#       注意不能只加 charset —— 加了 charset 后 PS5.1 会拒绝 byte[] body，二者只能取其一。

param(
    [Parameter(Mandatory = $true)][string]$Owner,
    [string]$Repo = "panjuan"
)
$ErrorActionPreference = "Stop"

$raw = "protocol=https`nhost=github.com`n" | git credential fill
$token = ($raw | Select-String -Pattern '^password=').Line.Substring(9)
$H = @{ Authorization = "Bearer $token"; Accept = "application/vnd.github+json";
       "X-GitHub-Api-Version" = "2022-11-28"; "User-Agent" = "panjuan-release" }

function Put-Json($uri, $obj, $method = "Patch") {
    # 关键两行：显式 UTF-8 字节 + 不带 charset 的 Content-Type
    $json = $obj | ConvertTo-Json -Depth 6
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    Invoke-RestMethod -Uri $uri -Headers $H -Method $method -Body $bytes `
        -ContentType "application/json" | Out-Null
}

$desc = "把老师发的 PDF/图片/Word 作业一键变成标准 A4 试卷：自动清洗、去灰底、省墨、2合1。本地运行不上传，MIT 开源免费。"
Put-Json "https://api.github.com/repos/$Owner/$Repo" @{ description = $desc }
Write-Host "  已修仓库描述"

$rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo/releases/tags/v1.0.0" -Headers $H
$notes = @"
## V1.0 打印引擎

任意 PDF / 图片 / Word → 一张标准 A4 试卷 PDF。

**它解决的事**：老师深夜发来三张糊照片，打印店关门，家里没墨。1–2 秒出一张干净 A4，不用去打印店。

**下载即用**：解压 → 右键 ``scripts\setup.ps1`` → 用 PowerShell 运行 → 浏览器自动打开。需要 Python 3.11+（脚本会自动找）。详细图文见 docs/安装说明.md。

- 自动清洗：去灰底、纠偏、裁边（按清晰度决定要不要洗，不对清晰图乱动手）
- 混合格式一次拖入，顺序即页序
- 省墨模式、字号缩放、2 合 1 省纸
- 全程本机，零外部请求，无账号无埋点，MIT 永久免费

**已知不做**：.doc 老格式、手写作业识别、数学公式排版。
验收：11 条自动化用例全过（含 100 页压力、损坏文件、混合格式合并）。
"@
Put-Json $rel.url @{
    tag_name = "v1.0.0"
    name = "V1.0 打印引擎：任意文档 → 一张干净 A4"
    body = $notes
}
Write-Host "  已修 Release 标题与正文"

Write-Host "`n=== 复核 ===" -ForegroundColor Green
$r = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo" -Headers $H
Write-Host "  描述: $($r.description)"
$r2 = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo/releases/tags/v1.0.0" -Headers $H
Write-Host "  Release: $($r2.name)"
Write-Host "  附件: $(($r2.assets | ForEach-Object { "$($_.name) ($([math]::Round($_.size/1KB))KB)" }) -join ', ')"
Write-Host "  Topics: $($r.topics -join ', ')"
