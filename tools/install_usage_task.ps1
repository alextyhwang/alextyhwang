# Registers the local publisher that keeps the profile's T3 charts current.
# It reads only the aggregate spend section of t3plus-home.json and pushes the
# four SVGs to the profile repository's output branch once per hour.
param(
  [string]$Python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source,
  [string]$Feed = (Join-Path $HOME ".t3\userdata\tailnet-files\t3plus-home.json")
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot "publish_usage.py"
if (-not $Python -or -not (Test-Path $Python)) { throw "python.exe not found; pass -Python <path to python.exe>" }
if (-not (Test-Path $Feed)) { throw "T3 feed not found: $Feed" }
$log = Join-Path $env:TEMP "alextyhwang-t3-usage-task.log"
$arguments = "/d /c `"`"$Python`" `"$script`" --feed `"$Feed`" >> `"$log`" 2>&1`""
$action = New-ScheduledTaskAction -Execute "$env:ComSpec" -Argument $arguments -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "alextyhwang T3 usage charts" -Action $action -Trigger $trigger -Settings $settings `
  -Description "Publishes aggregate T3 Code usage charts for Alex's public profile README." -Force | Out-Null
Write-Output "Registered 'alextyhwang T3 usage charts' (hourly)"
