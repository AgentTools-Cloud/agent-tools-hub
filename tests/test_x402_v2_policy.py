import base64
import json

from hub import x402
from hub.db import DB
from hub.gateway import (
    _apply_request_policy,
    _payment_header,
    _sanitize_upstream_response,
)
from hub.sellers import _public_view


def _service(**overrides):
    service = {
        "slug": "deepseek-v4-flash-0731",
        "request_policy_json": json.dumps({
            "allowed_methods": ["POST"],
            "allowed_paths": ["v1/chat/completions"],
            "require_json": True,
            "fixed_model": "DeepSeek-V4-Flash-0731",
            "upstream_model": "deepseek-ai/DeepSeek-V4-Flash",
            "sanitize_response": True,

            "max_request_bytes": 20 * 1024 * 1024,
            "max_output_tokens": 4096,
            "allow_stream": False,
        }),
    }
    service.update(overrides)
    return service


def _apply(payload, **kwargs):
    return _apply_request_policy(
        service=kwargs.pop("service", _service()),
        path=kwargs.pop("path", "v1/chat/completions"),
        method=kwargs.pop("method", "POST"),
        body=json.dumps(payload).encode(),
        **kwargs,
    )


def _error(response):
    return json.loads(response.body)["error"]


def test_payment_signature_preferred_with_legacy_fallback():
    assert _payment_header({"payment-signature": "v2", "x-payment": "v1"}) == "v2"
    assert _payment_header({"x-payment": "v1"}) == "v1"
    assert _payment_header({}) is None


def test_payment_response_is_base64_json():
    value = {"success": True, "transaction": "0xabc"}
    encoded = x402.encode_payment_response(value)
    assert json.loads(base64.b64decode(encoded)) == value


def test_empty_policy_preserves_request_bytes():
    body = b"not-json"
    result, error = _apply_request_policy(
        service={"slug": "legacy", "request_policy_json": None},
        path="anything", method="DELETE", body=body,
    )
    assert result == body
    assert error is None


def test_policy_injects_model_and_default_output_cap():
    result, error = _apply({"messages": [{"role": "user", "content": "hi"}]})
    assert error is None
    payload = json.loads(result)
    assert payload["model"] == "deepseek-ai/DeepSeek-V4-Flash"
    assert payload["max_tokens"] == 4096


def test_policy_accepts_exact_model_and_small_limit():
    result, error = _apply({
        "model": "DeepSeek-V4-Flash-0731",
        "messages": [],
        "max_completion_tokens": 128,
    })
    assert error is None
    payload = json.loads(result)
    assert payload["model"] == "deepseek-ai/DeepSeek-V4-Flash"
    assert payload["max_completion_tokens"] == 128


def test_policy_rejects_wrong_model_before_payment():
    _, error = _apply({"model": "deepseek-ai/DeepSeek-V4-Flash", "messages": []})
    assert error.status_code == 422
    assert "fixed model" in _error(error)


def test_policy_rejects_streaming_and_oversized_output():
    _, stream_error = _apply({"messages": [], "stream": True})
    assert stream_error.status_code == 422
    _, limit_error = _apply({"messages": [], "max_tokens": 4097})
    assert limit_error.status_code == 422
    assert "4096" in _error(limit_error)


def test_policy_rejects_wrong_route_and_large_body():
    _, method_error = _apply({}, method="GET")
    assert method_error.status_code == 405
    _, path_error = _apply({}, path="v1/models")
    assert path_error.status_code == 404
    policy = json.loads(_service()["request_policy_json"])
    policy["max_request_bytes"] = 2
    _, size_error = _apply_request_policy(
        service=_service(request_policy_json=json.dumps(policy)),
        path="v1/chat/completions", method="POST", body=b"{}\n",
    )
    assert size_error.status_code == 413


def test_invalid_policy_fails_closed():
    _, error = _apply_request_policy(
        service=_service(request_policy_json="not-json"),
        path="v1/chat/completions", method="POST", body=b"{}",
    )
    assert error.status_code == 503


def test_db_persists_request_policy(tmp_path):
    db = DB(str(tmp_path / "hub.db"))
    seller_id = db.create_seller(
        slug="internal-owner", name="Internal", contact_email=None,
        payout_address="0x1111111111111111111111111111111111111111",
        payout_network="eip155:8453",
    )
    policy = _service()["request_policy_json"]
    db.create_service(
        seller_id=seller_id,
        slug="deepseek-v4-flash-0731",
        upstream_base_url="https://tianshu-gateway.cloud",
        upstream_auth_header="Authorization",
        upstream_auth_enc="encrypted",
        price_usdc=0.01,
        description="DeepSeek V4 Flash",
        category="AI/LLM",
        facilitator="payai",
        request_policy_json=policy,
    )
    row = db.service_with_payout("deepseek-v4-flash-0731")
    assert row["request_policy_json"] == policy


def test_public_service_view_hides_request_policy():
    public = _public_view({
        "id": 100,
        "seller_id": 100,
        "slug": "deepseek-v4-flash-0731",
        "upstream_base_url": "https://private.example",
        "created_at": 1,
        "request_policy_json": _service()["request_policy_json"],
    })
    assert public == {"slug": "deepseek-v4-flash-0731"}



def test_base_usdc_requirements_use_onchain_eip712_name():
    requirements = x402.build_requirements(
        service={
            "price_usdc": 0.01,
            "payout_address": "0x1111111111111111111111111111111111111111",
        },
        resource_url="https://example.com/paid",
        network="eip155:8453",
        usdc_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    )
    assert requirements["extra"] == {"name": "USD Coin", "version": "2"}


def test_policy_accepts_prompt_larger_than_old_limit():
    prompt = "x" * (256 * 1024)
    result, error = _apply({"messages": [{"role": "user", "content": prompt}]})
    assert error is None
    payload = json.loads(result)
    assert payload["messages"][0]["content"] == prompt


def test_policy_rejects_invalid_upstream_model_config():
    policy = json.loads(_service()["request_policy_json"])
    policy["upstream_model"] = ""
    _, error = _apply_request_policy(
        service=_service(request_policy_json=json.dumps(policy)),
        path="v1/chat/completions", method="POST", body=b"{}",
    )
    assert error.status_code == 503


def test_response_policy_hides_internal_model_cost_and_metadata():
    upstream = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "deepseek-ai/DeepSeek-V4-Flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
        "usage": {
            "prompt_tokens": 2,
            "completion_tokens": 1,
            "total_tokens": 3,
            "cost": 0.0001,
            "backend_id": 33,
        },
        "backend": "internal-router",
        "system_fingerprint": "private",
    }
    content, status, sanitized = _sanitize_upstream_response(
        service=_service(), content=json.dumps(upstream).encode(), status_code=200)
    payload = json.loads(content)
    assert status == 200 and sanitized is True
    assert payload["model"] == "DeepSeek-V4-Flash-0731"
    assert payload["usage"] == {
        "prompt_tokens": 2,
        "completion_tokens": 1,
        "total_tokens": 3,
    }
    assert "backend" not in payload and "system_fingerprint" not in payload


def test_response_policy_replaces_upstream_error_details():
    content, status, sanitized = _sanitize_upstream_response(
        service=_service(),
        content=b'{"error":"private host failed","backend":"10.0.0.1"}',
        status_code=502,
    )
    assert status == 502 and sanitized is True
    assert json.loads(content) == {"error": "upstream request failed", "status": 502}
