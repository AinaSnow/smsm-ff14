param(
    [Parameter(Mandatory)][string]$ClientRoot,
    [Parameter(Mandatory)][string]$UserSid,
    [switch]$Revoke
)
$ErrorActionPreference = 'Stop'
$gameRoot = [IO.Path]::GetFullPath((Join-Path $ClientRoot 'game'))
if (-not (Test-Path -LiteralPath (Join-Path $gameRoot 'ffxiv_dx11.exe'))) { throw 'Not an FFXIV game directory.' }
$statePath = Join-Path (Split-Path $PSScriptRoot -Parent) 'artifacts\capture-permission.json'
$sid = [Security.Principal.SecurityIdentifier]::new($UserSid)
$rule = [Security.AccessControl.FileSystemAccessRule]::new(
    $sid,
    [Security.AccessControl.FileSystemRights]::CreateDirectories,
    [Security.AccessControl.InheritanceFlags]::None,
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow
)
$acl = Get-Acl -LiteralPath $gameRoot
if ($Revoke) {
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($state.GameRoot -ne $gameRoot -or $state.UserSid -ne $UserSid) { throw 'Permission receipt does not match this request.' }
    $acl.RemoveAccessRuleSpecific($rule)
    Set-Acl -LiteralPath $gameRoot -AclObject $acl
    Remove-Item -LiteralPath $statePath
    Write-Output 'Removed the directory-only frame capture permission. Existing captures are preserved.'
    exit
}
if (Test-Path -LiteralPath $statePath) { throw 'A capture permission receipt already exists. Review it before changing permissions again.' }
# Do not merge a grant with existing explicit rules for this SID: make revocation precise.
$existing = @($acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier]) | Where-Object { $_.IdentityReference.Value -eq $UserSid })
if ($existing.Count) { throw 'This SID already has explicit permissions. Review those rules rather than merging automatically.' }
$acl.AddAccessRule($rule)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($statePath)) | Out-Null
# Save the narrowly scoped grant before applying it, so an interrupted invocation remains reversible.
@{ GameRoot=$gameRoot; UserSid=$UserSid; Rights='CreateDirectories'; Inheritance='None' } |
    ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
Set-Acl -LiteralPath $gameRoot -AclObject $acl
Write-Output "Granted CreateDirectories on this directory only to $UserSid. Existing file ACLs are unchanged. Retry F8 with hunting enabled."
