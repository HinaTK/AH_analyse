param(
    [string]$PythonExe = "python",
    [switch]$Mock
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backend = Join-Path $repoRoot "ah_recommendation_system\backend"
$mockArg = if ($Mock) { " --mock" } else { "" }
$env:PYTHONPATH = $repoRoot

$preArgs = "-m scheduler.daily_job --mode pre_market --push$mockArg"
$postArgs = "-m scheduler.daily_job --mode post_market --push$mockArg"
$weeklyArgs = "-m scheduler.daily_job --mode weekly_reweight$mockArg"

$preAction = New-ScheduledTaskAction -Execute $PythonExe -Argument $preArgs -WorkingDirectory $backend
$postAction = New-ScheduledTaskAction -Execute $PythonExe -Argument $postArgs -WorkingDirectory $backend
$weeklyAction = New-ScheduledTaskAction -Execute $PythonExe -Argument $weeklyArgs -WorkingDirectory $backend
$preTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "08:30"
$postTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "18:30"
$weeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At "19:00"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName "AHAnalyse-PreMarket" -Action $preAction -Trigger $preTrigger -Settings $settings -Description "A-share pre-market recommendation" -Force
Register-ScheduledTask -TaskName "AHAnalyse-PostMarket" -Action $postAction -Trigger $postTrigger -Settings $settings -Description "A-share post-market review" -Force
Register-ScheduledTask -TaskName "AHAnalyse-WeeklyReweight" -Action $weeklyAction -Trigger $weeklyTrigger -Settings $settings -Description "Weekly bounded factor reweight" -Force

Write-Host "Installed pre-market, post-market, and weekly reweight tasks."
Write-Host "Set AH_FEISHU_WEBHOOK and optional AH_FEISHU_SECRET as persistent environment variables before running."
