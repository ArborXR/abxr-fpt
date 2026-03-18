"""Download adb and aapt2 for the current platform."""
import io
import os
import platform
import stat
import sys
import urllib.request
import zipfile

TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools')

# aapt2 version from Google's Maven repository
AAPT2_VERSION = "8.7.3-12006047"


def get_platform_keys():
    """Return (platform_tools_key, aapt2_key) for the current OS."""
    system = platform.system().lower()
    if system == 'darwin':
        return 'darwin', 'osx'
    elif system == 'windows':
        return 'windows', 'windows'
    return 'linux', 'linux'


def download_and_extract(url, members_map):
    """Download zip/jar, extract specific files to TOOLS_DIR."""
    print(f"Downloading {url}...")
    resp = urllib.request.urlopen(url)
    with zipfile.ZipFile(io.BytesIO(resp.read())) as zf:
        for zip_path, local_name in members_map.items():
            for name in zf.namelist():
                if name.endswith(zip_path):
                    data = zf.read(name)
                    out_path = os.path.join(TOOLS_DIR, local_name)
                    with open(out_path, 'wb') as f:
                        f.write(data)
                    if sys.platform != 'win32':
                        os.chmod(out_path, os.stat(out_path).st_mode | stat.S_IEXEC)
                    print(f"  Extracted {local_name}")
                    break


def main():
    os.makedirs(TOOLS_DIR, exist_ok=True)
    pt_plat, aapt2_plat = get_platform_keys()
    ext = '.exe' if sys.platform == 'win32' else ''

    # Platform tools (adb) — direct zip download from Google
    pt_url = f"https://dl.google.com/android/repository/platform-tools-latest-{pt_plat}.zip"
    download_and_extract(pt_url, {f"adb{ext}": f"adb{ext}"})

    # aapt2 — from Google's Maven repository (JAR is a zip containing the binary)
    aapt2_url = (
        f"https://dl.google.com/dl/android/maven2/com/android/tools/build/aapt2/"
        f"{AAPT2_VERSION}/aapt2-{AAPT2_VERSION}-{aapt2_plat}.jar"
    )
    download_and_extract(aapt2_url, {f"aapt2{ext}": f"aapt2{ext}"})

    # On Windows, adb also needs AdbWinApi.dll and AdbWinUsbApi.dll
    if sys.platform == 'win32':
        download_and_extract(pt_url, {
            "AdbWinApi.dll": "AdbWinApi.dll",
            "AdbWinUsbApi.dll": "AdbWinUsbApi.dll",
        })

    print(f"\nTools in {TOOLS_DIR}:")
    for f in sorted(os.listdir(TOOLS_DIR)):
        print(f"  {f}")


if __name__ == '__main__':
    main()
