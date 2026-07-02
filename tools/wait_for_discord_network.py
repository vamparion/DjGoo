from __future__ import annotations

import argparse
import socket
import sys
import time


HOSTS = ("discord.com", "gateway.discord.gg")


def can_resolve_and_connect(host: str, port: int, timeout_seconds: float) -> bool:
    try:
        addresses = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return False
    for _family, _socktype, _proto, _canonname, sockaddr in addresses:
        try:
            with socket.create_connection(sockaddr, timeout=timeout_seconds):
                return True
        except OSError:
            continue
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Wait until Discord DNS and TCP are usable.")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--stable-checks", type=int, default=2)
    args = parser.parse_args()

    deadline = time.monotonic() + args.timeout
    stable_checks = 0
    last_failure = "not checked"
    while time.monotonic() < deadline:
        failed_hosts = [host for host in HOSTS if not can_resolve_and_connect(host, 443, 4.0)]
        if not failed_hosts:
            stable_checks += 1
            if stable_checks >= args.stable_checks:
                print("Discord network is ready.", flush=True)
                return 0
        else:
            stable_checks = 0
            last_failure = ", ".join(failed_hosts)
            print(f"Waiting for Discord network: {last_failure}", flush=True)
        time.sleep(args.interval)

    print(f"Discord network was not ready before timeout: {last_failure}", file=sys.stderr, flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
