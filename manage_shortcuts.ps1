param([Parameter(Mandatory=$true)][ValidateSet('Desktop','Enable','Disable','Check')][string]$Action)
$ErrorActionPreference='Stop'
$pythonw=Join-Path $PSScriptRoot 'venv\Scripts\pythonw.exe'
$launcher=Join-Path $PSScriptRoot 'launch.py'
$desktop=Join-Path ([Environment]::GetFolderPath('Desktop')) 'Jarvis v2.0.lnk'
$startup=Join-Path ([Environment]::GetFolderPath('Startup')) 'Jarvis v2.0.lnk'
$shellObject=New-Object -ComObject WScript.Shell
if($Action -eq 'Check') {
    foreach($linkPath in @($desktop,$startup)) {
        if(Test-Path -LiteralPath $linkPath) {
            $shortcut=$shellObject.CreateShortcut($linkPath)
            Write-Output "Shortcut: $linkPath"
            Write-Output "Target: $($shortcut.TargetPath)"
            Write-Output "Arguments: $($shortcut.Arguments)"
            Write-Output "Working folder: $($shortcut.WorkingDirectory)"
        } else {Write-Output "Not installed: $linkPath"}
    }
    exit 0
}
if($Action -eq 'Disable') {
    if(Test-Path -LiteralPath $startup) {Remove-Item -LiteralPath $startup}
    Write-Output 'Jarvis v2 autostart disabled.'
    exit 0
}
if(!(Test-Path -LiteralPath $pythonw) -or !(Test-Path -LiteralPath $launcher)) {throw 'venv or launch.py is missing.'}
$linkPath=if($Action -eq 'Desktop') {$desktop} else {$startup}
$shortcut=$shellObject.CreateShortcut($linkPath)
$shortcut.TargetPath=$pythonw
$shortcut.Arguments='"'+$launcher+'"'
if($Action -eq 'Enable') {$shortcut.Arguments+=' --hidden'}
$shortcut.WorkingDirectory=$PSScriptRoot
$shortcut.Save()
Write-Output "Created: $linkPath"
