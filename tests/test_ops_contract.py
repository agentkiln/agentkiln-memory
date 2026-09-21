from scripts.ops_contract import (
    ContractError,
    validate_add_response,
    validate_health_response,
    validate_search_response,
)


def test_validate_health_response_accepts_public_health_payload() -> None:
    validate_health_response(
        {"status": "ok", "version": "1.0.0", "llm_mode": "off", "llm_ready": True}
    )


def test_validate_add_response_requires_echoed_identifiers() -> None:
    request = {
        "request_id": "eval:run:conv:chunk-0",
        "user_id": "eval:run:conv",
        "session_id": "eval:run:sample:0",
    }
    validate_add_response(
        request,
        {
            "success": True,
            "request_id": request["request_id"],
            "user_id": request["user_id"],
            "session_id": request["session_id"],
        },
    )


def test_validate_search_response_rejects_more_than_top_k() -> None:
    response = {
        "data": [
            {"id": "mem_1", "content": "one"},
            {"id": "mem_2", "content": "two"},
        ]
    }
    try:
        validate_search_response(response, top_k=1)
    except ContractError as exc:
        assert "top_k" in str(exc)
    else:
        raise AssertionError("expected contract failure")

