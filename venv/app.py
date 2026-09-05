import os
import sys
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import customtkinter as ctk
from tkinter import filedialog, messagebox

from prayer_calc import calculate_prayer_times, METHODS, ASR_FACTORS, PRAYER_ORDER
from online_source import fetch_online_times, EDMONTON_LAT, EDMONTON_LON
from custom_import import load_custom_schedule, get_times_for_date

APP_DIR = os.path.dirname(os.path.abspath(__file__))
EDMONTON_TZ = ZoneInfo("America/Edmonton")

DEFAULT_FAJR_ATHAN = os.path.join(APP_DIR, "athan_fajr.wav")
DEFAULT_OTHER_ATHAN = os.path.join(APP_DIR, "athan.wav")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")


def edmonton_utc_offset(d: date) -> float:
    """Correct UTC offset for Edmonton on a given date, DST included."""
    dt = datetime(d.year, d.month, d.day, 12, tzinfo=EDMONTON_TZ)  
    return dt.utcoffset().total_seconds() / 3600


def play_sound_file(path: str):
    """Play a .wav file asynchronously via Windows' built-in winsound."""
    if sys.platform.startswith("win"):
        try:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as exc:
            print(f"[audio error] {exc}")
    else:
        print(f"[would play athan sound here on Windows]: {path}")


class AthanApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Athan - Edmonton Prayer Times")
        self.geometry("680x660")
        self.minsize(620, 600)

        self.fajr_athan_path = DEFAULT_FAJR_ATHAN if os.path.exists(DEFAULT_FAJR_ATHAN) else ""
        self.other_athan_path = DEFAULT_OTHER_ATHAN if os.path.exists(DEFAULT_OTHER_ATHAN) else ""
        self.alarms_enabled = ctk.BooleanVar(value=True)
        self.custom_schedule = {}
        self.custom_schedule_name = ""
        self.today_times = {}
        self._computed_for = None
        self._last_triggered = None  

        self._build_ui()
        self.refresh_times()
        self.after(1000, self._tick)

   
    def _build_ui(self):
        
        self.grid_rowconfigure(3, weight=1)  
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(self, text="🕌  Athan — Edmonton, AB",
                               font=ctk.CTkFont(size=24, weight="bold"))
        header.grid(row=0, column=0, pady=(16, 4), sticky="ew")

        self.source_label = ctk.CTkLabel(self, text="Source: —", text_color="gray70",
                                          font=ctk.CTkFont(size=12))
        self.source_label.grid(row=1, column=0, pady=(0, 8), sticky="ew")

        # ----- Settings -----
        settings = ctk.CTkFrame(self)
        settings.grid(row=2, column=0, padx=12, pady=6, sticky="ew")
        settings.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(settings, text="Method:", anchor="w").grid(
            row=0, column=0, padx=(10, 6), pady=(10, 4), sticky="w")
        self.method_var = ctk.StringVar(value="ISNA (North America)")
        ctk.CTkOptionMenu(settings, values=list(METHODS.keys()), variable=self.method_var,
                           command=lambda _: self.refresh_times()).grid(
            row=0, column=1, padx=(0, 10), pady=(10, 4), sticky="ew")

        ctk.CTkLabel(settings, text="Asr calc:", anchor="w").grid(
            row=1, column=0, padx=(10, 6), pady=(4, 10), sticky="w")
        self.asr_var = ctk.StringVar(value="Standard (Shafi/Maliki/Hanbali)")
        ctk.CTkOptionMenu(settings, values=list(ASR_FACTORS.keys()), variable=self.asr_var,
                           command=lambda _: self.refresh_times()).grid(
            row=1, column=1, padx=(0, 10), pady=(4, 10), sticky="ew")

        self.cards_frame = ctk.CTkFrame(self)
        self.cards_frame.grid(row=3, column=0, padx=12, pady=6, sticky="nsew")
        self.card_labels = {}
        cols = 3
        for c in range(cols):
            self.cards_frame.grid_columnconfigure(c, weight=1)
        for r in range((len(PRAYER_ORDER) + cols - 1) // cols):
            self.cards_frame.grid_rowconfigure(r, weight=1)

        for i, name in enumerate(PRAYER_ORDER):
            card = ctk.CTkFrame(self.cards_frame, corner_radius=12)
            card.grid(row=i // cols, column=i % cols, padx=8, pady=8, sticky="nsew")
            ctk.CTkLabel(card, text=name, font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 2))
            time_lbl = ctk.CTkLabel(card, text="--:--", font=ctk.CTkFont(size=20))
            time_lbl.pack(pady=(0, 10))
            self.card_labels[name] = time_lbl

        self.next_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self.next_label.grid(row=4, column=0, pady=(4, 10), sticky="ew")

        audio = ctk.CTkFrame(self)
        audio.grid(row=5, column=0, padx=12, pady=6, sticky="ew")
        audio.grid_columnconfigure(1, weight=1)

        ctk.CTkCheckBox(audio, text="Play athan automatically at prayer time",
                         variable=self.alarms_enabled).grid(
            row=0, column=0, columnspan=3, padx=10, pady=(10, 6), sticky="w")

        ctk.CTkLabel(audio, text="Fajr sound:", anchor="w").grid(
            row=1, column=0, padx=(10, 6), pady=4, sticky="w")
        self.fajr_status = ctk.CTkLabel(audio, text=self._status_text(self.fajr_athan_path),
                                         text_color="gray70", font=ctk.CTkFont(size=11), anchor="w")
        self.fajr_status.grid(row=1, column=1, padx=4, pady=4, sticky="ew")
        ctk.CTkButton(audio, text="Choose...", width=90,
                       command=lambda: self._pick_audio_file("fajr")).grid(row=1, column=2, padx=4)
        ctk.CTkButton(audio, text="Test", width=60,
                       command=lambda: self._test_sound("fajr")).grid(row=1, column=3, padx=(4, 10))

        ctk.CTkLabel(audio, text="Other prayers:", anchor="w").grid(
            row=2, column=0, padx=(10, 6), pady=(4, 10), sticky="w")
        self.other_status = ctk.CTkLabel(audio, text=self._status_text(self.other_athan_path),
                                          text_color="gray70", font=ctk.CTkFont(size=11), anchor="w")
        self.other_status.grid(row=2, column=1, padx=4, pady=(4, 10), sticky="ew")
        ctk.CTkButton(audio, text="Choose...", width=90,
                       command=lambda: self._pick_audio_file("other")).grid(row=2, column=2, padx=4, pady=(4, 10))
        ctk.CTkButton(audio, text="Test", width=60,
                       command=lambda: self._test_sound("other")).grid(row=2, column=3, padx=(4, 10), pady=(4, 10))

        importer = ctk.CTkFrame(self)
        importer.grid(row=6, column=0, padx=12, pady=(6, 14), sticky="ew")
        importer.grid_columnconfigure(0, weight=1)
        self.import_status = ctk.CTkLabel(importer, text="No custom schedule imported.",
                                           text_color="gray70", font=ctk.CTkFont(size=11), anchor="w")
        self.import_status.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        ctk.CTkButton(importer, text="Import CSV/JSON...", width=150,
                       command=self._import_schedule).grid(row=0, column=1, padx=(4, 4), pady=10)
        ctk.CTkButton(importer, text="Clear", width=70,
                       command=self._clear_schedule).grid(row=0, column=2, padx=(0, 10), pady=10)

    def _status_text(self, path):
        return f"{os.path.basename(path)}" if path and os.path.exists(path) else "No sound file set (.wav)"

    def _pick_audio_file(self, which):
        path = filedialog.askopenfilename(
            title=f"Choose {'Fajr' if which == 'fajr' else 'other prayers'} athan sound (.wav)",
            filetypes=[("WAV audio", "*.wav"), ("All files", "*.*")],
        )
        if not path:
            return
        if which == "fajr":
            self.fajr_athan_path = path
            self.fajr_status.configure(text=self._status_text(path))
        else:
            self.other_athan_path = path
            self.other_status.configure(text=self._status_text(path))

    def _test_sound(self, which):
        path = self.fajr_athan_path if which == "fajr" else self.other_athan_path
        if not path or not os.path.exists(path):
            messagebox.showinfo("No sound file", "Choose a .wav sound file first.")
            return
        play_sound_file(path)

    def _import_schedule(self):
        path = filedialog.askopenfilename(
            title="Import custom prayer times (CSV or JSON)",
            filetypes=[("CSV or JSON", "*.csv *.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.custom_schedule = load_custom_schedule(path)
            self.custom_schedule_name = os.path.basename(path)
            self.import_status.configure(text=f"Using: {self.custom_schedule_name}")
        except Exception as exc:
            messagebox.showerror("Import failed", str(exc))
            return
        self.refresh_times()

    def _clear_schedule(self):
        self.custom_schedule = {}
        self.custom_schedule_name = ""
        self.import_status.configure(text="No custom schedule imported.")
        self.refresh_times()

    def refresh_times(self):
        today = date.today()
        self._computed_for = today.strftime("%Y-%m-%d")

        if self.custom_schedule:
            entry = get_times_for_date(self.custom_schedule, today)
            if entry:
                self._apply_times(entry, f"Custom import ({self.custom_schedule_name})")
                return

        method = self.method_var.get()
        asr_hanafi = self.asr_var.get() == "Hanafi"

        def worker():
            online = fetch_online_times(today, method, asr_hanafi)
            if online:
                self.after(0, lambda: self._apply_times(online, "Online — AlAdhan.com"))
            else:
                local = calculate_prayer_times(
                    today, EDMONTON_LAT, EDMONTON_LON, edmonton_utc_offset(today),
                    method=method, asr_method=self.asr_var.get(),
                )
                self.after(0, lambda: self._apply_times(local, "Local calculation (offline)"))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_times(self, entry, source_text):
        self.today_times = entry
        for name, info in entry.items():
            if name in self.card_labels:
                self.card_labels[name].configure(text=info["display"])
        self.source_label.configure(text=f"Source: {source_text}")
        self._update_next_prayer_label()

    def _update_next_prayer_label(self):
        if not self.today_times:
            return

        now = datetime.now()
        upcoming = None

        for name in PRAYER_ORDER:
            info = self.today_times.get(name)
            if not info:
                continue

            t = now.replace(
                hour=info["hour"],
                minute=info["minute"],
                second=0,
                microsecond=0
            )

            if t > now:
                upcoming = (name, t)
                break

        if upcoming is None:
            fajr = self.today_times.get("Fajr")

            if fajr:
                fajr_time = now.replace(
                    hour=fajr["hour"],
                    minute=fajr["minute"],
                    second=0,
                    microsecond=0
                )

                fajr_time += timedelta(days=1)
                delta = fajr_time - now

                h, rem = divmod(int(delta.total_seconds()), 3600)
                m, s = divmod(rem, 60)

                self.next_label.configure(
                    text=f"Next: Fajr in {h:02d}h {m:02d}m {s:02d}s"
                )
        else:
            name, t = upcoming
            delta = t - now

            h, rem = divmod(int(delta.total_seconds()), 3600)
            m, s = divmod(rem, 60)

            self.next_label.configure(
                text=f"Next: {name} in {h:02d}h {m:02d}m {s:02d}s"
            )

    def _tick(self):
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        if self._computed_for != today_str:
            self.refresh_times()

        self._update_next_prayer_label()

        if self.alarms_enabled.get():
            for name in PRAYER_ORDER:
                info = self.today_times.get(name)
                if not info:
                    continue
                if now.hour == info["hour"] and now.minute == info["minute"]:
                    key = (today_str, name)
                    if self._last_triggered != key:
                        self._last_triggered = key
                        path = self.fajr_athan_path if name == "Fajr" else self.other_athan_path
                        if path and os.path.exists(path):
                            play_sound_file(path)

        self.after(1000, self._tick)


if __name__ == "__main__":
    app = AthanApp()
    app.mainloop()