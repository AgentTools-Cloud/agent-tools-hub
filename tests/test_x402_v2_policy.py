import base64
import json

from hub import x402
from hub.db import DB
from hub.gateway import _apply_request_policy, _payment_header
from hub.sellers import _public_view


def _service(**overrides):
    service = {
        "slug": "tianshu-deepseek-v4-flash",
        "request_policy_json": json.dumps({
            "allowed_methods": ["POST"],
            "allowed_paths": ["v1/chat/completions"],
            "require_json": True,
            "fixed_model": "deepseek-ai/DeepSeek-V4-Flash",
            "max_request_bytes": 128 * 1024,
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
        "model": "deepseek-ai/DeepSeek-V4-Flash",
        "messages": [],
        "max_completion_tokens": 128,
    })
    assert error is None
    assert json.loads(result)["max_completion_tokens"] == 128


def test_policy_rejects_wrong_model_before_payment():
    _, error = _apply({"model": "Anthropic/Claude-Opus-5.5", "messages": []})
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
        slug="tianshu-deepseek-v4-flash",
        upstream_base_url="https://tianshu-gateway.cloud",
        upstream_auth_header="Authorization",
        upstream_auth_enc="encrypted",
        price_usdc=0.01,
        description="DeepSeek V4 Flash",
        category="AI/LLM",
        facilitator="payai",
        request_policy_json=policy,
    )
    row = db.service_with_payout("tianshu-deepseek-v4-flash")
    assert row["request_policy_json"] == policy


def test_public_service_view_hides_request_policy():
    public = _public_view({
        "slug": "tianshu-deepseek-v4-flash",
        "request_policy_json": _service()["request_policy_json"],
    })
    assert public == {"slug": "tianshu-deepseek-v4-flash"}


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
