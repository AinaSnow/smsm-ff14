param([Parameter(Mandatory)][string]$Package)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$fixture = Join-Path $repoRoot ('artifacts\installer-test-' + [guid]::NewGuid().ToString('N'))
$game = Join-Path $fixture 'game'
[IO.Directory]::CreateDirectory($game) | Out-Null
$installer = Join-Path $PSScriptRoot 'Install-Preview.ps1'
function ExpectFailure([scriptblock]$Action, [string]$Message) {
    $failed = $false
    try { & $Action } catch { $failed = $true; if ($_.Exception.Message -notlike "*$Message*") { throw } }
    if (-not $failed) { throw "Expected failure: $Message" }
}
Set-Content -LiteralPath (Join-Path $game 'ffxivgame.ver') -Value 'wrong-build' -NoNewline
ExpectFailure { & $installer -ClientRoot $fixture -Package $Package } 'Client build mismatch'
Set-Content -LiteralPath (Join-Path $game 'ffxivgame.ver') -Value '2026.09.15.0000.0000' -NoNewline
$collision = Join-Path $game 'd3d11.dll'
Set-Content -LiteralPath $collision -Value 'existing-wrapper' -NoNewline
ExpectFailure { & $installer -ClientRoot $fixture -Package $Package } 'Existing file would be overwritten'
if ((Get-Content -LiteralPath $collision -Raw) -ne 'existing-wrapper') { throw 'Existing wrapper was modified' }
Remove-Item -LiteralPath $collision
& $installer -ClientRoot $fixture -Package $Package
$installedConfig = Join-Path $game 'd3dx.ini'
Add-Content -LiteralPath $installedConfig -Value '; user modification'
ExpectFailure { & $installer -ClientRoot $fixture -Package $Package -Uninstall } 'Installed file changed'
if (-not (Test-Path -LiteralPath $collision)) { throw 'Uninstall removed files before finishing integrity checks' }
Copy-Item -LiteralPath (Join-Path $Package 'd3dx.ini') -Destination $installedConfig
& $installer -ClientRoot $fixture -Package $Package -Uninstall
if (Test-Path -LiteralPath $collision) { throw 'Wrapper not removed' }
if (-not (Test-Path -LiteralPath (Join-Path $game 'ffxivgame.ver'))) { throw 'Game version file was removed' }
Write-Output 'PASS: build guard, collision protection, edited-file protection, install and uninstall.'
