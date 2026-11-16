"""
Photo Sorter — porządkuje zdjęcia i filmy lokalnie i KOPIUJE je do wybranego
folderu w układzie jak UGREEN Sync & Backup (domyślnie Rok\\MM).

Uwaga (UGREEN Sync & Backup): nie wiadomo, czy Sync rozpozna pliki wgrane tym
programem jako już istniejące. Test: skopiuj 3–5 zdjęć do
Photos\\MobileBackup\\<urządzenie>\\RRRR\\MM, zapisz liczbę/rozmiar, uruchom
Sync z telefonu i sprawdź, czy te same pliki nie poszły ponownie.

Uwaga (MTP): kopiowanie z telefonu na PC może zmieniać datę modyfikacji —
dlatego data z nazwy pliku ma pierwszeństwo przed datą pliku (po EXIF).

Instalacja:   pip install pillow pillow-heif reverse_geocoder customtkinter
Uruchomienie: python photo_sorter.py
Opcjonalnie w PATH: exiftool lub ffprobe (lepsze daty filmów).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import datetime as dt
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

try:
    import reverse_geocoder as rg
except ImportError:
    rg = None

VERSION = "2.0.0"
APP_TITLE = f"Photo Sorter {VERSION}"

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".3gp", ".mkv"}
ALL_EXT = PHOTO_EXT | VIDEO_EXT
NO_PLACE = "Bez lokalizacji"
HASH_CHUNK = 1024 * 1024
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
DEFAULT_MODE = "year_month"

TYPE_CAMERA = "Aparat"
TYPE_VIDEO = "Filmy"
TYPE_SCREENSHOT = "Zrzuty ekranu"
TYPE_OTHER = "Inne"

if sys.platform == "darwin":
    CONFIG_DIR = os.path.expanduser("~/Library/Application Support/PhotoSorter")
else:
    CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PhotoSorter")
CONFIG = os.path.join(CONFIG_DIR, "config.json")

NAME_DATE_RE = re.compile(
    r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"
    r"(?:[_-]([01]\d|2[0-3])([0-5]\d)([0-5]\d))?(?!\d)"
)

TXT = {
    "title": APP_TITLE,
    "step1": "1. Gdzie są zdjęcia do posortowania?",
    "step2": "2. Gdzie zapisać posortowane?",
    "step3": "3. Jak ułożyć foldery?",
    "pick": "Wybierz folder",
    "dry": "Tylko sprawdź, nic nie kopiuj",
    "dry_tip": "Program tylko zapisze log CSV — nic nie skopiuje i nie utworzy folderów.",
    "start": "Start",
    "cancel": "Anuluj",
    "ready": "Gotowe. Wybierz foldery i naciśnij Start.",
    "advanced": "Ustawienia zaawansowane",
    "dev": "Podfolder urządzenia (np. nazwa telefonu)",
    "dev_tip": "Gdy wypełnisz, pliki trafią do: folder docelowy\\ta nazwa\\…",
    "hash": "Dokładniej wykrywaj duplikaty (wolniej)",
    "hash_tip": "Przy tej samej nazwie i rozmiarze porównuje treść pliku (hash). Wolniejsze.",
    "split": "Rozdziel według typu (Filmy / Zrzuty / Inne)",
    "split_tip": "UGREEN trzyma wszystko razem — zostaw wyłączone, jeśli chcesz ten sam układ.",
    "example": "Przykład:",
    "missing": "Wskaż folder ze zdjęciami i folder docelowy.",
    "nosrc": "Folder ze zdjęciami nie istnieje. Sprawdź, czy dysk jest podłączony.",
    "nodst": "Nie można zapisać w folderze docelowym. Sprawdź, czy folder istnieje i masz prawo zapisu.",
    "dry_nodst": "Folder docelowy nie istnieje. Próba i tak zostanie uruchomiona (nic nie skopiuje).",
    "scan": "Szukam plików…",
    "confirm_title": "Potwierdzenie",
    "confirm": "Znaleziono {n} plików ({p} zdjęć, {v} filmów).\n\nKontynuować kopiowanie?",
    "confirm_dry": "Znaleziono {n} plików ({p} zdjęć, {v} filmów).\n\nUruchomić tylko sprawdzenie (bez kopiowania)?",
    "confirm_ok": "Kopiuj",
    "confirm_dry_ok": "Sprawdź",
    "confirm_cancel": "Anuluj",
    "meta": "Czytam informacje o plikach…",
    "geo": "Ustalam lokalizacje…",
    "copy": "Kopiuję…",
    "dry_run": "Sprawdzam (bez kopiowania)…",
    "nofiles": "Nie znaleziono zdjęć ani filmów w wybranym folderze.",
    "done": "Skopiowano: {c}, pominięto: {s}, błędy: {f}",
    "done_dry": "Sprawdzenie zakończone. Do skopiowania: {c}, pominięto: {s}, błędy: {f}",
    "stopped": "Przerwano. Skopiowano: {c}, pominięto: {s}, błędy: {f}",
    "summary_title": "Podsumowanie",
    "open_folder": "Otwórz folder",
    "open_log": "Otwórz log",
    "close": "Zamknij",
    "eta": "Pozostało ok. {t}",
    "eta_calc": "Szacuję czas…",
    "progress": "{i} z {n}  ({pct}%)",
    "modes": {
        "year_month": "Rok\\MM (np. 2024\\04) — jak UGREEN",
        "year": "Rok (np. 2024)",
        "year_month_day": "Rok\\MM\\Dzień (np. 2024\\04\\15)",
        "year_place": "Rok\\Miejsce (np. 2024\\Warszawa)",
        "year_month_place": "Rok\\MM\\Miejsce (np. 2024\\04\\Warszawa)",
    },
    "mode_trees": {
        "year_month": "2024\\04\\zdjęcie.jpg",
        "year": "2024\\zdjęcie.jpg",
        "year_month_day": "2024\\04\\15\\zdjęcie.jpg",
        "year_place": "2024\\Warszawa\\zdjęcie.jpg",
        "year_month_place": "2024\\04\\Warszawa\\zdjęcie.jpg",
    },
}

MODE_BUILDERS = {
    "year_month": lambda t, city: [f"{t.year}", f"{t.month:02d}"],
    "year": lambda t, city: [f"{t.year}"],
    "year_month_day": lambda t, city: [f"{t.year}", f"{t.month:02d}", f"{t.day:02d}"],
    "year_place": lambda t, city: [f"{t.year}", city or NO_PLACE],
    "year_month_place": lambda t, city: [f"{t.year}", f"{t.month:02d}", city or NO_PLACE],
}


if os.sep != "\\":
    for group in ("modes", "mode_trees"):
        TXT[group] = {key: value.replace("\\", os.sep) for key, value in TXT[group].items()}
    TXT["dev_tip"] = TXT["dev_tip"].replace("\\", os.sep)


def open_path(path: str) -> None:
    """Open a folder or file with the system's default application."""
    if sys.platform == "win32":
        os.startfile(path)
    else:
        command = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.run([command, os.path.abspath(path)], check=True)


def safe(name: str) -> str:
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "")
    name = "".join(c for c in name if ord(c) >= 32)
    return name.strip(" .")


def win_long(path: str) -> str:
    if os.name != "nt" or not path:
        return path
    if path.startswith("\\\\?\\"):
        return path
    try:
        path = os.path.abspath(path)
    except (OSError, ValueError):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path.lstrip("\\")
    if len(path) >= 240:
        return "\\\\?\\" + path
    return path


def strip_long(path: str) -> str:
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def norm_key(path: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(path))
    except (OSError, ValueError, TypeError):
        return os.path.normcase(str(path))


def is_inside(path: str, parent: str) -> bool:
    if not path or not parent:
        return False
    try:
        p = norm_key(path)
        q = norm_key(parent)
        if p == q:
            return True
        sep = "\\" if os.name == "nt" else os.sep
        if not q.endswith(sep):
            q = q + sep
        return p.startswith(q)
    except (OSError, ValueError, TypeError):
        return False


def load_cfg() -> dict:
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg: dict) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _num(x) -> float:
    if hasattr(x, "numerator") and hasattr(x, "denominator"):
        den = float(x.denominator)
        return float(x.numerator) / den if den else 0.0
    if isinstance(x, (tuple, list)) and len(x) == 2:
        den = float(x[1])
        return float(x[0]) / den if den else 0.0
    return float(x)


def to_deg(v) -> float:
    return _num(v[0]) + _num(v[1]) / 60.0 + _num(v[2]) / 3600.0


def _hemi(value, neg: str) -> int:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("ascii", errors="ignore")
    return -1 if str(value).strip().upper().startswith(neg) else 1


def parse_dt(raw) -> dt.datetime | None:
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    s = str(raw).strip()
    if not s or s.startswith("0000"):
        return None
    s = s.replace("T", " ").replace("-", ":")
    if "+" in s[10:]:
        s = s[: s.index("+", 10)]
    elif s.endswith("Z"):
        s = s[:-1]
    s = s.strip()
    for fmt, n in (("%Y:%m:%d %H:%M:%S", 19), ("%Y:%m:%d %H:%M", 16), ("%Y:%m:%d", 10)):
        try:
            return dt.datetime.strptime(s[:n], fmt)
        except ValueError:
            continue
    return None


def date_ok(taken: dt.datetime | None, *, name_rules: bool = False) -> bool:
    if taken is None:
        return False
    now = dt.datetime.now()
    if taken > now + dt.timedelta(days=1):
        return False
    if name_rules:
        if taken.year < 2000 or taken.year > now.year:
            return False
        try:
            dt.date(taken.year, taken.month, taken.day)
        except ValueError:
            return False
        return True
    if taken.year < 1971:
        return False
    return True


def file_mtime(path: str) -> dt.datetime:
    return dt.datetime.fromtimestamp(os.path.getmtime(win_long(path)))


def parse_date_from_name(filename: str) -> dt.datetime | None:
    base = os.path.splitext(os.path.basename(filename))[0]
    best = None
    for m in NAME_DATE_RE.finditer(base):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh = int(m.group(4)) if m.group(4) else 0
        mm = int(m.group(5)) if m.group(5) else 0
        ss = int(m.group(6)) if m.group(6) else 0
        try:
            taken = dt.datetime(y, mo, d, hh, mm, ss)
        except ValueError:
            continue
        if date_ok(taken, name_rules=True):
            best = taken
    return best


def _run_tool(args, timeout=90):
    kw = dict(
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    if CREATE_NO_WINDOW:
        kw["creationflags"] = CREATE_NO_WINDOW
    return subprocess.run(args, **kw)


def video_date(path: str):
    lp = win_long(path)
    try:
        r = _run_tool([
            "exiftool", "-j", "-n",
            "-DateTimeOriginal", "-CreateDate", "-CreationDate",
            "-MediaCreateDate", "-TrackCreateDate",
            lp,
        ])
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            if data:
                row = data[0]
                for key in (
                    "DateTimeOriginal", "CreationDate", "CreateDate",
                    "MediaCreateDate", "TrackCreateDate",
                ):
                    taken = parse_dt(row.get(key))
                    if date_ok(taken):
                        return taken, "metadane"
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, IndexError):
        pass

    try:
        r = _run_tool([
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_entries", "format_tags=creation_time:stream_tags=creation_time",
            lp,
        ])
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            tags = (data.get("format") or {}).get("tags") or {}
            taken = parse_dt(tags.get("creation_time"))
            if date_ok(taken):
                return taken, "metadane"
            for stream in data.get("streams") or []:
                st = stream.get("tags") or {}
                taken = parse_dt(st.get("creation_time"))
                if date_ok(taken):
                    return taken, "metadane"
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, TypeError):
        pass

    return None, "plik"


def read_gps(exif):
    try:
        gps = exif.get_ifd(0x8825)
    except Exception:
        return None, None
    if not gps or 2 not in gps or 4 not in gps:
        return None, None
    try:
        lat = to_deg(gps[2]) * _hemi(gps.get(1, "N"), "S")
        lon = to_deg(gps[4]) * _hemi(gps.get(3, "E"), "W")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None, None
        return lat, lon
    except Exception:
        return None, None


def classify_media(path: str, make=None, model=None) -> str:
    ext = os.path.splitext(path)[1].lower()
    name = os.path.basename(path).lower()
    parent = os.path.basename(os.path.dirname(path)).lower()
    if ext in VIDEO_EXT:
        return TYPE_VIDEO
    if (
        "screenshot" in name
        or "zrzut" in name
        or "screenshot" in parent
        or "zrzut" in parent
    ):
        return TYPE_SCREENSHOT
    if ext == ".png" and not make and not model:
        return TYPE_SCREENSHOT
    if ext in PHOTO_EXT and not make and not model:
        return TYPE_OTHER
    return TYPE_CAMERA


def type_folder(media_type: str) -> str | None:
    if media_type == TYPE_VIDEO:
        return TYPE_VIDEO
    if media_type == TYPE_SCREENSHOT:
        return TYPE_SCREENSHOT
    if media_type == TYPE_OTHER:
        return TYPE_OTHER
    return None


def read_meta(path: str):
    taken = None
    source = "plik"
    lat = lon = None
    make = model = None
    warn = ""
    ext = os.path.splitext(path)[1].lower()
    lp = win_long(path)
    exif_dt = None
    name_dt = parse_date_from_name(path)

    if ext in PHOTO_EXT:
        try:
            with Image.open(lp) as img:
                exif = img.getexif()
                raw = None
                try:
                    raw = exif.get_ifd(0x8769).get(36867)
                except Exception:
                    pass
                if not raw:
                    raw = exif.get(306)
                parsed = parse_dt(raw)
                if date_ok(parsed):
                    exif_dt = parsed
                lat, lon = read_gps(exif)
                try:
                    make = exif.get(271)
                    model = exif.get(272)
                    if isinstance(make, bytes):
                        make = make.decode("utf-8", errors="ignore")
                    if isinstance(model, bytes):
                        model = model.decode("utf-8", errors="ignore")
                    make = (make or "").strip() or None
                    model = (model or "").strip() or None
                except Exception:
                    make = model = None
        except Exception:
            pass

    if exif_dt is not None:
        taken, source = exif_dt, "exif"
        if name_dt is not None and abs((exif_dt.date() - name_dt.date()).days) > 1:
            warn = "ostrzezenie: data EXIF i nazwa rozne (>1 dzien); uzyto EXIF"
    elif name_dt is not None:
        taken, source = name_dt, "nazwa"
    elif ext in VIDEO_EXT:
        taken, source = video_date(path)
        if taken is None:
            source = "plik"

    if taken is None or not date_ok(taken):
        taken = file_mtime(path)
        source = "plik"

    media_type = classify_media(path, make, model)
    return taken, source, lat, lon, media_type, warn


def place_batch(points):
    cache = {}
    if rg is None or not points:
        return cache
    uniq = {}
    for lat, lon in points:
        key = (round(lat, 4), round(lon, 4))
        uniq.setdefault(key, (lat, lon))
    try:
        keys = list(uniq.keys())
        coords = [uniq[k] for k in keys]
        results = rg.search(coords, mode=1)
        for key, r in zip(keys, results):
            city = safe(r.get("name") or "") or NO_PLACE
            full = f"{r.get('name', '')}, {r.get('admin1', '')}, {r.get('cc', '')}".strip(", ")
            cache[key] = (city, full)
    except Exception:
        pass
    return cache


def lookup_place(cache, lat, lon):
    if lat is None or lon is None:
        return "", ""
    key = (round(lat, 4), round(lon, 4))
    return cache.get(key, ("", ""))


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(win_long(path), "rb") as f:
        while True:
            chunk = f.read(HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def unique_target(folder, name, size, src_path, use_hash):
    target = os.path.join(folder, name)
    base, ext = os.path.splitext(name)
    i = 1
    while os.path.exists(win_long(target)):
        try:
            same_size = os.path.getsize(win_long(target)) == size
        except OSError:
            same_size = False
        if same_size:
            if not use_hash:
                return None
            try:
                if file_hash(target) == file_hash(src_path):
                    return None
            except OSError:
                pass
        target = os.path.join(folder, f"{base}_{i}{ext}")
        i += 1
        if i > 10000:
            raise OSError("Zbyt wiele wariantow nazwy pliku")
    return target


def check_writable(folder: str, create: bool = True) -> bool:
    try:
        if create:
            os.makedirs(win_long(folder), exist_ok=True)
        elif not os.path.isdir(win_long(folder)):
            return False
        probe = os.path.join(folder, ".photo_sorter_test")
        with open(win_long(probe), "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(win_long(probe))
        return True
    except OSError:
        return False


def open_log(src: str):
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"photo_sorter_log_{stamp}.csv"
    log_path = os.path.join(src, name)
    try:
        return open(win_long(log_path), "w", newline="", encoding="utf-8-sig"), log_path
    except OSError:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        log_path = os.path.join(CONFIG_DIR, name)
        return open(win_long(log_path), "w", newline="", encoding="utf-8-sig"), log_path


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, PermissionError):
        return "Brak uprawnień lub plik jest używany przez inny program"
    if isinstance(exc, FileNotFoundError):
        return "Nie znaleziono pliku (może został przeniesiony)"
    if isinstance(exc, OSError):
        return "Problem z odczytem lub zapisem pliku (dysk, sieć albo uszkodzony plik)"
    return "Nie udało się obsłużyć tego pliku"


def format_eta(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:
        return TXT["eta_calc"]
    sec = int(seconds)
    if sec < 60:
        return TXT["eta"].format(t=f"{sec} s")
    if sec < 3600:
        return TXT["eta"].format(t=f"{sec // 60} min {sec % 60} s")
    return TXT["eta"].format(t=f"{sec // 3600} h {(sec % 3600) // 60} min")


def make_app_icon():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, 60, 60), radius=14, fill=(49, 130, 206, 255))
    d.rounded_rectangle((14, 18, 50, 46), radius=6, fill=(235, 248, 255, 255))
    d.ellipse((22, 24, 34, 36), fill=(49, 130, 206, 255))
    d.polygon([(36, 42), (44, 28), (48, 42)], fill=(66, 153, 225, 255))
    return ImageTk.PhotoImage(img)


class ToolTip:
    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tw = ctk.CTkToplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        label = ctk.CTkLabel(
            tw, text=self.text, justify="left", wraplength=320,
            corner_radius=6, fg_color=("gray90", "gray20"),
            text_color=("gray10", "gray90"),
        )
        label.pack(padx=10, pady=8)

    def _hide(self, _event=None):
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.title(TXT["title"])
        self.geometry("780x820")
        self.minsize(700, 700)

        cfg = load_cfg()
        self.src = ctk.StringVar(value=cfg.get("src", ""))
        self.dst = ctk.StringVar(value=cfg.get("dst", ""))
        self.dev = ctk.StringVar(value=cfg.get("dev", ""))
        mode = cfg.get("mode", DEFAULT_MODE)
        if mode not in MODE_BUILDERS:
            mode = DEFAULT_MODE
        self.mode = ctk.StringVar(value=mode)
        self.use_hash = ctk.BooleanVar(value=bool(cfg.get("use_hash", False)))
        self.split_type = ctk.BooleanVar(value=bool(cfg.get("split_type", False)))
        self.dry = ctk.BooleanVar(value=False)
        self.stop = threading.Event()
        self._busy = False
        self._icon = make_app_icon()
        self.iconphoto(True, self._icon)
        self._mode_cards = {}
        self._adv_open = False
        self._job_base = ""
        self._log_path = ""

        self.src.trace_add("write", lambda *_: self.refresh_example())
        self.dst.trace_add("write", lambda *_: self.refresh_example())
        self.dev.trace_add("write", lambda *_: self.refresh_example())
        self.mode.trace_add("write", lambda *_: self.refresh_example())
        self.split_type.trace_add("write", lambda *_: self.refresh_example())

        self._build_ui()
        self.refresh_example()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew", padx=18, pady=14)
        scroll.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            scroll, text=APP_TITLE, font=ctk.CTkFont(size=26, weight="bold")
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))

        self._section(scroll, 1, TXT["step1"])
        row1 = ctk.CTkFrame(scroll, fg_color="transparent")
        row1.grid(row=2, column=0, sticky="ew", pady=(4, 14))
        row1.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(row1, textvariable=self.src, height=40, font=ctk.CTkFont(size=14)).grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        ctk.CTkButton(row1, text=TXT["pick"], width=130, height=40, command=lambda: self.pick(self.src)).grid(
            row=0, column=1
        )

        self._section(scroll, 3, TXT["step2"])
        row2 = ctk.CTkFrame(scroll, fg_color="transparent")
        row2.grid(row=4, column=0, sticky="ew", pady=(4, 6))
        row2.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(row2, textvariable=self.dst, height=40, font=ctk.CTkFont(size=14)).grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        ctk.CTkButton(row2, text=TXT["pick"], width=130, height=40, command=lambda: self.pick(self.dst)).grid(
            row=0, column=1
        )
        dry_cb = ctk.CTkCheckBox(scroll, text=TXT["dry"], variable=self.dry, font=ctk.CTkFont(size=13))
        dry_cb.grid(row=5, column=0, sticky="w", pady=(0, 14))
        ToolTip(dry_cb, TXT["dry_tip"])

        self._section(scroll, 6, TXT["step3"])
        tiles = ctk.CTkFrame(scroll, fg_color="transparent")
        tiles.grid(row=7, column=0, sticky="ew", pady=(4, 6))
        tiles.grid_columnconfigure((0, 1), weight=1)
        for i, key in enumerate(MODE_BUILDERS):
            card = self._mode_card(tiles, key)
            card.grid(row=i // 2, column=i % 2, sticky="ew", padx=4, pady=4)

        self.example = ctk.CTkLabel(
            scroll, text="", font=ctk.CTkFont(size=13),
            text_color=("gray30", "gray70"), anchor="w", justify="left", wraplength=700,
        )
        self.example.grid(row=8, column=0, sticky="ew", pady=(4, 12))

        self.adv_btn = ctk.CTkButton(
            scroll, text="▸  " + TXT["advanced"], fg_color="transparent",
            text_color=("gray20", "gray80"), hover=False, anchor="w",
            font=ctk.CTkFont(size=14, weight="bold"), command=self.toggle_advanced,
        )
        self.adv_btn.grid(row=9, column=0, sticky="w")

        self.adv_frame = ctk.CTkFrame(scroll, corner_radius=10)
        self.adv_frame.grid(row=10, column=0, sticky="ew", pady=(4, 12))
        self.adv_frame.grid_remove()
        self.adv_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.adv_frame, text=TXT["dev"], anchor="w").grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 2)
        )
        dev_entry = ctk.CTkEntry(self.adv_frame, textvariable=self.dev, height=36)
        dev_entry.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        ToolTip(dev_entry, TXT["dev_tip"])
        hash_cb = ctk.CTkCheckBox(
            self.adv_frame, text=TXT["hash"], variable=self.use_hash, font=ctk.CTkFont(size=13)
        )
        hash_cb.grid(row=2, column=0, sticky="w", padx=12, pady=4)
        ToolTip(hash_cb, TXT["hash_tip"])
        split_cb = ctk.CTkCheckBox(
            self.adv_frame, text=TXT["split"], variable=self.split_type, font=ctk.CTkFont(size=13)
        )
        split_cb.grid(row=3, column=0, sticky="w", padx=12, pady=(4, 12))
        ToolTip(split_cb, TXT["split_tip"])

        btns = ctk.CTkFrame(scroll, fg_color="transparent")
        btns.grid(row=11, column=0, sticky="ew", pady=(8, 10))
        btns.grid_columnconfigure(0, weight=1)
        self.btn_start = ctk.CTkButton(
            btns, text=TXT["start"], height=52, font=ctk.CTkFont(size=18, weight="bold"),
            command=self.start,
        )
        self.btn_start.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.btn_cancel = ctk.CTkButton(
            btns, text=TXT["cancel"], height=52, width=120, state="disabled",
            fg_color=("gray70", "gray35"), command=self.request_stop,
        )
        self.btn_cancel.grid(row=0, column=1)

        self.progress = ctk.CTkProgressBar(scroll, height=18)
        self.progress.grid(row=12, column=0, sticky="ew", pady=(8, 4))
        self.progress.set(0)

        self.lbl_progress = ctk.CTkLabel(scroll, text="", font=ctk.CTkFont(size=14), anchor="w")
        self.lbl_progress.grid(row=13, column=0, sticky="ew")
        self.lbl_file = ctk.CTkLabel(
            scroll, text="", font=ctk.CTkFont(size=13),
            text_color=("gray35", "gray65"), anchor="w", wraplength=700,
        )
        self.lbl_file.grid(row=14, column=0, sticky="ew")
        self.lbl_eta = ctk.CTkLabel(
            scroll, text="", font=ctk.CTkFont(size=13),
            text_color=("gray35", "gray65"), anchor="w",
        )
        self.lbl_eta.grid(row=15, column=0, sticky="ew", pady=(0, 4))
        self.status = ctk.CTkLabel(
            scroll, text=TXT["ready"], font=ctk.CTkFont(size=14), anchor="w", wraplength=700,
        )
        self.status.grid(row=16, column=0, sticky="ew", pady=(4, 10))

    def _section(self, parent, row, text):
        ctk.CTkLabel(
            parent, text=text, font=ctk.CTkFont(size=16, weight="bold"), anchor="w"
        ).grid(row=row, column=0, sticky="w")

    def _mode_style(self, selected: bool):
        if selected:
            return {
                "border_color": ("#2563eb", "#60a5fa"),
                "fg_color": ("#dbeafe", "#1e3a5f"),
                "title_color": ("gray10", "gray95"),
                "tree_color": ("gray35", "#93c5fd"),
            }
        return {
            "border_color": ("gray75", "gray35"),
            "fg_color": ("gray95", "gray20"),
            "title_color": ("gray10", "gray90"),
            "tree_color": ("gray40", "gray60"),
        }

    def _mode_card(self, parent, key: str):
        selected = self.mode.get() == key
        style = self._mode_style(selected)
        frame = ctk.CTkFrame(
            parent, corner_radius=10, border_width=2,
            border_color=style["border_color"],
            fg_color=style["fg_color"],
        )
        title = ctk.CTkLabel(
            frame, text=TXT["modes"][key], font=ctk.CTkFont(size=13, weight="bold"),
            text_color=style["title_color"], wraplength=300, justify="left", anchor="w",
        )
        title.pack(fill="x", padx=12, pady=(10, 2))
        tree = ctk.CTkLabel(
            frame, text=TXT["mode_trees"][key], font=ctk.CTkFont(size=12),
            text_color=style["tree_color"], wraplength=300, justify="left", anchor="w",
        )
        tree.pack(fill="x", padx=12, pady=(0, 10))

        def select(_event=None, k=key):
            self.mode.set(k)
            self._refresh_mode_cards()

        for w in (frame, title, tree):
            w.bind("<Button-1>", select)
        self._mode_cards[key] = (frame, title, tree)
        return frame

    def _refresh_mode_cards(self):
        cur = self.mode.get()
        for key, (frame, title, tree) in self._mode_cards.items():
            style = self._mode_style(key == cur)
            frame.configure(
                border_color=style["border_color"],
                fg_color=style["fg_color"],
            )
            title.configure(text_color=style["title_color"])
            tree.configure(text_color=style["tree_color"])

    def toggle_advanced(self):
        self._adv_open = not self._adv_open
        if self._adv_open:
            self.adv_frame.grid()
            self.adv_btn.configure(text="▾  " + TXT["advanced"])
        else:
            self.adv_frame.grid_remove()
            self.adv_btn.configure(text="▸  " + TXT["advanced"])

    def refresh_example(self):
        default_dst = r"D:\Posortowane" if os.name == "nt" else os.path.expanduser("~/Pictures/Posortowane")
        dst = self.dst.get().strip() or default_dst
        dev = safe(self.dev.get())
        base = os.path.join(dst, dev) if dev else dst
        key = self.mode.get() if self.mode.get() in MODE_BUILDERS else DEFAULT_MODE
        sample = TXT["mode_trees"].get(key, os.path.join("2024", "04", "zdjęcie.jpg"))
        if self.split_type.get():
            parts = sample.rsplit(os.sep, 1)
            if len(parts) == 2:
                sample = os.path.join(parts[0], "Filmy", parts[1])
        path = os.path.join(base, sample)
        self.example.configure(text=f"{TXT['example']} {path}")

    def pick(self, var):
        folder = filedialog.askdirectory(parent=self)
        if folder:
            var.set(os.path.normpath(folder))

    def request_stop(self):
        self.stop.set()

    def _on_close(self):
        if self._busy:
            if not messagebox.askyesno(APP_TITLE, "Trwa praca. Zamknąć mimo to?"):
                return
            self.stop.set()
        self.destroy()

    def set_busy(self, busy: bool):
        self._busy = busy
        self.btn_start.configure(state="disabled" if busy else "normal")
        self.btn_cancel.configure(state="normal" if busy else "disabled")

    def ui(self, *, status=None, progress=None, file=None, eta=None, counts=None):
        def apply():
            if status is not None:
                self.status.configure(text=status)
            if progress is not None:
                i, n = progress
                pct = 0 if n <= 0 else int(i / n * 100)
                self.progress.set(0 if n <= 0 else i / n)
                self.lbl_progress.configure(text=TXT["progress"].format(i=i, n=n, pct=pct))
            if file is not None:
                name = file if len(file) < 80 else "…" + file[-77:]
                self.lbl_file.configure(text=name)
            if eta is not None:
                self.lbl_eta.configure(text=eta)
            if counts is not None:
                c, s, f = counts
                self.lbl_eta.configure(text=f"Skopiowano {c} · pominięto {s} · błędy {f}")

        self.after(0, apply)

    def start(self):
        src, dst = self.src.get().strip(), self.dst.get().strip()
        if not src or not dst:
            messagebox.showwarning(APP_TITLE, TXT["missing"])
            return
        if not os.path.isdir(win_long(src)):
            messagebox.showwarning(APP_TITLE, TXT["nosrc"])
            return

        dry = bool(self.dry.get())
        dev = safe(self.dev.get())
        base = os.path.join(dst, dev) if dev else dst

        if dry:
            if not os.path.isdir(win_long(dst)):
                messagebox.showwarning(APP_TITLE, TXT["dry_nodst"])
        else:
            if not check_writable(base, create=True):
                messagebox.showerror(APP_TITLE, TXT["nodst"])
                return

        mode = self.mode.get() if self.mode.get() in MODE_BUILDERS else DEFAULT_MODE
        save_cfg({
            "src": src,
            "dst": dst,
            "dev": self.dev.get(),
            "mode": mode,
            "use_hash": bool(self.use_hash.get()),
            "split_type": bool(self.split_type.get()),
        })

        job = {
            "src": src,
            "dst": dst,
            "dev": dev,
            "mode": mode,
            "dry": dry,
            "use_hash": bool(self.use_hash.get()),
            "split_type": bool(self.split_type.get()),
            "base": base,
        }
        self._job_base = base
        self.stop.clear()
        self.set_busy(True)
        self.progress.set(0)
        self.ui(status=TXT["scan"], progress=(0, 0), file="", eta="")
        threading.Thread(target=self.work, args=(job,), daemon=True).start()

    def work(self, job):
        try:
            self.run(job)
        except Exception:
            self.ui(status="Wystąpił nieoczekiwany błąd. Spróbuj ponownie.")
        finally:
            self.after(0, lambda: self.set_busy(False))

    def _ask_confirm(self, n, photos, videos, dry) -> bool:
        result = {"ok": False}
        event = threading.Event()

        def show():
            win = ctk.CTkToplevel(self)
            win.title(TXT["confirm_title"])
            win.geometry("460x230")
            win.transient(self)
            win.grab_set()
            win.focus_force()
            msg = (TXT["confirm_dry"] if dry else TXT["confirm"]).format(n=n, p=photos, v=videos)
            ctk.CTkLabel(
                win, text=msg, font=ctk.CTkFont(size=15), wraplength=400, justify="left"
            ).pack(padx=20, pady=(24, 18), anchor="w")
            row = ctk.CTkFrame(win, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=10)

            def accept():
                result["ok"] = True
                win.destroy()
                event.set()

            def reject():
                result["ok"] = False
                win.destroy()
                event.set()

            win.protocol("WM_DELETE_WINDOW", reject)
            ctk.CTkButton(
                row, text=TXT["confirm_dry_ok"] if dry else TXT["confirm_ok"],
                width=140, command=accept,
            ).pack(side="left", padx=(0, 8))
            ctk.CTkButton(
                row, text=TXT["confirm_cancel"], width=120,
                fg_color=("gray70", "gray35"), command=reject,
            ).pack(side="left")

        self.after(0, show)
        event.wait()
        return result["ok"]

    def _show_summary(self, msg, folder, log_path):
        def show():
            win = ctk.CTkToplevel(self)
            win.title(TXT["summary_title"])
            win.geometry("480x240")
            win.transient(self)
            win.grab_set()
            ctk.CTkLabel(
                win, text=msg, font=ctk.CTkFont(size=15), wraplength=420, justify="left"
            ).pack(padx=20, pady=(24, 16), anchor="w")
            row = ctk.CTkFrame(win, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=8)

            def open_folder():
                target = folder if os.path.isdir(win_long(folder)) else os.path.dirname(folder)
                try:
                    open_path(target)
                except (OSError, subprocess.CalledProcessError):
                    messagebox.showwarning(APP_TITLE, "Nie udało się otworzyć folderu.")

            def open_log():
                try:
                    open_path(log_path)
                except (OSError, subprocess.CalledProcessError):
                    messagebox.showwarning(APP_TITLE, "Nie udało się otworzyć pliku logu.")

            ctk.CTkButton(row, text=TXT["open_folder"], command=open_folder).pack(side="left", padx=(0, 8))
            ctk.CTkButton(row, text=TXT["open_log"], command=open_log).pack(side="left", padx=(0, 8))
            ctk.CTkButton(row, text=TXT["close"], command=win.destroy).pack(side="right")

        self.after(0, show)

    def run(self, job):
        src = job["src"]
        dst = job["dst"]
        base = job["base"]
        dry = job["dry"]
        use_hash = job["use_hash"]
        split_type = job["split_type"]
        parts_fn = MODE_BUILDERS[job["mode"]]
        need_place = "place" in job["mode"]

        self.ui(status=TXT["scan"], file="")
        files = []
        try:
            for folder, dirs, names in os.walk(win_long(src)):
                if self.stop.is_set():
                    break
                folder_show = strip_long(folder)
                dirs[:] = [
                    d for d in dirs
                    if not is_inside(os.path.join(folder_show, d), dst)
                    and not is_inside(os.path.join(folder_show, d), base)
                ]
                for n in names:
                    if os.path.splitext(n)[1].lower() in ALL_EXT:
                        files.append(os.path.join(folder_show, n))
                if len(files) % 40 == 0:
                    self.ui(status=f"{TXT['scan']} {len(files)}", file=folder_show)
        except OSError:
            self.ui(status="Nie udało się przeczytać folderu źródłowego.")
            return

        if self.stop.is_set():
            self.ui(status=TXT["stopped"].format(c=0, s=0, f=0))
            return

        if not files:
            self.ui(status=TXT["nofiles"])
            self.after(0, lambda: messagebox.showinfo(APP_TITLE, TXT["nofiles"]))
            return

        photos = sum(1 for p in files if os.path.splitext(p)[1].lower() in PHOTO_EXT)
        videos = sum(1 for p in files if os.path.splitext(p)[1].lower() in VIDEO_EXT)
        if not self._ask_confirm(len(files), photos, videos, dry):
            self.ui(status=TXT["ready"])
            return

        if self.stop.is_set():
            self.ui(status=TXT["stopped"].format(c=0, s=0, f=0))
            return

        self.ui(status=TXT["meta"], progress=(0, len(files)))
        rows = []
        gps_points = []
        t0 = dt.datetime.now().timestamp()
        for i, path in enumerate(files, 1):
            if self.stop.is_set():
                break
            try:
                taken, source, lat, lon, media_type, warn = read_meta(path)
                size = os.path.getsize(win_long(path))
                rows.append({
                    "path": path, "taken": taken, "source": source,
                    "lat": lat, "lon": lon, "size": size,
                    "type": media_type, "warn": warn, "error": None,
                })
                if lat is not None and lon is not None:
                    gps_points.append((lat, lon))
            except Exception as e:
                rows.append({
                    "path": path, "taken": None, "source": "",
                    "lat": None, "lon": None, "size": 0,
                    "type": "", "warn": "", "error": friendly_error(e),
                })
            elapsed = dt.datetime.now().timestamp() - t0
            eta = format_eta(elapsed / i * (len(files) - i)) if i >= 3 else TXT["eta_calc"]
            self.ui(
                status=TXT["meta"],
                progress=(i, len(files)),
                file=os.path.basename(path),
                eta=eta,
            )

        if self.stop.is_set() and not rows:
            self.ui(status=TXT["stopped"].format(c=0, s=0, f=0))
            return

        cache = {}
        if need_place and gps_points and not self.stop.is_set():
            self.ui(status=TXT["geo"], file="")
            cache = place_batch(gps_points)

        try:
            log_file, log_path = open_log(src)
        except OSError:
            self.ui(status="Nie udało się utworzyć pliku logu.")
            return
        self._log_path = log_path

        copied = skipped = failed = 0
        stopped = False
        total = len(rows)
        done_i = 0
        phase = TXT["dry_run"] if dry else TXT["copy"]
        t1 = dt.datetime.now().timestamp()

        with log_file:
            w = csv.writer(log_file, delimiter=";")
            w.writerow([
                "plik", "data", "zrodlo_daty", "typ", "lat", "lon", "miejsce", "cel", "status",
            ])
            for i, row in enumerate(rows, 1):
                if self.stop.is_set():
                    stopped = True
                    break
                done_i = i
                path = row["path"]
                try:
                    if row["error"]:
                        raise OSError(row["error"])
                    taken = row["taken"]
                    source = row["source"]
                    lat, lon = row["lat"], row["lon"]
                    media_type = row["type"]
                    city, full = lookup_place(cache, lat, lon) if need_place else ("", "")
                    if need_place:
                        if lat is None or lon is None or not city:
                            city, full = NO_PLACE, NO_PLACE
                    folder_parts = parts_fn(taken, city)
                    if split_type:
                        extra = type_folder(media_type)
                        if extra:
                            folder_parts = list(folder_parts) + [extra]
                    folder = os.path.join(base, *folder_parts)
                    size = row["size"]
                    lat_s = f"{lat:.6f}" if lat is not None else ""
                    lon_s = f"{lon:.6f}" if lon is not None else ""
                    date_s = taken.isoformat(sep=" ") if taken else ""
                    warn = row.get("warn") or ""

                    if dry:
                        target = unique_target(folder, os.path.basename(path), size, path, use_hash)
                        if target is None:
                            skipped += 1
                            status = "pominiety (juz jest)"
                            cel = folder
                        else:
                            copied += 1
                            status = "proba"
                            cel = target
                        if warn:
                            status = f"{status}; {warn}"
                        w.writerow([path, date_s, source, media_type, lat_s, lon_s, full, cel, status])
                    else:
                        os.makedirs(win_long(folder), exist_ok=True)
                        target = unique_target(folder, os.path.basename(path), size, path, use_hash)
                        if target is None:
                            skipped += 1
                            status = "pominiety (juz jest)"
                            if warn:
                                status = f"{status}; {warn}"
                            w.writerow([
                                path, date_s, source, media_type, lat_s, lon_s, full, folder, status,
                            ])
                        else:
                            shutil.copy2(win_long(path), win_long(target))
                            copied += 1
                            status = "skopiowany"
                            if warn:
                                status = f"{status}; {warn}"
                            w.writerow([
                                path, date_s, source, media_type, lat_s, lon_s, full, target, status,
                            ])
                except Exception as e:
                    failed += 1
                    w.writerow([path, "", "", row.get("type", ""), "", "", "", "", f"blad: {friendly_error(e)}"])

                elapsed = dt.datetime.now().timestamp() - t1
                eta = format_eta(elapsed / i * (total - i)) if i >= 2 else TXT["eta_calc"]
                self.ui(
                    status=phase,
                    progress=(i, total),
                    file=os.path.basename(path),
                    eta=eta,
                    counts=(copied, skipped, failed),
                )

        key = "stopped" if stopped else ("done_dry" if dry else "done")
        msg = TXT[key].format(c=copied, s=skipped, f=failed)
        self.ui(status=msg, progress=(done_i if stopped else total, total), file="", eta="")
        self._show_summary(msg, base, log_path)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
