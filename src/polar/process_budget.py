"""Owned Linux process-group supervision for finite synchronous service computations.

No shell, broad process kill, cgroup/daemon mutation or fixture retry. The child is
trusted application code: it must not detach from its new session/process group.
Linux subreaping preserves CPU accounting for orphaned descendants. Samples retain
an RSS sum peak; the exact wait4 CPU total includes exited/reaped children.
"""
import ctypes
import json
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


def supervise(argv, *, env, output, cpu_seconds=600., wall_seconds=900., poll=.05):
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
