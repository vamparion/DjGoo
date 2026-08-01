from __future__ import annotations

import argparse
import asyncio
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace


READY_LINE = "Lavalink is ready to accept connections."
CLIENT_HOST = "[::1]"
PORT = 2333
PASSWORD = "youshallnotpass"


class FakeBot:
    def __init__(self) -> None:
        self.user = SimpleNamespace(id=1515225909861417111)
        self.shard_count = 1
        self._listeners: list[tuple[object, str | None]] = []

    def add_listener(self, callback, name: str | None = None) -> None:
        self._listeners.append((callback, name))

    def remove_listener(self, callback, name: str | None = None) -> None:
        try:
            self._listeners.remove((callback, name))
        except ValueError:
            pass


def _reader(stream, output: queue.Queue[str], captured: list[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            captured.append(line)
            output.put(line)
    finally:
        stream.close()


def wait_for_server(process: subprocess.Popen[str], timeout: float) -> list[str]:
    if process.stdout is None:
        raise RuntimeError("Lavalink stdout was not captured")
    lines: list[str] = []
    output: queue.Queue[str] = queue.Queue()
    thread = threading.Thread(
        target=_reader,
        args=(process.stdout, output, lines),
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Lavalink exited with code {process.returncode} before readiness.\n"
                + "".join(lines[-100:])
            )
        try:
            line = output.get(timeout=0.5)
        except queue.Empty:
            continue
        if READY_LINE in line:
            return lines
    raise TimeoutError(
        f"Lavalink did not become ready within {timeout:.0f} seconds.\n"
        + "".join(lines[-100:])
    )


async def verify_client_connection() -> None:
    import lavalink

    bot = FakeBot()
    node = None
    try:
        node = await lavalink.initialize(
            bot=bot,
            host=CLIENT_HOST,
            password=PASSWORD,
            port=PORT,
            timeout=30,
            resume_key="DjGoo-CI-contract-check",
            secured=False,
        )
        await node.wait_until_ready(timeout=10)
        if not node.ready:
            raise RuntimeError(f"Red-Lavalink node did not reach ready state: {node!r}")
        nodes = list(lavalink.get_all_nodes())
        if node not in nodes or not any(candidate.ready for candidate in nodes):
            raise RuntimeError("Red-Lavalink did not retain a ready node")
        print(
            "Red-Lavalink connection verified:",
            f"host={node.host}",
            f"port={node.port}",
            f"ready={node.ready}",
        )
    finally:
        if node is not None:
            await lavalink.close(bot)


def java_executable(root: Path) -> Path:
    for path in (
        root / "runtime" / "java" / "bin" / "java.exe",
        root / "runtime" / "java" / "bin" / "java",
    ):
        if path.is_file():
            return path
    raise FileNotFoundError("Bundled Java executable is missing")


def run(project_root: Path, timeout: float) -> None:
    root = project_root.resolve()
    audio_dir = root / "data" / "discordbot" / "cogs" / "Audio"
    jar = audio_dir / "Lavalink.jar"
    application = audio_dir / "application.yml"
    if not jar.is_file() or not application.is_file():
        raise FileNotFoundError("Packaged Lavalink.jar or application.yml is missing")

    command = [
        str(java_executable(root)),
        "-Xms64M",
        "-Xmx512M",
        "-jar",
        str(jar),
    ]
    process = subprocess.Popen(
        command,
        cwd=audio_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=os.environ.copy(),
    )
    try:
        wait_for_server(process, timeout)
        asyncio.run(verify_client_connection())
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start packaged Lavalink and verify a real Red-Lavalink WebSocket connection."
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()

    if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    run(args.project_root, args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
