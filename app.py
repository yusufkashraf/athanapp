import os
import sys
import shutil
import threading
import winreg
import json
import urllib.request
import webbrowser
import subprocess

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import customtkinter as ctk
from tkinter import filedialog, messagebox

from prayer_calc import (
    calculate_prayer_times,
    METHODS,
    ASR_FACTORS,
    PRAYER_ORDER
)

from online_source import (
    fetch_online_times,
    EDMONTON_LAT,
    EDMONTON_LON
)

from custom_import import (
    load_custom_schedule,
    get_times_for_date
)

import pystray
from PIL import Image


EDMONTON_TZ = ZoneInfo("America/Edmonton")
APP_VERSION = "2.1.0"
GITHUB_REPO = "yusufkashraf/athanapp"
GITHUB_RELEASES_API = (
    f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
)
GITHUB_RELEASE_PAGE = (
    f"https://github.com/{GITHUB_REPO}/releases/latest"
)


def resource_path(*parts):
    if hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(
            os.path.abspath(__file__)
        )
    return os.path.join(
        base,
        *parts
    )


if getattr(sys, "frozen", False):
    EXE_DIR = os.path.dirname(
        sys.executable
    )
else:
    EXE_DIR = os.path.dirname(
        os.path.abspath(__file__)
    )


APP_DATA_DIR = os.path.join(
    os.environ.get(
        "APPDATA",
        os.path.expanduser("~")
    ),
    "Athan"
)

AUDIO_DIR = os.path.join(
    APP_DATA_DIR,
    "audio"
)

SETTINGS_FILE = os.path.join(
    APP_DATA_DIR,
    "settings.json"
)

CUSTOM_SCHEDULE_BASE = os.path.join(
    APP_DATA_DIR,
    "custom_schedule"
)

CUSTOM_SCHEDULE_META = os.path.join(
    APP_DATA_DIR,
    "custom_schedule_meta.json"
)

BUNDLED_FAJR_ATHAN = resource_path(
    "assets",
    "athan_fajr.wav"
)

BUNDLED_OTHER_ATHAN = resource_path(
    "assets",
    "athan.wav"
)

USER_FAJR_ATHAN = os.path.join(
    AUDIO_DIR,
    "athan_fajr.wav"
)

USER_OTHER_ATHAN = os.path.join(
    AUDIO_DIR,
    "athan.wav"
)


DEFAULT_SETTINGS = {
    "method": "ISNA (North America)",
    "asr_method": "Standard (Shafi/Maliki/Hanbali)",
    "alarms_enabled": True,
    "startup_enabled": False,
    "fajr_sound": "",
    "other_sound": ""
}


def ensure_app_directories():
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)


def load_settings():
    ensure_app_directories()

    settings = DEFAULT_SETTINGS.copy()

    if not os.path.exists(SETTINGS_FILE):
        return settings

    try:
        with open(
            SETTINGS_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            saved = json.load(file)

        if isinstance(saved, dict):
            for key in DEFAULT_SETTINGS:
                if key in saved:
                    settings[key] = saved[key]

    except (
        OSError,
        json.JSONDecodeError
    ) as exc:
        print(
            f"[settings] Could not load settings: {exc}"
        )

    return settings


def save_settings(settings):
    ensure_app_directories()

    try:
        temporary_file = SETTINGS_FILE + ".tmp"

        with open(
            temporary_file,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                settings,
                file,
                indent=4
            )

        os.replace(
            temporary_file,
            SETTINGS_FILE
        )

    except OSError as exc:
        print(
            f"[settings] Could not save settings: {exc}"
        )


def default_sound(user_path, bundled_path):
    if user_path and os.path.exists(user_path):
        return user_path

    if os.path.exists(bundled_path):
        return bundled_path

    return ""


def play_sound_file(path):
    if not path or not os.path.exists(path):
        return

    if sys.platform.startswith("win"):
        try:
            import winsound

            winsound.PlaySound(
                path,
                winsound.SND_FILENAME |
                winsound.SND_ASYNC
            )

        except Exception as exc:
            print(
                f"[audio error] {exc}"
            )

    else:
        print(
            f"[would play athan here]: {path}"
        )


def edmonton_utc_offset(d: date) -> float:
    dt = datetime(
        d.year,
        d.month,
        d.day,
        12,
        tzinfo=EDMONTON_TZ
    )

    return (
        dt.utcoffset().total_seconds()
        / 3600
    )


def get_persistent_schedule_path(extension):
    extension = extension.lower()

    if extension not in (".csv", ".json"):
        raise ValueError(
            "Custom schedules must be CSV or JSON files."
        )

    return CUSTOM_SCHEDULE_BASE + extension


class AthanApp(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.title(
            "Athan - Edmonton Prayer Times"
        )

        self.geometry(
            "680x660"
        )

        self.minsize(
            620,
            600
        )

        # Load saved settings
        self.settings = load_settings()

        # Variables
        self.method_var = ctk.StringVar(
            value=self.settings.get(
                "method",
                DEFAULT_SETTINGS["method"]
            )
        )

        self.asr_var = ctk.StringVar(
            value=self.settings.get(
                "asr_method",
                DEFAULT_SETTINGS["asr_method"]
            )
        )

        self.alarms_enabled = ctk.BooleanVar(
            value=self.settings.get(
                "alarms_enabled",
                True
            )
        )

        self.startup_var = ctk.BooleanVar(
            value=self.is_startup_enabled()
        )

        # Audio
        self.fajr_athan_path = default_sound(
            self.settings.get(
                "fajr_sound",
                ""
            ),
            BUNDLED_FAJR_ATHAN
        )

        self.other_athan_path = default_sound(
            self.settings.get(
                "other_sound",
                ""
            ),
            BUNDLED_OTHER_ATHAN
        )

        # Prayer data
        self.custom_schedule = {}
        self.custom_schedule_name = ""
        self.custom_schedule_file = ""
        self.today_times = {}
        self._computed_for = None
        self._last_triggered = None

        self._load_saved_schedule()

        # UI
        self._build_ui()

        self.protocol(
            "WM_DELETE_WINDOW",
            self.hide_to_tray
        )

        self.setup_tray()

        self.refresh_times()

        self.after(
            1000,
            self._tick
        )

        self.after(
            3000,
            self.check_for_updates
        )

    def save_current_settings(self):
        self.settings["method"] = (
            self.method_var.get()
        )

        self.settings["asr_method"] = (
            self.asr_var.get()
        )

        self.settings["alarms_enabled"] = (
            self.alarms_enabled.get()
        )

        self.settings["startup_enabled"] = (
            self.startup_var.get()
        )

        if (
            self.fajr_athan_path
            and os.path.abspath(
                self.fajr_athan_path
            ) == os.path.abspath(
                USER_FAJR_ATHAN
            )
        ):
            self.settings["fajr_sound"] = (
                USER_FAJR_ATHAN
            )

        if (
            self.other_athan_path
            and os.path.abspath(
                self.other_athan_path
            ) == os.path.abspath(
                USER_OTHER_ATHAN
            )
        ):
            self.settings["other_sound"] = (
                USER_OTHER_ATHAN
            )

        save_settings(
            self.settings
        )

    def save_method(self, value=None):
        self.settings["method"] = (
            self.method_var.get()
        )

        save_settings(
            self.settings
        )

        self.refresh_times()

    def save_asr_method(self, value=None):
        self.settings["asr_method"] = (
            self.asr_var.get()
        )

        save_settings(
            self.settings
        )

        self.refresh_times()

    def save_alarm_setting(self):
        self.settings["alarms_enabled"] = (
            self.alarms_enabled.get()
        )

        save_settings(
            self.settings
        )

    def _build_ui(self):

        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(
            self,
            text="🕌  Athan — Edmonton, AB",
            font=ctk.CTkFont(
                size=24,
                weight="bold"
            )
        )

        header.grid(
            row=0,
            column=0,
            pady=(16, 4),
            sticky="ew"
        )

        self.source_label = ctk.CTkLabel(
            self,
            text="Source: —",
            text_color="gray70",
            font=ctk.CTkFont(size=12)
        )

        self.source_label.grid(
            row=1,
            column=0,
            pady=(0, 8),
            sticky="ew"
        )

        # ----- Settings -----

        settings = ctk.CTkFrame(self)

        settings.grid(
            row=2,
            column=0,
            padx=12,
            pady=6,
            sticky="ew"
        )

        settings.grid_columnconfigure(
            1,
            weight=1
        )

        ctk.CTkLabel(
            settings,
            text="Method:",
            anchor="w"
        ).grid(
            row=0,
            column=0,
            padx=(10, 6),
            pady=(10, 4),
            sticky="w"
        )

        self.method_var = ctk.StringVar(
            value=self.settings.get(
                "method",
                DEFAULT_SETTINGS["method"]
            )
        )

        ctk.CTkOptionMenu(
            settings,
            values=list(METHODS.keys()),
            variable=self.method_var,
            command=self.save_method
        ).grid(
            row=0,
            column=1,
            padx=(0, 10),
            pady=(10, 4),
            sticky="ew"
        )

        ctk.CTkLabel(
            settings,
            text="Asr calc:",
            anchor="w"
        ).grid(
            row=1,
            column=0,
            padx=(10, 6),
            pady=(4, 10),
            sticky="w"
        )

        self.asr_var = ctk.StringVar(
            value=self.settings.get(
                "asr_method",
                DEFAULT_SETTINGS["asr_method"]
            )
        )

        ctk.CTkOptionMenu(
            settings,
            values=list(ASR_FACTORS.keys()),
            variable=self.asr_var,
            command=self.save_asr_method
        ).grid(
            row=1,
            column=1,
            padx=(0, 10),
            pady=(4, 10),
            sticky="ew"
        )

        ctk.CTkCheckBox(
            settings,
            text="Start Athan with Windows",
            variable=self.startup_var,
            command=self.set_startup
        ).grid(
            row=2,
            column=0,
            columnspan=2,
            padx=10,
            pady=(0, 10),
            sticky="w"
        )

        self.cards_frame = ctk.CTkFrame(self)

        self.cards_frame.grid(
            row=3,
            column=0,
            padx=12,
            pady=6,
            sticky="nsew"
        )

        self.card_labels = {}

        cols = 3

        for c in range(cols):
            self.cards_frame.grid_columnconfigure(
                c,
                weight=1
            )

        for r in range(
            (len(PRAYER_ORDER) + cols - 1) // cols
        ):
            self.cards_frame.grid_rowconfigure(
                r,
                weight=1
            )

        for i, name in enumerate(PRAYER_ORDER):

            card = ctk.CTkFrame(
                self.cards_frame,
                corner_radius=12
            )

            card.grid(
                row=i // cols,
                column=i % cols,
                padx=8,
                pady=8,
                sticky="nsew"
            )

            ctk.CTkLabel(
                card,
                text=name,
                font=ctk.CTkFont(
                    size=14,
                    weight="bold"
                )
            ).pack(
                pady=(10, 2)
            )

            time_lbl = ctk.CTkLabel(
                card,
                text="--:--",
                font=ctk.CTkFont(size=20)
            )

            time_lbl.pack(
                pady=(0, 10)
            )

            self.card_labels[name] = time_lbl

        self.next_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(
                size=16,
                weight="bold"
            )
        )

        self.next_label.grid(
            row=4,
            column=0,
            pady=(4, 10),
            sticky="ew"
        )

        audio = ctk.CTkFrame(self)

        audio.grid(
            row=5,
            column=0,
            padx=12,
            pady=6,
            sticky="ew"
        )

        audio.grid_columnconfigure(
            1,
            weight=1
        )

        ctk.CTkCheckBox(
            audio,
            text="Play athan automatically at prayer time",
            variable=self.alarms_enabled,
            command=self.save_alarm_setting
        ).grid(
            row=0,
            column=0,
            columnspan=3,
            padx=10,
            pady=(10, 6),
            sticky="w"
        )

        ctk.CTkLabel(
            audio,
            text="Fajr sound:",
            anchor="w"
        ).grid(
            row=1,
            column=0,
            padx=(10, 6),
            pady=4,
            sticky="w"
        )

        self.fajr_status = ctk.CTkLabel(
            audio,
            text=self._status_text(
                self.fajr_athan_path
            ),
            text_color="gray70",
            font=ctk.CTkFont(size=11),
            anchor="w"
        )

        self.fajr_status.grid(
            row=1,
            column=1,
            padx=4,
            pady=4,
            sticky="ew"
        )

        ctk.CTkButton(
            audio,
            text="Choose...",
            width=90,
            command=lambda:
            self._pick_audio_file("fajr")
        ).grid(
            row=1,
            column=2,
            padx=4
        )

        ctk.CTkButton(
            audio,
            text="Test",
            width=60,
            command=lambda:
            self._test_sound("fajr")
        ).grid(
            row=1,
            column=3,
            padx=(4, 10)
        )

        ctk.CTkLabel(
            audio,
            text="Other prayers:",
            anchor="w"
        ).grid(
            row=2,
            column=0,
            padx=(10, 6),
            pady=(4, 10),
            sticky="w"
        )

        self.other_status = ctk.CTkLabel(
            audio,
            text=self._status_text(
                self.other_athan_path
            ),
            text_color="gray70",
            font=ctk.CTkFont(size=11),
            anchor="w"
        )

        self.other_status.grid(
            row=2,
            column=1,
            padx=4,
            pady=(4, 10),
            sticky="ew"
        )

        ctk.CTkButton(
            audio,
            text="Choose...",
            width=90,
            command=lambda:
            self._pick_audio_file("other")
        ).grid(
            row=2,
            column=2,
            padx=4,
            pady=(4, 10)
        )

        ctk.CTkButton(
            audio,
            text="Test",
            width=60,
            command=lambda:
            self._test_sound("other")
        ).grid(
            row=2,
            column=3,
            padx=(4, 10),
            pady=(4, 10)
        )

        importer = ctk.CTkFrame(self)

        importer.grid(
            row=6,
            column=0,
            padx=12,
            pady=(6, 14),
            sticky="ew"
        )

        importer.grid_columnconfigure(
            0,
            weight=1
        )

        if self.custom_schedule_name:
            schedule_text = (
                f"Using: "
                f"{self.custom_schedule_name}"
            )
        else:
            schedule_text = (
                "No custom schedule imported."
            )

        self.import_status = ctk.CTkLabel(
            importer,
            text=schedule_text,
            text_color="gray70",
            font=ctk.CTkFont(size=11),
            anchor="w"
        )

        self.import_status.grid(
            row=0,
            column=0,
            padx=10,
            pady=10,
            sticky="ew"
        )

        ctk.CTkButton(
            importer,
            text="Import CSV/JSON...",
            width=150,
            command=self._import_schedule
        ).grid(
            row=0,
            column=1,
            padx=(4, 4),
            pady=10
        )

        ctk.CTkButton(
            importer,
            text="Clear",
            width=70,
            command=self._clear_schedule
        ).grid(
            row=0,
            column=2,
            padx=(0, 10),
            pady=10
        )

    def _status_text(self, path):
        if not path or not os.path.exists(path):
            return "No sound file set (.wav)"

        return os.path.basename(path)

    def _pick_audio_file(self, which):
        path = filedialog.askopenfilename(
            title=(
                "Choose "
                f"{'Fajr' if which == 'fajr' else 'other prayers'} "
                "athan sound (.wav)"
            ),
            filetypes=[
                ("WAV audio", "*.wav"),
                ("All files", "*.*")
            ]
        )

        if not path:
            return

        ensure_app_directories()

        if which == "fajr":
            destination = USER_FAJR_ATHAN
        else:
            destination = USER_OTHER_ATHAN

        try:
            shutil.copyfile(
                path,
                destination
            )

        except Exception as exc:
            messagebox.showerror(
                "Could not save sound",
                f"Could not copy the sound file:\n\n{exc}"
            )
            return

        if which == "fajr":
            self.fajr_athan_path = (
                destination
            )

            self.settings["fajr_sound"] = (
                destination
            )

            self.fajr_status.configure(
                text=self._status_text(
                    destination
                )
            )

        else:
            self.other_athan_path = (
                destination
            )

            self.settings["other_sound"] = (
                destination
            )

            self.other_status.configure(
                text=self._status_text(
                    destination
                )
            )

        save_settings(
            self.settings
        )

    def _test_sound(self, which):
        if which == "fajr":
            path = self.fajr_athan_path
        else:
            path = self.other_athan_path

        if not path or not os.path.exists(path):
            messagebox.showinfo(
                "No sound file",
                "Choose a .wav sound file first."
            )
            return

        play_sound_file(
            path
        )

    def _load_saved_schedule(self):
        if not os.path.exists(
            CUSTOM_SCHEDULE_META
        ):
            return

        try:
            with open(
                CUSTOM_SCHEDULE_META,
                "r",
                encoding="utf-8"
            ) as file:
                metadata = json.load(file)

            if not isinstance(metadata, dict):
                return

            saved_file = metadata.get(
                "file",
                ""
            )

            saved_name = metadata.get(
                "name",
                ""
            )

            if saved_file not in (
                "custom_schedule.csv",
                "custom_schedule.json"
            ):
                return

            schedule_path = os.path.join(
                APP_DATA_DIR,
                saved_file
            )

            if not os.path.isfile(
                schedule_path
            ):
                return

            schedule = load_custom_schedule(
                schedule_path
            )

            self.custom_schedule = schedule

            self.custom_schedule_file = (
                schedule_path
            )

            if (
                isinstance(saved_name, str)
                and saved_name
            ):
                self.custom_schedule_name = (
                    saved_name
                )
            else:
                self.custom_schedule_name = (
                    os.path.basename(
                        schedule_path
                    )
                )

        except Exception as exc:
            print(
                f"[custom schedule] "
                f"Could not load saved schedule: {exc}"
            )

            self.custom_schedule = {}
            self.custom_schedule_name = ""
            self.custom_schedule_file = ""

    def _save_schedule_metadata(
        self,
        name,
        filename
    ):
        ensure_app_directories()

        metadata = {
            "name": name,
            "file": filename
        }

        temporary_file = (
            CUSTOM_SCHEDULE_META + ".tmp"
        )

        try:
            with open(
                temporary_file,
                "w",
                encoding="utf-8"
            ) as file:
                json.dump(
                    metadata,
                    file,
                    indent=4
                )

            os.replace(
                temporary_file,
                CUSTOM_SCHEDULE_META
            )

        except OSError as exc:
            print(
                f"[custom schedule] "
                f"Could not save metadata: {exc}"
            )

            try:
                if os.path.exists(
                    temporary_file
                ):
                    os.remove(
                        temporary_file
                    )
            except OSError:
                pass

    def _import_schedule(self):
        path = filedialog.askopenfilename(
            title="Import custom prayer times (CSV or JSON)",
            filetypes=[
                ("CSV or JSON", "*.csv *.json"),
                ("All files", "*.*")
            ]
        )

        if not path:
            return

        extension = os.path.splitext(
            path
        )[1].lower()

        if extension not in (
            ".csv",
            ".json"
        ):
            messagebox.showerror(
                "Import failed",
                "Custom schedules must be CSV or JSON files."
            )
            return

        try:
            schedule = load_custom_schedule(
                path
            )

            ensure_app_directories()

            destination = (
                get_persistent_schedule_path(
                    extension
                )
            )

            other_extension = (
                ".json"
                if extension == ".csv"
                else ".csv"
            )

            old_destination = (
                get_persistent_schedule_path(
                    other_extension
                )
            )

            shutil.copyfile(
                path,
                destination
            )

            if os.path.exists(
                old_destination
            ):
                os.remove(
                    old_destination
                )

            self.custom_schedule = schedule

            self.custom_schedule_name = (
                os.path.basename(path)
            )

            self.custom_schedule_file = (
                destination
            )

            self._save_schedule_metadata(
                self.custom_schedule_name,
                os.path.basename(destination)
            )

            self.import_status.configure(
                text=(
                    f"Using: "
                    f"{self.custom_schedule_name}"
                )
            )

        except Exception as exc:
            messagebox.showerror(
                "Import failed",
                str(exc)
            )
            return

        self.refresh_times()

    def _clear_schedule(self):
        self.custom_schedule = {}
        self.custom_schedule_name = ""
        self.custom_schedule_file = ""

        for extension in (
            ".csv",
            ".json"
        ):
            path = get_persistent_schedule_path(
                extension
            )

            try:
                if os.path.exists(path):
                    os.remove(path)

            except OSError as exc:
                print(
                    f"[custom schedule] "
                    f"Could not remove {path}: {exc}"
                )

        try:
            if os.path.exists(
                CUSTOM_SCHEDULE_META
            ):
                os.remove(
                    CUSTOM_SCHEDULE_META
                )

        except OSError as exc:
            print(
                f"[custom schedule] "
                f"Could not remove metadata: {exc}"
            )

        self.import_status.configure(
            text="No custom schedule imported."
        )

        self.refresh_times()

    def refresh_times(self):
        today = date.today()

        self._computed_for = (
            today.strftime("%Y-%m-%d")
        )

        # Custom schedule
        if self.custom_schedule:
            entry = get_times_for_date(
                self.custom_schedule,
                today
            )

            if entry:
                self._apply_times(
                    entry,
                    (
                        "Custom import "
                        f"({self.custom_schedule_name})"
                    )
                )
                return

        # Online / local calculation
        method = self.method_var.get()

        asr_hanafi = (
            self.asr_var.get()
            == "Hanafi"
        )

        def worker():
            online = fetch_online_times(
                today,
                method,
                asr_hanafi
            )

            if online:
                self.after(
                    0,
                    lambda:
                    self._apply_times(
                        online,
                        "Online — AlAdhan.com"
                    )
                )

            else:
                local = calculate_prayer_times(
                    today,
                    EDMONTON_LAT,
                    EDMONTON_LON,
                    edmonton_utc_offset(today),
                    method=method,
                    asr_method=self.asr_var.get()
                )

                self.after(
                    0,
                    lambda:
                    self._apply_times(
                        local,
                        "Local calculation (offline)"
                    )
                )

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    def _apply_times(
        self,
        entry,
        source_text
    ):
        self.today_times = entry

        for name, info in entry.items():
            if name in self.card_labels:
                self.card_labels[
                    name
                ].configure(
                    text=info["display"]
                )

        self.source_label.configure(
            text=f"Source: {source_text}"
        )

        self._update_next_prayer_label()

    def _update_next_prayer_label(self):
        if not self.today_times:
            return

        now = datetime.now()
        upcoming = None

        for name in PRAYER_ORDER:
            info = self.today_times.get(
                name
            )

            if not info:
                continue

            prayer_time = now.replace(
                hour=info["hour"],
                minute=info["minute"],
                second=0,
                microsecond=0
            )

            if prayer_time > now:
                upcoming = (
                    name,
                    prayer_time
                )
                break

        # All prayers today have passed.
        # The next prayer is tomorrow's Fajr.
        if upcoming is None:
            fajr = self.today_times.get(
                "Fajr"
            )

            if fajr:
                fajr_time = now.replace(
                    hour=fajr["hour"],
                    minute=fajr["minute"],
                    second=0,
                    microsecond=0
                )

                fajr_time += timedelta(
                    days=1
                )

                delta = (
                    fajr_time - now
                )

                h, rem = divmod(
                    int(delta.total_seconds()),
                    3600
                )

                m, s = divmod(
                    rem,
                    60
                )

                self.next_label.configure(
                    text=(
                        f"Next: Fajr in "
                        f"{h:02d}h "
                        f"{m:02d}m "
                        f"{s:02d}s"
                    )
                )

        else:
            name, prayer_time = upcoming

            delta = (
                prayer_time - now
            )

            h, rem = divmod(
                int(delta.total_seconds()),
                3600
            )

            m, s = divmod(
                rem,
                60
            )

            self.next_label.configure(
                text=(
                    f"Next: {name} in "
                    f"{h:02d}h "
                    f"{m:02d}m "
                    f"{s:02d}s"
                )
            )

def _tick(self):
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # Recalculate prayer times when
    # the calendar day changes.
    if self._computed_for != today_str:
        self.refresh_times()

    self._update_next_prayer_label()

    # Athan alarms
    if self.alarms_enabled.get():
        for name in PRAYER_ORDER:
            info = self.today_times.get(name)
            if not info:
                continue

            prayer_time = now.replace(
                hour=info["hour"],
                minute=info["minute"],
                second=0,
                microsecond=0
            )

            key = (
                today_str,
                name
            )

            # Play the athan once when the prayer time
            # has been reached, but only during the
            # first minute after the scheduled time.
            if (
                prayer_time <= now
                < prayer_time + timedelta(minutes=1)
            ):
                if self._last_triggered != key:
                    self._last_triggered = key

                    if name == "Fajr":
                        path = self.fajr_athan_path
                    else:
                        path = self.other_athan_path

                    if (
                        path
                        and os.path.exists(path)
                    ):
                        play_sound_file(path)
                    else:
                        print(
                            f"[audio] No athan file found for {name}: "
                            f"{path}"
                        )

    # Keep running even when the main
    # window is hidden in the tray.
    self.after(
        1000,
        self._tick
    )

    def check_for_updates(self):
        def worker():
            try:
                request = urllib.request.Request(
                    GITHUB_RELEASES_API,
                    headers={
                        "User-Agent": "Athan-App"
                    }
                )

                with urllib.request.urlopen(
                    request,
                    timeout=10
                ) as response:
                    data = json.loads(
                        response.read().decode(
                            "utf-8"
                        )
                    )

                latest_tag = data.get(
                    "tag_name",
                    ""
                )

                if not latest_tag:
                    return

                latest_version = (
                    latest_tag.lstrip("vV")
                )

                if self._version_is_newer(
                    latest_version,
                    APP_VERSION
                ):
                    self.after(
                        0,
                        lambda:
                        self._show_update_available(
                            latest_version,
                            data
                        )
                    )

            except Exception as exc:
                print(
                    f"[update check] {exc}"
                )

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    def _version_is_newer(
        self,
        latest,
        current
    ):
        try:
            latest_parts = tuple(
                int(part)
                for part in latest.split(".")
            )

            current_parts = tuple(
                int(part)
                for part in current.split(".")
            )

            length = max(
                len(latest_parts),
                len(current_parts)
            )

            latest_parts += (
                0,
            ) * (
                length - len(latest_parts)
            )

            current_parts += (
                0,
            ) * (
                length - len(current_parts)
            )

            return (
                latest_parts
                > current_parts
            )

        except ValueError:
            return False

    def _show_update_available(
        self,
        latest_version,
        release_data
    ):
        result = messagebox.askyesno(
            "Update Available",
            (
                f"Athan v{latest_version} is available.\n\n"
                f"You are currently running "
                f"v{APP_VERSION}.\n\n"
                "Would you like to download and "
                "install the update now?"
            )
        )

        if not result:
            return

        assets = release_data.get(
            "assets",
            []
        )

        installer_asset = None

        for asset in assets:
            name = asset.get(
                "name",
                ""
            )

            if (
                name.lower().endswith(".exe")
                and "setup" in name.lower()
            ):
                installer_asset = asset
                break

        if not installer_asset:
            messagebox.showerror(
                "Update failed",
                (
                    "The latest GitHub release does not "
                    "contain an Athan installer."
                )
            )
            return

        download_url = installer_asset.get(
            "browser_download_url",
            ""
        )

        if not download_url:
            messagebox.showerror(
                "Update failed",
                "The installer download link is missing."
            )
            return

        temp_dir = os.path.join(
            os.environ.get(
                "TEMP",
                os.path.expanduser("~")
            ),
            "AthanUpdate"
        )

        os.makedirs(
            temp_dir,
            exist_ok=True
        )

        installer_path = os.path.join(
            temp_dir,
            installer_asset["name"]
        )

        def download_worker():
            try:
                request = urllib.request.Request(
                    download_url,
                    headers={
                        "User-Agent": "Athan-App"
                    }
                )

                with urllib.request.urlopen(
                    request,
                    timeout=60
                ) as response:
                    with open(
                        installer_path,
                        "wb"
                    ) as file:
                        shutil.copyfileobj(
                            response,
                            file
                        )

                if not os.path.isfile(
                    installer_path
                ):
                    raise OSError(
                        "The installer was not downloaded."
                    )

                self.after(
                    0,
                    lambda:
                    self._install_update(
                        installer_path
                    )
                )

            except Exception as exc:
                error_message = str(exc)

                self.after(
                    0,
                    lambda:
                    messagebox.showerror(
                        "Update failed",
                        (
                            "Could not download the update:\n\n"
                            f"{error_message}"
                        )
                    )
                )

        messagebox.showinfo(
            "Downloading Update",
            (
                f"Downloading Athan v{latest_version}.\n\n"
                "Athan will close automatically when "
                "the download is complete."
            )
        )

        threading.Thread(
            target=download_worker,
            daemon=True
        ).start()

    def _install_update(
        self,
        installer_path
    ):
        try:
            self.save_current_settings()

            subprocess.Popen(
                [
                    installer_path
                ]
            )

            self.tray_icon.stop()

            self.destroy()

        except Exception as exc:
            messagebox.showerror(
                "Update failed",
                (
                    "Could not start the installer:\n\n"
                    f"{exc}"
                )
            )

    def is_startup_enabled(self):
        if not sys.platform.startswith("win"):
            return False

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ
            ) as key:

                winreg.QueryValueEx(
                    key,
                    "Athan"
                )

                return True

        except FileNotFoundError:
            return False

        except OSError:
            return False

    def set_startup(self):
        if not sys.platform.startswith("win"):
            return

        startup_key = (
            r"Software\Microsoft\Windows\CurrentVersion\Run"
        )

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                startup_key,
                0,
                winreg.KEY_SET_VALUE
            ) as key:

                if self.startup_var.get():

                    if getattr(
                        sys,
                        "frozen",
                        False
                    ):
                        app_path = (
                            sys.executable
                        )

                    else:
                        app_path = (
                            sys.executable
                            + " "
                            + os.path.abspath(
                                __file__
                            )
                        )

                    winreg.SetValueEx(
                        key,
                        "Athan",
                        0,
                        winreg.REG_SZ,
                        f'"{app_path}"'
                    )

                else:
                    try:
                        winreg.DeleteValue(
                            key,
                            "Athan"
                        )

                    except FileNotFoundError:
                        pass

                self.settings[
                    "startup_enabled"
                ] = self.startup_var.get()

                save_settings(
                    self.settings
                )

        except OSError as exc:
            self.startup_var.set(
                not self.startup_var.get()
            )

            messagebox.showerror(
                "Startup setting failed",
                (
                    "Could not change the "
                    "Windows startup setting:\n"
                    f"{exc}"
                )
            )

    def setup_tray(self):
        # Temporary icon.
        # Replace this later with the actual Athan icon.
        image = Image.new(
            "RGB",
            (64, 64),
            "white"
        )

        menu = pystray.Menu(
            pystray.MenuItem(
                "Open Athan",
                self.show_window
            ),
            pystray.MenuItem(
                "Exit",
                self.exit_app
            )
        )

        self.tray_icon = pystray.Icon(
            "Athan",
            image,
            "Athan",
            menu
        )

        threading.Thread(
            target=self.tray_icon.run,
            daemon=True
        ).start()

    def hide_to_tray(self):
        self.withdraw()

    def show_window(
        self,
        icon=None,
        item=None
    ):
        self.after(
            0,
            self.deiconify
        )

        self.after(
            0,
            self.lift
        )

        self.after(
            0,
            self.focus_force
        )

    def exit_app(
        self,
        icon=None,
        item=None
    ):
        self.save_current_settings()

        self.tray_icon.stop()

        self.after(
            0,
            self.destroy
        )


if __name__ == "__main__":
    app = AthanApp()
    app.mainloop()
