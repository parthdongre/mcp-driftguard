import importlib.resources

import pytest

pytest.importorskip("fastapi")

from driftguard.api import create_app


def test_dashboard_routes_are_exposed():
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/" in paths
    assert "/ui/styles.css" in paths
    assert "/ui/app.js" in paths


def test_dashboard_markup_has_core_landmarks():
    html = (
        importlib.resources.files("driftguard.ui")
        .joinpath("index.html")
        .read_text(encoding="utf-8")
    )

    assert 'id="app-shell"' in html
    assert 'id="overview-grid"' in html
    assert 'id="revision-list"' in html
    assert 'id="activity-timeline"' in html
    assert 'id="revision-inspector"' in html
    assert 'aria-live="polite"' in html
