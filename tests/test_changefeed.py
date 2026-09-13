from datetime import UTC, datetime, timedelta

from driftguard.changefeed import build_change_feed, changes_after
from driftguard.render import (
    render_change_event,
    render_revision_delta,
    render_surface_status,
)
from driftguard.revisions import (
    SurfaceObservation,
    compare_to_trusted,
    diff_revisions,
    make_discovery_revision,
)


def _tool(name: str, description: str):
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": {}},
    }


def _revisions():
    start = datetime(2026, 9, 13, tzinfo=UTC)
    first = make_discovery_revision(
        server_id="demo",
        tools=[_tool("search", "Search documents")],
        observed_at=start,
    )
    unchanged = make_discovery_revision(
        server_id="demo",
        tools=[_tool("search", "Search documents")],
        parent_revision_id=first.revision_id,
        observed_at=start + timedelta(seconds=1),
    )
    changed = make_discovery_revision(
        server_id="demo",
        tools=[
            _tool("search", "Search documents with metadata"),
            _tool("format", "Format output"),
        ],
        parent_revision_id=unchanged.revision_id,
        observed_at=start + timedelta(seconds=2),
    )
    return first, unchanged, changed


def test_change_feed_distinguishes_unchanged_poll_from_content_change():
    first, unchanged, changed = _revisions()
    feed = build_change_feed([first, unchanged, changed])

    assert feed[0].initial is True
    assert feed[1].content_changed is False
    assert feed[2].content_changed is True
    assert feed[2].added_tools == ["format"]
    assert [item.tool_name for item in feed[2].modified_tools] == ["search"]


def test_change_feed_cursor_returns_only_newer_revisions():
    first, unchanged, changed = _revisions()

    feed = changes_after([first, unchanged, changed], unchanged.revision_id)

    assert feed is not None
    assert [item.revision_id for item in feed] == [changed.revision_id]
    assert changes_after([first], "missing") is None


def test_human_renderers_use_git_style_change_markers():
    first, _, changed = _revisions()
    delta = diff_revisions(first, changed)
    rendered = render_revision_delta(delta)

    assert "A  format" in rendered
    assert "M  search" in rendered

    event = build_change_feed([first, changed])[-1]
    assert "changed" in render_change_event(event)


def test_status_renderer_shows_trusted_state():
    first, _, changed = _revisions()
    status = SurfaceObservation(
        revision=changed,
        previous_delta=diff_revisions(first, changed),
        trusted_status=compare_to_trusted(changed, []),
    )

    rendered = render_surface_status(status)

    assert "Changes since previous revision:" in rendered
    assert "?  format  (not approved)" in rendered
    assert "?  search  (not approved)" in rendered
