import pytest

pytest.importorskip("fastapi")

from driftguard.api import create_app


def test_api_exposes_revision_and_realtime_routes():
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/v1/servers/{server_id}/timeline" in paths
    assert "/v1/servers/{server_id}/events" in paths
    assert "/v1/servers/{server_id}/revisions/{revision_id}/view" in paths
