"""Offline checks of the v1.0.0 R2 ticket client."""

from __future__ import annotations

import json

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from znepro import PATH_CLIENT_TASK_COMMIT, PATH_CLIENT_TASK_INIT, ZNEProClient, open_envelope, seal_envelope

_TICKET_KEY = "ab" * 32


def test_single_run_payload_omits_calibration_and_scales() -> None:
    raw = ZNEProClient.build_job_json(
        "OPENQASM 2.0;\nqreg q[1];\nh q[0];\n",
        {"0": 2100, "1": 1900},
        observable="Z",
        shots=4000,
        calibration=None,
    )
    body = json.loads(raw)
    assert "hardware_calibration" not in body
    assert "hardware_scales" not in body
    assert body["shots"]["0"] == 2100
    assert sum(body["shots"].values()) == 4000


def test_seal_round_trip_matches_aesgcm() -> None:
    key = bytes(range(32))
    nonce = b"abcdefghijkl"
    plain = b'{"qasm":"OPENQASM 2.0;","shots":{"0":1}}'
    sealed = seal_envelope(plain, key.hex(), nonce=nonce)
    assert sealed == nonce + AESGCM(key).encrypt(nonce, plain, None)
    assert open_envelope(sealed, key) == plain
    damaged = bytearray(sealed)
    damaged[-1] ^= 0xFF
    try:
        open_envelope(bytes(damaged), key)
    except InvalidTag:
        return
    raise AssertionError("flipped tag was accepted")


def test_ticket_routes_round_trip_with_a_fake_transport() -> None:
    calls: list[str] = []
    put_url = "https://example-r2.cloudflarestorage.com/bucket/in?X-Amz-Signature=putsig"
    get_url = "https://example-r2.cloudflarestorage.com/bucket/out?X-Amz-Signature=getsig"

    def transport(method, url, body, headers, timeout):
        calls.append(f"{method} {url}")
        lowered = {str(key).lower(): value for key, value in headers.items()}
        assert timeout > 0
        if url.endswith(PATH_CLIENT_TASK_INIT):
            assert lowered["authorization"] == "Bearer test-key"
            return 200, json.dumps({
                "task_id": "task-demo",
                "upload_presigned_url": put_url,
                "output_presigned_url": get_url,
                "encryption_key_hex": _TICKET_KEY,
            }).encode()
        if url == put_url:
            assert "authorization" not in lowered
            assert lowered.get("user-agent") == "znepro-sdk/1.0.2"
            assert "content-type" not in lowered
            uploaded = json.loads(open_envelope(body, _TICKET_KEY))
            assert uploaded["shots"]["0"] == 3000
            assert uploaded["backend_name"] == "superconducting"
            return 200, b""
        if url.endswith(PATH_CLIENT_TASK_COMMIT):
            assert lowered["authorization"] == "Bearer test-key"
            sent = json.loads(body.decode())
            assert sent["task_id"] == "task-demo"
            return 200, json.dumps({"status": "QUEUED"}).encode()
        if url == get_url:
            assert "authorization" not in lowered
            receipt = json.dumps({
                "status": "COMPLETED",
                "task_id": "task-demo",
                "metrics": {"mitigated_expectation": 0.5, "unmitigated_expectation": 0.4},
            }).encode()
            return 200, seal_envelope(receipt, _TICKET_KEY, nonce=b"0123456789ab")
        raise AssertionError(url)

    client = ZNEProClient(api_key="test-key", transport=transport, timeout_s=5)
    result = client.submit_job(
        "OPENQASM 2.0;\nqreg q[1];\nh q[0];\n",
        {"0": 3000, "1": 1000},
        observable="Z",
        shots=4000,
    )
    assert result["metrics"]["mitigated_expectation"] == 0.5
    assert any(PATH_CLIENT_TASK_INIT in call for call in calls)
    assert any(PATH_CLIENT_TASK_COMMIT in call for call in calls)
