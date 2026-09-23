import unittest
import tempfile
import shutil
from pathlib import Path
from main import copy_cleaned_images, is_converted_dir, is_dot_file_or_dir


class TestCleanedImagesCopy(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.src_dir = Path(self.test_dir) / "source"
        self.dst_dir = Path(self.test_dir) / "target"
        self.src_dir.mkdir()
        self.dst_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_filter_predicates(self):
        self.assertTrue(is_converted_dir("Converted"))
        self.assertTrue(is_converted_dir("Converted PS"))
        self.assertTrue(is_converted_dir("converted PS"))
        self.assertTrue(is_converted_dir("Converted by PS"))
        self.assertTrue(is_converted_dir("Converted korr gh"))
        self.assertFalse(is_converted_dir("Originals"))
        self.assertFalse(is_converted_dir("Photos"))

        self.assertTrue(is_dot_file_or_dir(".DS_Store"))
        self.assertTrue(is_dot_file_or_dir("._image.jpg"))
        self.assertTrue(is_dot_file_or_dir(".hidden_folder"))
        self.assertFalse(is_dot_file_or_dir("image.jpg"))
        self.assertFalse(is_dot_file_or_dir("folder"))

    def test_copy_structure_and_filters(self):
        # Create nested directory structure
        (self.src_dir / "Sub1" / "Sub2").mkdir(parents=True)
        (self.src_dir / "Converted").mkdir()
        (self.src_dir / "Sub1" / "Converted PS").mkdir()
        (self.src_dir / ".hidden_dir").mkdir()

        # Create valid files
        valid_img1 = self.src_dir / "img1.jpg"
        valid_img1.write_text("image1")

        valid_img2 = self.src_dir / "Sub1" / "Sub2" / "img2.JPEG"
        valid_img2.write_text("image2")

        # Create files that start with dot
        dot_file1 = self.src_dir / ".DS_Store"
        dot_file1.write_text("metadata")

        dot_file2 = self.src_dir / "Sub1" / "._img1.jpg"
        dot_file2.write_text("apple double")

        # Create files inside converted directories
        conv_file1 = self.src_dir / "Converted" / "conv1.jpg"
        conv_file1.write_text("converted1")

        conv_file2 = self.src_dir / "Sub1" / "Converted PS" / "conv2.jpg"
        conv_file2.write_text("converted2")

        # Create file in hidden directory
        hidden_img = self.src_dir / ".hidden_dir" / "hidden.jpg"
        hidden_img.write_text("hidden")

        # Run copy function
        stats = copy_cleaned_images(self.src_dir, self.dst_dir, verbose=False)

        # Assert statistics
        self.assertEqual(stats.copied_count, 2)
        self.assertEqual(stats.skipped_dot_files_count, 2)

        # Check copied files in target
        target_img1 = self.dst_dir / "img1.jpg"
        target_img2 = self.dst_dir / "Sub1" / "Sub2" / "img2.JPEG"

        self.assertTrue(target_img1.exists())
        self.assertTrue(target_img2.exists())
        self.assertEqual(target_img1.read_text(), "image1")
        self.assertEqual(target_img2.read_text(), "image2")

        # Check that excluded files and folders were NOT copied
        self.assertFalse((self.dst_dir / ".DS_Store").exists())
        self.assertFalse((self.dst_dir / "Sub1" / "._img1.jpg").exists())
        self.assertFalse((self.dst_dir / "Converted").exists())
        self.assertFalse((self.dst_dir / "Sub1" / "Converted PS").exists())
        self.assertFalse((self.dst_dir / ".hidden_dir").exists())

    def test_dry_run(self):
        (self.src_dir / "test.jpg").write_text("content")
        stats = copy_cleaned_images(self.src_dir, self.dst_dir, dry_run=True, verbose=False)
        self.assertEqual(stats.copied_count, 1)
        self.assertFalse((self.dst_dir / "test.jpg").exists())

    def test_cli_parser_options(self):
        import argparse
        import sys
        from unittest.mock import patch
        from main import main

        test_args = ["main.py", "--source", str(self.src_dir), "--target", str(self.dst_dir), "--dry-run", "--quiet"]
        with patch.object(sys, "argv", test_args):
            # Sollte ohne Fehler durchlaufen
            main()


if __name__ == "__main__":
    unittest.main()
