from pathlib import Path

path = Path("tools/djgoo_portable_stack.py")
text = path.read_text(encoding="utf-8")
old = '''    if heartbeat.get("ready") is not True:
        return False
    if heartbeat.get("audio_loaded") is not True or heartbeat.get("discord_ready") is not True:
        return False

    max_age = 120.0 if heartbeat.get("event") == "redbot.ready" else 15.0
    return -5.0 <= age <= max_age
'''
new = '''    if heartbeat.get("ready") is not True:
        return False
    if heartbeat.get("audio_loaded") is not True or heartbeat.get("discord_ready") is not True:
        return False
    if not _lavalink_port_ready():
        return False

    max_age = 120.0 if heartbeat.get("event") == "redbot.ready" else 15.0
    return -5.0 <= age <= max_age
'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("portable Redbot readiness anchor missing")
path.write_text(text, encoding="utf-8")
