import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image
import photo_sorter as sorter


class PlatformSupportTests(unittest.TestCase):
    def test_mac_opens_path_as_one_argument(self):
        with patch.object(sorter.sys, "platform", "darwin"), patch.object(sorter.subprocess, "run") as run:
            sorter.open_path("folder ze zdjęciami/log.csv")
        run.assert_called_once_with(["open", os.path.abspath("folder ze zdjęciami/log.csv")], check=True)

    def test_windows_keeps_native_opener(self):
        with patch.object(sorter.sys, "platform", "win32"), patch.object(sorter.os, "startfile", create=True) as startfile:
            sorter.open_path("C:\\Zdjecia")
        startfile.assert_called_once_with("C:\\Zdjecia")

    def test_preview_uses_native_separators_with_type_folder(self):
        app = Mock()
        app.dst.get.return_value = os.path.join("photos", "sorted")
        app.dev.get.return_value = "Telefon"
        app.mode.get.return_value = "year_month"
        app.split_type.get.return_value = True
        sorter.App.refresh_example(app)
        app.example.configure.assert_called_once_with(
            text="Przykład: " + os.path.join("photos", "sorted", "Telefon", "2024", "04", "Filmy", "zdjęcie.jpg")
        )

    def test_worker_dry_run_copy_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "źródło"
            target = Path(folder) / "posortowane"
            source.mkdir()
            photo = source / "IMG_20240415_120000.jpg"
            Image.new("RGB", (8, 8), "blue").save(photo)
            original = photo.read_bytes()
            app = Mock()
            app.stop = threading.Event()
            app._ask_confirm.return_value = True
            job = dict(src=str(source), dst=str(target), base=str(target),
                       dry=True, use_hash=True, split_type=False, mode="year_month")

            sorter.App.run(app, job)
            self.assertFalse(target.exists())
            self.assertIn("Do skopiowania: 1", app._show_summary.call_args.args[0])

            job["dry"] = False
            sorter.App.run(app, job)
            result = target / "2024" / "04" / photo.name
            self.assertEqual(result.read_bytes(), original)
            self.assertEqual(photo.read_bytes(), original)

            sorter.App.run(app, job)
            self.assertIn("Skopiowano: 0, pominięto: 1, błędy: 0", app._show_summary.call_args.args[0])
            self.assertEqual(list(target.rglob("*.jpg")), [result])

    def test_heic_and_offline_geocoder_are_available(self):
        with tempfile.TemporaryDirectory() as folder:
            photo = Path(folder) / "IMG_20240415_120000.heic"
            Image.new("RGB", (8, 8), "blue").save(photo, format="HEIF")
            self.assertEqual(sorter.read_meta(str(photo))[0].date().isoformat(), "2024-04-15")
        self.assertTrue(sorter.place_batch([(52.2297, 21.0122)]))


if __name__ == "__main__":
    unittest.main()
