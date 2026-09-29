"""SQLite engine / session factory and schema migration to Alembic head."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event
from sqlmodel import Session, create_engine

from training.config import PROJECT_ROOT, Settings, get_settings

ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def _sqlite_pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def make_engine(db_path: Path) -> Engine:
    db_path = db_path.expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path.resolve()}")
    event.listen(engine, "connect", _sqlite_pragmas)
    return engine


def migrate(db_path: Path) -> None:
    """Bring the database at `db_path` to Alembic head (creates it if missing)."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.expanduser().resolve()}")
    db_path.expanduser().parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(cfg, "head")


def get_engine(settings: Settings | None = None, *, upgrade: bool = True) -> Engine:
    settings = settings or get_settings()
    if upgrade:
        migrate(settings.db_path)
    return make_engine(settings.db_path)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Session that commits on success and rolls back on error."""
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
