from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from tkinter import LEFT, X, Frame, Label, StringVar, messagebox

from tools.app_layout import active_app_root, package_root, runtime_python
from tools.cleanup_legacy_layout import cleanup_legacy_layout


def main() -> int:
    root = package_root(Path(__file__).resolve().parents[1])
    app = active_app_root(root)
    os.environ["DJGOO_HOME"] = str(root)
    os.environ["DJGOO_APP_ROOT"] = str(app)
    cleanup_legacy_layout(root)

    import launcher.djgoo_launcher as base

    @dataclass(frozen=True)
    class LayeredLayout(base.Layout):
        @property
        def app_root(self) -> Path:
            return active_app_root(self.root)

        @property
        def runtime_python(self) -> Path:
            return runtime_python(self.root, "host")

        @property
        def runtime_pythonw(self) -> Path:
            return runtime_python(self.root, "host", windowed=True)

        @property
        def stack_script(self) -> Path:
            return self.app_root / "tools" / "djgoo_portable_stack_entry.py"

        @property
        def setup_script(self) -> Path:
            return self.app_root / "tools" / "portable_red_setup.py"

        @property
        def bot_console_script(self) -> Path:
            return self.app_root / "tools" / "layered_redbot_selector.py"

        @property
        def update_worker(self) -> Path:
            return self.app_root / "tools" / "layered_apply_update.py"

    base.application_root = lambda: root
    base.Layout = LayeredLayout

    import launcher.djgoo_host_experience as experience

    experience.application_root = lambda: root
    experience.Layout = LayeredLayout

    import launcher.djgoo_host_control_center as control
    from tools.layered_stack import host_speech_available
    from tools.speech_runtime import install_speech_runtime

    class LayeredHostControlCenter(control.DjGooHostControlCenter):
        def __init__(self, window, layout) -> None:
            self._speech_busy = False
            self._speech_status = StringVar(window, value="Checking local voice runtime…")
            super().__init__(window, layout)

        def _build(self) -> None:
            super()._build()
            ready = host_speech_available(self.layout.root)
            self._speech_status.set(
                "Local voice recognition is installed."
                if ready
                else "Local voice recognition is optional and not installed."
            )
            panel = Frame(self.root, bg=control.PANEL, padx=16, pady=10)
            panel.pack(fill=X, padx=20, pady=(0, 10), before=self.activity)
            Label(
                panel,
                textvariable=self._speech_status,
                bg=control.PANEL,
                fg=control.GOOD if ready else control.MUTED,
            ).pack(side=LEFT)
            self._speech_button = self._button(
                panel,
                "Install local voice" if not ready else "Repair local voice",
                self.install_local_voice,
                accent=not ready,
            )
            self._speech_button.pack(side=LEFT, padx=(12, 0))

        def install_local_voice(self) -> None:
            if self._speech_busy:
                return
            if self._redbot_or_stack_active():
                messagebox.showwarning(
                    "DjGoo",
                    "Stop DjGoo before installing or repairing the local voice runtime.",
                    parent=self.root,
                )
                return
            self._speech_busy = True
            self._speech_button.configure(state="disabled")
            self._speech_status.set("Downloading and verifying local voice runtime…")
            self.log("Installing the optional shared speech-recognition layer…")
            threading.Thread(
                target=self._install_speech_worker,
                name="djgoo-speech-runtime-install",
                daemon=True,
            ).start()

        def _install_speech_worker(self) -> None:
            try:
                install_speech_runtime(self.layout.root)
            except Exception as exc:
                self.root.after(0, lambda problem=exc: self._speech_finished(problem))
                return
            self.root.after(0, lambda: self._speech_finished(None))

        def _speech_finished(self, error: Exception | None) -> None:
            self._speech_busy = False
            self._speech_button.configure(state="normal")
            if error is not None:
                self._speech_status.set("Local voice runtime installation failed.")
                self.log(f"Local voice runtime failed: {type(error).__name__}: {error}")
                messagebox.showerror("DjGoo", str(error), parent=self.root)
                return
            self._speech_status.set("Local voice recognition is installed.")
            self._speech_button.configure(text="Repair local voice")
            self.log("Local voice runtime installed and verified.")
            messagebox.showinfo(
                "DjGoo",
                "Local voice recognition is ready. Select Start to launch DjGoo with Host voice control.",
                parent=self.root,
            )

    control.application_root = lambda: root
    control.Layout = LayeredLayout
    control.DjGooHostControlCenter = LayeredHostControlCenter
    return int(control.main())


if __name__ == "__main__":
    raise SystemExit(main())
