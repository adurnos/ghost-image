# ghost-photo

<!-- Add an asciinema demo when available. -->

A lightweight Python command-line utility built in an effort to improve visual privacy. ghost-photo removes embedded metadata (EXIF, GPS, camera profiles) and adds small pixel perturbations intended to minimize visible changes while attempting to make automated image matching harder. These changes do not guarantee invisibility or protection from AI recognition.

Built with a strict local-first security mandate, the tool never touches the network and uses atomic file replacement to avoid partial writes to original images.

**TO DOWNLOAD, USE THIS COMMAND IN YOUR TERMINAL:**

```bash
pip install ghost-photo
```

## Why Visual Privacy Matters

When you take a photo, your device may embed hidden EXIF data directly into the file. Anyone who downloads the image can read metadata left in it. ghost-photo removes this metadata in an effort to reduce privacy risks:

- Physical Safety and Stalking: Photos can store exact GPS coordinates. Posting pictures of items on marketplaces like eBay, sharing family photos of your kids, or uploading casual snapshots can accidentally expose your home address to strangers.
- Source and Identity Protection: Device serial numbers, precise timestamps, and camera profiles can reveal device or capture details, risking anonymity for journalists protecting sources, whistleblowers, or security researchers.
- AI Scraping Countermeasures: Automated scrapers and facial recognition networks index images based on visual structures and hashes. Our small pixel perturbations attempt to interfere with automated matching while minimizing visible changes. Their effectiveness against these systems has not been established.

## Features

- Metadata Removal: Removes source EXIF, GPS, embedded timestamps, and camera profiles. Filesystem timestamps are not anonymized.
- Pixel Perturbation: Adds a structured, high-frequency mask bounded to plus or minus two color levels before encoding, in an effort to interfere with automated matching. Lossy encoding can introduce larger changes.
- Atomic Operations: Verifies encoded output in RAM, writes it to a temporary file beside the source, then atomically replaces the original.
- Zero Network Footprint: Operates 100% locally with no web or analytics dependencies.
- Directory Scanning: Recursively processes images and skips non-image files, reporting failures without stopping the batch.

## Installation

Requires Python 3.10 or newer.

Install the utility globally via PyPI to register the `gp` terminal command:

```bash
pip install ghost-photo
```

## Usage

### 1. Cloak Images

Process a single file or a whole directory of images:

```bash
gp cloak photo.jpg
gp cloak ./my_photos/
```

### 2. Configuration Management

Configure how the tool handles modified files.

- Inplace mode replaces the original image (default).
- Copy mode makes a new modified file.

```bash
gp config --mode copy
gp config --mode inplace
```

Configuration is stored at `~/.config/ghost/config.json`, resolved from your home directory on each platform. Invalid configurations are rejected rather than silently switching modes.

## Supported Images and Limits

Supports JPEG, PNG, WEBP, HEIC, and HEIF. HEIF encoding requires a compatible pillow-heif build. Animated, multi-image, and detected high-bit-depth inputs are rejected to avoid losing frames or precision.

Inputs are limited to 256 MiB, 32 million pixels, and 32,768 pixels per side. Directory batches use up to four CPU-aware workers. Source files must be regular files; symlinks are skipped during scanning.

Copy mode writes copies into a `ghost_images/` folder beside the source and never overwrites existing outputs. It requires filesystem support for hard links. Directory scans in copy mode skip that folder.

Removing color profiles or re-encoding images may change their appearance. Metadata removal does not hide faces, landmarks, filenames, or platform-held information. Source-change checks reduce accidental overwrites but do not lock files against concurrent writers.

## Core Security and Architecture Mandate

1. Local-Only: No network libraries are permitted. Data never leaves your local machine.
2. Memory Safety First: All image manipulations happen entirely in system memory (RAM) and are structure-verified before any disk modification occurs.
3. Atomic Swaps: `os.replace` publishes completed output without partially overwriting the original. Keep backups of important images.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.