from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .adapters import ToolsListInterception, intercept_tools_list
from .runtime import DriftGuardService, ReviewEvent


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

    return app
