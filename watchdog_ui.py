import tkinter as tk
from tkinter import ttk
import sounddevice as sd
import numpy as np
import subprocess
import threading
import time
import pystray
import os, traceback
from PIL import Image, ImageDraw
from tkinter import messagebox

SAMPLE_RATE = 44100
BLOCK_SIZE = 1024

class MicWatchdog:
    def __init__(self, root):
        
        self.root = root
        root.title("Mic Loudness Watchdog")
        root.geometry("420x460")
        root.resizable(False, False)

        self.running = False
        self.last_trigger = 0
        self.stream = None
        self.current_db = -999

        tk.Label(root, text="Select Microphone").pack(pady=(15, 0))
        self.devices = self.get_input_devices()
        self.device_var = tk.StringVar()
        self.device_dropdown = ttk.Combobox(
            root, textvariable=self.device_var,
            values=[d["label"] for d in self.devices],
            state="readonly", width=45
        )
        if self.devices:
            self.device_dropdown.current(0)
        self.device_dropdown.pack(pady=5)

        tk.Button(root, text="Refresh Devices", command=self.refresh_devices).pack()

        # Threshold slider
        tk.Label(root, text="Trigger Threshold (dB)").pack(pady=(15, 0))
        self.threshold_var = tk.DoubleVar(value=-10)
        self.threshold_slider = tk.Scale(
            root, from_=-60, to=0, orient="horizontal",
            variable=self.threshold_var, length=350
        )
        self.threshold_slider.pack()

        # Cooldown
        tk.Label(root, text="Cooldown (seconds)").pack(pady=(10, 0))
        self.cooldown_var = tk.DoubleVar(value=5)
        tk.Scale(root, from_=1, to=30, orient="horizontal",
        variable=self.cooldown_var, length=350).pack()

        # Target process
        tk.Label(root, text="Target process (e.g. notepad.exe)").pack(pady=(10, 0))
        self.target_var = tk.StringVar(value="RobloxPlayerBeta.exe")
        tk.Entry(root, textvariable=self.target_var, width=40).pack()

        # Live meter
        tk.Label(root, text="Live Mic Level").pack(pady=(15, 0))
        self.meter = ttk.Progressbar(root, length=350, maximum=60)
        self.meter.pack(pady=5)
        self.db_label = tk.Label(root, text="-- dB")
        self.db_label.pack()

        # Start/Stop
        self.toggle_btn = tk.Button(root, text="Start Listening", command=self.toggle, width=20)
        self.toggle_btn.pack(pady=15)

        # Log
        self.log = tk.Text(root, height=6, width=48, state="disabled")
        self.log.pack()

        root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.root.after(300, self.auto_start)

    def log_msg(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')} - {msg}\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def rms_to_db(self, block):
        rms = np.sqrt(np.mean(block**2))
        if rms == 0:
            return -999
        return 20 * np.log10(rms)

    def audio_callback(self, indata, frames, time_info, status):
        db = self.rms_to_db(indata)
        self.current_db = db
        now = time.time()

        if db >= self.threshold_var.get() and (now - self.last_trigger) > self.cooldown_var.get():
            self.last_trigger = now
            self.root.after(0, self.trigger_action, db)

    def trigger_action(self, db):
        target = self.target_var.get().strip()
        self.log_msg(f"Threshold hit ({db:.1f} dB) — closing {target}")
        try:
            subprocess.run(
                ["taskkill", "/IM", target, "/F"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            messagebox.showinfo("Hi Zaren", f"Maingay ka masyado.")
        except Exception as e:
            self.log_msg(f"Error: {e}")

    def update_meter(self):
        if self.running:
            display_db = max(self.current_db, -60)
            self.meter["value"] = display_db + 60  # shift range to 0-60
            self.db_label.config(text=f"{self.current_db:.1f} dB")
        self.root.after(100, self.update_meter)

    def auto_start(self):
        if not self.running:
            self.toggle()

    def toggle(self):
        if not self.running:
            self.running = True
            self.toggle_btn.config(text="Stop Listening")
            self.stream = sd.InputStream(
                device=self.get_selected_device_index(),
                callback=self.audio_callback,
                channels=1,
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE
            )
            self.stream.start()
            self.log_msg("Started listening")
        else:
            self.running = False
            self.toggle_btn.config(text="Start Listening")
            if self.stream:
                self.stream.stop()
                self.stream.close()
            self.log_msg("Stopped listening")

    def get_input_devices(self):
        devices = []
        seen_names = set()
        try:
            all_devices = sd.query_devices()
            for i, d in enumerate(all_devices):
                if d.get("max_input_channels", 0) <= 0:
                    continue

                name = d.get("name", "").strip()
                normalized_name = name.lower()

                exclude_patterns = [
                    "sound mapper",
                    "primary sound",
                    "output",
                    "speaker",
                    "headphone",
                    "line out",
                    "cable in 16ch",
                ]
                if any(pattern in normalized_name for pattern in exclude_patterns):
                    continue

                include_patterns = [
                    "microphone",
                    "mic",
                    "voicemod",
                    "input",
                ]
                if not any(pattern in normalized_name for pattern in include_patterns):
                    continue

                simplified_name = normalized_name.replace("(r)", "").replace("realtek", "").replace("audio", "").replace("with sst", "").strip()
                if simplified_name in seen_names:
                    continue
                seen_names.add(simplified_name)

                devices.append({
                    "index": i,
                    "name": name,
                    "label": f"{i}: {name}"
                })
        except Exception as e:
            print(f"Error querying devices: {e}")
        return devices

    def refresh_devices(self):
        self.devices = self.get_input_devices()
        self.device_dropdown["values"] = [d["label"] for d in self.devices]
        if self.devices:
            self.device_dropdown.current(0)

    def get_selected_device_index(self):
        idx = self.device_dropdown.current()
        if idx == -1 or not self.devices:
            return None
        return self.devices[idx]["index"]

    def create_tray_icon(self):
        img = Image.new("RGB", (64, 64), "black")
        d = ImageDraw.Draw(img)
        d.ellipse((16, 16, 48, 48), fill="white")
        menu = pystray.Menu(
            pystray.MenuItem("Show", self.show_window),
            pystray.MenuItem("Quit", self.quit_app)
        )
        self.tray_icon = pystray.Icon("MicWatchdog", img, "Mic Watchdog", menu)

    def hide_to_tray(self):
        self.root.withdraw()
        self.create_tray_icon()
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window(self, icon=None, item=None):
        self.tray_icon.stop()
        self.root.after(0, self.root.deiconify)

    def quit_app(self, icon=None, item=None):
        self.tray_icon.stop()
        self.root.after(0, self.root.destroy)

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = MicWatchdog(root)
        app.update_meter()
        root.mainloop()
    except Exception:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "error_log.txt")
        with open(log_path, "w") as f:
            traceback.print_exc(file=f)