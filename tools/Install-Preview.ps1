param(
    [Parameter(Mandatory)][string]$ClientRoot,
    [Parameter(Mandatory)][string]$Package,
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$gameRoot = [IO.Path]::GetFullPath((Join-Path $ClientRoot 'game'))
$packageRoot = (Resolve-Path -LiteralPath $Package).Path
$manifest = Get-Content -LiteralPath (Join-Path $packageRoot 'SMSM-preview.json') -Raw | ConvertFrom-Json
$version = (Get-Content -LiteralPath (Join-Path $gameRoot 'ffxivgame.ver') -Raw).Trim()
if (-not $Uninstall -and $version -ne $manifest.client_build) { throw "Client build mismatch: $version" }
if (Get-Process -Name ffxiv_dx11 -ErrorAction SilentlyContinue) { throw 'Close the game before installing or removing the preview.' }

$entries = @($manifest.files.PSObject.Properties | ForEach-Object {
    $relative = $_.Name
    $target = [IO.Path]::GetFullPath((Join-Path $gameRoot $relative))
    $source = [IO.Path]::GetFullPath((Join-Path $packageRoot $relative))
    if (-not $target.StartsWith($gameRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Invalid target path: $relative"
    }
    if (-not $source.StartsWith($packageRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Invalid source path: $relative"
    }
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $_.Value) { throw "Package integrity failure: $relative" }
    [pscustomobject]@{ Source=$source; Target=$target; Hash=$_.Value }
})

$receipt = Join-Path $gameRoot 'SMSM-preview.json'
if ($Uninstall) {
    if (-not (Test-Path -LiteralPath $receipt)) { throw 'No installation receipt found.' }
    if ((Get-FileHash -LiteralPath $receipt).Hash -ne (Get-FileHash -LiteralPath (Join-Path $packageRoot 'SMSM-preview.json')).Hash) {
        throw 'Installed receipt does not match this package.'
    }
    # Check every installed file before removing any. Preserve user edits.
    foreach ($entry in $entries) {
        if ((Test-Path -LiteralPath $entry.Target) -and (Get-FileHash -LiteralPath $entry.Target).Hash -ne $entry.Hash) {
            throw "Installed file changed; preserve and review it first: $($entry.Target)"
        }
    }
    foreach ($entry in $entries) {
        if (Test-Path -LiteralPath $entry.Target) { Remove-Item -LiteralPath $entry.Target }
    }
    Remove-Item -LiteralPath $receipt
    Write-Output 'Preview removed. Generated logs/captures and empty folders are preserved.'
    exit
}

if (Test-Path -LiteralPath $receipt) { throw 'A preview is already installed; remove it with the matching package first.' }
# Refuse collisions rather than overwrite a ReShade/3DMigoto installation.
foreach ($entry in $entries) {
    if (Test-Path -LiteralPath $entry.Target) { throw "Existing file would be overwritten: $($entry.Target)" }
}
$created = [Collections.Generic.List[string]]::new()
try {
    foreach ($entry in $entries) {
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($entry.Target)) | Out-Null
        $created.Add($entry.Target)
        Copy-Item -LiteralPath $entry.Source -Destination $entry.Target
        if ((Get-FileHash -LiteralPath $entry.Target).Hash -ne $entry.Hash) { throw "Installed file integrity failure: $($entry.Target)" }
    }
    Copy-Item -LiteralPath (Join-Path $packageRoot 'SMSM-preview.json') -Destination $receipt
} catch {
    foreach ($file in $created) {
        if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
    }
    throw
}
$config = Get-Content -LiteralPath (Join-Path $packageRoot 'd3dx.ini') -Raw
$captureHint = if ($config -match '(?m)^\s*analyse_frame\s*=') { 'F8: capture.' } else { 'Frame capture disabled.' }
Write-Output "Installed $($manifest.shaders.Count) preview shaders for $version. F9: hold for original; F10: reload; numpad 0: hunting; $captureHint"
