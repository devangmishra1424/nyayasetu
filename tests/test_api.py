import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ["SKIP_MODEL_LOAD"] = "true"

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_query_too_short():
    response = client.post("/query", json={"query": "hi"})
    assert response.status_code == 400

def test_query_too_long():
    response = client.post("/query", json={"query": "a" * 2001})
    assert response.status_code == 400

def test_query_empty():
    response = client.post("/query", json={"query": ""})
    assert response.status_code == 400