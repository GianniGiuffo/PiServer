#!/usr/bin/env python3
"""Run Renovate in an isolated container; notify StatusBot with durable deduplication."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPOSITORY = "GianniGiuffo/PiServer"
BASE_BRANCH = "master"
STATE_DIR = Path("/var/lib/rack-pi-renovate")
CONTAINER = "rack-pi-renovate"
STATUS_FILE = Path("/srv/rack-pi/data/monitoring/renovate.json")
PREFIX = "Origine: rack-pi\nRenovate Â· mini-pc\n"
PATCHED_IMAGE = "ghcr.io/lklynet/aurral"


def publish_status(status: str, *, open_prs=None, updates=None) -> None:
    """Publish only non-secret summary fields for the Homepage widget."""
    previous = {}
    try:
        value = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            previous = value
    except (OSError, ValueError):
        pass
    now = datetime.now(timezone.utc)
    finished = status in ("Completato", "Errore")
    payload = {
        "status": status,
        "updated_at": now.isoformat(),
        "last_run": now.isoformat() if finished else previous.get("last_run"),
        "last_run_display": (
            now.astimezone(ZoneInfo("Europe/Rome")).strftime("%d/%m %H:%M")
            if finished else previous.get("last_run_display", "Mai")
        ),
        "open_prs": open_prs if open_prs is not None else previous.get("open_prs"),
        "updates": updates if updates is not None else previous.get("updates"),
    }
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    temp = STATUS_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.chmod(0o644)
    temp.replace(STATUS_FILE)


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value.startswith("CHANGE_ME"):
        raise RuntimeError(f"Configurare {name} in /etc/rack-pi/renovate.env.")
    return value


def load_env(path: Path) -> None:
    """Read literal assignments, compatible with this template and EnvironmentFile."""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise RuntimeError("Formato non valido nel file delle credenziali.")
        # No shell expansion/evaluation. Existing service environment takes priority.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def request_json(url: str, *, headers=None, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = dict(headers or {})
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers)
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        # Never include the URL: Telegram URLs contain the secret bot token.
        raise RuntimeError(f"Richiesta API fallita (HTTP {error.code}).") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise RuntimeError("Richiesta API fallita: rete o risposta non valida.") from None


def send_telegram(message: str) -> None:
    token = required("TELEGRAM_BOT_TOKEN")
    payload = {
        "chat_id": required("TELEGRAM_CHAT_ID"),
        "text": PREFIX + message,
        "disable_web_page_preview": True,
    }
    thread = os.environ.get("TELEGRAM_MESSAGE_THREAD_ID", "").strip()
    if thread:
        payload["message_thread_id"] = int(thread)
    result = request_json(
        f"https://api.telegram.org/bot{token}/sendMessage", payload=payload
    )
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError("Telegram non ha confermato la notifica.")


def open_pull_requests(token: str) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PiServer-rack-pi-renovate",
    }
    result = []
    page = 1
    while True:
        items = request_json(
            f"https://api.github.com/repos/{REPOSITORY}/pulls"
            f"?state=open&base={BASE_BRANCH}&per_page=100&page={page}",
            headers=headers,
        )
        if not isinstance(items, list):
            raise RuntimeError("GitHub non ha restituito un elenco di PR.")
        result.extend(
            pr for pr in items
            if pr.get("head", {}).get("ref", "").startswith("renovate/")
            and (pr.get("head", {}).get("repo") or {}).get("full_name") == REPOSITORY
            and pr.get("base", {}).get("ref") == BASE_BRANCH
        )
        if len(items) < 100:
            return result
        page += 1


def update_events(log_file: Path) -> dict[str, str]:
    """Read the structured lookup record emitted by the pinned Renovate version."""
    events = {}
    found_lookup = False
    with log_file.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if (record.get("repository") != REPOSITORY
                    or record.get("msg") != "packageFiles with updates"):
                continue
            found_lookup = True
            for files in record.get("config", {}).values():
                for package in files:
                    for dep in package.get("deps", []):
                        name = dep.get("depName", "")
                        for update in dep.get("updates", []):
                            new = update.get("newValue") or update.get("newVersion")
                            digest = update.get("newDigest", "")
                            if not new and not digest:
                                continue
                            kind = update.get("updateType", "")
                            identity = [name, new, digest, kind]
                            key = "release:" + fingerprint(identity)
                            current = dep.get("currentValue", "?")
                            label = dep.get("depType") or name
                            if kind == "pinDigest":
                                action = "Proposta di fissare il digest (non una nuova versione)"
                            elif digest and current == new:
                                action = "Nuova build disponibile per il tag selezionato"
                            else:
                                action = "Nuova versione disponibile"
                            message = f"{action}\n{label}\n{name}: {current} â†’ {new or current}"
                            if digest:
                                message += f"\nDigest: {digest}"
                            if name == PATCHED_IMAGE:
                                message += "\nAurral: verificare patch e mount locali prima del merge."
                            events[key] = message
    if not found_lookup:
        raise RuntimeError("Lookup Renovate assente: controllare il log JSON locale.")
    return events


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def pr_events(pulls: list[dict]) -> dict[str, str]:
    events = {}
    for pr in pulls:
        # Rebases alone do not notify again. A changed proposal does.
        identity = [pr["number"], pr["title"], pr.get("body") or ""]
        key = "pr:" + fingerprint(identity)
        events[key] = (
            f"PR disponibile o proposta aggiornata: #{pr['number']}\n"
            f"{pr['title']}\n{pr['html_url']}\nRevisione, merge e deploy manuali."
        )
    return events


def read_state(path: Path) -> dict:
    if not path.exists():
        return {"seen": {}, "failed": False}
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state.get("seen"), dict):
        raise RuntimeError("Stato delle notifiche non valido; conservarlo e verificarlo.")
    return state


def write_state(path: Path, state: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(path)


def notify_events(events: dict[str, str], state: dict, path: Path) -> None:
    """Acknowledge each batch only after Telegram confirms successful delivery."""
    batch = []
    length = len(PREFIX)
    for key, message in events.items():
        if key in state["seen"]:
            continue
        if batch and length + len(message) + 2 > 3500:
            deliver_batch(batch, state, path)
            batch = []
            length = len(PREFIX)
        batch.append((key, message))
        length += len(message) + 2
    if batch:
        deliver_batch(batch, state, path)


def deliver_batch(batch: list[tuple[str, str]], state: dict, path: Path) -> None:
    send_telegram("\n\n".join(message for _, message in batch))
    state["seen"].update({key: True for key, _ in batch})
    write_state(path, state)


def docker_command(repo_dir: Path, image: str, dry_run: bool) -> list[str]:
    if not re.fullmatch(r"ghcr\.io/renovatebot/renovate:[0-9]+\.[0-9]+\.[0-9]+", image):
        raise RuntimeError("RENOVATE_IMAGE deve essere una release esplicita di Renovate.")
    command = [
        "docker", "run", "--rm", "--name", CONTAINER,
        "--user", "1000:1000", "--memory", "1536m", "--cpus", "1.5",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "-e", "RENOVATE_TOKEN", "-e", "RENOVATE_CONFIG_FILE=/opt/renovate/config.cjs",
        "-e", "LOG_LEVEL=info", "-e", "LOG_FILE=/state/renovate.log",
        "-e", "LOG_FILE_LEVEL=debug", "-e", "LOG_FORMAT=json",
        "-v", f"{repo_dir / 'renovate.json'}:/opt/renovate/renovate-repository.json:ro",
        "-v", f"{repo_dir / 'rack-pi/config/renovate.cjs'}:/opt/renovate/config.cjs:ro",
        "-v", f"{STATE_DIR}:/state",
        image, "--automerge=false", "--platform-automerge=false", "--auto-approve=false",
    ]
    if dry_run:
        command.append("--dry-run=full")
    return command


def run(dry_run: bool) -> int:
    token = required("RENOVATE_TOKEN")
    if not dry_run:
        required("TELEGRAM_BOT_TOKEN")
        required("TELEGRAM_CHAT_ID")
    repo_dir = Path(__file__).resolve().parents[2]
    if not STATE_DIR.is_dir():
        raise RuntimeError("Eseguire prima install-renovate.sh sul Raspberry.")
    log_file = STATE_DIR / "renovate.log"
    # Last run only; caches and notification state persist separately.
    log_file.unlink(missing_ok=True)
    command = docker_command(repo_dir, required("RENOVATE_IMAGE"), dry_run)
    if not dry_run:
        publish_status("In corso")
    status = 1
    try:
        completed = subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=3600, check=False,
        )
        status = completed.returncode
    except subprocess.TimeoutExpired:
        subprocess.run(
            ["docker", "stop", "--timeout=30", CONTAINER],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45, check=False,
        )
    if status:
        print(f"Container Renovate terminato con codice {status}.", file=sys.stderr)
    if dry_run:
        if status:
            raise RuntimeError("Dry run fallito: consultare /var/lib/rack-pi-renovate/renovate.log.")
        events = update_events(log_file)
        print(f"Dry run completato: {len(events)} proposte; nessuna scrittura GitHub o notifica.")
        return 0

    path = STATE_DIR / "notifications.json"
    state = read_state(path)
    failed = bool(status)
    events = {}
    # Report known updates even if a later branch/PR operation failed.
    try:
        events.update(update_events(log_file))
    except (RuntimeError, OSError):
        failed = True
    pulls = None
    try:
        pulls = open_pull_requests(token)
        events.update(pr_events(pulls))
    except RuntimeError:
        failed = True
    notify_events(events, state, path)
    if failed and not state.get("failed"):
        send_telegram(
            "Controllo incompleto o creazione PR fallita. Verificare "
            "journalctl -u rack-renovate e /var/lib/rack-pi-renovate/renovate.log."
        )
    elif not failed and state.get("failed"):
        send_telegram("Il controllo degli aggiornamenti Ã¨ tornato operativo.")
    state["failed"] = failed
    write_state(path, state)
    publish_status(
        "Errore" if failed else "Completato",
        open_prs=len(pulls) if pulls is not None else None,
        updates=sum(key.startswith("release:") for key in events),
    )
    print(f"Renovate: controllo {'incompleto' if failed else 'completato'}; "
          f"{len(events)} eventi rilevati. Merge e deploy restano manuali.")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--init-status", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path("/etc/rack-pi/renovate.env"))
    args = parser.parse_args()
    if args.init_status:
        if not STATUS_FILE.exists():
            publish_status("Da configurare")
        return 0
    if args.env_file.exists():
        load_env(args.env_file)
    # systemd already serializes service starts; also exclude concurrent manual runs.
    import fcntl
    with Path("/run/lock/rack-pi-renovate.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Un controllo Renovate Ã¨ giÃ  in esecuzione.") from None
        return run(args.dry_run)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError) as error:
        if "--dry-run" not in sys.argv:
            try:
                publish_status(
                    "Da configurare" if isinstance(error, RuntimeError)
                    and str(error).startswith("Configurare ") else "Errore"
                )
            except (OSError, ValueError):
                pass
        # Only our RuntimeError messages are safe to publish: no API URLs/secrets.
        print(str(error) if isinstance(error, RuntimeError) else
              "Errore locale: verificare configurazione e stato Renovate.", file=sys.stderr)
        sys.exit(1)
