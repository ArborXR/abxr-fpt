#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#
"""Disk space checks, so a run that can't fit stops with a clear message instead of failing partway.

Two disks matter: this computer's temp folder, where each item of the package is copied before it's pushed, and the
headset's storage, which has to hold everything the package loads.
"""

import shutil

GB = 1024 ** 3
# Room kept free on top of what's needed: Android and desktop systems both misbehave when a disk is completely full.
SPACE_HEADROOM_BYTES = 1 * GB

TEMP_HINT = "Free up space, or point the temp folder at a bigger drive: TMPDIR on macOS and Linux, TEMP on Windows."


class NotEnoughSpaceError(Exception):
    """A disk can't hold what this run needs. `short` is the reason shown on the FPD display."""

    def __init__(self, message, short):
        super().__init__(message)
        self.short = short


def format_size(size_bytes):
    """Sizes the way Windows Explorer and macOS Finder's "GB" read closest to (1 GB = 1024^3 bytes)."""
    return f"{size_bytes / GB:.1f} GB"


def parse_df_available_bytes(df_output):
    """Free bytes from `df -k <path>` on the headset, or None if it can't be read. Handles a long filesystem name
    printed on its own line, with the numbers on the next."""
    lines = [line for line in df_output.strip().splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    numbers = [token for token in lines[-1].split() if token.isdigit()]
    if len(numbers) < 3:
        return None
    # 1K-blocks, Used, Available.
    return int(numbers[2]) * 1024


def headset_space_needed(content_bytes):
    """What a headset needs free before a package is loaded: its content plus 5% and the headroom."""
    return int(content_bytes * 1.05) + SPACE_HEADROOM_BYTES


def check_headset_space(free_bytes, content_bytes):
    """Raise NotEnoughSpaceError when the headset can't hold the package's content."""
    needed = headset_space_needed(content_bytes)
    if free_bytes < needed:
        raise NotEnoughSpaceError(
            f"Not enough space on the headset: this package needs {format_size(needed)} and the headset has "
            f"{format_size(free_bytes)} free. Nothing on the headset was changed. Remove content from it or use a "
            "headset with more storage. When re-provisioning a headset that already has this content, pass "
            "--skip-space-check.",
            "Headset full",
        )


def temp_space_plan(free_bytes, per_headset_bytes, max_parallel):
    """(enough, how many headsets at once would fit) for this computer's temp folder."""
    usable = free_bytes - SPACE_HEADROOM_BYTES
    if per_headset_bytes <= 0:
        return usable >= 0, max_parallel if usable >= 0 else 0
    fits = max(0, usable // per_headset_bytes)
    return fits >= max_parallel, int(min(fits, max_parallel))


def computer_space_message(package_name, free_bytes, per_headset_bytes, max_parallel, temp_dir):
    """Lines explaining why this computer can't run the package at this parallelism, or None when it can."""
    enough, fits = temp_space_plan(free_bytes, per_headset_bytes, max_parallel)
    if enough:
        return None
    needed = per_headset_bytes * max_parallel + SPACE_HEADROOM_BYTES
    lines = [
        f"Not enough space on this computer for {package_name} to run {max_parallel} headset(s) at once: that needs "
        f"{format_size(needed)} in the temp folder ({temp_dir}), and it has {format_size(free_bytes)} free. "
        f"Each headset needs {format_size(per_headset_bytes)} there while it runs.",
    ]
    if fits:
        lines.append(f"Running {fits} at a time instead. To run more, free up space or point the temp folder at a bigger drive: TMPDIR on macOS and Linux, TEMP on Windows.")
    else:
        lines.append(f"Not even one headset fits, so the tool can't start. {TEMP_HINT}")
    return lines


def require_free_space(directory, needed_bytes, what):
    """Raise NotEnoughSpaceError when `directory`'s disk can't take `needed_bytes` more, plus the headroom."""
    free = shutil.disk_usage(directory).free
    needed = needed_bytes + SPACE_HEADROOM_BYTES
    if free < needed:
        raise NotEnoughSpaceError(
            f"Not enough space on this computer to {what}: needs {format_size(needed)}, has {format_size(free)} "
            f"free in {directory}. {TEMP_HINT}",
            "PC disk full",
        )
