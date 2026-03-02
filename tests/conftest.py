import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from llmos.db.models import Base
from llmos.api.app import create_app


@pytest.fixture
def db_session(tmp_path):
    db_file = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield Session
    engine.dispose()


@pytest.fixture
def test_client(tmp_path):
    """
    Returns a FastAPI TestClient with the full app.
    The worker thread is started but the daemon uses an in-process SQLite DB.
    """
    import os
    db_file = tmp_path / "test.db"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["WORKSPACE_DIR"] = str(workspace)
    os.environ["STEP_TIMEOUT_SECONDS"] = "10"
    os.environ["APPROVAL_TIMEOUT_SECONDS"] = "5"

    # Re-import settings after env override
    import importlib
    import llmos.config as cfg_mod
    importlib.reload(cfg_mod)
    import llmos.db.engine as eng_mod
    importlib.reload(eng_mod)

    app = create_app()
    with TestClient(app) as client:
        yield client
