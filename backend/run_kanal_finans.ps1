# Runs kanal_finans.py from THIS machine, on a Windows Task Scheduler trigger.
#
# Why here and not GitHub Actions -- and note the reason is NOT the one it
# used to be. This script no longer touches YouTube at all; the transcript
# fetch moved to ../Kanal-Finans-Fetcher on 2026-09-08 (see kanal_finans.py's
# module docstring). What is left reads `kanal_finans_mentions` rows the
# fetcher wrote and applies them, which any host could do.
#
# It stays local because the FETCHER is local -- YouTube refuses transcript
# requests from Azure IP ranges outright (verified in XRP-Guess, 15/15 videos
# on two separate manual runs), so new mentions only ever appear while this
# machine is awake. Running the applier beside it on the same 15-minute tick
# is what makes a fresh mention reach the portfolio within minutes; a cloud
# cron would be waking up to find nothing new by construction.
#
# If the machine is asleep at the trigger time that run is skipped; main() is
# idempotent and `applied_at is null` is the queue, so the next run catches
# up on its own. The one thing that must NOT wait for this machine -- the
# kanalfinans stop-loss -- is watched from predict.py's daily Actions run.
#
# Task Scheduler does not load a shell profile, so backend/.env is read here
# and pushed into the process environment by hand.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Error "backend\.env bulunamadi -- backend\.env.example'i .env olarak kopyalayip gercek degerleri gir."
    exit 1
}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
    $name, $value = $_.Split('=', 2)
    [System.Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
}

$logDir = Join-Path $PSScriptRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ("kanal_finans_{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# BOTH halves of the UTF-8 story have to be here, and neither is cosmetic.
#
#   1. Out-File -Encoding utf8 rather than *>> or >>. In Windows PowerShell
#      5.1 the redirection operators write UTF-16LE, which every tool that
#      later reads this log (grep, an editor, the Read tool) renders as
#      unreadable text with a space between each character.
#
#   2. [Console]::OutputEncoding = UTF8. PowerShell DECODES a native
#      program's output using this; kanal_finans.py already forces its stdout
#      to UTF-8, but if the console stays on cp1252 those correct UTF-8 bytes
#      become mojibake on the way in. One without the other is not enough.
#
# XRP-Guess lost a scheduled task to exactly this: a Turkish video title in a
# print() raised UnicodeEncodeError, every run exited 1, and the retry
# bookkeeping that should have recorded the failures never executed.
$previousOutputEncoding = [Console]::OutputEncoding
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try {
    & $python (Join-Path $PSScriptRoot "kanal_finans.py") 2>&1 |
        Out-File -FilePath $logFile -Append -Encoding utf8
} finally {
    [Console]::OutputEncoding = $previousOutputEncoding
}
