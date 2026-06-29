<#
.SYNOPSIS
  一键部署:本地 push -> 服务器 git pull -> pinctl build(重建前端 + 重启服务)。

.DESCRIPTION
  在本地 Windows 运行。需要本机 ssh 配置里有 "ubuntu-server" 这个 Host 别名
  (见 ~/.ssh/config)。

.PARAMETER Message
  如果当前有未提交改动,用这个信息自动 git commit。不传则只 push 已有提交。

.EXAMPLE
  ./deploy.ps1
  ./deploy.ps1 -Message "fix: 修复评论面板"
  ./deploy.ps1 "fix: 修复评论面板"
#>
param(
  [Parameter(Position = 0)]
  [string]$Message,

  # ssh config 里的 Host 别名
  [string]$SshHost = "ubuntu-server",

  # 服务器上的仓库目录
  [string]$RemoteDir = "~/project/pin-web"
)

$ErrorActionPreference = "Stop"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "    $text" -ForegroundColor Green }

# 切到脚本所在目录(仓库根)
Set-Location -Path $PSScriptRoot

# 1) 处理本地改动
$dirty = (git status --porcelain)
if ($dirty) {
  if ($Message) {
    Step "提交本地改动"
    git add -A
    git commit -m $Message
    Ok "已提交: $Message"
  }
  else {
    Write-Host "`n检测到未提交的改动:" -ForegroundColor Yellow
    git status --short
    Write-Host "用 ./deploy.ps1 -Message '说明' 自动提交,或先手动 commit。" -ForegroundColor Yellow
    exit 1
  }
}
else {
  Ok "工作区干净,无需提交"
}

# 2) push 到 GitHub
Step "推送到 origin"
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
git push origin $branch
Ok "已推送分支: $branch"

# 3) SSH 上服务器:拉代码 + 构建 + 重启
Step "在服务器 ($SshHost) 上拉代码并构建"
$remoteCmd = "set -e; cd $RemoteDir && git pull --ff-only && ./pinctl build"
ssh $SshHost $remoteCmd
if ($LASTEXITCODE -ne 0) {
  Write-Host "`n部署失败(远端命令退出码 $LASTEXITCODE)。" -ForegroundColor Red
  exit $LASTEXITCODE
}

Step "完成 ✅"
Ok "服务已重建并重启。查看日志: ssh $SshHost 'cd $RemoteDir && ./pinctl logs'"
