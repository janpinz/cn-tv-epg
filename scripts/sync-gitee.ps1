<#
.SYNOPSIS
    全流程同步到 Gitee：抓取 → 生成 → 发布发行版附件 → 推送代码。
    不依赖 GitHub，已挂成 Windows 计划任务每天自动跑。

.EXAMPLE
    .\scripts\sync-gitee.ps1                    # 用 %USERPROFILE%\.cn-tv-epg\gitee.token
    .\scripts\sync-gitee.ps1 -SkipBuild         # 只发布，不重新抓
    .\scripts\sync-gitee.ps1 -Token xxx -SkipPush

.NOTES
    本文件必须保存为 UTF-8 **带 BOM**，否则 Windows PowerShell 5.1 会按 GBK 解码导致中文乱码。
#>
param(
    [string]$GiteeUser = 'janpin',
    [string]$Token = '',
    [switch]$SkipBuild,
    [switch]$SkipPush,
    [string]$PythonPath = ''
)

# 注意：不要用 'Stop'。PowerShell 5.1 里原生命令往 stderr 写东西（比如 git 的换行符警告），
# 在 Stop 模式下会被当成终止性错误。这里统一用 Continue，靠 $LASTEXITCODE 判断成败。
$ErrorActionPreference = 'Continue'
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repoRoot

$logDir = Join-Path $env:USERPROFILE '.cn-tv-epg'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir 'sync.log'

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Host $line
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
}

function Stop-Sync([string]$Message) {
    Write-Log "!! $Message"
    exit 1
}

# 计划任务里没有用户的 PATH，所以自己按优先级找可执行文件
function Resolve-Tool([string[]]$Candidates, [string]$Name) {
    foreach ($c in $Candidates) {
        if ($c -and (Test-Path -LiteralPath $c)) { return $c }
    }
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike '*WindowsApps*') { return $cmd.Source }
    return $null
}

# 令牌优先级：参数 > 环境变量 > 文件
if (-not $Token) { $Token = $env:GITEE_TOKEN }
$tokenFile = Join-Path $logDir 'gitee.token'
if (-not $Token -and (Test-Path $tokenFile)) {
    $Token = (Get-Content -LiteralPath $tokenFile -Raw).Trim()
}
if (-not $Token) {
    Stop-Sync "缺少 Gitee 令牌：请用 -Token 传入，或写入 $tokenFile"
}

Write-Log "===== 开始同步（$repoRoot） ====="
# 让 Python 在管道里也用 UTF-8 输出，否则中文日志会 UnicodeEncodeError
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$pythonCandidates = @(
    $PythonPath,
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
    'C:\Program Files\Python312\python.exe',
    'C:\Program Files\Python311\python.exe'
)
$python = Resolve-Tool $pythonCandidates 'python'
if (-not $python) { Stop-Sync "找不到 Python，请先安装 Python 3.11+（winget install Python.Python.3.12）" }
Write-Log "Python: $python"

$git = Resolve-Tool @('C:\Program Files\Git\cmd\git.exe', 'C:\Program Files (x86)\Git\cmd\git.exe') 'git'
if (-not $git) { Stop-Sync "找不到 git，请先安装 Git" }
$env:Path = (Split-Path -Parent $git) + ';' + $env:Path
Write-Log "Git:    $git"

if (-not $SkipBuild) {
    Write-Log "[1/4] 抓取并生成节目单"
    & $python -m epg build --days 2
    if ($LASTEXITCODE -ne 0) { Stop-Sync "构建失败（exit $LASTEXITCODE）" }
} else {
    Write-Log "[1/4] 跳过构建"
}

Write-Log "[2/4] 发布发行版附件"
$env:GITEE_USER = $GiteeUser
$env:GITEE_TOKEN = $Token
& $python scripts/publish_gitee.py dist/epg.xml dist/epg.json
if ($LASTEXITCODE -ne 0) { Stop-Sync "发布失败（exit $LASTEXITCODE）" }

if ($SkipPush) {
    Write-Log "[3/4] 跳过代码推送"
} else {
    Write-Log "[3/4] 提交并推送代码到 Gitee"
    & $git add -A dist data/archive
    & $git diff --staged --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Log "  没有变化，跳过提交"
    } else {
        & $git commit -q -m "chore(epg): 本地同步 $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
        if ($LASTEXITCODE -ne 0) { Stop-Sync "提交失败（exit $LASTEXITCODE）" }
        $remote = "https://${GiteeUser}:${Token}@gitee.com/${GiteeUser}/cn-tv-epg.git"
        & $git push $remote "HEAD:master" --force
        if ($LASTEXITCODE -ne 0) { Stop-Sync "推送失败（exit $LASTEXITCODE）" }
    }
}

Write-Log "[4/4] 完成"
Write-Log "  节目单：https://gitee.com/$GiteeUser/cn-tv-epg/releases/download/data/epg.xml"
Write-Log "  仓库：  https://gitee.com/$GiteeUser/cn-tv-epg"
Write-Log "===== 同步结束 ====="
