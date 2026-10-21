"""
Database engine + session setup.

Plain-language summary:
- `engine` is the low-level connection to the database.
- `SessionLocal` is a factory that hands out a "conversation" with
  the database (a session) for each request.
- `get_db()` is a FastAPI dependency: each API endpoint that needs
  DB access asks for `db: Session = Depends(get_db)`, and FastAPI
  will open a session, give it to the endpoint, and close it
  afterwards automatically -- even if the endpoint raises an error.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings

# SQLite needs a special connect arg because, by default, it only
# allows one thread to use a connection. FastAPI can use multiple
# threads for one request lifecycle, so we relax that restriction.
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
