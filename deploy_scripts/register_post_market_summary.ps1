param(
    [switch]$Preview
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$wrapper = Join-Path $PSScriptRoot 'run_and_push.py'
$summary = Join-Path $PSScriptRoot 'post_market_summary.py'
$pythonw = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\pythonw.exe'
$taskName = 'AH盘后-只读参考汇总'
$legacyTasks = @(
    'AH市况-1535右侧信号',
    'AH利率-1540点火',
    'AH观察哨-1550',
    'AH网格-波动扩张观察'
)
$principalName = [System.Security.SecurityElement]::Escape([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$escapedWrapper = [System.Security.SecurityElement]::Escape($wrapper)
$escapedRepo = [System.Security.SecurityElement]::Escape($repo)
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>工作日 16:05 合并执行盘后只读参考（市况右侧信号、利率点火、观察哨、波动扩张观察），有触发才推一条汇总，全静默则不推。</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-11-25T16:05:00+08:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek><Monday/><Tuesday/><Wednesday/><Thursday/><Friday/></DaysOfWeek></ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals><Principal id="Author"><UserId>$principalName</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><Enabled>true</Enabled>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author"><Exec><Command>$pythonw</Command><Arguments>&quot;$escapedWrapper&quot; --job post_market_summary</Arguments><WorkingDirectory>$escapedRepo</WorkingDirectory></Exec></Actions>
</Task>
"@
if ($Preview) {
    Write-Output $xml
    return
}
foreach ($p in @($wrapper, $summary)) {
    if (!(Test-Path -LiteralPath $p)) { throw "脚本不存在：$p" }
}
$python = Join-Path (Split-Path $pythonw -Parent) 'python.exe'
& $python -c 'import ast, sys, tokenize; [ast.parse(tokenize.open(p).read()) for p in sys.argv[1:]]' `
    $wrapper $summary `
    (Join-Path $PSScriptRoot 'market_phase_monitor.py') `
    (Join-Path $PSScriptRoot 'rate_ignition_monitor_wrapper.py') `
    (Join-Path $PSScriptRoot 'watchtower_wrapper.py') `
    (Join-Path $PSScriptRoot 'volatility_expansion_watch.py')
if ($LASTEXITCODE -ne 0) { throw '盘后汇总脚本语法验证失败，拒绝注册' }

$backupDir = Join-Path $repo '.cache\scheduler-backups'
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'

foreach ($name in (@($taskName) + $legacyTasks)) {
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing) {
        $safe = ($name -replace '[\\/:*?"<>|]', '_')
        Export-ScheduledTask -TaskName $name | Set-Content -LiteralPath (Join-Path $backupDir "$safe-$stamp.xml") -Encoding Unicode
    }
}

Register-ScheduledTask -TaskName $taskName -Xml $xml -Force | Out-Null
$task = Get-ScheduledTask -TaskName $taskName
if (!$task.Settings.Enabled) { throw '盘后汇总任务注册后未启用' }

$disabled = @()
foreach ($name in $legacyTasks) {
    $old = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($old) {
        Disable-ScheduledTask -TaskName $name | Out-Null
        $after = Get-ScheduledTask -TaskName $name
        $disabled += [pscustomobject]@{
            TaskName = $after.TaskName
            State = [string]$after.State
            Enabled = $after.Settings.Enabled
        }
    }
}

$info = $task | Get-ScheduledTaskInfo
[pscustomobject]@{
    MergedTask = [pscustomobject]@{
        TaskName = $task.TaskName
        State = [string]$task.State
        Enabled = $task.Settings.Enabled
        StartBoundary = $task.Triggers[0].StartBoundary
        NextRun = if ($info.NextRunTime) { $info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss') } else { '' }
        Execute = $task.Actions[0].Execute
        Arguments = $task.Actions[0].Arguments
    }
    DisabledLegacy = $disabled
} | ConvertTo-Json -Depth 4
