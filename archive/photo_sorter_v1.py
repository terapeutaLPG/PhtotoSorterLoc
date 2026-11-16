"""
Photo Sorter - skanuje WYBRANY folder (razem z podfolderami), czyta date i
lokalizacje z EXIF i KOPIUJE pliki do wybranego folderu docelowego wg
wybranego schematu (domyslnie Rok\\MM, jak aplikacja UGREEN Sync & Backup).
Nic nie jest wpisane na sztywno - foldery wybiera uzytkownik i program je pamieta.

Instalacja:   pip install pillow pillow-heif reverse_geocoder
Uruchomienie: python photo_sorter.py
"""
import csv
import json
import os
import shutil
import threading
import datetime as dt
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

from PIL import Image

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

try:
    import reverse_geocoder as rg  # dziala offline
except ImportError:
    rg = None

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".3gp", ".mkv"}
NO_PLACE = "Bez lokalizacji"

CONFIG = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                      "PhotoSorter", "config.json")

# Teksty interfejsu w jednym miejscu (latwo dodac inny jezyk)
TXT = {
    "src": "Folder ze zdjeciami (razem z podfolderami):",
    "dst": "Folder docelowy (np. na NAS-ie):",
    "dev": "Podfolder urzadzenia (opcjonalnie, np. nazwa telefonu):",
    "mode": "Uklad folderow:",
    "pick": "Wybierz",
    "dry": "Proba (nic nie kopiuj, tylko zapisz log)",
    "start": "Start",
    "cancel": "Anuluj",
    "ready": "Gotowe.",
    "missing": "Wybierz folder zrodlowy i docelowy.",
    "nosrc": "Folder zrodlowy nie istnieje.",
    "nodst": "Nie mozna zapisac w folderze docelowym. Sprawdz dostep do NAS-a.",
    "scan": "Szukam plikow...",
    "nofiles": "Nie znaleziono zdjec ani filmow.",
    "done": "Skopiowano: {c}, pominieto: {s}, bledy: {f}",
    "done_dry": "Proba zakonczona. Do skopiowania: {c}, pominieto: {s}, bledy: {f}",
    "stopped": "Przerwano. Skopiowano: {c}, pominieto: {s}, bledy: {f}",
}

MODES = {
    "Rok \\ Miesiac (jak UGREEN)": lambda t, city: [f"{t.year}", f"{t.month:02d}"],
    "Rok": lambda t, city: [f"{t.year}"],
    "Rok \\ Miesiac \\ Dzien": lambda t, city: [f"{t.year}", f"{t.month:02d}", f"{t.day:02d}"],
    "Rok \\ Miejsce": lambda t, city: [f"{t.year}", city or NO_PLACE],
    "Rok \\ Miesiac \\ Miejsce": lambda t, city: [f"{t.year}", f"{t.month:02d}", city or NO_PLACE],
}


def safe(name):
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "")
    return name.strip(" .")


def is_inside(path, parent):
    p = os.path.normcase(os.path.abspath(path))
    q = os.path.normcase(os.path.abspath(parent))
    return p == q or p.startswith(q + os.sep)


def load_cfg():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def to_deg(v):
    return float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600


def read_meta(path):
    """Zwraca (datetime, zrodlo_daty, lat, lon)."""
    taken, source, lat, lon = None, "plik", None, None
    if os.path.splitext(path)[1].lower() in PHOTO_EXT:
        try:
            with Image.open(path) as img:
                exif = img.getexif()
                raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
                if raw:
                    taken = dt.datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S")
                    source = "exif"
                gps = exif.get_ifd(0x8825)
                if gps and 2 in gps and 4 in gps:
                    lat = to_deg(gps[2]) * (-1 if gps.get(1) == "S" else 1)
                    lon = to_deg(gps[4]) * (-1 if gps.get(3) == "W" else 1)
        except Exception:
            pass
    if taken is None:
        taken = dt.datetime.fromtimestamp(os.path.getmtime(path))
    return taken, source, lat, lon


def place_info(lat, lon):
    """Zwraca (miasto, pelny opis); puste, gdy brak GPS lub biblioteki."""
    if lat is None or rg is None:
        return "", ""
    try:
        r = rg.search((lat, lon), mode=1)[0]
        return safe(r["name"]), f"{r['name']}, {r['admin1']}, {r['cc']}"
    except Exception:
        return "", ""


def unique_target(folder, name, size):
    """Sciezka docelowa albo None, jesli identyczny plik juz istnieje."""
    target = os.path.join(folder, name)
    base, ext = os.path.splitext(name)
    i = 1
    while os.path.exists(target):
        if os.path.getsize(target) == size:
            return None
        target = os.path.join(folder, f"{base}_{i}{ext}")
        i += 1
    return target


def check_writable(folder):
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".photo_sorter_test")
        open(probe, "w").close()
        os.remove(probe)
        return True
    except OSError:
        return False


class App:
    def __init__(self, root):
        self.root = root
        root.title("Photo Sorter")
        root.geometry("560x400")
        root.resizable(False, False)
        cfg = load_cfg()

        self.src = tk.StringVar(value=cfg.get("src", ""))
        self.dst = tk.StringVar(value=cfg.get("dst", ""))
        self.dev = tk.StringVar(value=cfg.get("dev", ""))
        mode = cfg.get("mode")
        self.mode = tk.StringVar(value=mode if mode in MODES else next(iter(MODES)))
        self.dry = tk.BooleanVar(value=False)
        self.stop = threading.Event()

        r = 0
        for key, var in (("src", self.src), ("dst", self.dst)):
            ttk.Label(root, text=TXT[key]).grid(row=r, column=0, sticky="w", padx=10, pady=(10, 0))
            ttk.Entry(root, textvariable=var, width=58).grid(row=r + 1, column=0, padx=10)
            ttk.Button(root, text=TXT["pick"], command=lambda v=var: self.pick(v)).grid(row=r + 1, column=1)
            r += 2
        ttk.Label(root, text=TXT["dev"]).grid(row=r, column=0, sticky="w", padx=10, pady=(10, 0))
        ttk.Entry(root, textvariable=self.dev, width=58).grid(row=r + 1, column=0, padx=10)
        ttk.Label(root, text=TXT["mode"]).grid(row=r + 2, column=0, sticky="w", padx=10, pady=(10, 0))
        ttk.Combobox(root, textvariable=self.mode, values=list(MODES), state="readonly",
                     width=55).grid(row=r + 3, column=0, padx=10, sticky="w")
        ttk.Checkbutton(root, text=TXT["dry"], variable=self.dry).grid(
            row=r + 4, column=0, sticky="w", padx=10, pady=8)

        box = ttk.Frame(root)
        box.grid(row=r + 5, column=0, pady=4)
        self.btn = ttk.Button(box, text=TXT["start"], command=self.start)
        self.btn.pack(side="left", padx=5)
        self.btn_stop = ttk.Button(box, text=TXT["cancel"], command=self.stop.set, state="disabled")
        self.btn_stop.pack(side="left", padx=5)
        self.bar = ttk.Progressbar(root, length=420)
        self.bar.grid(row=r + 6, column=0, padx=10, pady=4)
        self.status = ttk.Label(root, text=TXT["ready"])
        self.status.grid(row=r + 7, column=0, pady=4)

    def pick(self, var):
        folder = filedialog.askdirectory()
        if folder:
            var.set(os.path.normpath(folder))

    def start(self):
        src, dst = self.src.get().strip(), self.dst.get().strip()
        if not src or not dst:
            messagebox.showwarning("Photo Sorter", TXT["missing"])
            return
        if not os.path.isdir(src):
            messagebox.showwarning("Photo Sorter", TXT["nosrc"])
            return
        save_cfg({"src": src, "dst": dst, "dev": self.dev.get(), "mode": self.mode.get()})
        self.stop.clear()
        self.btn.config(state="disabled")
        self.btn_stop.config(state="normal")
        threading.Thread(target=self.work, daemon=True).start()

    def ui(self, text=None, value=None):
        def apply():
            if text is not None:
                self.status.config(text=text)
            if value is not None:
                self.bar["value"] = value
        self.root.after(0, apply)

    def finish(self):
        self.btn.config(state="normal")
        self.btn_stop.config(state="disabled")

    def work(self):
        try:
            self.run()
        except Exception as e:
            self.ui(f"Blad: {e}")
        finally:
            self.root.after(0, self.finish)

    def run(self):
        src, dst = self.src.get().strip(), self.dst.get().strip()
        dev = safe(self.dev.get())
        base = os.path.join(dst, dev) if dev else dst
        dry = self.dry.get()
        parts_fn = MODES[self.mode.get()]

        if not dry and not check_writable(base):
            self.ui(TXT["nodst"])
            self.root.after(0, lambda: messagebox.showerror("Photo Sorter", TXT["nodst"]))
            return

        self.ui(TXT["scan"], 0)
        files = []
        for folder, dirs, names in os.walk(src):
            dirs[:] = [d for d in dirs if not is_inside(os.path.join(folder, d), dst)]
            for n in names:
                if os.path.splitext(n)[1].lower() in PHOTO_EXT | VIDEO_EXT:
                    files.append(os.path.join(folder, n))
        if not files:
            self.ui(TXT["nofiles"])
            return

        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(src, f"photo_sorter_log_{stamp}.csv")
        try:
            log_file = open(log_path, "w", newline="", encoding="utf-8-sig")
        except OSError:
            os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
            log_path = os.path.join(os.path.dirname(CONFIG), f"photo_sorter_log_{stamp}.csv")
            log_file = open(log_path, "w", newline="", encoding="utf-8-sig")

        copied = skipped = failed = 0
        stopped = False
        with log_file:
            w = csv.writer(log_file, delimiter=";")
            w.writerow(["plik", "data", "zrodlo_daty", "lat", "lon", "miejsce", "cel", "status"])
            for i, path in enumerate(files, 1):
                if self.stop.is_set():
                    stopped = True
                    break
                try:
                    taken, source, lat, lon = read_meta(path)
                    city, full = place_info(lat, lon)
                    folder = os.path.join(base, *parts_fn(taken, city))
                    size = os.path.getsize(path)
                    if dry:
                        w.writerow([path, taken.isoformat(), source, lat, lon, full, folder, "proba"])
                        copied += 1
                    else:
                        os.makedirs(folder, exist_ok=True)
                        target = unique_target(folder, os.path.basename(path), size)
                        if target is None:
                            skipped += 1
                            w.writerow([path, taken.isoformat(), source, lat, lon, full, folder,
                                        "pominiety (juz jest)"])
                        else:
                            shutil.copy2(path, target)
                            copied += 1
                            w.writerow([path, taken.isoformat(), source, lat, lon, full, target,
                                        "skopiowany"])
                except Exception as e:
                    failed += 1
                    w.writerow([path, "", "", "", "", "", "", f"blad: {e}"])
                self.ui(f"{i}/{len(files)}", i / len(files) * 100)

        key = "stopped" if stopped else ("done_dry" if dry else "done")
        self.ui(TXT[key].format(c=copied, s=skipped, f=failed))


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
