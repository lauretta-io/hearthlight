from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from hearthlight.workspace import DEFAULT_WORKSPACE_PATH, load_user_config, resolve_workspace

APP_TITLE = "Hearthlight Manager"


def resolve_dashboard_url(workspace_text: str) -> str:
    workspace = Path(workspace_text).expanduser()
    env_path = workspace / ".env"
    port = "3000"
    if env_path.exists():
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "WEBAPP_UI_HOST_PORT":
                cleaned = value.strip().strip('"').strip("'")
                if cleaned:
                    port = cleaned
                break
    return f"http://localhost:{port}"


def resolve_helper_command() -> list[str]:
    if getattr(sys, "frozen", False):
        helper_path = Path(sys.executable).resolve().parent / "hearthlight-helper"
        if helper_path.exists():
            return [str(helper_path)]
    return [sys.executable, "-m", "hearthlight"]


class HearthlightManagerApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("980x640")
        self.root.minsize(860, 520)

        self.output_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.busy = False

        configured_workspace = resolve_workspace() or Path(
            load_user_config().get("default_workspace", DEFAULT_WORKSPACE_PATH)
        )
        self.workspace_var = tk.StringVar(value=str(configured_workspace))
        self.status_var = tk.StringVar(
            value="Ready. Install or update Hearthlight, then start the control plane."
        )

        self._build_ui()
        self.root.after(100, self._drain_output_queue)

    def _build_ui(self) -> None:
        tk = self.tk
        ttk = self.ttk

        container = ttk.Frame(self.root, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        header = ttk.Label(container, text=APP_TITLE, font=("Helvetica", 22, "bold"))
        header.pack(anchor="w")

        subtitle = ttk.Label(
            container,
            text=(
                "Packaged bootstrap manager for onboarding, Docker infrastructure, "
                "database reset, and control-plane startup."
            ),
            wraplength=820,
        )
        subtitle.pack(anchor="w", pady=(6, 14))

        workspace_frame = ttk.LabelFrame(container, text="Workspace", padding=12)
        workspace_frame.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(workspace_frame, text="Managed checkout path").grid(row=0, column=0, sticky="w")
        workspace_entry = ttk.Entry(workspace_frame, textvariable=self.workspace_var, width=84)
        workspace_entry.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        workspace_frame.columnconfigure(0, weight=1)

        actions = ttk.LabelFrame(container, text="Actions", padding=12)
        actions.pack(fill=tk.X, pady=(0, 12))

        self.install_button = ttk.Button(
            actions,
            text="Install / Update Hearthlight",
            command=lambda: self._run_command(
                [
                    "onboard",
                    "--yes",
                    "--target-dir",
                    self.workspace_var.get().strip(),
                    "--start-webapp",
                ],
                banner="Installing or updating Hearthlight",
            ),
        )
        self.install_button.grid(row=0, column=0, padx=(0, 8), pady=(0, 8), sticky="ew")

        self.start_button = ttk.Button(
            actions,
            text="Start Full System",
            command=lambda: self._run_command(
                [
                    "start",
                    "--workspace",
                    self.workspace_var.get().strip(),
                    "--open-dashboard",
                ],
                banner="Starting full system",
            ),
        )
        self.start_button.grid(row=0, column=1, padx=(0, 8), pady=(0, 8), sticky="ew")

        self.stop_button = ttk.Button(
            actions,
            text="Stop Services",
            command=lambda: self._run_command(
                ["stop", "--workspace", self.workspace_var.get().strip()],
                banner="Stopping services",
            ),
        )
        self.stop_button.grid(row=0, column=2, pady=(0, 8), sticky="ew")

        self.reset_button = ttk.Button(
            actions,
            text="Reset Database",
            command=lambda: self._run_command(
                ["reset-db", "--docker", "--workspace", self.workspace_var.get().strip()],
                banner="Resetting database",
            ),
        )
        self.reset_button.grid(row=1, column=0, padx=(0, 8), sticky="ew")

        self.status_button = ttk.Button(
            actions,
            text="Show Status",
            command=lambda: self._run_command(
                ["status", "--workspace", self.workspace_var.get().strip()],
                banner="Querying service status",
            ),
        )
        self.status_button.grid(row=1, column=1, padx=(0, 8), sticky="ew")

        self.dashboard_button = ttk.Button(
            actions,
            text="Open Dashboard",
            command=self._open_dashboard,
        )
        self.dashboard_button.grid(row=1, column=2, sticky="ew")

        for column in range(3):
            actions.columnconfigure(column, weight=1)

        status_frame = ttk.Frame(container)
        status_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(status_frame, text="Status:", font=("Helvetica", 11, "bold")).pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.status_var, wraplength=780).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        output_frame = ttk.LabelFrame(container, text="Logs / Output", padding=12)
        output_frame.pack(fill=tk.BOTH, expand=True)

        self.output_text = tk.Text(output_frame, wrap="word", height=22)
        self.output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.output_text.configure(state=tk.DISABLED)

        scrollbar = ttk.Scrollbar(output_frame, command=self.output_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.output_text.configure(yscrollcommand=scrollbar.set)

    def _append_output(self, text: str) -> None:
        self.output_text.configure(state=self.tk.NORMAL)
        self.output_text.insert(self.tk.END, text)
        self.output_text.see(self.tk.END)
        self.output_text.configure(state=self.tk.DISABLED)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = self.tk.DISABLED if busy else self.tk.NORMAL
        for button in (
            self.install_button,
            self.start_button,
            self.stop_button,
            self.reset_button,
            self.status_button,
        ):
            button.configure(state=state)

    def _run_command(self, args: list[str], *, banner: str) -> None:
        workspace = self.workspace_var.get().strip()
        if not workspace:
            self.status_var.set("Workspace path is required.")
            return
        if self.busy:
            self.status_var.set("A command is already running.")
            return

        self._set_busy(True)
        self.status_var.set(banner + "...")
        self._append_output(f"\n== {banner} ==\n")

        def worker() -> None:
            command = resolve_helper_command() + args
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=os.environ.copy(),
            )
            assert process.stdout is not None
            for line in process.stdout:
                self.output_queue.put(("line", line))
            return_code = process.wait()
            self.output_queue.put(("done", str(return_code)))

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _open_dashboard(self) -> None:
        webbrowser.open(resolve_dashboard_url(self.workspace_var.get().strip()))
        self.status_var.set("Opened dashboard in the default browser.")

    def _drain_output_queue(self) -> None:
        try:
            while True:
                message_type, payload = self.output_queue.get_nowait()
                if message_type == "line":
                    self._append_output(payload)
                elif message_type == "done":
                    code = int(payload)
                    if code == 0:
                        self.status_var.set("Command completed successfully.")
                    else:
                        self.status_var.set(f"Command failed with exit code {code}.")
                    self._append_output(f"\n[exit {code}]\n")
                    self._set_busy(False)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._drain_output_queue)


def main() -> None:
    import tkinter as tk

    root = tk.Tk()
    HearthlightManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
