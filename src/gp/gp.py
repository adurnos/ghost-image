#!/usr/bin/env python3

from __future__ import annotations

import argparse
import concurrent.futures as cf
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
import warnings

VERSION = "1.0.0"
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".hif"}
FORMATS = {"JPEG", "PNG", "WEBP", "HEIF", "HEIC"}
COPY_DIR = "ghost_images"
MAX_BYTES = 256 * 1024 * 1024
MAX_PIXELS = 32_000_000
MAX_SIDE = 32_768
MAX_CONFIG = 16 * 1024
OUT_LOCK = threading.Lock()
STOP = threading.Event()

# Keep help usable without image dependencies.
try:
    import numpy as np
    from PIL import Image, ImageOps
    import pillow_heif
except ImportError as exc:
    DEP_ERROR = exc.name
else:
    DEP_ERROR = None
    pillow_heif.register_heif_opener()
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)


class GhostError(Exception):
    pass


def safe(text: object) -> str:
    # Block terminal escape injection.
    return ascii(str(text))[1:-1]


def log(msg: str, *, err: bool = False) -> None:
    with OUT_LOCK:
        print(msg, file=sys.stderr if err else sys.stdout, flush=True)


def header() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\r\x1b[2K")
    log(f"ghost-photo {VERSION}")


def config_path() -> Path:
    return Path.home() / ".config" / "ghost" / "config.json"


def regular(path: Path) -> os.stat_result:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode):
        raise GhostError("Not a regular file; symlinks are not followed.")
    return st


def fingerprint(st: os.stat_result) -> tuple:
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def read_checked(path: Path, limit: int) -> tuple[bytes, os.stat_result]:
    before = regular(path)
    if before.st_size > limit:
        raise GhostError(f"File exceeds the {limit // 1024} KiB limit.")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as src:
        opened = os.fstat(src.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise GhostError("Opened file is not a regular file.")
        if fingerprint(before) != fingerprint(opened):
            raise GhostError("File changed while opening.")
        raw = src.read(limit + 1)
        after = os.fstat(src.fileno())
    if len(raw) > limit:
        raise GhostError("File grew beyond the size limit.")
    if fingerprint(opened) != fingerprint(after):
        raise GhostError("File changed while reading.")
    return raw, opened


def config_dir(*, create: bool = False) -> Path:
    parent = config_path().parent
    if create:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = parent.lstat()
    if not stat.S_ISDIR(st.st_mode):
        raise GhostError("Config directory must not be a symlink.")
    if os.name == "posix" and st.st_uid != os.getuid():
        raise GhostError("Config directory belongs to another user.")
    return parent


def valid_mode(mode: object) -> bool:
    return isinstance(mode, str) and mode in {"inplace", "copy"}


def load_config() -> dict:
    try:
        config_dir()
        raw, st = read_checked(config_path(), MAX_CONFIG)
    except FileNotFoundError:
        return {"mode": "inplace"}
    if os.name == "posix" and st.st_uid != os.getuid():
        raise GhostError("Config file belongs to another user.")
    try:
        cfg = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError):
        raise GhostError("Invalid config JSON.") from None
    if not isinstance(cfg, dict) or not valid_mode(cfg.get("mode")):
        raise GhostError("Config mode must be inplace or copy.")
    return {"mode": cfg["mode"]}


def sync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        # Some filesystems do not support directory fsync.
        pass


def remove_temp(path: Path | None) -> None:
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log(f"Warning: temporary file remains: {safe(path)}", err=True)


def save_config(mode: str) -> Path:
    if not valid_mode(mode):
        raise GhostError("Config mode must be inplace or copy.")
    path = config_path()
    parent = config_dir(create=True)
    if os.name == "posix":
        os.chmod(parent, 0o700)
    if path.is_symlink():
        raise GhostError("Config file must not be a symlink.")
    data = (json.dumps({"mode": mode}, indent=2) + "\n").encode("utf-8")
    tmp = None
    try:
        fd, name = tempfile.mkstemp(prefix=".ghost-config-", suffix=".tmp", dir=parent)
        tmp = Path(name)
        with os.fdopen(fd, "wb") as dst:
            if dst.write(data) != len(data):
                raise GhostError("Short write.")
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(tmp, path)
        tmp = None
        sync_dir(parent)
    finally:
        remove_temp(tmp)
    return path


def perturb(img: Image.Image) -> Image.Image:
    arr = np.array(img, dtype=np.uint8, copy=True)
    height, width = arr.shape[:2]
    colors = 1 if arr.ndim == 2 else 3
    salt = int.from_bytes(os.urandom(2), "little")
    x = np.arange(width, dtype=np.int32)[None, :]
    # Bound scratch arrays even for wide images.
    rows = max(1, min(128, 262_144 // width))
    for start in range(0, height, rows):
        if STOP.is_set():
            raise GhostError("Cancelled.")
        end = min(start + rows, height)
        y = np.arange(start, end, dtype=np.int32)[:, None]
        check = ((x + y + salt) & 1).astype(np.int16) * 2 - 1
        stripe = ((x + 2 * y + (salt >> 1)) % 4 < 2).astype(np.int16) * 2 - 1
        for channel in range(colors):
            plane = arr[start:end] if arr.ndim == 2 else arr[start:end, :, channel]
            src = plane.astype(np.int16)
            grad = np.zeros_like(src)
            grad[:, 1:] = src[:, 1:] - src[:, :-1]
            delta = np.clip(
                check + stripe * np.sign(grad) * (-1 if channel == 1 else 1), -2, 2
            )
            plane[:] = np.clip(src + delta, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _blob_len(value: object) -> int:
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8", "ignore"))
    return 0


def metadata_bytes(img: Image.Image) -> int:
    # Approximate the bytes of removable metadata before it is discarded.
    total = 0
    try:
        total += len(img.getexif().tobytes())
    except Exception:
        pass
    keys = ("icc_profile", "xmp", "XML:com.adobe.xmp", "comment", "iptc", "photoshop")
    for key in keys:
        total += _blob_len(img.info.get(key))
    for value in getattr(img, "text", {}).values():
        total += _blob_len(value)
    return total


def metadata_counts(img: Image.Image) -> dict[str, int]:
    exif = img.getexif()
    fields = len(exif)
    for tag in (34665, 34853):
        if tag in exif:
            nested = exif.get_ifd(tag)
            fields += len(nested)
            if tag == 34665 and 40965 in nested:
                fields += len(exif.get_ifd(40965))
    keys = {"icc_profile", "xmp", "XML:com.adobe.xmp", "comment", "iptc", "photoshop"}
    blocks = {key for key in keys if img.info.get(key)}
    blocks.update(getattr(img, "text", {}).keys())
    return {"exif": fields, "blocks": len(blocks), "bytes": metadata_bytes(img)}


def verify(buf: io.BytesIO, size: tuple[int, int]) -> None:
    buf.seek(0)
    with Image.open(buf) as check:
        check.verify()
    buf.seek(0)
    with Image.open(buf) as check:
        check.load()
        if check.size != size or getattr(check, "n_frames", 1) != 1:
            raise GhostError("Output verification failed.")
        counts = metadata_counts(check)
        if counts["exif"] or counts["blocks"]:
            raise GhostError("Output still contains removable metadata.")
        for key in ("exif", "icc_profile", "xmp", "XML:com.adobe.xmp", "comment"):
            if check.info.get(key):
                raise GhostError(f"Output still contains {key} metadata.")


def encode(raw: bytes, stats: dict[str, int] | None = None) -> io.BytesIO:
    # Pillow converts 16-bit RGB PNGs to 8-bit before exposing their mode.
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) > 24 and raw[24] > 8:
        raise GhostError("High-bit-depth images are skipped to avoid precision loss.")
    with Image.open(io.BytesIO(raw)) as img:
        fmt = (img.format or "").upper()
        if fmt not in FORMATS:
            raise GhostError(f"Unsupported format: {fmt or 'unknown'}.")
        if getattr(img, "n_frames", 1) != 1:
            raise GhostError("Animated or multi-image files are skipped.")
        if img.width * img.height > MAX_PIXELS:
            raise GhostError("Image exceeds the pixel limit.")
        if max(img.size) > MAX_SIDE:
            raise GhostError("Image exceeds the dimension limit.")
        if img.mode.startswith(("I", "F")) or int(img.info.get("bit_depth", 8)) > 8:
            raise GhostError("High-bit-depth images are skipped to avoid precision loss.")
        img.load()
        counts = metadata_counts(img)
        upright = ImageOps.exif_transpose(img)
        try:
            alpha = "A" in upright.getbands() or "transparency" in upright.info
            mode = "RGBA" if alpha else ("L" if upright.mode == "L" else "RGB")
            pixels = upright.convert(mode)
            try:
                clean = perturb(pixels)
            finally:
                pixels.close()
        finally:
            if upright is not img:
                upright.close()

    buf = io.BytesIO()
    try:
        clean.info.clear()
        if fmt == "JPEG":
            clean.save(buf, format="JPEG", quality=100, subsampling=0)
        elif fmt == "PNG":
            clean.save(buf, format="PNG", compress_level=6)
        elif fmt == "WEBP":
            clean.save(buf, format="WEBP", lossless=True, exact=True)
        else:
            clean.save(buf, format="HEIF", quality=-1, chroma="444")
        verify(buf, clean.size)
        if stats is not None:
            stats.update(counts)
        buf.seek(0)
        return buf
    except BaseException:
        buf.close()
        raise
    finally:
        clean.close()


def commit(buf: io.BytesIO, path: Path, mode: str, before: os.stat_result) -> Path:
    if not valid_mode(mode):
        raise GhostError("Config mode must be inplace or copy.")
    if mode == "copy":
        # Copies live in a sibling folder to keep the source directory clean.
        dest_dir = path.parent / COPY_DIR
        dest_dir.mkdir(mode=0o700, exist_ok=True)
        if not stat.S_ISDIR(dest_dir.lstat().st_mode):
            raise GhostError("Copy directory must not be a symlink.")
        dest = dest_dir / path.name
    else:
        dest_dir = path.parent
        dest = path
    tmp = None
    try:
        fd, name = tempfile.mkstemp(prefix=".ghost-", suffix=".tmp", dir=dest_dir)
        tmp = Path(name)
        with os.fdopen(fd, "wb") as dst:
            buf.seek(0)
            while chunk := buf.read(1024 * 1024):
                if dst.write(chunk) != len(chunk):
                    raise GhostError("Short write.")
            dst.flush()
            # Keep incomplete output private until the write succeeds.
            if os.name == "posix":
                os.fchmod(dst.fileno(), stat.S_IMODE(before.st_mode) & 0o777)
            os.fsync(dst.fileno())
        if STOP.is_set():
            raise GhostError("Cancelled.")
        if fingerprint(regular(path)) != fingerprint(before):
            raise GhostError("Source changed; refusing replacement.")
        if mode == "inplace":
            os.replace(tmp, dest)
            tmp = None
        else:
            # Publish atomically without overwriting existing copies.
            try:
                os.link(tmp, dest)
            except FileExistsError:
                raise GhostError("Copy already exists; refusing overwrite.") from None
            except OSError as exc:
                raise GhostError(f"Atomic copy publication failed: {exc.strerror}.") from None
            remove_temp(tmp)
            tmp = None
        sync_dir(dest_dir)
        if dest_dir != path.parent:
            sync_dir(path.parent)
        return dest
    finally:
        remove_temp(tmp)


def cloak_one(path: Path, mode: str) -> int | None:
    name = safe(path)
    buf = None
    try:
        if STOP.is_set():
            return None
        if mode == "copy" and os.path.lexists(path.parent / COPY_DIR / path.name):
            raise GhostError("Copy already exists; refusing overwrite.")
        log(f"{name}: Purging EXIF...")
        raw, before = read_checked(path, MAX_BYTES)
        log(f"{name}: Shifting Hashes...")
        stats = {}
        buf = encode(raw, stats)
        del raw
        commit(buf, path, mode, before)
        if stats["exif"] or stats["blocks"]:
            log(
                f"{name}: Metadata removed: {stats['exif']} EXIF fields, "
                f"{stats['blocks']} other metadata blocks. [SUCCESS]"
            )
        else:
            log(f"{name}: No removable metadata found. [SUCCESS]")
        return stats["exif"] + stats["blocks"]
    except Exception as exc:
        # Catch plugin-specific errors without stopping the batch.
        log(f"{name}: [FAILED] {safe(str(exc).strip() or type(exc).__name__)}", err=True)
        return None
    finally:
        if buf is not None:
            buf.close()


def scan(root: Path, mode: str, errors: list[int]):
    dirs = [root]
    while dirs and not STOP.is_set():
        directory = dirs.pop()
        try:
            if not stat.S_ISDIR(directory.lstat().st_mode):
                errors[0] += 1
                log(f"{safe(directory)}: Directory changed; skipping.", err=True)
                continue
            with os.scandir(directory) as entries:
                for entry in entries:
                    if STOP.is_set():
                        return
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if mode == "copy" and entry.name == COPY_DIR:
                                continue
                            dirs.append(Path(entry.path))
                        elif (
                            entry.is_file(follow_symlinks=False)
                            and Path(entry.name).suffix.lower() in EXTS
                        ):
                            yield Path(entry.path)
                    except OSError as exc:
                        errors[0] += 1
                        log(f"{safe(entry.path)}: {safe(exc.strerror or 'Scan failed.')}", err=True)
        except OSError as exc:
            errors[0] += 1
            log(f"{safe(directory)}: {safe(exc.strerror or 'Scan failed.')}", err=True)


def batch(paths, mode: str, workers: int) -> tuple[int, int, int]:
    ok = failed = removed = 0
    pool = cf.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ghost")
    pending: set[cf.Future] = set()
    items = iter(paths)
    exhausted = False
    try:
        while pending or not exhausted:
            while not exhausted and len(pending) < workers * 2:
                try:
                    path = next(items)
                except StopIteration:
                    exhausted = True
                    break
                pending.add(pool.submit(cloak_one, path, mode))
            if not pending:
                break
            done, pending = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
            for future in done:
                result = future.result()
                if result is None:
                    failed += 1
                else:
                    ok += 1
                    removed += result
    except KeyboardInterrupt:
        STOP.set()
        for future in pending:
            future.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return ok, failed, removed


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="gp",
        description="Local metadata stripping and bounded pixel perturbation.",
        epilog="Python 3.10+ required.",
    )
    ap.add_argument("--version", action="version", version=f"ghost-photo {VERSION}")
    subs = ap.add_subparsers(dest="cmd", required=True)
    cloak = subs.add_parser("cloak", help="Clean a file or recursively scan a directory.")
    cloak.add_argument("path", type=Path)
    cfg = subs.add_parser("config", help="Show or change the default mode.")
    cfg.add_argument("--mode", choices=("inplace", "copy"))
    return ap


def main() -> int:
    args = parser().parse_args()
    header()
    STOP.clear()
    try:
        if args.cmd == "config":
            if args.mode:
                path = save_config(args.mode)
                log(f"Mode saved: {args.mode}")
                log(f"Config: {safe(path)}")
            else:
                log(f"Mode: {load_config()['mode']}")
                log(f"Config: {safe(config_path())}")
            return 0
        if DEP_ERROR:
            raise GhostError(
                f"Missing dependency: {DEP_ERROR}. Required: Pillow, numpy, pillow-heif."
            )
        mode = load_config()["mode"]
        path = args.path.expanduser().absolute()
        st = path.lstat()
        errors = [0]
        if stat.S_ISREG(st.st_mode):
            if path.suffix.lower() not in EXTS:
                raise GhostError("Supported extensions: JPEG, PNG, WEBP, HEIC, HEIF.")
            paths = iter((path,))
            workers = 1
        elif stat.S_ISDIR(st.st_mode):
            paths = scan(path, mode, errors)
            # Cap workers to limit RAM use.
            workers = min(4, max(1, (os.cpu_count() or 1) - 1))
        else:
            raise GhostError("Path must be a regular file or directory, not a symlink.")
        log(f"Mode: {mode}")
        started = time.monotonic()
        ok, failed, removed = batch(paths, mode, workers)
        elapsed = time.monotonic() - started
        failed += errors[0]
        if not ok and not failed:
            log("No eligible images found.")
        elif failed:
            log("Cloak complete with errors.")
        elif removed:
            images = "image" if ok == 1 else "images"
            pieces = "piece" if removed == 1 else "pieces"
            log(
                f"Cloak complete. Removed {removed} {pieces} of information from "
                f"{ok} {images} in {elapsed:.2f}s (mode: {mode})."
            )
        else:
            log("Cloak complete. No removable metadata found.")
        return 1 if failed else 0
    except KeyboardInterrupt:
        STOP.set()
        log("Interrupted. Uncommitted originals were not replaced.", err=True)
        return 130
    except (GhostError, OSError, ValueError) as exc:
        log(f"Error: {safe(str(exc).strip() or type(exc).__name__)}", err=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
