<#
.SYNOPSIS
    把本地节目单同步到 Gitee（GitHub Actions 出问题时的备用手段）。

.EXAMPLE
    # 只推送现有内容
    .\scripts\sync-gitee.ps1 -GiteeUser janpinz -Token <你的Gitee私人令牌>

.EXAMPLE
    # 先在本机重新抓一遍再推
    .\scripts\sync-gitee.ps1 -GiteeUser janpinz -Token <令牌> -Build
#>
param(
    [Parameter(Mandatory = $true)][string]$GiteeUser,
    [Parameter(Mandatory = $true)][string]$Token,
    [switch]$Build
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repoRoot

Write-Host "仓库目录：$repoRoot"

if ($Build) {
    Write-Host "`n[1/3] 重新抓取节目单…"
    python -m epg build --days 2
    if ($LASTEXITCODE -ne 0) { throw "构建失败（exit $LASTEXITCODE）" }
}

Write-Host "`n[2/3] 提交本地变更…"
git add -A dist data/archive
git diff --staged --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "没有变化，跳过提交"
} else {
    git commit -m "chore(epg): 本地同步 $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}

Write-Host "`n[3/3] 推送到 Gitee…"
$remote = "https://${GiteeUser}:${Token}@gitee.com/${GiteeUser}/cn-tv-epg.git"
git push $remote "HEAD:master" --force
if ($LASTEXITCODE -ne 0) { throw "推送失败（exit $LASTEXITCODE）" }

Write-Host "`n完成：https://gitee.com/$GiteeUser/cn-tv-epg"
Write-Host "节目单地址：https://gitee.com/$GiteeUser/cn-tv-epg/raw/master/dist/epg.xml"
