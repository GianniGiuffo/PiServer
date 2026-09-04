#!/usr/bin/env python3
"""Check that Rest Server sees the same live repository as its host."""

from __future__ import annotations

from pathlib import Path
import sys


def verify_mount(host_root: Path, container_root: Path, repositories: list[Path]) -> None:
    host_root = host_root.resolve(strict=True)
    for path in [host_root, *repositories]:
        relative = path.resolve(strict=True).relative_to(host_root)
        inside = container_root / relative
        host_stat = path.stat()
        container_stat = inside.stat()
        if (host_stat.st_dev, host_stat.st_ino) != (
            container_stat.st_dev,
            container_stat.st_ino,
        ):
            raise ValueError(f"Rest Server has a different mount for {relative}")
        if relative != Path("."):
            # Metadata can be cached even after unplugging a USB disk. Read
            # the small config file as well; never touch repository contents.
            if path.read_bytes() != inside.read_bytes():
                raise ValueError(f"Rest Server has a stale config for {relative}")


def main() -> int:
    try:
        pid = int(sys.argv[1])
        if pid <= 0:
            raise ValueError("Rest Server is not running")
        mountinfo = Path(f"/proc/{pid}/mountinfo").read_text()
        mounts = [line.split() for line in mountinfo.splitlines()]
        data_mount = next(row for row in mounts if row[4] == "/data")
        options = set(data_mount[5].split(",")) | set(data_mount[-1].split(","))
        if options & {"ro", "shutdown"}:
            raise ValueError("Rest Server's filesystem is read-only or shut down")
        verify_mount(
            Path(sys.argv[2]),
            Path(f"/proc/{pid}/root/data"),
            [Path(path) for path in sys.argv[3:]],
        )
        return 0
    except (OSError, ValueError, IndexError, StopIteration) as error:
        print(f"Rest Server mount is not usable: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
