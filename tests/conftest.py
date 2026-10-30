import os
import sys
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

# Banco isolado e IA generativa sempre offline nos testes (deterministico, sem custo)
os.environ["PETLINK_DB"] = str(Path(tempfile.mkdtemp()) / "teste.db")
os.environ["PETLINK_SEED"] = "1"
os.environ["ANTHROPIC_API_KEY"] = ""


@pytest.fixture()
def cliente():
    from fastapi.testclient import TestClient
    from api.main import app
    with TestClient(app) as c:
        c.post("/api/demo/reset")
        yield c
