#!/bin/bash
set -e
python scripts/download_platform_tools.py
pip install pyinstaller
pip install --no-deps -e .
pyinstaller pyinstaller/abxr-provision.spec
echo "Binary: dist/abxr-provision"
