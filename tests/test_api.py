import pytest
from fastapi.testclient import TestClient
import os

os.environ["SKIP_MODEL_LOAD"] = "true"

from api.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_info():
    response = client.get("/info")
    assert response.status_code == 200
    assert "entity_types" in response.json()

def test_query_too_short():
    response = client.post("/query", json={"query": "hi"})
    assert response.status_code == 422

def test_query_too_long():
    response = client.post("/query", json={"query": "a" * 2001})
    assert response.status_code == 422

def test_query_empty():
    response = client.post("/query", json={"query": ""})
    assert response.status_code == 422