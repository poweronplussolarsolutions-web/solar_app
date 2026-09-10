#!/usr/bin/env python3
"""Create a compressed MySQL backup for the Solar app.

Designed to run from a scheduler (the included systemd timer runs it daily).
It reads DATABASE_URL from the same environment file as the Flask app and
keeps successful backups for a configurable number of days.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from subprocess import CalledProcessError, run
from urllib.parse import unquote, urlsplit

APP_DIR = Path(__file__).resolve().parent


def load_environment_file(path: Path) -> None:
    """Load simple KEY=VALUE pairs without making the scheduler depend on Flask."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_environment_file(APP_DIR.parent / ".env")
load_environment_file(APP_DIR / ".env")


def mysql_settings(database_url: str) -> dict[str, str]:
    """Turn mysql+pymysql://user:pass@host:port/database into dump settings."""
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"mysql", "mysql+pymysql", "mysql+mysqldb"}:
        raise ValueError("DATABASE_URL must use a MySQL URL, e.g. mysql+pymysql://...")
    if not parsed.hostname or not parsed.path or parsed.path == "/":
        raise ValueError("DATABASE_URL must include a MySQL host and database name")

    return {
        "host": parsed.hostname,
        "port": str(parsed.port or 3306),
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": unquote(parsed.path.lstrip("/").split("/", 1)[0]),
    }


def remove_expired_backups(backup_dir: Path, keep_days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    removed = 0
    for backup in backup_dir.glob("solar_app_*.sql.gz"):
        if datetime.fromtimestamp(backup.stat().st_mtime, timezone.utc) < cutoff:
            backup.unlink()
            removed += 1
    return removed


def create_backup(backup_dir: Path, keep_days: int) -> Path:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    settings = mysql_settings(database_url)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destination = backup_dir / f"solar_app_{timestamp}.sql.gz"
    temporary = destination.with_suffix(".sql.gz.part")
    dump_command = [
        os.getenv("MYSQLDUMP_BIN", "mysqldump"),
        f"--host={settings['host']}",
        f"--port={settings['port']}",
        f"--user={settings['user']}",
        "--single-transaction",
        "--quick",
        "--routines",
        "--events",
        "--triggers",
        settings["database"],
    ]
    environment = os.environ.copy()
    environment["MYSQL_PWD"] = settings["password"]

    try:
        with temporary.open("wb") as raw_file:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_file) as compressed_file:
                run(dump_command, stdout=compressed_file, stderr=None, env=environment, check=True)
        temporary.replace(destination)  # A failed dump is never presented as a backup.
    except (CalledProcessError, FileNotFoundError):
        temporary.unlink(missing_ok=True)
        raise

    removed = remove_expired_backups(backup_dir, keep_days)
    logging.info("Backup saved to %s; removed %d expired backup(s)", destination, removed)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a compressed MySQL backup for Solar app.")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path(os.getenv("BACKUP_DIR", APP_DIR / "backups")),
        help="Directory that will hold .sql.gz backups (default: BACKUP_DIR or app/backups).",
    )
    parser.add_argument(
        "--keep-days",
        type=int,
        default=int(os.getenv("BACKUP_KEEP_DAYS", "30")),
        help="Number of days to retain backups (default: BACKUP_KEEP_DAYS or 30).",
    )
    args = parser.parse_args()
    if args.keep_days < 1:
        parser.error("--keep-days must be at least 1")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    create_backup(args.backup_dir, args.keep_days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
