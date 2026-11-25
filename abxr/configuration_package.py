#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#

import json
import re
import shutil
import uuid
from pathlib import Path
import zipfile

from abxr.disk_space import require_free_space
from abxr.log import log


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
        self._bundle_sizes = {}
        self.settings_entry = None
        self.apps = []
        self.obb_packaged_apps = []
        self.obbs = []
        self.files = []
        self.videos = []
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
        # The package root is the folder that holds settings.json: the package id for portal builds, or the zip
        # root. Using the first entry instead breaks when e.g. a .DS_Store sorts first.
        settings_files = [entry for entry in self._entries() if entry.lstrip("/").split("/")[-1] == "settings.json"]
        # A settings.json at the zip root wins; otherwise it must sit in a single top-level folder.
        candidates = [entry for entry in settings_files if entry.lstrip("/").count("/") == 0]
        if not candidates:
            candidates = [entry for entry in settings_files if entry.lstrip("/").count("/") == 1]
        if len(candidates) == 0:
            raise Exception("settings.json not found at the package root or in a top-level folder. If the package was re-zipped, zip the package folder itself.")
        if len(candidates) > 1:
            raise Exception(f"More than one package in this zip (settings.json in {', '.join(candidates)}). Provision one package per zip.")

        self.settings_entry = candidates[0]
        relative = self.settings_entry.lstrip("/")
        self.root_prefix = relative[: relative.rindex("/") + 1] if "/" in relative else ""

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
            # images/<AppIcons|VideoIcons|...>/<file> goes to /sdcard/ArborXR/Media/<folder>/<file>, as in the Device
            # Setup App (ImageType.toDirectoryName). Other folders don't come from the portal; they keep their path
            # under Media so two files with the same name can't overwrite each other.
            return f"/sdcard/ArborXR/Media/{remainder}"

        raise Exception(f"No device path for package entry {entry}")

    def pushes(self):
        """Every entry that's pushed as a plain file, with its device path."""
        entries = self.obbs + self.files + self.videos + self.images
        return [(entry, self.device_path(entry)) for entry in entries]

    def created_at(self):
        try:
            return self.settings["createdAt"]
        except Exception as e:
            log(f"Error getting created at: {e}")
            return None

    def device_group(self):
        try:
            if self.is_xrdm2:
                return self.settings["group"]
            else:
                return self.settings["deviceGroup"]
        except Exception as e:
            log(f"Error getting device group: {e}")
            return None

    def model_name(self):
        try:
            return self.settings["deviceModel"]["name"]
        except Exception as e:
            log(f"Error getting device model name: {e}")
            return None
        
    def model_names(self):
        try:
            if self.is_xrdm2:
                return self.settings["deviceModel"]["enrollmentIdentifiers"]
            else:
                return self.settings["deviceModel"]["modelNames"]
        except Exception as e:
            log(f"Error getting device model names: {e}")
            return None
        
    def extract_item(self, item, output_path):
        try:
            path = self.zip_file.extract(item, output_path)
            return path
        except Exception as e:
            raise Exception(f"Error extracting {item} to {output_path}: {e}")
        
    def close(self):
        if self.zip_file:
            self.zip_file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def entry_size(self, entry):
        return self.zip_file.getinfo(entry).file_size if entry else 0

    def bundle_unpacked_size(self, entry):
        """What an app bundle zip unpacks to (its APK and OBBs), read from its own directory. Falls back to the
        bundle's size when it can't be read."""
        if entry not in self._bundle_sizes:
            try:
                with self.zip_file.open(entry) as raw, zipfile.ZipFile(raw) as bundle:
                    size = sum(info.file_size for info in bundle.infolist())
            except Exception:
                size = self.entry_size(entry)
            self._bundle_sizes[entry] = size
        return self._bundle_sizes[entry]

    def content_size(self):
        """Bytes the package's apps, unpacked bundles and files take on a headset."""
        entries = self.apps + [entry for entry, _ in self.pushes()]
        return sum(self.entry_size(entry) for entry in entries) + sum(self.bundle_unpacked_size(entry) for entry in self.obb_packaged_apps)

    def client_and_launcher_size(self):
        return self.entry_size(self.client_apk) + self.entry_size(self.launcher_apk)

    def temp_space_needed(self, entry):
        """Temp space one item needs while it's loaded: an app bundle zip is copied out, then unpacked next to it."""
        size = self.entry_size(entry)
        return size + self.bundle_unpacked_size(entry) if entry in self.obb_packaged_apps else size

    def largest_item_size(self):
        entries = self.apps + self.obb_packaged_apps + [entry for entry, _ in self.pushes()]
        return max((self.temp_space_needed(entry) for entry in entries), default=0)

    def extract_item_flat(self, item, output_path):
        """Extract one entry to a short random name with the same extension, like the Device Setup App's GUID
        names: a package's full paths can pass Windows' 260-character limit inside a temp directory."""
        require_free_space(output_path, self.entry_size(item), f"copy {Path(item).name} out of the package")
        target = Path(output_path) / f"{uuid.uuid4().hex}{Path(item).suffix}"
        try:
            with self.zip_file.open(item) as source, open(target, "wb") as destination:
                shutil.copyfileobj(source, destination, 1024 * 1024)
            return target
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
            with self.zip_file.open(self.settings_entry) as settings_file:
                return settings_file.read()
        except Exception as e:
            raise Exception(f"Error reading settings.json from zip: {e}")
