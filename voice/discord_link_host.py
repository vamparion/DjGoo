from __future__ import annotations

from typing import Any

from voice.command_acceptance import (
    AuthenticatedCommandProcessor,
    CommandRejected,
)
from voice.relay_crypto import (
    RelayHostIdentity,
    decrypt_request,
    encrypt_response,
)


class DiscordLinkHostProcessor:
    """Decrypt, authorize, and encrypt one Discord-hosted request."""

    def __init__(
        self,
        identity: RelayHostIdentity,
        commands: AuthenticatedCommandProcessor,
    ) -> None:
        self.identity = identity
        self.commands = commands

    async def handle(
        self,
        envelope: dict[str, Any],
        *,
        webhook_id: str,
    ) -> dict[str, Any]:
        room_id = str(envelope.get("room_id") or "")
        request_id = str(envelope.get("request_id") or "")
        if room_id != str(webhook_id):
            raise ValueError(
                "Discord Link request targeted the wrong webhook room"
            )
        plaintext, client_public_key = decrypt_request(
            self.identity.encryption_private_key,
            envelope,
        )
        action = str(plaintext.get("action") or "")
        payload = plaintext.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        try:
            if action == "pair":
                result = await self.commands.redeem_pairing(
                    str(payload.get("code") or ""),
                    str(
                        payload.get("device_name")
                        or "DjGoo Voice"
                    ),
                )
                status = 201
            elif action == "command":
                result = await self.commands.accept(
                    str(payload.get("device_token") or ""),
                    payload,
                )
                status = 202
            elif action == "status":
                result = await self.commands.status(
                    str(payload.get("device_token") or "")
                )
                status = 200
            else:
                raise CommandRejected(
                    400,
                    "Unknown Discord Link action",
                )
            response = {
                "ok": True,
                "status": status,
                "result": result,
            }
        except CommandRejected as exc:
            response = {
                "ok": False,
                "status": exc.status,
                "error": exc.message,
            }
        except Exception:
            response = {
                "ok": False,
                "status": 500,
                "error": "DjGoo Host could not process the encrypted request",
            }

        return encrypt_response(
            client_public_key,
            room_id,
            request_id,
            response,
        )
