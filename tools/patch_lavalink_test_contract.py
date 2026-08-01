from pathlib import Path

red_setup = Path("tests/test_portable_red_setup.py")
text = red_setup.read_text(encoding="utf-8")
old = '''    monkeypatch.setattr(
        start_redbot_selector,
        "apply_runtime_patches",
        lambda: calls.append("patch"),
    )
'''
new = '''    monkeypatch.setattr(
        start_redbot_selector,
        "apply_runtime_patches",
        lambda _root: calls.append("patch"),
    )
'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("portable Red setup test anchor missing")
red_setup.write_text(text, encoding="utf-8")

adapter_test = Path("tests/test_portable_stack_adapter.py")
text = adapter_test.read_text(encoding="utf-8")
old = '''    core.read_json = lambda path: heartbeat
    monkeypatch.setattr(adapter.time, "time", lambda: 1000.0)

    assert adapter._portable_redbot_ready(core) is True
'''
new = '''    core.read_json = lambda path: heartbeat
    monkeypatch.setattr(adapter.time, "time", lambda: 1000.0)
    monkeypatch.setattr(adapter, "_lavalink_port_ready", lambda: True)

    assert adapter._portable_redbot_ready(core) is True
'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("portable stack readiness test anchor missing")
adapter_test.write_text(text, encoding="utf-8")
