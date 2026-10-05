# Starts a GitHub Actions workflow from THIS machine at its intended hour
# (Task Scheduler), instead of waiting for GitHub's own `schedule:` event.
# One script for every cron this repo has moved local; the task passes the
# workflow file and the stand-down window:
#
#   Task                          Workflow             When (TR)          Window
#   XAU-Guess Predict Trigger     predict.yml          Tue-Sat 02:00      12h
#   XAU-Guess Retrain Trigger     daily_retrain.yml    daily 04:30        12h
#   XAU-Guess Report Trigger      daily_report.yml     Mon-Fri 11:00      18h
#
# Each hour is its workflow's cron converted to TR (fixed UTC+3); the report's
# must also equal daily_report.REPORT_HOUR_TRT.
#
# Why: the crons stopped keeping time. Measured 2026-09-29..30 on the report
# (6.3 hours late, then not at all by 10:45), and 2026-09-28..10-05 on the
# rest: predict.yml's 23:00Z started at 01:41-01:57Z, daily_retrain.yml's
# 01:30Z at 06:39-07:17Z. Every run that started succeeded -- nothing in the
# scripts was wrong. XRP-Guess hit the same degradation first
# (XRP-Guess/backend/trigger_predict.ps1).
#
# A workflow_dispatch is an ordinary API call and queues like a push; the job
# itself still runs on GitHub's runners with the repo's secrets, on the free
# public-repo minutes, exactly as before. This machine only makes the call.
#
# Two guards keep it at ONE run per slot, and the cron stays as the fallback
# for a slot this machine sleeps through:
#   - here: no dispatch if a run of the workflow from the last $WindowHours
#     is running or succeeded (the task has StartWhenAvailable, so a machine
#     that wakes hours late must not follow a late cron run that already did
#     the work);
#   - the workflow: a SCHEDULED run stands down if a dispatched run exists in
#     the same window (its gate step/job, which must use the same number).
# For the report the second run would be a second mail. For predict and
# retrain it would be harmless -- predict.py skips a session it already
# wrote, the ETF and breakout books act on position state, retrain.py is
# idempotent -- but it is a wasted run and a second commit.
#
# The window must be longer than the cron's delay (up to ~7 hours measured)
# and shorter than a day minus that delay, or yesterday's late cron would
# count for today. 12 hours sits inside both; the report keeps the 18 it
# shipped with.
#
# If GitHub cannot be asked, nothing is dispatched: the cron fallback still
# runs (late), whereas a blind dispatch could run twice.
param(
    [Parameter(Mandatory = $true)][string]$Workflow,
    [int]$WindowHours = 12,
    # Log the decision without dispatching -- for checking a new task by hand.
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$repo = "erdemdelibasi/XAU-Guess"

$logDir = Join-Path $PSScriptRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$name = [IO.Path]::GetFileNameWithoutExtension($Workflow)
$logFile = Join-Path $logDir ("trigger_{0}_{1}.log" -f $name, (Get-Date -Format "yyyy-MM-dd"))

function Log([string]$msg) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $line | Out-File -FilePath $logFile -Append -Encoding utf8
    if ($DryRun) { Write-Output $line }
}

# Absolute path, not a bare `gh`: Task Scheduler does not reliably carry the
# interactive shell's PATH (same as XRP-Guess/backend/trigger_predict.ps1).
$gh = "C:\Program Files\GitHub CLI\gh.exe"

$previousOutputEncoding = [Console]::OutputEncoding
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try {
    $raw = & $gh run list --repo $repo --workflow $Workflow --limit 20 --json "createdAt,startedAt,event,status,conclusion" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Log "gh run list failed (exit=$LASTEXITCODE): $raw -- not dispatching, the cron fallback stays"
        exit 1
    }
    $cutoff = (Get-Date).ToUniversalTime().AddHours(-$WindowHours)
    # Parsed here rather than with --jq: Windows PowerShell 5.1 strips the
    # double quotes a jq string literal needs on its way to a native program.
    # Two steps on purpose: 5.1's ConvertFrom-Json writes a JSON array as ONE
    # object, so @(... | ConvertFrom-Json) is an array holding the array.
    $parsed = $raw | Out-String | ConvertFrom-Json
    $runs = @($parsed | Where-Object { $_ })
    # A scheduled run that found a dispatch in ITS OWN window stood down and
    # did nothing, yet still concludes "success". Counting it here cost a
    # morning's mail: on 10-01 the report cron started 7 hours late (14:54Z)
    # and stood down behind the 08:00Z dispatch; at 11:00 on 10-02 this guard
    # saw it 17.1 hours back, skipped, and the mail went out with the 14:16Z
    # cron instead. Same rule as the workflow's gate, applied at the time the
    # gate ran (startedAt).
    $dispatched = @($runs | Where-Object {
        $_.event -eq "workflow_dispatch" -and $_.conclusion -notin @("failure", "cancelled")
    } | ForEach-Object { ([datetime]$_.createdAt).ToUniversalTime() })
    function StoodDown($run) {
        if ($run.event -ne "schedule") { return $false }
        $at = if ($run.startedAt) { $run.startedAt } else { $run.createdAt }
        $t = ([datetime]$at).ToUniversalTime()
        return @($dispatched | Where-Object { $_ -le $t -and $_ -ge $t.AddHours(-$WindowHours) }).Count -gt 0
    }
    $recent = @($runs | Where-Object {
        ([datetime]$_.createdAt).ToUniversalTime() -ge $cutoff -and
        $_.conclusion -notin @("failure", "cancelled", "startup_failure", "timed_out") -and
        -not (StoodDown $_)
    })
    if ($recent.Count -gt 0) {
        $r = $recent[0]
        Log "skip: a $Workflow run already exists in the last ${WindowHours}h ($($r.createdAt) $($r.event) $($r.status) $($r.conclusion))"
        exit 0
    }
    if ($DryRun) {
        Log "dry run: would dispatch $Workflow (no run in the last ${WindowHours}h)"
        exit 0
    }
    $out = & $gh workflow run $Workflow --repo $repo --ref main 2>&1
    Log "dispatched ${Workflow}: $out exit=$LASTEXITCODE"
    exit $LASTEXITCODE
} catch {
    # Under Windows PowerShell 5.1 with Stop, a native program's stderr line
    # arriving through 2>&1 is itself a terminating error -- without this the
    # run would die before writing a word to the log.
    Log "error: $_ -- not dispatching, the cron fallback stays"
    exit 1
} finally {
    [Console]::OutputEncoding = $previousOutputEncoding
}
