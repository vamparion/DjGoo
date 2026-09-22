from __future__ import annotations

from typing import Any

from voice.command_acceptance import (
    AuthenticatedCommandProcessor,
    CommandRejected,
)
from voice.operational_log import log_event
from voice.relay_crypto import (
    RelayHostIdentity,
    decrypt_request,
    encrypt_response,
)


async def handle_host_envelope(
    identity: RelayHostIdentity,
    processor: AuthenticatedCommandProcessor,
    envelope: dict[str, Any],
) -> dict[str, Any]:
    """Decrypt, authorize, execute, and encrypt one relay request."""

    room_id = str(envelope.get("room_id") or "")
    request_id = str(envelope.get("request_id") or "")
    if room_id != identity.room_id:
        raise ValueError("Relay request targeted the wrong Host room")
    plaintext, client_public_key = decrypt_request(
        identity.encryption_private_key,
        envelope,
    )
    action = str(plaintext.get("action") or "")
    payload = plaintext.get("payload")
    if not isinstance(payload, dict):
        payload = {}

    try:
        if action == "pair":
            result = await processor.redeem_pairing(
                str(payload.get("code") or ""),
                str(payload.get("device_name") or "DjGoo Voice Remote"),
            )
        elif action == "command":
            result = await processor.accept(
                str(payload.get("device_token") or ""),
                payload,
            )
        elif action == "status":
            result = await processor.status(
                str(payload.get("device_token") or ""),
            )
        elif action == "web/state":
            result = await processor.remote_state(
                str(payload.get("device_token") or ""),
            )
        else:
            raise CommandRejected(400, "Unknown relay action")
        response_plaintext = {"ok": True, "status": 200, "result": result}
    except CommandRejected as error:
        response_plaintext = {
            "ok": False,
            "status": error.status,
            "error": error.message,
        }
    except Exception as exc:
        log_event(
            "voice.relay.host.request_failed",
            request_id=request_id,
            action=action,
            error=type(exc).__name__,
            detail=str(exc),
        )
        response_plaintext = {
            "ok": False,
            "status": 500,
            "error": "Host could not process the encrypted request",
        }
    return encrypt_response(
        client_public_key,
        identity.room_id,
        request_id,
        response_plaintext,
    )
