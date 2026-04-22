import os

from urllib.parse import quote
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_engine = None
_session_factory = sessionmaker(autocommit=False, autoflush=False)


def get_database_uri():
    required_env = [
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
    ]
    missing = [key for key in required_env if not os.environ.get(key)]
    if missing:
        missing_csv = ", ".join(missing)
        raise RuntimeError(f"Missing database environment variables: {missing_csv}")

    db_username = os.environ["POSTGRES_USER"]
    db_password = quote(os.environ["POSTGRES_PASSWORD"])
    db_host = os.environ["POSTGRES_HOST"]
    db_port = os.environ["POSTGRES_PORT"]
    db_name = os.environ["POSTGRES_DB"]
    return f"postgresql://{db_username}:{db_password}@{db_host}:{db_port}/{db_name}"


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_database_uri(),
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            connect_args={"options": "-c synchronous_commit=off"},
        )
        _session_factory.configure(bind=_engine)
    return _engine


def reset_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


class LazySessionFactory:
    def __call__(self, *args, **kwargs):
        get_engine()
        return _session_factory(*args, **kwargs)


SessionLocal = LazySessionFactory()


def get_db():
    db = None
    try:
        db = SessionLocal()
        yield db
    finally:
        if db is not None:
            db.close()
