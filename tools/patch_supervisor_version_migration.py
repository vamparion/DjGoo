from pathlib import Path


launcher = Path("launcher/djgoo_launcher.py")
text = launcher.read_text(encoding="utf-8")
import_anchor = "from tools.portable_environment import portable_environment\n"
import_line = "from tools.supervisor_lifecycle import restart_stale_supervisor\n"
if import_line not in text:
    if import_anchor not in text:
        raise SystemExit("launcher import anchor missing")
    text = text.replace(import_anchor, import_anchor + import_line, 1)

init_old = "        self._build()\n        self._report_update_result()\n        self.refresh_status()\n"
init_new = "        self._build()\n        self._report_update_result()\n        self._replace_stale_supervisor()\n        self.refresh_status()\n"
if init_old in text:
    text = text.replace(init_old, init_new, 1)
elif init_new not in text:
    raise SystemExit("launcher init anchor missing")

method_anchor = "    def _build(self) -> None:\n"
method = '''    def _replace_stale_supervisor(self) -> None:
        version = read_installed_version(self.layout.root).text
        try:
            replaced = restart_stale_supervisor(
                self.layout.root,
                installed_version=version,
                runtime_python=self.layout.runtime_python,
                runtime_pythonw=self.layout.runtime_pythonw,
                stack_script=self.layout.stack_script,
                environment=self._environment(),
                log=self.log,
            )
        except BaseException as exc:
            self.log(f"Could not replace the stale supervisor: {exc}")
            messagebox.showerror(
                APP_NAME,
                "DjGoo updated its files but could not restart the old background supervisor.\\n\\n"
                f"{exc}",
            )
            return
        if replaced:
            self._requested_desired = None
            self._requested_at = 0.0

'''
if "def _replace_stale_supervisor" not in text:
    if method_anchor not in text:
        raise SystemExit("launcher method anchor missing")
    text = text.replace(method_anchor, method + method_anchor, 1)
launcher.write_text(text, encoding="utf-8")

stack = Path("tools/djgoo_stack.py")
text = stack.read_text(encoding="utf-8")
class_anchor = "class SupervisorState:\n"
version_helper = '''def installed_version_text() -> str:
    try:
        payload = json.loads(
            (PROJECT_ROOT / "data" / "installed-version.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return "development"
    if not isinstance(payload, dict):
        return "development"
    return str(payload.get("version") or "development").strip() or "development"


'''
if "def installed_version_text" not in text:
    if class_anchor not in text:
        raise SystemExit("supervisor class anchor missing")
    text = text.replace(class_anchor, version_helper + class_anchor, 1)

state_old = "        self.started_at = time.time()\n        self.component_status: dict[str, dict[str, Any]] = {}\n"
state_new = "        self.started_at = time.time()\n        self.version = installed_version_text()\n        self.component_status: dict[str, dict[str, Any]] = {}\n"
if state_old in text:
    text = text.replace(state_old, state_new, 1)
elif state_new not in text:
    raise SystemExit("supervisor state anchor missing")

snapshot_old = '                "started_at": self.started_at,\n                "components": self.component_status,\n'
snapshot_new = '                "started_at": self.started_at,\n                "supervisor_version": self.version,\n                "components": self.component_status,\n'
if snapshot_old in text:
    text = text.replace(snapshot_old, snapshot_new, 1)
elif snapshot_new not in text:
    raise SystemExit("supervisor snapshot anchor missing")

pid_old = '            "project_root": str(PROJECT_ROOT),\n'
pid_new = '            "project_root": str(PROJECT_ROOT),\n            "version": STATE.version,\n'
if pid_old in text:
    text = text.replace(pid_old, pid_new, 1)
elif pid_new not in text:
    raise SystemExit("supervisor PID anchor missing")
stack.write_text(text, encoding="utf-8")

updater = Path("tools/apply_update.py")
text = updater.read_text(encoding="utf-8")
function_anchor = "def stack_was_running(root: Path) -> bool:\n"
function = '''def recorded_supervisor_pid(root: Path) -> int:
    for path in (
        root / "data" / "pids" / "supervisor.json",
        root / "data" / "djgoo-supervisor-state.json",
    ):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        try:
            pid = int(payload.get("pid") or payload.get("supervisor_pid") or 0)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            return pid
    return 0


'''
if "def recorded_supervisor_pid" not in text:
    if function_anchor not in text:
        raise SystemExit("updater function anchor missing")
    text = text.replace(function_anchor, function + function_anchor, 1)

update_old = '''    resume_stack = stack_was_running(root)
    invoke_stack(root, "stop", log)
    try:
'''
update_new = '''    resume_stack = stack_was_running(root)
    supervisor_pid = recorded_supervisor_pid(root)
    invoke_stack(root, "shutdown", log)
    if supervisor_pid:
        wait_for_process_exit(supervisor_pid, timeout=PARENT_EXIT_TIMEOUT_SECONDS)
        log(f"Supervisor PID {supervisor_pid} exited before file replacement.")
    try:
'''
if update_old in text:
    text = text.replace(update_old, update_new, 1)
elif update_new not in text:
    raise SystemExit("updater shutdown anchor missing")
updater.write_text(text, encoding="utf-8")
