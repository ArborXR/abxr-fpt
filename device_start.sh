#!/bin/bash
#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#

gpio_status=$(raspi-gpio get 21)

if echo "$gpio_status" | grep -q "level=1"; then
    loop_device=$(losetup --show -fP /home/abxr/mass_storage.img)
    mount $loop_device /home/abxr/abxr

    if [ -f /home/abxr/abxr/field-provisioning-tools-update.zip ]; then
        unzip -o /home/abxr/abxr/field-provisioning-tools-update.zip -d /home/abxr/Projects/field-provisioning-tools
        rm /home/abxr/abxr/field-provisioning-tools-update.zip
	    su abxr -c 'cd /home/abxr/Projects/field-provisioning-tools; . ./venv/bin/activate; ./install.sh'
    fi

    su abxr -c 'cd /home/abxr/Projects/field-provisioning-tools; . ./venv/bin/activate; abxr-provision'
else
    su abxr -c 'cd /home/abxr/Projects/field-provisioning-tools; . ./venv/bin/activate; abxr-display-setup-mode'
fi

