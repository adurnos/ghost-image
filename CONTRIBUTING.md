# Contributing to ghost-photo

Contributions may include bug fixes, documentation, tests, performance improvements, and carefully evaluated privacy features.

## Before Opening an Issue

Search existing open and closed issues and pull requests for duplicates. If a related discussion exists, add useful reproduction details there instead of opening another report.

Use a clear title and keep each issue focused on one problem or proposal. Do not attach private photos, GPS coordinates, device identifiers, credentials, or sensitive configuration. Prefer synthetic images with fabricated metadata.

### Bug Reports

Include:

- A concise description of the problem.
- Operating system, Python version, ghost-photo version, and relevant dependency versions.
- The exact command and output mode used.
- Minimal steps to reproduce the failure.
- Expected behavior and actual behavior.
- Sanitized terminal output and a synthetic reproducer, when possible.
- Image format, dimensions, and whether the problem concerns decoding, metadata removal, perturbation, or file publication.

Report corruption, unexpected original-file replacement, and failed metadata verification explicitly. Preserve your own backups before reproducing a destructive failure.

### Feature Requests and Suggestions

Describe the use case, proposed behavior, expected privacy benefit, and alternatives considered. Identify compatibility, performance, memory, dependency, and security implications.

Claims about defeating AI recognition or reverse image search must include reproducible evidence and clear limits. A changed file hash is not evidence that perceptual recognition has been defeated.

### Sensitive Security Reports

Do not publish private image data or exploit details that would put users at immediate risk. Use a private maintainer contact or repository security-reporting channel if one is available. If neither is configured, open a minimal issue requesting a private reporting channel without disclosing sensitive details.

## Development Setup

1. Fork the repository to your own account.
2. Clone your fork and create a focused branch.
3. Use Python 3.10 or newer for the current engine.
4. Create an isolated development environment and install the project.

```sh
python -m venv .venv
```

Activate the environment on your platform, then run:

```sh
python -m pip install -e .
gp --help
gp --version
```

Package installation can download dependencies. This does not permit network access during image processing. Use trusted local wheels when an offline development environment is required.

## Code and Security Requirements

All code must remain local-first with zero external tracking dependencies.

- Do not add telemetry, analytics, remote image processing, automatic uploads, or runtime network calls.
- Do not introduce network libraries into the execution engine.
- Keep image transformations in RAM and encode into `io.BytesIO` before writing output.
- Verify the encoded image structure and required metadata checks before publishing it.
- Preserve same-directory temporary files and `os.replace` for inplace publication.
- Never replace atomic publication with direct writes to the original file.
- Preserve copy mode's refusal to overwrite existing destination files.
- Handle corrupted inputs, permission failures, and interrupted operations without misleading success messages.
- Bound memory use, queued tasks, and worker counts. Avoid unbounded submissions and per-pixel Python loops.
- Prevent filenames and error messages from injecting terminal control sequences.
- Avoid unnecessary dependencies and keep installation cross-platform.

Match the existing code style. Use comments to explain safety constraints or non-obvious decisions, not basic syntax. Keep changes focused and do not include unrelated reformatting.

### Perturbation Algorithms

Any new perturbation algorithm must include a concise description of the underlying mathematics and matrix operations used.

The pull request should explain:

- Input array shape, color space, dtype, and channel handling.
- How gradients, masks, checkerboards, frequency components, or other matrices are constructed.
- The perturbation formula and its magnitude bounds.
- Clipping, rounding, overflow prevention, and alpha preservation.
- Whether the bound applies before encoding or to decoded output.
- Expected time complexity and peak memory use.
- Effects of JPEG compression, HEIF encoding, resizing, and other transformations.
- Measured benefits, test methodology, and known failures.

If protection against a recognition system is claimed, provide reproducible evaluation on legally obtained, non-sensitive data. Clearly distinguish exact-hash changes from perceptual robustness or model-specific adversarial effects. Do not claim guaranteed invisibility, anonymity, or universal AI protection without evidence.

## Testing and Verification

No automated test suite is currently included. Verify changes with synthetic images in temporary directories and report any checks you could not run.

Check syntax and the command interface:

```sh
python -m py_compile src/gp/gp.py
gp --help
gp --version
```

For image-processing changes, test synthetic JPEG, PNG, WEBP, and HEIF inputs where codec support is available. Include tests for:

- EXIF, GPS, orientation, and ancillary metadata removal.
- Image verification and output dimensions.
- Perturbation bounds before encoding and preservation of alpha.
- Both inplace and copy modes.
- Original preservation when decoding, verification, writing, or publication fails.
- Existing copy destinations and source-change detection.
- Corrupted images, unsupported formats, non-image files, and symlinks.
- Animated files, high-bit-depth inputs, size limits, and permission errors.
- Recursive directory scans and mixed successful and failed batches.
- Valid and invalid configurations, with an isolated temporary home directory.

Use temporary directories and synthetic images. Never run destructive tests against personal photos or your real home configuration. Mark unavailable codec or platform checks explicitly rather than presenting them as successes.

For packaging changes, verify that source and wheel builds succeed, include the engine and required documentation, and install a working `gp` entry point in a clean environment.

## Pull Request Process

1. Create a focused branch in your fork.
2. Implement the change and relevant tests.
3. Update documentation when behavior, installation, supported versions, or security guarantees change.
4. Run applicable checks and inspect your diff for private data, temporary artifacts, and unrelated edits.
5. Commit the change with a clear message.
6. Open a pull request from your fork to the upstream repository's default branch.

Include in the pull request:

- The problem being addressed and links to related issues.
- A brief explanation of the approach.
- Tests run and their results, including skipped checks.
- Security, compatibility, dependency, and performance implications.
- Mathematical details for new perturbation algorithms.
- Any remaining limitations or follow-up work.

Keep the scope small enough to review. Respond to review feedback and update tests or documentation when requested. Discuss large architectural changes in an issue before implementation.

## Documentation Contributions

Use clear markdown and examples that match the actual CLI.

Documentation-only changes should verify command names, configuration defaults, supported formats, installation guidance, and links against the current repository.
