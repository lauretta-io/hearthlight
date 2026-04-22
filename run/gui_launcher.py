import subprocess
import sys
import threading
import webbrowser

import tkinter as tk
from tkinter import font
import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, X

RUNNER = [sys.executable, "-m", "hearthlight"]


class RunGUI:
    def __init__(self, master):
        self.master = master
        master.title("Hearthlight Manager")
        self.custom_font = font.Font(family="Arial", size=14)
        self.process = None

        self.main_frame = ttk.Frame(master)
        self.main_frame.pack(padx=10, pady=10, fill=BOTH, expand=True)

        self.run_button = ttk.Button(
            self.main_frame,
            text="Run (CLI Interactive)",
            command=self.run_hearthlight,
            bootstyle="success",
        )
        self.run_button.pack(pady=(0, 5), fill=X)

        self.open_localhost_button = ttk.Button(
            self.main_frame,
            text="Open Dashboard",
            command=self.open_dashboard,
            bootstyle="info",
        )
        self.open_localhost_button.pack(pady=(5, 10), fill=X)

        self.stop_button = ttk.Button(
            self.main_frame,
            text="Stop",
            command=self.stop_hearthlight,
            state="disabled",
            bootstyle="danger",
        )
        self.stop_button.pack(fill=X)

        self.close_button = ttk.Button(
            self.main_frame,
            text="Close",
            command=self.close_program,
            bootstyle="secondary",
            state="normal",
        )
        self.close_button.pack(pady=(5, 0), fill=X)

        self.terminal_label = ttk.Label(self.main_frame, text="Console Output")
        self.terminal_label.pack(pady=(10, 0))

        self.terminal_output = tk.Text(self.main_frame, font=self.custom_font)
        self.terminal_output.pack(pady=(10, 0), fill=BOTH, expand=True)

    def _stream_pipe(self, pipe):
        for line in iter(pipe.readline, ""):
            self.terminal_output.insert(tk.END, line)
            self.terminal_output.see(tk.END)
            self.terminal_output.update_idletasks()

    def run_hearthlight(self):
        command = RUNNER + ["start", "--open-dashboard"]
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        threading.Thread(target=self._stream_pipe, args=(self.process.stdout,), daemon=True).start()
        threading.Thread(target=self._stream_pipe, args=(self.process.stderr,), daemon=True).start()
        self.run_button.config(state="disabled", text="Running")
        self.stop_button.config(state="normal")
        self.close_button.config(state="disabled")

    def open_dashboard(self):
        webbrowser.open("http://localhost:3000")

    def stop_hearthlight(self):
        process = subprocess.Popen(
            RUNNER + ["stop"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        threading.Thread(target=self._stream_pipe, args=(process.stdout,), daemon=True).start()
        threading.Thread(target=self._stream_pipe, args=(process.stderr,), daemon=True).start()

        def wait_and_reset():
            process.wait()
            self.run_button.config(state="normal", text="Run (CLI Interactive)")
            self.stop_button.config(state="disabled")
            self.close_button.config(state="normal")

        threading.Thread(target=wait_and_reset, daemon=True).start()

    def close_program(self):
        self.master.destroy()


def main():
    root = ttk.Window(themename="flatly")
    root.protocol("WM_DELETE_WINDOW", lambda: None)
    root.geometry("1500x600")
    root.resizable(True, True)
    RunGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
