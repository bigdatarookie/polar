import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    dsn: str
    artifacts: Path
    lease_seconds: int = 15
    job_seconds: int = 60
    storage_bytes: int = 64 * 1024**3
    history_cursor_key_file: Path = Path("/run/secrets/history_cursor_key")

    history_calendar_dir: Path | None = None

    @classmethod
    def load(cls):
        # Credentials are read from a mounted secret. Never log the DSN.
        secret = Path(os.environ.get("POLAR_DB_PASSWORD_FILE", "/run/secrets/db_password"))
        if "POLAR_DATABASE_URL" in os.environ:
            dsn = os.environ["POLAR_DATABASE_URL"]
        else:
            from psycopg.conninfo import make_conninfo
            dsn = make_conninfo(host=os.environ.get("POLAR_DB_HOST", "db"),
                               dbname="polar", user="polar", password=secret.read_text().strip(),
                               connect_timeout=3)
        allocation = os.environ.get("POLAR_STORAGE_BYTES", str(64 * 1024**3))
        if (not allocation.isascii() or not allocation.isdecimal() or len(allocation) > 11 or
                not 1 <= int(allocation) <= 64 * 1024**3):
            raise ValueError("INVALID_STORAGE_ALLOCATION")
        return cls(dsn, Path(os.environ.get("POLAR_ARTIFACT_ROOT", "/data/artifacts")), storage_bytes=int(allocation),
                   history_calendar_dir=Path(os.environ["POLAR_HISTORY_CALENDAR_DIR"]) if "POLAR_HISTORY_CALENDAR_DIR" in os.environ else None,
                   history_cursor_key_file=Path(os.environ.get("POLAR_HISTORY_CURSOR_KEY_FILE", "/run/secrets/history_cursor_key")))
