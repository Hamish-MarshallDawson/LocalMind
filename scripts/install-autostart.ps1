<#
.SYNOPSIS
    Start LocalMind whenever Windows boots (before anyone signs in), so the gateway can wake this
    PC and find LocalMind ready. It shuts the PC down again after 10 idle minutes.

.DESCRIPTION
    Registers a scheduled task "LocalMind" that runs `localmind serve --lan --auto-shutdown` at
    startup as your account. Run once from an elevated PowerShell (Run as administrator):

        .\scripts\install-autostart.ps1

    Secrets are stored as your user environment variables (only your account can read them):
      LOCALMIND_PASSWORD        the web UI password (needed for --lan)
      LOCALMIND_GATEWAY_TOKEN   shared with the always-on gateway
      LOCALMIND_GATEWAY_URL     the gateway's address (optional; blank = don't report anywhere)

    Remove it again with:  .\scripts\install-autostart.ps1 -Uninstall
#>
param(
    [switch]$Uninstall,
    [string]$TaskName = "LocalMind"
)
$ErrorActionPreference = "Stop"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this from PowerShell opened with 'Run as administrator' (creating a start-up task needs it)."
}

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed the '$TaskName' start-up task. Your saved secrets were left in place."
    return
}

$repo = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $repo ".venv\Scripts\localmind.exe"
if (-not (Test-Path $exe)) { throw "Couldn't find $exe. Install LocalMind into .venv first." }
$logs = Join-Path $repo "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null

foreach ($name in "LOCALMIND_PASSWORD", "LOCALMIND_GATEWAY_TOKEN") {
    $current = [Environment]::GetEnvironmentVariable($name, "User")
    if ([string]::IsNullOrWhiteSpace($current)) {
        $secure = Read-Host "Enter $name" -AsSecureString
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
        if ([string]::IsNullOrWhiteSpace($plain)) { throw "$name can't be empty." }
        [Environment]::SetEnvironmentVariable($name, $plain, "User")
        Write-Host "Saved $name for your account."
    } else {
        Write-Host "$name is already set for your account."
    }
}

if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("LOCALMIND_GATEWAY_URL", "User"))) {
    $url = Read-Host "Gateway address, e.g. https://your-server.your-tailnet.ts.net (blank to skip)"
    if (-not [string]::IsNullOrWhiteSpace($url)) {
        [Environment]::SetEnvironmentVariable("LOCALMIND_GATEWAY_URL", $url.Trim(), "User")
        Write-Host "Saved LOCALMIND_GATEWAY_URL for your account."
    }
} else {
    Write-Host "LOCALMIND_GATEWAY_URL is already set for your account."
}

# A small wrapper so output lands in a log file (a start-up task has no console).
$runner = Join-Path $repo "scripts\run-localmind.cmd"
@"
@echo off
rem Started by the '$TaskName' scheduled task at boot. Logs: data\logs\localmind.log
cd /d "$repo"
"$exe" serve --lan --auto-shutdown >> "$logs\localmind.log" 2>&1
"@ | Set-Content -Encoding ascii $runner

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$runner`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT20S"  # let the network and Tailscale come up first
# S4U: runs as you at boot without anyone signing in, and without storing your Windows password.
# Highest: so it may shut the PC down when idle.
$principalSpec = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable -MultipleInstances IgnoreNew

# Started at boot, nobody is there to answer Windows' "allow through the firewall?" prompt, so let
# the gateway reach LocalMind's port explicitly: home network (Private) and Tailscale addresses only.
$port = 7860
$configPort = Select-String -Path (Join-Path $repo "config.yaml") -Pattern '^\s*port:\s*(\d+)' | Select-Object -First 1
if ($configPort) { $port = [int]$configPort.Matches[0].Groups[1].Value }
Get-NetFirewallRule -DisplayName "LocalMind (gateway access)" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "LocalMind (gateway access)" -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort $port -Profile Private -RemoteAddress LocalSubnet, "100.64.0.0/10" | Out-Null
Write-Host "Allowed inbound TCP $port from your home network and Tailscale."

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principalSpec `
    -Settings $settings -Description "LocalMind: starts at boot for the gateway, shuts the PC down after 10 idle minutes." -Force | Out-Null

Write-Host ""
Write-Host "Done. LocalMind now starts when Windows boots, and turns the PC off after 10 idle minutes."
Write-Host "Start it now without rebooting:  Start-ScheduledTask -TaskName $TaskName"
Write-Host "Logs: $logs\localmind.log"
