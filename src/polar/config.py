import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    dsn: str
    artifacts: Path
    lease_seconds: int = 15
    job_seconds: int = 60
    storage_bytes: int = 4 * 1024**3

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
        return cls(dsn, Path(os.environ.get("POLAR_ARTIFACT_ROOT", "/data/artifacts")))
