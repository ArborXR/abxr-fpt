#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#

import json
import re
from pathlib import Path
import zipfile

# Image folders inside a package's images/ directory. The Device Setup App puts each one under
# /sdcard/ArborXR/Media/<folder>/ (device repo, SetupApp.Core/ConfigPackage.fs, ImageType.toDirectoryName).
IMAGE_DIRECTORIES = [
    "AppIcons",
    "VideoIcons",
    "WebXrIcons",
    "OrganizationIcons",
    "EnvironmentBanners",
    "EnvironmentBackgrounds",
    "EnvironmentSkyboxes",
    "Wallpapers",
]

class AbxrClientApk:
    PACKAGE_NAME = "app.xrdm.client"

    def __init__(self, path):
        if type(path) == str:
            path = Path(path)

        if not path.exists():
            raise Exception(f"Error: {path} does not exist.")
        
        self.path = path
        self.version = None

        self._load_version()

    def _load_version(self):
        self.version = self.get_client_version_from_filename(self.path)

    def get_client_version_from_filename(self, filename):
        pattern = r'(\d{4}\.\d{1,2}\.\d+)'
        match = re.search(pattern, str(filename))
        if match:
            return match.group(1)
        return None
    
class AbxrLauncherApk:
    PACKAGE_NAME = "app.xrdm.launcher"

    def __init__(self, path):
        if type(path) == str:
            path = Path(path)

        if not path.exists():
            raise Exception(f"Error: {path} does not exist.")
        
        self.path = path
        self.version = None

        self._load_version()

    def _load_version(self):
        self.version = self.get_launcher_version_from_filename(self.path)

    def get_launcher_version_from_filename(self, apk_filename):
        pattern = r'(\d{4}\.\d{1,2}\.\d+)'
        match = re.search(pattern, str(apk_filename))
        if match:
            return match.group(1)
        return None


class ConfigurationPackage:
    def __init__(self, path):
        if type(path) == str:
            path = Path(path)

        self.path = path
        self.version = None
        self.is_xrdm2 = False
        self.settings = None
        self.zip_file = None
        self.client_apk = None
        self.launcher_apk = None

        self.root_prefix = ""
        self.apps = []
        self.obb_packaged_apps = []
        self.obbs = []
        self.files = []
        self.videos = []
        self.launcher_media = []
        self.images = []

        self._open()
        self._find_root_prefix()
        self._load_settings_json()

        self._find_client_apk()
        self._find_launcher_apk()
        self._find_content()

    def _open(self):
        try:
            self.zip_file = zipfile.ZipFile(self.path, 'r')
        except zipfile.BadZipFile:
            raise Exception(f"Error: {self.path} is not a valid zip file")

    def _load_settings_json(self):
        try:
            self.settings = json.loads(self.read_settings_json_from_zip().decode('utf-8'))
            self.version = self.settings.get("version", None)
            if self.version == "2.0.0":
                self.is_xrdm2 = True
                print("Found a v2 config package")
        except Exception as e:
            raise Exception(f"Error parsing settings.json: {e}")
        
    def _find_client_apk(self):
        client_apk = [f for f in self.zip_file.namelist() if 'client/app.xrdm.client' in f]
        
        if len(client_apk) > 1:
            raise Exception("Multiple ArborXR APK files found in the zip file.")
        elif len(client_apk) == 0:
            raise Exception("ArborXR Client APK not found in the zip file.")

        self.client_apk = client_apk[0]

    def _find_launcher_apk(self):
        launcher_apk = [f for f in self.zip_file.namelist() if 'launcher/app.xrdm.launcher' in f]

        if len(launcher_apk) > 1:
            raise Exception("Multiple ArborXR APK files found in the zip file.")
        elif len(launcher_apk) == 1:         
            self.launcher_apk = launcher_apk[0]
        else:
            self.launcher_apk = None

    def _entries(self):
        return [f for f in self.zip_file.namelist() if not f.endswith("/") and "MACOSX" not in f]

    def _find_root_prefix(self):
        # A package has one root folder (its id). Same rule as the Device Setup App: the first file's leading folder.
        entries = self._entries()
        if entries:
            first = entries[0].lstrip("/")
            if "/" in first:
                self.root_prefix = first[: first.index("/") + 1]

    def entry_category(self, entry):
        """The entry's top-level folder (apps, files, videos, images, ...) and the rest of its path."""
        relative = entry.lstrip("/")
        if self.root_prefix and relative.startswith(self.root_prefix):
            relative = relative[len(self.root_prefix):]

        if "/" not in relative:
            return relative.lower(), ""

        category, remainder = relative.split("/", 1)
        return category.lower(), remainder

    def _find_content(self):
        # Sort entries by their top-level folder only. A substring match would put e.g.
        # files/~/sdcard/videos/x.mp4 in both files and videos.
        for entry in self._entries():
            category, _ = self.entry_category(entry)
            lower = entry.lower()

            if category == "apps":
                if lower.endswith(".apk"):
                    self.apps.append(entry)
                elif lower.endswith(".zip"):
                    self.obb_packaged_apps.append(entry)
                elif lower.endswith(".obb"):
                    self.obbs.append(entry)
            elif category == "files":
                self.files.append(entry)
            elif category == "videos":
                self.videos.append(entry)
            elif category == "images":
                self.images.append(entry)
            elif category == "launcher-media":
                self.launcher_media.append(entry)

    def device_path(self, entry):
        """Where an entry goes on the device, matching the Device Setup App (SetupApp.Core/ConfigPackage.fs)."""
        category, remainder = self.entry_category(entry)
        file_name = remainder.split("/")[-1]

        if category == "apps":
            parts = remainder.split("/")
            package_name = parts[0] if len(parts) >= 2 else "unknown"
            return f"/sdcard/Android/obb/{package_name}/{file_name}"

        if category == "files":
            device_relative = remainder[2:] if remainder.startswith("~/") else remainder
            return f"/{device_relative}"

        if category == "videos":
            return f"/sdcard/ArborXR/Videos/{file_name}"

        if category == "images":
            image_directory, _, after_directory = remainder.partition("/")
            if image_directory in IMAGE_DIRECTORIES:
                return f"/sdcard/ArborXR/Media/{image_directory}/{after_directory}"
            return "/sdcard"

        if category == "launcher-media":
            return f"/sdcard/{remainder}"

        raise Exception(f"No device path for package entry {entry}")

    def pushes(self):
        """Every entry that's pushed as a plain file, with its device path."""
        entries = self.obbs + self.files + self.videos + self.images + self.launcher_media
        return [(entry, self.device_path(entry)) for entry in entries]

    def created_at(self):
        try:
            return self.settings["createdAt"]
        except Exception as e:
            print("Error getting created at: {e}")
            return None

    def device_group(self):
        try:
            if self.is_xrdm2:
                return self.settings["group"]
            else:
                return self.settings["deviceGroup"]
        except Exception as e:
            print("Error getting device group: {e}")
            return None

    def model_name(self):
        try:
            return self.settings["deviceModel"]["name"]
        except Exception as e:
            print("Error getting device model name: {e}")
            return None
        
    def model_names(self):
        try:
            if self.is_xrdm2:
                return self.settings["deviceModel"]["enrollmentIdentifiers"]
            else:
                return self.settings["deviceModel"]["modelNames"]
        except Exception as e:
            print("Error getting device model names: {e}")
            return None
        
    def extract_item(self, item, output_path):
        try:
            path = self.zip_file.extract(item, output_path)
            return path
        except Exception as e:
            raise Exception(f"Error extracting {item} to {output_path}: {e}")
        
    def extract_client_apk_from_zip(self, output_path):        
        try:
            path = self.extract_item(self.client_apk, output_path)
            return AbxrClientApk(path)
        except Exception as e:
            raise Exception(f"Error extracting ArborXR APK from zip: {e}")
    
    def read_settings_json_from_zip(self):
        try:
            settings_json_locations = [f for f in self.zip_file.namelist() if 'settings.json' in f]
            if len(settings_json_locations) > 1:
                raise Exception("Multiple settings.json files found in the zip file.")
            
            settings_json_location = settings_json_locations[0]

            if settings_json_location:
                with self.zip_file.open(settings_json_location) as settings_file:
                    return settings_file.read()
            else:
                raise Exception("settings.json not found in the zip file.")
        except Exception as e:
            raise Exception(f"Error reading settings.json from zip: {e}")
        