from fastapi.testclient import TestClient

from csre.main import app


def test_live_healthcheck() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["status"] == "ok"
    assert payload["data"]["checks"]["liveness"] == "ok"
