#!/bin/bash
#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#

rm -rf build
mkdir build

git archive --format=zip HEAD -o build/repo.zip

unzip build/repo.zip -d build

python3 -m venv build/venv
source build/venv/bin/activate
pip install -r requirements.txt
deactivate

cd build
zip -r field-provisioning-tools-update.zip .
cd ..

rm build/repo.zip