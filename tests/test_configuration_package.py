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
            "images/Unknown/a/thing.png",
            "images/logo.png",
        )

        self.assertEqual(
            {
                f"{PACKAGE_ID}/apps/com.example.obb/main.1.com.example.obb.obb": "/sdcard/Android/obb/com.example.obb/main.1.com.example.obb.obb",
                f"{PACKAGE_ID}/files/~/sdcard/Movies/training/scene 1.mp4": "/sdcard/Movies/training/scene 1.mp4",
                f"{PACKAGE_ID}/videos/~/sdcard/ArborXR/videos/abc123.mp4": "/sdcard/ArborXR/Videos/abc123.mp4",
                f"{PACKAGE_ID}/images/AppIcons/icon.png": "/sdcard/ArborXR/Media/AppIcons/icon.png",
                f"{PACKAGE_ID}/images/Wallpapers/wallpaper.png": "/sdcard/ArborXR/Media/Wallpapers/wallpaper.png",
                f"{PACKAGE_ID}/images/Unknown/a/thing.png": "/sdcard/ArborXR/Media/Unknown/a/thing.png",
                f"{PACKAGE_ID}/images/logo.png": "/sdcard/ArborXR/Media/logo.png",
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

    def test_prefers_a_settings_json_at_the_zip_root(self):
        path = Path(self.directory.name) / "flat.zip"
        with zipfile.ZipFile(path, "w") as zip_file:
            zip_file.writestr("settings.json", json.dumps({"version": "2.0.0", "deviceModel": {"name": "Quest 3S"}}))
            zip_file.writestr("client/app.xrdm.client-2026.47.0.apk", b"apk")
            zip_file.writestr("videos/settings.json", b"{}")
            zip_file.writestr("apps/com.example.app.apk", b"x")
        package = ConfigurationPackage(path)
        self.assertEqual("", package.root_prefix)
        self.assertEqual(["apps/com.example.app.apk"], package.apps)

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


class ConfigurationPackageSizeTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = Path(self.directory.name) / "package.zip"
        with zipfile.ZipFile(path, "w") as zip_file:
            zip_file.writestr(f"{PACKAGE_ID}/settings.json", json.dumps({"version": "2.0.0", "deviceModel": {"name": "Quest 3S"}}))
            zip_file.writestr(f"{PACKAGE_ID}/client/app.xrdm.client-2026.47.0-arm64-v8a.apk", b"c" * 10)
            zip_file.writestr(f"{PACKAGE_ID}/apps/com.example.app.apk", b"a" * 100)
            zip_file.writestr(f"{PACKAGE_ID}/apps/com.example.big.zip", b"b" * 300)
            zip_file.writestr(f"{PACKAGE_ID}/files/~sdcard/Movies/intro.mp4", b"f" * 50)
        self.package = ConfigurationPackage(path)

    def tearDown(self):
        self.package.zip_file.close()
        self.directory.cleanup()

    def test_content_size_counts_apps_bundles_and_files_but_not_the_client(self):
        self.assertEqual(self.package.content_size(), 100 + 300 + 50)
        self.assertEqual(self.package.client_and_launcher_size(), 10)

    def test_an_app_bundle_needs_its_size_and_its_unpacked_size_in_temp(self):
        # Not a valid inner zip, so its unpacked size falls back to its own size.
        self.assertEqual(self.package.largest_item_size(), 600)

    def test_an_app_bundle_counts_what_it_unpacks_to(self):
        import io
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("game.apk", b"a" * 5000)
            bundle.writestr("main.1.com.example.game.obb", b"o" * 20000)
        path = Path(self.directory.name) / "bundle-package.zip"
        with zipfile.ZipFile(path, "w") as zip_file:
            zip_file.writestr(f"{PACKAGE_ID}/settings.json", json.dumps({"version": "2.0.0", "deviceModel": {"name": "Quest 3S"}}))
            zip_file.writestr(f"{PACKAGE_ID}/client/app.xrdm.client-2026.47.0-arm64-v8a.apk", b"c")
            zip_file.writestr(f"{PACKAGE_ID}/apps/com.example.game.zip", inner.getvalue())
        with ConfigurationPackage(path) as package:
            bundle_size = len(inner.getvalue())
            self.assertLess(bundle_size, 25000)
            self.assertEqual(package.content_size(), 25000)
            self.assertEqual(package.largest_item_size(), bundle_size + 25000)
        self.assertIsNone(package.zip_file.fp)

    def test_copying_out_stops_when_the_computer_is_full(self):
        from unittest import mock
        from collections import namedtuple
        from abxr.disk_space import NotEnoughSpaceError

        app = self.package.apps[0]
        with tempfile.TemporaryDirectory() as out, mock.patch("abxr.disk_space.shutil.disk_usage", return_value=namedtuple("Usage", "total used free")(0, 0, 10)):
            with self.assertRaises(NotEnoughSpaceError):
                self.package.extract_item_flat(app, out)
            self.assertEqual(list(Path(out).iterdir()), [])
