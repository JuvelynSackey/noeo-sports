import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
import app.database.models  # noqa: F401 registers all tables


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
