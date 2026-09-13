from driftguard.adapters import extract_tools


def test_extract_tools_from_jsonrpc_result():
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "search"}]}}
    assert extract_tools(payload) == [{"name": "search"}]


def test_extract_tools_rejects_non_list_tools():
    assert extract_tools({"tools": {"name": "search"}}) == []
