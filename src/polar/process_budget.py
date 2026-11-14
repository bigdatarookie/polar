"""Owned Linux process-group supervision for finite synchronous service computations.

No shell, broad process kill, cgroup/daemon mutation or fixture retry. The child is
trusted application code: it must not detach from its new session/process group.
Linux subreaping preserves CPU accounting for orphaned descendants. Samples retain
an RSS sum peak; the exact wait4 CPU total includes exited/reaped children.
"""
import ctypes
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

from .hyp007_contract import check


def group_sample(pgid):
    ticks = os.sysconf("SC_CLK_TCK")
    page = os.sysconf("SC_PAGE_SIZE")
    cpu, rss, pids = 0., 0, []
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal():
            continue
        try:
            raw = (path/"stat").read_text()
            fields = raw[raw.rfind(")")+2:].split()
            if int(fields[2]) != pgid:
                continue
            # utime/stime plus waited-for descendants; only live group members remain.
            cpu += sum(int(fields[i]) for i in (11,12,13,14))/ticks
            rss += max(0, int(fields[21]))*page
            pids.append(int(path.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return cpu, rss, pids


def _supervise_legacy(argv, *, env, output, cpu_seconds=600., wall_seconds=900., poll=.05):
    check(sys.platform == "linux" and Path("/proc/self/stat").is_file(), "PROCESS_ACCOUNTING_UNAVAILABLE")
    libc = ctypes.CDLL(None, use_errno=True)
    # PR_SET_CHILD_SUBREAPER, scoped to this application supervisor process.
    check(libc.prctl(36, 1, 0, 0, 0) == 0, "PROCESS_ACCOUNTING_UNAVAILABLE")
    start = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_SELF)
    with output.open("xb") as log, output.with_suffix(".resources.ndjson").open("xb") as journal:
        child = subprocess.Popen(argv, env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT)
        pgid = child.pid
        status, spent, peak, maximum, killed, waited = None, 0., 0, 0., None, []
        try:
            while True:
                live_cpu, rss, pids = group_sample(pgid)
                peak = max(peak, rss)
                current = resource.getrusage(resource.RUSAGE_SELF)
                own_cpu = current.ru_utime+current.ru_stime-before.ru_utime-before.ru_stime
                maximum = max(maximum, spent+live_cpu+own_cpu)
                elapsed = time.monotonic()-start
                sample = {"wall_seconds": elapsed, "observed_cpu_seconds": maximum,
                          "sampled_group_rss_peak_bytes": peak, "owned_pids": pids}
                journal.write((json.dumps(sample,sort_keys=True)+"\n").encode())
                journal.flush(); os.fsync(journal.fileno())
                if killed is None and (maximum > cpu_seconds or elapsed > wall_seconds):
                    killed = "CPU_LIMIT" if maximum > cpu_seconds else "WALL_LIMIT"
                    try: os.killpg(pgid, signal.SIGKILL)
                    except ProcessLookupError: pass
                while True:
                    try:
                        pid, raw_status, usage = os.wait4(-pgid, os.WNOHANG)
                    except ChildProcessError:
                        pid = 0
                    if pid == 0:
                        break
                    spent += usage.ru_utime+usage.ru_stime
                    waited.append(pid)
                    if pid == child.pid:
                        status = os.waitstatus_to_exitcode(raw_status)
                        child.returncode = status
                if status is not None:
                    _, _, remaining = group_sample(pgid)
                    if remaining:
                        # Trusted operation must not leave children after its main exits.
                        killed = killed or "ORPHANED_CHILDREN"
                        try: os.killpg(pgid, signal.SIGKILL)
                        except ProcessLookupError: pass
                    else:
                        break
                time.sleep(poll)
        finally:
            if status is None:
                try: os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError: pass
                while True:
                    try:
                        pid, raw_status, usage = os.wait4(-pgid, 0)
                    except ChildProcessError:
                        break
                    spent += usage.ru_utime+usage.ru_stime
                    waited.append(pid)
                    if pid == child.pid:
                        status = os.waitstatus_to_exitcode(raw_status)
                        child.returncode = status
    current = resource.getrusage(resource.RUSAGE_SELF)
    own_cpu = current.ru_utime+current.ru_stime-before.ru_utime-before.ru_stime
    total = spent+own_cpu
    if total > cpu_seconds:
        killed = killed or "CPU_LIMIT"
    _, _, remaining = group_sample(pgid)
    return {"schema": "polar.process-budget/1", "exit_code": status, "failure": killed,
            "cpu_seconds": total, "wall_seconds": time.monotonic()-start,
            "child_cpu_seconds": spent, "supervisor_cpu_seconds": own_cpu,
            "cpu_limit": cpu_seconds, "wall_limit": wall_seconds,
            "sampled_group_rss_peak_bytes": peak, "sample_interval_seconds": poll,
            "rss_measurement": "SAMPLED_SUM_MAY_MISS_SHORT_PEAKS", "waited_owned_pids": waited,
            "remaining_owned_pids": remaining, "cleanup": "COMPLETE" if not remaining else "INCOMPLETE",
            "detached_children": "APPLICATION_PROHIBITED_NO_DETACH_CALLS"}


def supervise(argv, *, env, output, cpu_seconds=600., wall_seconds=900., poll=.05,
              rss_limit_bytes=None, max_output_bytes=None, max_journal_bytes=None,
              cleanup_seconds=None):
    """Supervise trusted, non-detaching application code in its own Linux group.

    Omitting every optional bound preserves the legacy path and receipt. Selecting
    any optional bound enables bounded cleanup (five seconds unless explicit).
    Byte bounds are positive integers; time bounds are positive finite numbers.
    RSS is sampled, not a hard allocation ceiling. Pipes bound stored output,
    including stderr, even when the child writes faster than the sampling loop.
    """
    bounded = any(value is not None for value in
                  (rss_limit_bytes, max_output_bytes, max_journal_bytes, cleanup_seconds))
    if not bounded:
        return _supervise_legacy(argv, env=env, output=output, cpu_seconds=cpu_seconds,
                                 wall_seconds=wall_seconds, poll=poll)
    for value in (rss_limit_bytes, max_output_bytes, max_journal_bytes):
        check(value is None or (type(value) is int and value > 0), "PROCESS_BUDGET_INVALID")
    cleanup_seconds = 5. if cleanup_seconds is None else cleanup_seconds
    for value in (cpu_seconds, wall_seconds, poll, cleanup_seconds):
        check(type(value) in (int, float) and 0 < value <= sys.float_info.max and math.isfinite(value),
              "PROCESS_BUDGET_INVALID")
    return _supervise_bounded(argv, env=env, output=output, cpu_seconds=cpu_seconds,
                              wall_seconds=wall_seconds, poll=poll,
                              rss_limit_bytes=rss_limit_bytes,
                              max_output_bytes=max_output_bytes,
                              max_journal_bytes=max_journal_bytes,
                              cleanup_seconds=cleanup_seconds)


def _supervise_bounded(argv, *, env, output, cpu_seconds, wall_seconds, poll,
                       rss_limit_bytes, max_output_bytes, max_journal_bytes,
                       cleanup_seconds):
    check(sys.platform == "linux" and Path("/proc/self/stat").is_file(),
          "PROCESS_ACCOUNTING_UNAVAILABLE")
    libc = ctypes.CDLL(None, use_errno=True)
    check(libc.prctl(36, 1, 0, 0, 0) == 0, "PROCESS_ACCOUNTING_UNAVAILABLE")
    start = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_SELF)
    status, spent, peak, maximum, killed, waited = None, 0., 0, 0., None, []
    output_observed = output_written = journal_observed = journal_written = 0
    output_truncated = journal_truncated = False
    cleanup_start = None
    remaining = []
    pipe_eof = False

    with output.open("xb") as log, output.with_suffix(".resources.ndjson").open("xb") as journal:
        child = subprocess.Popen(argv, env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        pgid = child.pid
        os.set_blocking(child.stdout.fileno(), False)

        def kill_group(reason):
            nonlocal killed, cleanup_start
            killed = killed or reason
            if cleanup_start is None:
                cleanup_start = time.monotonic()
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        def reap():
            nonlocal spent, status
            while True:
                try:
                    pid, raw_status, usage = os.wait4(-pgid, os.WNOHANG)
                except ChildProcessError:
                    break
                if not pid:
                    break
                spent += usage.ru_utime + usage.ru_stime
                waited.append(pid)
                if pid == child.pid:
                    status = os.waitstatus_to_exitcode(raw_status)
                    child.returncode = status

        def drain():
            nonlocal output_observed, output_written, output_truncated, pipe_eof
            if pipe_eof:
                return
            # Bound work per pass so a producer cannot starve time/CPU/RSS checks.
            for _ in range(16):
                try:
                    chunk = os.read(child.stdout.fileno(), 65536)
                except BlockingIOError:
                    break
                if not chunk:
                    pipe_eof = True
                    break
                output_observed += len(chunk)
                available = len(chunk) if max_output_bytes is None else max(0, max_output_bytes-output_written)
                kept = chunk[:available]
                log.write(kept)
                output_written += len(kept)
                if len(kept) < len(chunk):
                    output_truncated = True
                    kill_group("OUTPUT_LIMIT")
            log.flush()

        try:
            while True:
                drain()
                reap()
                live_cpu, rss, remaining = group_sample(pgid)
                peak = max(peak, rss)
                current = resource.getrusage(resource.RUSAGE_SELF)
                own_cpu = current.ru_utime+current.ru_stime-before.ru_utime-before.ru_stime
                maximum = max(maximum, spent+live_cpu+own_cpu)
                elapsed = time.monotonic()-start
                if maximum > cpu_seconds:
                    kill_group("CPU_LIMIT")
                elif elapsed > wall_seconds:
                    kill_group("WALL_LIMIT")
                elif rss_limit_bytes is not None and rss > rss_limit_bytes:
                    kill_group("RSS_LIMIT")
                sample = {"wall_seconds": elapsed, "observed_cpu_seconds": maximum,
                          "sampled_group_rss_peak_bytes": peak, "owned_pids": remaining}
                record = (json.dumps(sample, sort_keys=True)+"\n").encode()
                journal_observed += len(record)
                if max_journal_bytes is None or journal_written+len(record) <= max_journal_bytes:
                    journal.write(record)
                    journal_written += len(record)
                    journal.flush()
                else:
                    # Only whole NDJSON records: a tiny cap may produce an empty journal.
                    journal_truncated = True
                    kill_group("JOURNAL_LIMIT")
                if status is not None and remaining:
                    kill_group("ORPHANED_CHILDREN")
                if status is not None and not remaining and pipe_eof:
                    break
                if cleanup_start is not None and time.monotonic()-cleanup_start >= cleanup_seconds:
                    break
                # Poll never extends a selected wall or cleanup deadline.
                deadline = start+wall_seconds if cleanup_start is None else cleanup_start+cleanup_seconds
                time.sleep(min(poll, max(0., deadline-time.monotonic())))
        finally:
            if status is None or remaining:
                kill_group("SUPERVISOR_INTERRUPTED")
                while time.monotonic()-cleanup_start < cleanup_seconds:
                    drain()
                    reap()
                    _, _, remaining = group_sample(pgid)
                    if status is not None and not remaining and pipe_eof:
                        break
                    time.sleep(min(poll, max(0., cleanup_start+cleanup_seconds-time.monotonic())))
            child.stdout.close()
    current = resource.getrusage(resource.RUSAGE_SELF)
    own_cpu = current.ru_utime+current.ru_stime-before.ru_utime-before.ru_stime
    total = spent+own_cpu
    if total > cpu_seconds:
        killed = killed or "CPU_LIMIT"
    _, _, remaining = group_sample(pgid)
    cleanup_complete = status is not None and not remaining
    return {"schema": "polar.process-budget/1", "exit_code": status, "failure": killed,
            "owned_process_group_id": pgid,
            "cpu_seconds": total, "observed_cpu_seconds": max(maximum, total),
            "wall_seconds": time.monotonic()-start,
            "child_cpu_seconds": spent, "supervisor_cpu_seconds": own_cpu,
            "cpu_limit": cpu_seconds, "wall_limit": wall_seconds,
            "rss_limit_bytes": rss_limit_bytes, "max_output_bytes": max_output_bytes,
            "max_journal_bytes": max_journal_bytes, "cleanup_seconds": cleanup_seconds,
            "output_observed_bytes": output_observed, "output_written_bytes": output_written,
            "output_truncated": output_truncated, "output_eof": pipe_eof,
            "journal_observed_bytes": journal_observed, "journal_written_bytes": journal_written,
            "journal_truncated": journal_truncated,
            "sampled_group_rss_peak_bytes": peak, "sample_interval_seconds": poll,
            "rss_measurement": "SAMPLED_SUM_MAY_MISS_SHORT_PEAKS", "waited_owned_pids": waited,
            "remaining_owned_pids": remaining,
            "cleanup": "COMPLETE" if cleanup_complete else "INCOMPLETE",
            "cleanup_timed_out": not cleanup_complete,
            "cleanup_elapsed_seconds": 0. if cleanup_start is None else time.monotonic()-cleanup_start,
            "detached_children": "APPLICATION_PROHIBITED_NO_DETACH_CALLS"}
