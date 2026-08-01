from __future__ import annotations

import argparse
import asyncio
import math
import sys
from pathlib import Path

from faster_whisper import WhisperModel

from voice.audio_capture import PushToTalkAudioCapture, audio_metrics, prepare_for_whisper
from voice.command_parser import parse_command
from voice.command_queue import command_to_queue_item
from voice.connection_manager import load_recipient_transport, pair_from_invite
from voice.corrections import apply_corrections, correction_hotwords, load_corrections
from voice.djgoo_voice_listener import (
    HotkeyWaiter,
    feedback_sound,
    input_device_summary,
    resolve_input_device,
    transcribe,
)
from voice.listener_settings import voice_settings
from voice.operational_log import log_event
from voice.pairing_bundle import build_invite, parse_invite


def remote_config_path(project_root: Path) -> Path:
    return project_root / "data" / "voice-remote-credential.json"


def load_remote_settings(project_root: Path) -> dict:
    import json

    path = project_root / "config" / "voice-remote.json"
    if not path.exists():
        return voice_settings({}, project_root)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config/voice-remote.json must contain a JSON object")
    voice_config = data.get("voice") if isinstance(data.get("voice"), dict) else data
    return voice_settings(voice_config, project_root)


async def pair_device(project_root: Path, invite_text: str, device_name: str) -> None:
    invite = parse_invite(invite_text)
    credential, selected_transport = await pair_from_invite(
        invite,
        device_name=device_name,
        credential_path=remote_config_path(project_root),
    )
    print(
        f"Paired through {selected_transport} as Discord user {credential.discord_user_id} "
        f"in server {credential.guild_id}. Device ID: {credential.device_id}",
        flush=True,
    )


def run_remote(project_root: Path) -> None:
    credential_path = remote_config_path(project_root)
    if not credential_path.exists():
        raise RuntimeError(
            "This DjGoo Voice device is not paired. Paste a DjGoo Link invite first."
        )
    transport = load_recipient_transport(credential_path)
    credential = transport.credential
    settings = load_remote_settings(project_root)
    input_device = resolve_input_device(settings["input_device"])
    corrections = load_corrections(project_root, settings["corrections"])
    dynamic_hotwords = " ".join(
        part
        for part in (settings["hotwords"], correction_hotwords(corrections))
        if part.strip()
    )

    log_event(
        "voice.remote.starting",
        device_id=credential.device_id,
        guild_id=credential.guild_id,
        transport=credential.transport,
        model=settings["model_name"],
        device=settings["device"],
        compute_type=settings["compute_type"],
        hotkey=settings["hotkey"],
        input_device=input_device_summary(input_device),
    )
    print(
        f"Loading speech model {settings['model_name']} "
        f"({settings['device']}/{settings['compute_type']})...",
        flush=True,
    )
    model_kwargs = {
        "device": settings["device"],
        "compute_type": settings["compute_type"],
    }
    if settings["cpu_threads"] > 0:
        model_kwargs["cpu_threads"] = settings["cpu_threads"]
    model = WhisperModel(settings["model_name"], **model_kwargs)
    waiter = HotkeyWaiter(
        settings["hotkey"],
        poll_seconds=settings["hotkey_poll_seconds"],
    )

    with PushToTalkAudioCapture(
        device=input_device,
        block_seconds=settings["block_seconds"],
        preroll_seconds=settings["preroll_seconds"],
        release_tail_seconds=settings["release_tail_seconds"],
    ) as capture:
        print(
            f"DjGoo Voice is ready. Hold {settings['hotkey']} while speaking.",
            flush=True,
        )
        log_event(
            "voice.remote.ready",
            device_id=credential.device_id,
            transport=credential.transport,
            sample_rate=capture.sample_rate,
        )
        while True:
            waiter.wait_for_press()
            raw_audio = waiter.capture_while_held(
                capture,
                min_seconds=settings["min_record_seconds"],
                max_seconds=settings["max_record_seconds"],
            )
            audio = prepare_for_whisper(raw_audio, capture.sample_rate)
            metrics = audio_metrics(audio, 16_000)
            if metrics.rms < settings["silence_rms_threshold"]:
                log_event("voice.remote.audio.too_quiet", rms=metrics.rms)
                feedback_sound("rejected", settings["feedback_beeps"])
                continue

            result = transcribe(
                model,
                audio,
                language=settings["language"],
                beam_size=settings["beam_size"],
                hotwords=dynamic_hotwords,
                initial_prompt=settings["initial_prompt"],
                vad_filter=settings["vad_filter"],
                vad_min_silence_ms=settings["vad_min_silence_ms"],
                vad_speech_pad_ms=settings["vad_speech_pad_ms"],
            )
            if not result.text:
                feedback_sound("rejected", settings["feedback_beeps"])
                continue
            if (
                result.avg_logprob < settings["min_avg_logprob"]
                or result.no_speech_prob > settings["max_no_speech_prob"]
            ):
                log_event(
                    "voice.remote.transcript.rejected",
                    avg_logprob=result.avg_logprob,
                    no_speech_prob=result.no_speech_prob,
                )
                feedback_sound("rejected", settings["feedback_beeps"])
                continue

            transcript = apply_corrections(result.text, corrections)
            command = parse_command(transcript, require_wake=False)
            if command.intent in {"ignore", "unknown"}:
                log_event("voice.remote.command.ignored", transcript=transcript)
                feedback_sound("rejected", settings["feedback_beeps"])
                continue

            item = command_to_queue_item(
                command,
                transcript=transcript,
                source="voice_remote",
            )
            item["confidence"] = round(math.exp(min(0.0, result.avg_logprob)), 4)
            try:
                response = transport.send(item)
            except Exception as exc:
                log_event(
                    "voice.remote.command.failed",
                    error=type(exc).__name__,
                    detail=str(exc),
                )
                print(f"Command failed: {exc}", file=sys.stderr, flush=True)
                feedback_sound("rejected", settings["feedback_beeps"])
                continue
            log_event(
                "voice.remote.command.accepted",
                command_id=response.get("command_id"),
                duplicate=response.get("duplicate", False),
                intent=command.intent,
            )
            feedback_sound("accepted", settings["feedback_beeps"])


def _legacy_direct_invite(args: argparse.Namespace) -> str:
    invite = build_invite(
        code=args.code,
        expires_at=4_102_444_800,
        direct_url=args.gateway,
        direct_fingerprint=args.fingerprint,
    )
    return invite.to_uri()


def main() -> int:
    parser = argparse.ArgumentParser(description="DjGoo Voice")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    pair_parser = subparsers.add_parser("pair")
    pair_parser.add_argument("--invite")
    pair_parser.add_argument("--device-name", default="DjGoo Voice")
    # Backward-compatible direct fields for existing packages and scripts.
    pair_parser.add_argument("--gateway")
    pair_parser.add_argument("--code")
    pair_parser.add_argument("--fingerprint")
    subparsers.add_parser("run")
    args = parser.parse_args()
    project_root = Path(args.project_root).resolve()

    if args.action == "pair":
        invite_text = str(args.invite or "").strip()
        if not invite_text:
            if not all((args.gateway, args.code, args.fingerprint)):
                pair_parser.error("--invite is required")
            invite_text = _legacy_direct_invite(args)
        asyncio.run(pair_device(project_root, invite_text, args.device_name))
        return 0
    if args.action == "run":
        run_remote(project_root)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
