<#
.SYNOPSIS
    Records every process start and stop on this machine, from outside the
    test process, for the flake hunt in issue #8.

.DESCRIPTION
    Signature B of #8 is an interpreter that dies with exit code 1, no
    output and no traceback, eleven milliseconds into a test. Nothing
    inside that interpreter can ever explain it: a process ended by
    TerminateProcess never gets to report its own death, and the previous
    attempt -- a PowerShell process snapshot taken inside setUp -- was
    heavy enough to change the timing of the race being hunted, so the
    failure stopped appearing.

    This script is the replacement. It runs as its own process for the
    whole job, so the suite pays nothing for being watched, and it writes
    one line per process event to a log that survives the interpreter:

        HH:mm:ss.fff start pid=1234 parent=5678 name=taskkill.exe
        HH:mm:ss.fff stop  pid=4321 parent=0 name=python.exe exit=1

    Lineage comes from the start record: Win32_ProcessStopTrace reports a
    parent of 0 for everything, so the pair has to be read together. That
    matters more than it sounds, because PIDs are reused within seconds on
    a busy machine -- a local run of this script caught one PID being a
    bash.exe and then a python.exe five seconds apart -- so "start pid=N"
    is also what dates a PID, and a kill aimed at an N that was recycled
    in between is one of the mechanisms #8 is open on.

    Read together with the suite's own trace log (GARAGE_TEST_TRACE_LOG),
    that answers the two questions the issue could not: what exit status
    the interpreter actually died of, and whether a taskkill.exe was
    started around it -- and if so, whose child that taskkill was.

    CORRELATE BY PID, NOT BY CLOCK. These timestamps are when WMI
    delivered the indication, and delivery runs about a second behind the
    event: measured here, a process python spawned at 02:01:38.9 was
    reported with TIME_CREATED 02:01:40.196, while this script picked it
    up 77ms after that -- the latency is WMI's, not the watcher's, and
    TIME_CREATED does not carry the true creation time either. Ordering
    *within* this log is sound and every PID, parent and exit status is
    exact; it is only alignment against the suite's clock that is not. The
    suite spawns a calibration marker at startup and names its PID in its
    own log, so each run's offset can be measured rather than assumed.

    If a question ever turns on true sub-second ordering across the two
    logs, this mechanism is the wrong one and an ETW kernel-process
    session (logman + tracerpt) is the replacement.

    Command lines are deliberately not recorded. The only taskkill Garage
    runs is the one in `_kill_tree`, and the suite's trace log already
    names the PID it targets just before it runs; the parent PID recorded
    here is what says whether a given taskkill was that one or something
    else's.

.PARAMETER LogPath
    File to append records to. Its directory is created if missing.

.PARAMETER StopFile
    Watched for existence; the script exits when it appears. Defaults to
    "<LogPath>.stop", which is what the workflow's teardown step touches.

.PARAMETER MaxMinutes
    Backstop for a watcher whose stop file never arrives, so an abandoned
    process cannot outlive the job.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $LogPath,
    [string] $StopFile,
    [int] $MaxMinutes = 60
)

$ErrorActionPreference = 'Stop'

if (-not $StopFile) { $StopFile = "$LogPath.stop" }

$directory = Split-Path -Parent $LogPath
if ($directory -and -not (Test-Path $directory)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

# AutoFlush, because the interesting log is always one that was cut short.
$writer = [System.IO.StreamWriter]::new($LogPath, $true)
$writer.AutoFlush = $true

function Write-Record([string] $text, [DateTime] $when = [DateTime]::MinValue) {
    # `when` is WMI's own stamp for the event, which is closer to the
    # truth than reading the clock here but is still a delivery time --
    # see the note in the header. It is used so the lag this script adds
    # (tens of milliseconds) is at least not stacked on top of WMI's
    # (about a second).
    if ($when -eq [DateTime]::MinValue) { $when = [DateTime]::UtcNow }
    # The stamp is built first on purpose: passed inline, the comma reads
    # as WriteLine's own argument separator and the format never runs.
    $line = '{0} {1}' -f $when.ToString('HH:mm:ss.fff'), $text
    $writer.WriteLine($line)
}

$deadline = [DateTime]::UtcNow.AddMinutes($MaxMinutes)

# Win32_ProcessStartTrace and Win32_ProcessStopTrace are the exact events:
# they fire per process rather than being sampled, and the stop trace is
# the only source of the exit status of a process this script never
# owned. They need elevation, which a GitHub runner job has -- but if the
# image ever withholds it, a coarse poll still catches an interpreter
# disappearing, which is the record #8 is missing.
$tracing = $false
try {
    Register-CimIndicationEvent -Query 'SELECT * FROM Win32_ProcessStartTrace' `
        -SourceIdentifier 'GarageProcessStart' -ErrorAction Stop
    Register-CimIndicationEvent -Query 'SELECT * FROM Win32_ProcessStopTrace' `
        -SourceIdentifier 'GarageProcessStop' -ErrorAction Stop
    $tracing = $true
} catch {
    Write-Record "watcher: process traces unavailable ($($_.Exception.Message))"
}

try {
    if ($tracing) {
        Write-Record "watcher: started, mode=trace, pid=$PID, stop file=$StopFile"
        Write-Record ('watcher: stamps are WMI delivery times, roughly a second' +
            ' behind the event -- correlate with the suite log by PID, not by clock')
        # The stop file is checked when the queue runs dry, and every few
        # events otherwise. A Test-Path per event is what made this
        # loop fall behind the events it was recording.
        $maxLagMs = 0
        $sinceCheck = 0
        while ($true) {
            $notification = Wait-Event -Timeout 1
            if (-not $notification) {
                if ((Test-Path $StopFile) -or [DateTime]::UtcNow -ge $deadline) { break }
                continue
            }
            $traced = $notification.SourceEventArgs.NewEvent
            $raised = [DateTime]::FromFileTimeUtc([int64] $traced.TIME_CREATED)
            if ($notification.SourceIdentifier -eq 'GarageProcessStart') {
                Write-Record ('start pid={0} parent={1} name={2}' -f `
                        $traced.ProcessID, $traced.ParentProcessID, $traced.ProcessName) $raised
            } else {
                Write-Record ('stop  pid={0} parent={1} name={2} exit={3}' -f `
                        $traced.ProcessID, $traced.ParentProcessID, $traced.ProcessName, $traced.ExitStatus) $raised
            }
            Remove-Event -EventIdentifier $notification.EventIdentifier

            $lagMs = [int] ([DateTime]::UtcNow - $raised).TotalMilliseconds
            if ($lagMs -gt $maxLagMs) { $maxLagMs = $lagMs }
            $sinceCheck++
            if ($sinceCheck -ge 100) {
                $sinceCheck = 0
                if ((Test-Path $StopFile) -or [DateTime]::UtcNow -ge $deadline) { break }
            }
        }
        # This is the lag this script adds on top of WMI's, and it is the
        # number that says whether the loop kept up. Tens of milliseconds
        # is healthy; seconds would mean records were still queued when
        # the watcher was told to stop, and the tail of the log is short.
        Write-Record "watcher: worst lag between event and record was ${maxLagMs}ms"
    } else {
        # The fallback records appearances and disappearances only: a poll
        # cannot see an exit status, it misses any process that lives and
        # dies inside one interval, and its stamps are when this loop
        # looked rather than when anything happened -- so treat them as
        # accurate to the interval, not to the millisecond. It is still out
        # of band, and it still says whether the interpreter vanished.
        Write-Record "watcher: started, mode=poll, pid=$PID, stop file=$StopFile"
        $known = @{}
        foreach ($process in Get-CimInstance Win32_Process) {
            $known[[int] $process.ProcessId] = '{0} parent={1}' -f $process.Name, $process.ParentProcessId
        }
        while (-not (Test-Path $StopFile) -and [DateTime]::UtcNow -lt $deadline) {
            $current = @{}
            foreach ($process in Get-CimInstance Win32_Process) {
                $current[[int] $process.ProcessId] = '{0} parent={1}' -f $process.Name, $process.ParentProcessId
            }
            foreach ($pidSeen in $current.Keys) {
                if (-not $known.ContainsKey($pidSeen)) {
                    Write-Record "start pid=$pidSeen $($current[$pidSeen])"
                }
            }
            foreach ($pidGone in $known.Keys) {
                if (-not $current.ContainsKey($pidGone)) {
                    Write-Record "stop  pid=$pidGone $($known[$pidGone]) exit=unknown"
                }
            }
            $known = $current
            Start-Sleep -Milliseconds 100
        }
    }
} finally {
    if ($tracing) {
        Unregister-Event -SourceIdentifier 'GarageProcessStart' -ErrorAction SilentlyContinue
        Unregister-Event -SourceIdentifier 'GarageProcessStop' -ErrorAction SilentlyContinue
    }
    Write-Record 'watcher: stopping'
    $writer.Dispose()
}
