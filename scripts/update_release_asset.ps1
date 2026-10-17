# 用最新提交重打发行包并替换 Release 上的旧附件。
# 凭据走 Git Credential Manager，不落文件、不打印。

param(
    [Parameter(Mandatory = $true)][string]$Owner,
    [string]$Repo = "panjuan",
    [string]$Tag = "v1.0.0",
    # 附件名里的版本要和 README 写的下载名一致（README 用 panjuan-v1.0.zip）。
    # 曾把 $Tag 直接拼进文件名，得到 panjuan-v1.0.0.zip，文档与实际下载名不一致。
    [string]$Version = "1.0"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$raw = "protocol=https`nhost=github.com`n" | git credential fill
$token = ($raw | Select-String -Pattern '^password=').Line.Substring(9)
$H = @{ Authorization = "Bearer $token"; Accept = "application/vnd.github+json";
       "User-Agent" = "panjuan-release" }

$zip = Join-Path $root "..\$Repo-v$Version.zip"
git archive --format=zip -o $zip HEAD
Write-Host ("  重打发行包 {0} KB" -f [math]::Round((Get-Item $zip).Length / 1KB))

$rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo/releases/tags/$Tag" -Headers $H
foreach ($a in $rel.assets) {
    Invoke-RestMethod -Uri $a.url -Headers $H -Method Delete | Out-Null
    Write-Host "  删除旧附件 $($a.name)"
}

$up = ($rel.upload_url -replace '\{\?name,label\}', '') + "?name=$Repo-v$Version.zip"
$bytes = [System.IO.File]::ReadAllBytes($zip)
Invoke-RestMethod -Uri $up -Headers $H -Method Post -Body $bytes `
    -ContentType "application/zip" | Out-Null
Write-Host "  已上传新附件 $Repo-v$Version.zip"

$chk = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo/releases/tags/$Tag" -Headers $H
foreach ($a in $chk.assets) {
    Write-Host ("  线上确认: {0}  {1} KB  上传于 {2}" -f $a.name, [math]::Round($a.size/1KB), $a.updated_at)
}
