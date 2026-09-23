import json
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from generate_doc import (
    _calc_aspect_ratio,
    build_directory_tree,
    create_thumbnail_worker,
    extract_metadata_from_file,
    format_bytes,
    format_exposure_time,
    format_f_number,
    format_focal_length,
    generate_html_documentation,
    safe_serialize,
    url_encode_path,
)


class TestGenerateDoc(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.src_dir = Path(self.test_dir) / "source"
        self.dst_dir = Path(self.test_dir) / "output"
        self.src_dir.mkdir()
        self.dst_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_format_helpers(self):
        self.assertEqual(format_bytes(500), "500 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1024 * 1024 * 3), "3.00 MB")
        self.assertEqual(format_bytes(1024 * 1024 * 1024 * 2), "2.00 GB")

        self.assertEqual(format_exposure_time(0.008), "1/125s")
        self.assertEqual(format_exposure_time(0.004), "1/250s")
        self.assertEqual(format_exposure_time(2.0), "2s")
        self.assertEqual(format_exposure_time(2.5), "2.5s")
        self.assertIsNone(format_exposure_time(None))

        self.assertEqual(format_f_number(5.6), "f/5.6")
        self.assertEqual(format_f_number(2.0), "f/2")
        self.assertIsNone(format_f_number(None))

        self.assertEqual(format_focal_length(50.0), "50 mm")
        self.assertEqual(format_focal_length(50.0, 75.0), "50 mm (KB: 75 mm)")
        self.assertIsNone(format_focal_length(None))

        self.assertEqual(_calc_aspect_ratio(3000, 2000), "3:2")
        self.assertEqual(_calc_aspect_ratio(1920, 1080), "16:9")
        self.assertEqual(_calc_aspect_ratio(1000, 1000), "1:1")

    def test_safe_serialize(self):
        self.assertEqual(safe_serialize(b"test\x00"), "test")
        self.assertEqual(safe_serialize(123), 123)
        self.assertEqual(safe_serialize([1, b"a"]), [1, "a"])

    def test_url_encode_path(self):
        encoded = url_encode_path("Bilder/Malerei/01 Test & Äpfel/bild 01.jpg")
        self.assertIn("%26", encoded)
        self.assertIn("%C3%84pfel", encoded)
        self.assertIn("bild%2001.jpg", encoded)

    def test_build_directory_tree(self):
        directories = [
            "Malerei",
            "Malerei/Zyklus1",
            "Malerei/Zyklus2",
            "Fotografie",
        ]
        counts = {
            "Malerei": 5,
            "Malerei/Zyklus1": 10,
            "Malerei/Zyklus2": 15,
            "Fotografie": 20,
        }
        tree = build_directory_tree(directories, counts)
        self.assertEqual(tree["name"], "Hauptverzeichnis")
        self.assertEqual(tree["count"], 50)
        self.assertEqual(len(tree["children"]), 2)  # Malerei, Fotografie

        malerei_node = next(c for c in tree["children"] if c["name"] == "Malerei")
        self.assertEqual(malerei_node["count"], 30)  # 5 + 10 + 15
        self.assertEqual(len(malerei_node["children"]), 2)

    def test_metadata_extraction_and_thumbnail(self):
        # Dummy-Bild erstellen
        img_path = self.src_dir / "test_image.jpg"
        im = Image.new("RGB", (800, 600), color="blue")
        im.save(img_path, "JPEG")

        meta = extract_metadata_from_file(img_path, self.src_dir, 1)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.filename, "test_image.jpg")
        self.assertEqual(meta.width, 800)
        self.assertEqual(meta.height, 600)
        self.assertEqual(meta.format, "JPEG")

        # Thumbnail testen
        thumb_path = self.dst_dir / "thumb.jpg"
        success = create_thumbnail_worker((str(img_path), str(thumb_path), 200, 80))
        self.assertTrue(success)
        self.assertTrue(thumb_path.exists())

        with Image.open(thumb_path) as thumb_im:
            self.assertLessEqual(thumb_im.width, 200)
            self.assertLessEqual(thumb_im.height, 200)

    def test_generate_html_documentation_pipeline(self):
        # Verzeichnisse und Bilder vorbereiten
        sub1 = self.src_dir / "Ordner1"
        sub2 = self.src_dir / "Ordner2" / "Sub"
        sub1.mkdir(parents=True)
        sub2.mkdir(parents=True)

        for i, path in enumerate([self.src_dir / "root.jpg", sub1 / "img1.png", sub2 / "img2.jpg"]):
            im = Image.new("RGB", (400, 300), color=(i * 50, 100, 150))
            im.save(path)

        data = generate_html_documentation(
            source_dir=self.src_dir,
            target_dir=self.dst_dir,
            thumbnail_size=150,
            skip_thumbnails=False,
            verbose=False,
        )

        self.assertEqual(data["total_images"], 3)
        self.assertTrue((self.dst_dir / "index.html").exists())
        self.assertTrue((self.dst_dir / "styles.css").exists())
        self.assertTrue((self.dst_dir / "app.js").exists())
        self.assertTrue((self.dst_dir / "data.js").exists())

        # data.js Inhalt prüfen
        data_js_content = (self.dst_dir / "data.js").read_text(encoding="utf-8")
        self.assertTrue(data_js_content.startswith("/* Automatisch generierte"))
        self.assertIn("window.DOCUMENTATION_DATA =", data_js_content)


if __name__ == "__main__":
    unittest.main()
