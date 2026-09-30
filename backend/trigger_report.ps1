# Starts the Daily Email Report workflow from THIS machine at 11:00 TR on
# weekdays (Task Scheduler "XAU-Guess Report Trigger"), instead of waiting for
# GitHub Actions' own `schedule:` event. The hour must equal
# daily_report.REPORT_HOUR_TRT (09:00 until 2026-09-30, then 11:00 at the
# user's request).
#
# Measured 2026-09-29..30: the "0 6 * * 1-5" cron, which had started 15-18
# minutes late every weekday since the mail existed, started 6.3 hours late
# on 09-29 (15:19 TR) and had not started at all by 10:45 TR on 09-30. Every
# run that did start succeeded -- nothing in daily_report.py or the workflow
# was wrong. XRP-Guess hit the same degradation two days earlier and moved its
# trigger local the same way (XRP-Guess/backend/trigger_predict.ps1).
#
# A workflow_dispatch is an ordinary API call and queues like a push; the job
# itself still runs on GitHub's runners with the repo's secrets, exactly as
# before. This machine only makes the call.
#
# Two guards keep the day at ONE mail, because daily_report.py writes nothing
# and would happily send the same report twice:
#   - here: no dispatch if any report run from the last 18 hours is running or
#     succeeded (the task has StartWhenAvailable, so a machine that wakes at
#     14:00 must not follow a late cron run that already mailed);
#   - daily_report.yml: a SCHEDULED run stands down if a dispatched run exists
#     in the same window.
# 18 hours, not "today": a cron run delayed past midnight UTC would otherwise
# count for the wrong day.
#
# If GitHub cannot be asked, nothing is dispatched: the cron fallback still
# sends a (late) mail, whereas a blind dispatch could send a second one.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$repo = "erdemdelibasi/XAU-Guess"
$workflow = "daily_report.yml"
$windowHours = 18

$logDir = Join-Path $PSScriptRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ("trigger_report_{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

function Log([string]$msg) {
    "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg |
        Out-File -FilePath $logFile -Append -Encoding utf8
}

# Absolute path, not a bare `gh`: Task Scheduler does not reliably carry the
# interactive shell's PATH (same as XRP-Guess/backend/trigger_predict.ps1).
$gh = "C:\Program Files\GitHub CLI\gh.exe"

$previousOutputEncoding = [Console]::OutputEncoding
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try {
    $raw = & $gh run list --repo $repo --workflow $workflow --limit 10 --json "createdAt,event,status,conclusion" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Log "gh run list failed (exit=$LASTEXITCODE): $raw -- not dispatching, the cron fallback stays"
        exit 1
    }
    $cutoff = (Get-Date).ToUniversalTime().AddHours(-$windowHours)
    # Parsed here rather than with --jq: Windows PowerShell 5.1 strips the
    # double quotes a jq string literal needs on its way to a native program.
    $recent = @(($raw | Out-String | ConvertFrom-Json) | Where-Object {
        ([datetime]$_.createdAt).ToUniversalTime() -ge $cutoff -and
        $_.conclusion -notin @("failure", "cancelled", "startup_failure", "timed_out")
    })
    if ($recent.Count -gt 0) {
        $r = $recent[0]
        Log "skip: a report run already exists in the last ${windowHours}h ($($r.createdAt) $($r.event) $($r.status) $($r.conclusion))"
        exit 0
    }
    $out = & $gh workflow run $workflow --repo $repo --ref main 2>&1
    Log "dispatched: $out exit=$LASTEXITCODE"
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
