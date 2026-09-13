from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .adapters import ToolsListInterception, intercept_tools_list
from .blame import ToolBlame
from .changefeed import RevisionChangeEvent
from .checkpoints import TrustedCheckpoint
from .checks import RevisionSecurityCheck
from .overview import ServerOverview
from .revisions import DiscoveryRevision, RevisionChannel, RevisionDelta, SurfaceObservation
from .runtime import AuditIntegrityReport, DriftGuardService, ReviewEvent, verify_review_chain
from .signals import CatalogFreshnessStatus
from .sse import encode_sse_comment, encode_sse_event
from .timeline import TimelineEvent
from .views import RevisionView


class InterceptRequest(BaseModel):
    payload: dict[str, Any]
    protocol_version: str | None = None


class ReviewRequest(BaseModel):
    sha256: str = Field(min_length=64, max_length=64)
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=2000)


class CheckpointCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    revision_id: str | None = None
    created_by: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


def create_app(service: DriftGuardService | None = None) -> FastAPI:
    """Create the optional HTTP control plane used by CLI/UI clients."""

    runtime = service if service is not None else DriftGuardService()
    app = FastAPI(
        title="MCP DriftGuard",
        version="0.1.0",
        description="Version-aware MCP tool drift detection and review control plane.",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/v1/servers/{server_id}/tools/intercept",
        response_model=ToolsListInterception,
    )
    def intercept(server_id: str, request: InterceptRequest) -> ToolsListInterception:
        return intercept_tools_list(
            payload=request.payload,
            server_id=server_id,
            service=runtime,
            protocol_version=request.protocol_version,
            channel=RevisionChannel.API,
        )

    @app.get(
        "/v1/servers/{server_id}/overview",
        response_model=ServerOverview,
    )
    def overview(server_id: str) -> ServerOverview:
        result = runtime.overview(server_id)
        if result is None:
            raise HTTPException(status_code=404, detail="No discovery revision exists for this server.")
        return result

    @app.get(
        "/v1/servers/{server_id}/status",
        response_model=SurfaceObservation,
    )
    def status(server_id: str) -> SurfaceObservation:
        result = runtime.current_surface_status(server_id)
        if result is None:
            raise HTTPException(status_code=404, detail="No discovery revision exists for this server.")
        return result

    @app.get(
        "/v1/servers/{server_id}/freshness",
        response_model=CatalogFreshnessStatus,
    )
    def freshness(server_id: str) -> CatalogFreshnessStatus:
        return runtime.catalog_freshness(server_id)

    @app.get(
        "/v1/servers/{server_id}/revisions",
        response_model=list[DiscoveryRevision],
    )
    def revisions(server_id: str) -> list[DiscoveryRevision]:
        return runtime.revision_history(server_id)

    @app.get(
        "/v1/servers/{server_id}/changes",
        response_model=list[RevisionChangeEvent],
    )
    def changes(
        server_id: str,
        after_revision: str | None = None,
    ) -> list[RevisionChangeEvent]:
        result = runtime.change_feed(
            server_id,
            after_revision_id=after_revision,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Change-feed cursor revision not found.")
        return result

    @app.get(
        "/v1/servers/{server_id}/timeline",
        response_model=list[TimelineEvent],
    )
    def timeline(
        server_id: str,
        after_event: str | None = None,
        newest_first: bool = True,
    ) -> list[TimelineEvent]:
        result = runtime.timeline(
            server_id,
            after_event_id=after_event,
            newest_first=newest_first,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Timeline cursor event not found.")
        return result

    @app.get("/v1/servers/{server_id}/events")
    def events(
        server_id: str,
        after_event: str | None = None,
        poll_interval: float = Query(default=1.0, ge=0.1, le=30.0),
    ) -> StreamingResponse:
        initial = runtime.timeline(
            server_id,
            after_event_id=after_event,
            newest_first=False,
        )
        if initial is None:
            raise HTTPException(status_code=404, detail="Timeline cursor event not found.")

        async def event_stream() -> AsyncIterator[str]:
            cursor = after_event
            pending = initial

            while True:
                if pending:
                    for event in pending:
                        yield encode_sse_event(event)
                        cursor = event.event_id
                else:
                    yield encode_sse_comment()

                await asyncio.sleep(poll_interval)
                next_events = runtime.timeline(
                    server_id,
                    after_event_id=cursor,
                    newest_first=False,
                )
                if next_events is None:
                    return
                pending = next_events

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get(
        "/v1/servers/{server_id}/checkpoints",
        response_model=list[TrustedCheckpoint],
    )
    def checkpoints(server_id: str) -> list[TrustedCheckpoint]:
        return runtime.checkpoints(server_id)

    @app.post(
        "/v1/servers/{server_id}/checkpoints",
        response_model=TrustedCheckpoint,
    )
    def create_checkpoint(
        server_id: str,
        request: CheckpointCreateRequest,
    ) -> TrustedCheckpoint:
        try:
            return runtime.create_checkpoint(
                server_id=server_id,
                name=request.name,
                revision_id=request.revision_id,
                created_by=request.created_by,
                note=request.note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/v1/servers/{server_id}/checkpoint",
        response_model=TrustedCheckpoint,
    )
    def checkpoint(server_id: str, name: str) -> TrustedCheckpoint:
        result = runtime.get_checkpoint(server_id, name)
        if result is None:
            raise HTTPException(status_code=404, detail="Trusted checkpoint not found.")
        return result

    @app.get(
        "/v1/servers/{server_id}/checkpoint/compare",
        response_model=RevisionDelta,
    )
    def checkpoint_compare(
        server_id: str,
        name: str,
        to_revision: str | None = None,
    ) -> RevisionDelta:
        result = runtime.compare_checkpoint(
            server_id=server_id,
            checkpoint_name=name,
            to_revision_id=to_revision,
        )
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Checkpoint or target revision was not found.",
            )
        return result

    @app.get(
        "/v1/servers/{server_id}/checks",
        response_model=list[RevisionSecurityCheck],
    )
    def checks(server_id: str) -> list[RevisionSecurityCheck]:
        return runtime.revision_checks(server_id)

    @app.get(
        "/v1/servers/{server_id}/revisions/{revision_id}/check",
        response_model=RevisionSecurityCheck,
    )
    def revision_check(server_id: str, revision_id: str) -> RevisionSecurityCheck:
        result = runtime.get_revision_check(server_id, revision_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Revision security check not found.")
        return result

    @app.get(
        "/v1/servers/{server_id}/revisions/{revision_id}/view",
        response_model=RevisionView,
    )
    def revision_view(server_id: str, revision_id: str) -> RevisionView:
        result = runtime.revision_view(
            server_id=server_id,
            revision_id=revision_id,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Discovery revision not found.")
        return result

    @app.get(
        "/v1/servers/{server_id}/revisions/{revision_id}",
        response_model=DiscoveryRevision,
    )
    def revision(server_id: str, revision_id: str) -> DiscoveryRevision:
        result = runtime.get_revision(server_id, revision_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Discovery revision not found.")
        return result

    @app.get(
        "/v1/servers/{server_id}/compare/{from_revision_id}/{to_revision_id}",
        response_model=RevisionDelta,
    )
    def compare(
        server_id: str,
        from_revision_id: str,
        to_revision_id: str,
    ) -> RevisionDelta:
        result = runtime.compare_revisions(
            server_id=server_id,
            from_revision_id=from_revision_id,
            to_revision_id=to_revision_id,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="One or both discovery revisions were not found.")
        return result

    @app.get(
        "/v1/servers/{server_id}/tools/{tool_name}/blame",
        response_model=ToolBlame,
    )
    def tool_blame(
        server_id: str,
        tool_name: str,
        revision_id: str | None = None,
        path: str | None = None,
    ) -> ToolBlame:
        result = runtime.blame_tool(
            server_id=server_id,
            tool_name=tool_name,
            revision_id=revision_id,
            path_prefix=path,
        )
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Tool or requested revision was not found in discovery history.",
            )
        return result

    def resolve_snapshot(server_id: str, tool_name: str, sha256: str):
        snapshot = runtime.get_observed(
            server_id=server_id,
            tool_name=tool_name,
            sha256=sha256,
        )
        if snapshot is None:
            raise HTTPException(
                status_code=404,
                detail="Observed snapshot not found for server/tool/hash.",
            )
        return snapshot

    @app.post("/v1/servers/{server_id}/tools/{tool_name}/approve")
    def approve(server_id: str, tool_name: str, request: ReviewRequest) -> ReviewEvent:
        snapshot = resolve_snapshot(server_id, tool_name, request.sha256)
        runtime.approve(
            snapshot,
            reviewer=request.reviewer,
            reason=request.reason,
        )
        return runtime.store.reviews(server_id, tool_name)[-1]

    @app.post("/v1/servers/{server_id}/tools/{tool_name}/reject")
    def reject(server_id: str, tool_name: str, request: ReviewRequest) -> ReviewEvent:
        snapshot = resolve_snapshot(server_id, tool_name, request.sha256)
        runtime.reject(
            snapshot,
            reviewer=request.reviewer,
            reason=request.reason,
        )
        return runtime.store.reviews(server_id, tool_name)[-1]

    @app.get(
        "/v1/servers/{server_id}/tools/{tool_name}/reviews",
        response_model=list[ReviewEvent],
    )
    def reviews(server_id: str, tool_name: str) -> list[ReviewEvent]:
        return runtime.store.reviews(server_id, tool_name)

    @app.get(
        "/v1/servers/{server_id}/tools/{tool_name}/reviews/integrity",
        response_model=AuditIntegrityReport,
    )
    def review_integrity(server_id: str, tool_name: str) -> AuditIntegrityReport:
        return verify_review_chain(runtime.store.reviews(server_id, tool_name))

    return app
