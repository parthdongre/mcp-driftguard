from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .adapters import ToolsListInterception, intercept_tools_list
from .revisions import DiscoveryRevision, RevisionDelta, SurfaceObservation
from .runtime import AuditIntegrityReport, DriftGuardService, ReviewEvent, verify_review_chain


class InterceptRequest(BaseModel):
    payload: dict[str, Any]
    protocol_version: str | None = None


class ReviewRequest(BaseModel):
    sha256: str = Field(min_length=64, max_length=64)
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=2000)


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
        )

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
        "/v1/servers/{server_id}/revisions",
        response_model=list[DiscoveryRevision],
    )
    def revisions(server_id: str) -> list[DiscoveryRevision]:
        return runtime.revision_history(server_id)

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
