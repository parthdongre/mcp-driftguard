import json

from driftguard.runtime import DriftGuardService
from driftguard.stdio_proxy import StdioProxyFilter


def _tool(description: str = "Search documents"):
    return {
        "name": "search",
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }


def test_stdio_proxy_intercepts_tools_list_and_versions_surface():
    service = DriftGuardService()
    proxy = StdioProxyFilter(server_id="demo", service=service)

    request = '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}\n'
    response = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "result": {"tools": [_tool()]}}
    ) + "\n"

    assert proxy.process_client_line(request) == request
    filtered = json.loads(proxy.process_server_line(response))

    assert filtered["result"]["tools"] == []
    assert len(service.revision_history("demo")) == 1

    snapshot = service.store.history("demo", "search")[-1]
    service.approve(snapshot)

    proxy.process_client_line(
        '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n'
    )
    second = json.loads(
        proxy.process_server_line(
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": [_tool()]}}) + "\n"
        )
    )

    assert second["result"]["tools"][0]["name"] == "search"
    assert len(service.revision_history("demo")) == 2
    assert service.current_surface_status("demo") is not None


def test_stdio_proxy_leaves_unrelated_jsonrpc_responses_untouched():
    service = DriftGuardService()
    proxy = StdioProxyFilter(server_id="demo", service=service)
    request = '{"jsonrpc":"2.0","id":"x","method":"tools/call","params":{}}\n'
    response = '{"jsonrpc":"2.0","id":"x","result":{"content":[]}}\n'

    proxy.process_client_line(request)

    assert proxy.process_server_line(response) == response
    assert service.revision_history("demo") == []


def test_stdio_proxy_passes_non_json_stdout_through():
    proxy = StdioProxyFilter(server_id="demo", service=DriftGuardService())

    assert proxy.process_server_line("debug output\n") == "debug output\n"


def test_stdio_proxy_marks_catalog_dirty_on_list_changed_notification():
    service = DriftGuardService()
    proxy = StdioProxyFilter(server_id="demo", service=service)
    service.observe_surface(server_id="demo", tools=[_tool()])

    notification = (
        '{"jsonrpc":"2.0","method":"notifications/tools/list_changed"}\n'
    )
    assert proxy.process_server_line(notification) == notification
    assert service.catalog_freshness("demo").dirty is True

    proxy.process_client_line(
        '{"jsonrpc":"2.0","id":9,"method":"tools/list","params":{}}\n'
    )
    proxy.process_server_line(
        json.dumps({"jsonrpc": "2.0", "id": 9, "result": {"tools": [_tool()]}})
        + "\n"
    )

    assert service.catalog_freshness("demo").dirty is False
