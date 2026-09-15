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
    assert 'id="revision-trajectory"' in html
    assert 'id="surface-map"' in html
    assert 'id="risk-dial"' in html
    assert 'aria-live="polite"' in html


def test_dashboard_uses_framevitals_palette_and_single_primary_accent():
    css = (
        importlib.resources.files("driftguard.ui")
        .joinpath("styles.css")
        .read_text(encoding="utf-8")
    )

    assert "--bg-0: #0a0a0a;" in css
    assert "--ink-1: #f5efe6;" in css
    assert "--ink-2: #c9c1b4;" in css
    assert "--accent: #5eead4;" in css
    assert "--warn: #f5b14a;" in css
    assert "--bad: #f08080;" in css
    assert "--blue:" not in css
    assert "--purple:" not in css
