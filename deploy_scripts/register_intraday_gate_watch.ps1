param(
    [switch]$Preview
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$wrapper = Join-Path $PSScriptRoot 'run_and_push.py'
$pythonw = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\pythonw.exe'
$taskName = 'AH网格-盘中门控观察'
$principalName = [System.Security.SecurityElement]::Escape([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$escapedWrapper = [System.Security.SecurityElement]::Escape($wrapper)
$escapedRepo = [System.Security.SecurityElement]::Escape($repo)
# The Friday/weekend/holiday gates are enforced in the script as well.
# 09:45,10:00,...14:45; lunch invocations exit quietly before network access.
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>每15分钟观察持仓ETF盘中门控变化；独立存档，仅提醒，不切换正式门控。</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <Repetition><Interval>PT15M</Interval><Duration>PT5H1M</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <StartBoundary>2026-11-05T09:45:00+08:00</StartBoundary>
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
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author"><Exec><Command>$pythonw</Command><Arguments>&quot;$escapedWrapper&quot; --job gate_watch</Arguments><WorkingDirectory>$escapedRepo</WorkingDirectory></Exec></Actions>
</Task>
"@
if ($Preview) {
    Write-Output $xml
    return
}
# The script must exist and compile before a live task can be switched to it.
$launcher = Join-Path $PSScriptRoot 'grid_intraday_gate_watch.py'
if (!(Test-Path -LiteralPath $launcher)) { throw "观察脚本不存在：$launcher" }
$python = Join-Path (Split-Path $pythonw -Parent) 'python.exe'
& $python -c 'import ast, sys, tokenize; [ast.parse(tokenize.open(p).read()) for p in sys.argv[1:]]' $wrapper $launcher (Join-Path $repo 'tools\intraday_gate_watch.py')
if ($LASTEXITCODE -ne 0) { throw '观察脚本语法验证失败，拒绝注册' }
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    $backupDir = Join-Path $repo '.cache\scheduler-backups'
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath (Join-Path $backupDir "gate-watch-$stamp.xml") -Encoding Unicode
}
Register-ScheduledTask -TaskName $taskName -Xml $xml -Force | Out-Null
$task = Get-ScheduledTask -TaskName $taskName
if (!$task.Settings.Enabled) { throw '观察任务注册后未启用' }
[pscustomobject]@{
    TaskName = $task.TaskName
    State = [string]$task.State
    Execute = $task.Actions[0].Execute
    Arguments = $task.Actions[0].Arguments
    StartBoundary = $task.Triggers[0].StartBoundary
    Interval = $task.Triggers[0].Repetition.Interval
    Duration = $task.Triggers[0].Repetition.Duration
    Enabled = $task.Settings.Enabled
} | ConvertTo-Json
