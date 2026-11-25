import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from abxr.configuration_package import ConfigurationPackage

PACKAGE_ID = "9f1c2d3e-0000-4000-8000-000000000001"


def build_package(directory, entries, first_entry=None):
    path = Path(directory) / "package.zip"
    settings = {
        "version": "2.0.0",
        "token": "token",
        "group": {"id": "group", "name": "Final"},
        "deviceModel": {"name": "Quest 3S", "enrollmentIdentifiers": ["Quest 3S"]},
        "configurations": {},
    }
    with zipfile.ZipFile(path, "w") as zip_file:
        if first_entry:
            zip_file.writestr(first_entry, b"x")
        # Same shape as the portal's builds: settings.json first, under the package id.
        zip_file.writestr(f"{PACKAGE_ID}/settings.json", json.dumps(settings))
        zip_file.writestr(f"{PACKAGE_ID}/client/app.xrdm.client-2026.47.0-arm64-v8a.apk", b"apk")
        for entry in entries:
            zip_file.writestr(f"{PACKAGE_ID}/{entry}", b"x")
    return ConfigurationPackage(path)


class ConfigurationPackageTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.directory.cleanup()

    def package(self, *entries):
        return build_package(self.directory.name, entries)

    def test_sorts_entries_by_top_level_folder_only(self):
        package = self.package(
            "apps/com.example.app.apk",
            "apps/com.example.bundle.zip",
            "apps/com.example.obb/main.1.com.example.obb.obb",
            "files/~/sdcard/videos/intro.mp4",
            "files/~/sdcard/Download/apps/readme.txt",
            "videos/~/sdcard/ArborXR/videos/abc123.mp4",
            "images/AppIcons/icon.png",
        )

        self.assertEqual([f"{PACKAGE_ID}/apps/com.example.app.apk"], package.apps)
        self.assertEqual([f"{PACKAGE_ID}/apps/com.example.bundle.zip"], package.obb_packaged_apps)
        self.assertEqual([f"{PACKAGE_ID}/apps/com.example.obb/main.1.com.example.obb.obb"], package.obbs)
        self.assertEqual(
            [f"{PACKAGE_ID}/files/~/sdcard/videos/intro.mp4", f"{PACKAGE_ID}/files/~/sdcard/Download/apps/readme.txt"],
            package.files,
        )
        self.assertEqual([f"{PACKAGE_ID}/videos/~/sdcard/ArborXR/videos/abc123.mp4"], package.videos)
        self.assertEqual([f"{PACKAGE_ID}/images/AppIcons/icon.png"], package.images)

    def test_device_paths_match_the_device_setup_app(self):
        package = self.package(
            "apps/com.example.obb/main.1.com.example.obb.obb",
            "files/~/sdcard/Movies/training/scene 1.mp4",
            "videos/~/sdcard/ArborXR/videos/abc123.mp4",
            "images/AppIcons/icon.png",
            "images/Wallpapers/wallpaper.png",
            "images/Unknown/thing.png",
            "launcher-media/backgrounds/home.png",
        )

        self.assertEqual(
            {
                f"{PACKAGE_ID}/apps/com.example.obb/main.1.com.example.obb.obb": "/sdcard/Android/obb/com.example.obb/main.1.com.example.obb.obb",
                f"{PACKAGE_ID}/files/~/sdcard/Movies/training/scene 1.mp4": "/sdcard/Movies/training/scene 1.mp4",
                f"{PACKAGE_ID}/videos/~/sdcard/ArborXR/videos/abc123.mp4": "/sdcard/ArborXR/Videos/abc123.mp4",
                f"{PACKAGE_ID}/images/AppIcons/icon.png": "/sdcard/ArborXR/Media/AppIcons/icon.png",
                f"{PACKAGE_ID}/images/Wallpapers/wallpaper.png": "/sdcard/ArborXR/Media/Wallpapers/wallpaper.png",
                f"{PACKAGE_ID}/images/Unknown/thing.png": "/sdcard/thing.png",
                f"{PACKAGE_ID}/launcher-media/backgrounds/home.png": "/sdcard/launcher-media/backgrounds/home.png",
            },
            dict(package.pushes()),
        )

    def test_handles_entries_with_a_leading_slash(self):
        # The portal adds entries as "/{id}/...". ZipStream strips the slash, but older packages may keep it.
        package = self.package()
        self.assertEqual(("files", "~/sdcard/a.txt"), package.entry_category(f"/{PACKAGE_ID}/files/~/sdcard/a.txt"))

    def test_finds_the_root_from_settings_json_not_the_first_entry(self):
        package = build_package(self.directory.name, ["apps/com.example.app.apk"], first_entry=".DS_Store")
        self.assertEqual(f"{PACKAGE_ID}/", package.root_prefix)
        self.assertEqual([f"{PACKAGE_ID}/apps/com.example.app.apk"], package.apps)

    def test_ignores_settings_json_files_inside_the_content(self):
        package = self.package("files/~/sdcard/Android/data/com.example/files/settings.json")
        self.assertEqual(f"{PACKAGE_ID}/settings.json", package.settings_entry)
        self.assertEqual("2.0.0", package.version)

    def test_extracts_entries_to_short_names(self):
        entry = f"{PACKAGE_ID}/files/~/sdcard/Android/data/com.example/files/" + "deep/" * 30 + "scene.bin"
        package = self.package(entry.split("/", 1)[1])
        with tempfile.TemporaryDirectory() as output:
            extracted = package.extract_item_flat(entry, output)
            self.assertEqual(".bin", extracted.suffix)
            self.assertLess(len(extracted.name), 40)
            self.assertEqual(b"x", extracted.read_bytes())

    def test_reads_a_v2_package(self):
        package = self.package()
        self.assertTrue(package.is_xrdm2)
        self.assertEqual("Quest 3S", package.model_name())
        self.assertEqual(f"{PACKAGE_ID}/", package.root_prefix)


if __name__ == "__main__":
    unittest.main()
