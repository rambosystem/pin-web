<#
.SYNOPSIS
  One-click deploy: local push -> server git pull -> pinctl build (rebuild frontend + restart service).

.DESCRIPTION
  Run locally on Windows. Requires an "ubuntu-server" Host alias in your
  ~/.ssh/config. The script is intentionally ASCII-only so Windows PowerShell
  5.1 parses it correctly regardless of file encoding.

.PARAMETER Message
  If there are uncommitted changes, commit them with this message. The message
  may contain non-ASCII text (e.g. Chinese) - it is written to a UTF-8 temp file
  and passed via "git commit -F" to avoid console-encoding issues.
  If omitted and the tree is dirty, the script stops and asks you to commit.

.EXAMPLE
  ./deploy.ps1
  ./deploy.ps1 -Message "fix: something"
  ./deploy.ps1 "fix: something"
#>
param(
  [Parameter(Position = 0)]
  [string]$Message,

  # Host alias in ~/.ssh/config
  [string]$SshHost = "ubuntu-server",

  # Repo directory on the server
  [string]$RemoteDir = "~/project/pin-web"
)

$ErrorActionPreference = "Stop"

# Make sure native commands (git, ssh) receive/emit UTF-8.
try {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "    $text" -ForegroundColor Green }

# Move to the script directory (repo root).
Set-Location -Path $PSScriptRoot

# 1) Handle local changes.
$dirty = (git status --porcelain)
if ($dirty) {
  if ($Message) {
    Step "Committing local changes"
    git add -A
    # Write the commit message as UTF-8 (no BOM) and use -F to dodge arg encoding.
    $tmp = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tmp, $Message, (New-Object System.Text.UTF8Encoding $false))
    try {
      git commit -F $tmp
    } finally {
      Remove-Item $tmp -ErrorAction SilentlyContinue
    }
    Ok "Committed: $Message"
  }
  else {
    Write-Host "`nUncommitted changes detected:" -ForegroundColor Yellow
    git status --short
    Write-Host "Run ./deploy.ps1 -Message '...' to auto-commit, or commit manually first." -ForegroundColor Yellow
    exit 1
  }
}
else {
  Ok "Working tree clean, nothing to commit"
}

# 2) Push to GitHub.
Step "Pushing to origin"
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
git push origin $branch
Ok "Pushed branch: $branch"

# 3) SSH to the server: pull + build + restart.
Step "Pulling and building on server ($SshHost)"
$remoteCmd = "set -e; cd $RemoteDir; git pull --ff-only; ./pinctl build"
ssh $SshHost $remoteCmd
if ($LASTEXITCODE -ne 0) {
  Write-Host "`nDeploy failed (remote exit code $LASTEXITCODE)." -ForegroundColor Red
  exit $LASTEXITCODE
}

Step "Done"
Ok "Service rebuilt and restarted. Logs: ssh $SshHost 'cd $RemoteDir; ./pinctl logs'"
