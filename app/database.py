"""
Database engine with SQLite WAL-mode for concurrent read performance.
WAL (Write-Ahead Logging) allows multiple concurrent readers alongside a writer,
making SQLite viable for hundreds of concurrent users.
"""
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'data', 'app.db')}"

engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 30,          # wait up to 30s for a write lock
    },
    pool_size=20,               # keep 20 connections alive
    max_overflow=40,            # allow 40 more under burst
    pool_timeout=30,
    pool_recycle=1800,          # recycle connections every 30 min
    pool_pre_ping=True,         # verify connection before use
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _connection_record):
    """Apply performance and safety pragmas on every new connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")        # concurrent reads
    cursor.execute("PRAGMA synchronous=NORMAL")      # safe + fast
    cursor.execute("PRAGMA cache_size=-64000")       # 64 MB page cache
    cursor.execute("PRAGMA foreign_keys=ON")         # enforce FK constraints
    cursor.execute("PRAGMA temp_store=MEMORY")       # temp tables in RAM
    cursor.execute("PRAGMA mmap_size=268435456")     # 256 MB memory-mapped I/O
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
