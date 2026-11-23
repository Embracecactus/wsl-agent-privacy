[CmdletBinding()]
param(
    [ValidateSet('check', 'launch')][string]$Mode = 'check',
    [ValidateSet('https://claude.ai/login', 'https://claude.ai/')][string]$Url = 'https://claude.ai/login',
    [string]$Distribution
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$wslArgs = @()
if ($Distribution) { $wslArgs = @('--distribution', $Distribution) }
$probe = @'
for guard in "$HOME/.claude/skills/claude-bwrap/scripts/guard.py" "$HOME/.agents/skills/claude-bwrap/scripts/guard.py"; do
    if [ -f "$guard" ]; then exec /usr/bin/python3 -I "$guard" checked-port claude; fi
done
exit 1
'@
# Use stdin so Windows argv quoting cannot reinterpret the Linux shell paths.
$verified = ($probe -replace "`r", '') | & wsl.exe @wslArgs --exec /bin/sh -s
if ($LASTEXITCODE -ne 0 -or @($verified).Count -ne 1 -or [string]$verified -notmatch '^\d{4,5}$') {
    throw 'WSL could not verify the dedicated route'
}
$port = [int]$verified
if ($port -lt 1024 -or $port -gt 65535) { throw 'Invalid local proxy port' }
if ($Mode -eq 'check') { Write-Output 'Dedicated WSL route verified'; return }
$controller = Join-Path $PSScriptRoot 'browser_controller.cjs'
if (-not (Test-Path -LiteralPath $controller -PathType Leaf)) { throw 'Missing browser controller' }
$node = (Get-Command node.exe -CommandType Application).Source
$oldPort = $env:WSL_AGENT_VERIFIED_PORT
try {
    $env:WSL_AGENT_VERIFIED_PORT = [string]$port
    Start-Process -FilePath $node -WindowStyle Hidden -ArgumentList ('"{0}" --serve' -f $controller)
    @{url=$Url; port=$port} | ConvertTo-Json -Compress | & $node $controller
    if ($LASTEXITCODE -ne 0) { throw 'Dedicated Chrome did not open the requested page' }
} finally {
    $env:WSL_AGENT_VERIFIED_PORT = $oldPort
}
