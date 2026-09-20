#!/usr/bin/env python3
"""Connect Bazarr to the co-located Radarr and Sonarr instances.

Run this while Bazarr is stopped. The generated Bazarr YAML is deliberately
edited without an additional YAML dependency, preserving all unrelated and
provider-specific settings.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET


def api_key(config: Path) -> str:
    value = ET.parse(config).getroot().findtext("ApiKey", "").strip()
    if not value:
        raise SystemExit(f"ApiKey assente in {config}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bazarr-config", type=Path, required=True)
    parser.add_argument("--radarr-config", type=Path, required=True)
    parser.add_argument("--sonarr-config", type=Path, required=True)
    args = parser.parse_args()

    replacements = {
        ("general", "use_radarr"): "true",
        ("general", "use_sonarr"): "true",
        ("radarr", "apikey"): api_key(args.radarr_config),
        ("radarr", "ip"): "radarr",
        ("radarr", "port"): "7878",
        ("radarr", "ssl"): "false",
        ("sonarr", "apikey"): api_key(args.sonarr_config),
        ("sonarr", "ip"): "sonarr",
        ("sonarr", "port"): "8989",
        ("sonarr", "ssl"): "false",
    }
    found = {key: 0 for key in replacements}
    section = ""
    output: list[str] = []

    for line in args.bazarr_config.read_text(encoding="utf-8").splitlines(True):
        if line and not line.startswith((" ", "\t", "#", "---")) and line.rstrip().endswith(":"):
            section = line.split(":", 1)[0]
        stripped = line.lstrip()
        if line.startswith("  ") and ":" in stripped:
            key = stripped.split(":", 1)[0]
            replacement = replacements.get((section, key))
            if replacement is not None:
                newline = "\r\n" if line.endswith("\r\n") else "\n"
                line = f"  {key}: {replacement}{newline}"
                found[(section, key)] += 1
        output.append(line)

    invalid = [f"{section}.{key}={count}" for (section, key), count in found.items() if count != 1]
    if invalid:
        raise SystemExit("Chiavi Bazarr inattese: " + ", ".join(invalid))

    backup = args.bazarr_config.with_suffix(args.bazarr_config.suffix + ".before-arr")
    if not backup.exists():
        shutil.copy2(args.bazarr_config, backup)

    stat = args.bazarr_config.stat()
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=args.bazarr_config.parent, delete=False
    ) as handle:
        handle.writelines(output)
        temporary = Path(handle.name)
    os.chmod(temporary, stat.st_mode)
    os.chown(temporary, stat.st_uid, stat.st_gid)
    os.replace(temporary, args.bazarr_config)
    print("Bazarr collegato a Radarr e Sonarr; provider sottotitoli invariati.")


if __name__ == "__main__":
    main()
