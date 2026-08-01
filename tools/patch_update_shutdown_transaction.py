from pathlib import Path

path = Path("tools/apply_update.py")
text = path.read_text(encoding="utf-8")
old = '''    started_at = time.time()
    resume_stack = stack_was_running(root)
    supervisor_pid = recorded_supervisor_pid(root)
    invoke_stack(root, "shutdown", log)
    if supervisor_pid:
        wait_for_process_exit(supervisor_pid, timeout=PARENT_EXIT_TIMEOUT_SECONDS)
        log(f"Supervisor PID {supervisor_pid} exited before file replacement.")
    try:
        manifest = load_manifest(manifest_path)
'''
new = '''    started_at = time.time()
    resume_stack = stack_was_running(root)
    try:
        supervisor_pid = recorded_supervisor_pid(root)
        invoke_stack(root, "shutdown", log)
        if supervisor_pid:
            wait_for_process_exit(supervisor_pid, timeout=PARENT_EXIT_TIMEOUT_SECONDS)
            log(f"Supervisor PID {supervisor_pid} exited before file replacement.")
        manifest = load_manifest(manifest_path)
'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("updater transaction anchor missing")
path.write_text(text, encoding="utf-8")
