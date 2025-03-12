#!/bin/bash

if [ -z "$1" ]; then
    echo "Usage: $0 <path_to_configuration_package>"
    exit 1
fi

config_package="$1"

# Get a list of connected devices using "abxr-provision -l"
device_list=$(abxr-provision -l)

# Convert the device list to an array
IFS=$'\n' read -r -d '' -a devices <<< "$device_list"

# Print the collected device serial numbers
echo "Connected devices:"
for device in "${devices[@]}"; do
    echo "$device"
done

# For each device, run "abxr-provision -s <device_serial> -p <config_package>"
for device in "${devices[@]}"; do
    abxr-provision -s "$device" -p "$config_package" &
done

# Wait for all devices to finish updating
wait
