#!/usr/bin/env python3
"""Stop a remote backup promptly if its repository disappears during transfer."""

from __future__ import annotations

import signal
import subprocess
import sys
from collections.abc import Callable, Sequence


def repository_readable() -> bool:
    try:
        result = subprocess.run(
            ["restic", "--no-cache", "--no-lock", "cat", "config"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def stop_process(process: subprocess.Popen, grace: float = 10) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def run_backup(
    command: Sequence[str],
    probe: Callable[[], bool] = repository_readable,
    interval: float = 15,
) -> int:
    process = subprocess.Popen(command)
    try:
        while True:
            try:
                return process.wait(timeout=interval)
            except subprocess.TimeoutExpired:
                if not probe():
                    # Do not wait through Restic's repeated HTTP 500 retries
                    # while the caller's application writers remain stopped.
                    print(
                        "Restic repository became unavailable; aborting the transfer "
                        "so application services can resume.",
                        file=sys.stderr,
                        flush=True,
                    )
                    stop_process(process)
                    return 1
    finally:
        stop_process(process)


def interrupted(signum: int, _frame: object) -> None:
    # Unwind run_backup's finally block before the shell's EXIT cleanup runs.
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    if len(sys.argv) < 2:
        raise SystemExit("Usage: run-restic-backup.py restic backup [arguments...]")
    raise SystemExit(run_backup(sys.argv[1:]))
