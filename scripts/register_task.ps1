# Registers (or updates) a Windows scheduled task that runs the pipeline on the schedule
# set in config.yaml (monitoring.schedule). Runs as the current user; no admin rights needed.
#   powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Unregister
param([switch]$Unregister, [string]$TaskName = "FundingIntelligenceMonitor")

$root = Split-Path -Parent $PSScriptRoot
if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed task $TaskName"
    exit 0
}
$python = (Get-Command python -ErrorAction Stop).Source
$cfg = & $python -c "import yaml,json;print(json.dumps(yaml.safe_load(open(r'$root\config.yaml',encoding='utf-8'))['monitoring']['schedule']))" | ConvertFrom-Json
$time = [datetime]::ParseExact($cfg.time, "HH:mm", $null)
if ($cfg.full_run -eq "weekly") {
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $cfg.weekday -At $time
} else {
    $trigger = New-ScheduledTaskTrigger -Daily -At $time
}
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$root\scripts\run_pipeline.ps1`" -Python `"$python`"" `
    -WorkingDirectory $root
# StartWhenAvailable: if the PC was off at the scheduled time, run at next opportunity
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName $TaskName -Trigger $trigger -Action $action -Settings $settings `
    -Description "Research Funding Intelligence Dashboard: verify, monitor, rebuild, notify" -Force | Out-Null
Write-Output "Registered '$TaskName' ($($cfg.full_run) at $($cfg.time)) using $python"
