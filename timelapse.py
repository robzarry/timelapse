#!/usr/bin/env python3
"""
Timelapse Camera — Raspberry Pi Zero 2W
Captures stills at a user-defined interval, then compiles them into an MP4.
"""

import os
import sys
import time
import signal
import subprocess
import datetime
import pathlib
import shutil
import textwrap

# ---------------------------------------------------------------------------
# Guard: run setup.sh first if not yet configured
# ---------------------------------------------------------------------------
_SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
_SETUP_FLAG = _SCRIPT_DIR / ".setup_complete"

if not _SETUP_FLAG.exists():
    print("\n  ⚠  First-time setup has not been run.")
    print("  Please run:  sudo bash setup.sh\n")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Lazy import with friendly error messages
# ---------------------------------------------------------------------------
try:
    from picamera2 import Picamera2
    from libcamera import controls as LibControls
except ImportError:
    print("\n  Error: picamera2 is not installed.")
    print("  Run setup.sh, or manually: sudo apt install python3-picamera2\n")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    # Minimal fallback — tqdm not strictly required
    class tqdm:  # type: ignore
        def __init__(self, total=0, **_):
            self._total = total
            self._n = 0
        def update(self, n=1):
            self._n += n
            pct = int(100 * self._n / self._total) if self._total else 0
            print(f"  Progress: {self._n}/{self._total} ({pct}%)", end="\r")
        def close(self):
            print()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CYAN   = "\033[0;36m"
GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
RED    = "\033[0;31m"
BOLD   = "\033[1m"
NC     = "\033[0m"


def banner():
    print(f"{CYAN}")
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║       📷  Raspberry Pi Timelapse Camera  📷          ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print(f"{NC}")


def prompt_int(message: str, min_val: int = 1, max_val: int = 1_000_000) -> int:
    while True:
        try:
            raw = input(f"  {message}: ").strip()
            val = int(raw)
            if min_val <= val <= max_val:
                return val
            print(f"  {RED}Please enter a value between {min_val} and {max_val}.{NC}")
        except (ValueError, EOFError):
            print(f"  {RED}Invalid input — please enter a whole number.{NC}")


def human_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def choose_output_dir() -> pathlib.Path:
    """
    Prefer an attached USB drive or dedicated /media mount; fall back to ~/timelapse.
    """
    for mount in pathlib.Path("/media").glob("*"):
        if mount.is_dir() and os.access(mount, os.W_OK):
            return mount / "timelapse"
    return pathlib.Path.home() / "timelapse"


# ---------------------------------------------------------------------------
# Camera helpers
# ---------------------------------------------------------------------------

def build_camera() -> Picamera2:
    cam = Picamera2()
    config = cam.create_still_configuration(
        main={"size": (2592, 1944)},   # full sensor for Pi Camera v2 / HQ
        lores={"size": (320, 240)},
        display=None,
    )
    cam.configure(config)

    # Auto exposure & white balance — let camera settle
    cam.set_controls({
        "AeEnable": True,
        "AwbEnable": True,
        "AwbMode": LibControls.AwbModeEnum.Auto,
    })
    return cam


# ---------------------------------------------------------------------------
# Core capture loop
# ---------------------------------------------------------------------------

_STOP_REQUESTED = False


def _handle_signal(signum, frame):
    global _STOP_REQUESTED
    _STOP_REQUESTED = True
    print(f"\n  {YELLOW}Interrupt received — stopping capture after current photo...{NC}")


def capture_session(
    interval_s: int,
    duration_min: int,
    photo_dir: pathlib.Path,
) -> list[pathlib.Path]:
    """
    Capture photos at *interval_s* second intervals for *duration_min* minutes.
    Returns list of captured file paths.
    """
    global _STOP_REQUESTED
    _STOP_REQUESTED = False

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    photo_dir.mkdir(parents=True, exist_ok=True)

    duration_s = duration_min * 60
    total_photos = max(1, duration_s // interval_s)
    captured: list[pathlib.Path] = []

    print(f"\n  {BOLD}Session summary{NC}")
    print(f"  ├─ Interval   : {interval_s}s")
    print(f"  ├─ Duration   : {duration_min} min ({human_duration(duration_s)})")
    print(f"  ├─ Est. photos: ~{total_photos}")
    print(f"  └─ Output dir : {photo_dir}")
    print()

    print(f"  {CYAN}Initializing camera (allow 2 s for auto-exposure)...{NC}")
    cam = build_camera()
    cam.start()
    time.sleep(2)  # let AE/AWB converge

    start_time = time.monotonic()
    end_time = start_time + duration_s

    bar = tqdm(
        total=total_photos,
        unit="photo",
        bar_format="  {l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
        ncols=70,
    )

    photo_num = 0
    next_shot = start_time

    try:
        while not _STOP_REQUESTED:
            now = time.monotonic()
            if now >= end_time:
                break

            if now >= next_shot:
                photo_num += 1
                filename = photo_dir / f"frame_{photo_num:06d}.jpg"
                try:
                    cam.capture_file(str(filename))
                    captured.append(filename)
                    bar.update(1)
                except Exception as exc:
                    print(f"\n  {YELLOW}Warning: frame {photo_num} failed ({exc}) — skipping.{NC}")
                next_shot += interval_s

            # Sleep in small increments so signals are handled promptly
            remaining_to_next = next_shot - time.monotonic()
            if remaining_to_next > 0:
                time.sleep(min(0.25, remaining_to_next))

    finally:
        bar.close()
        cam.stop()
        cam.close()

    if _STOP_REQUESTED:
        print(f"\n  {YELLOW}Capture stopped early — {len(captured)} frames saved.{NC}")
    else:
        print(f"\n  {GREEN}Capture complete — {len(captured)} frames saved.{NC}")

    return captured


# ---------------------------------------------------------------------------
# Video compilation
# ---------------------------------------------------------------------------

def compile_video(
    photo_dir: pathlib.Path,
    output_path: pathlib.Path,
    fps: int = 24,
) -> pathlib.Path:
    """
    Use ffmpeg to compile JPEG frames into an MP4 (H.264).
    Frames must be named frame_000001.jpg … in the photo_dir.
    """
    print(f"\n  {CYAN}Compiling video ({fps} fps)...{NC}")
    print(f"  Output: {output_path}")

    if not shutil.which("ffmpeg"):
        raise EnvironmentError("ffmpeg not found. Run: sudo apt install ffmpeg")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",                          # overwrite without asking
        "-framerate", str(fps),
        "-i", str(photo_dir / "frame_%06d.jpg"),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",                  # quality 0-51, lower = better
        "-pix_fmt", "yuv420p",         # broad player compatibility
        "-movflags", "+faststart",     # web-friendly atom ordering
        str(output_path),
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        print(f"  {RED}ffmpeg error:{NC}")
        # Print last 20 lines of stderr for diagnosis
        for line in result.stderr.strip().splitlines()[-20:]:
            print(f"    {line}")
        raise RuntimeError("ffmpeg failed — see output above.")

    size_mb = output_path.stat().st_size / 1_048_576
    print(f"  {GREEN}Video saved ({size_mb:.1f} MB): {output_path}{NC}")
    return output_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    banner()

    # ── Parameters ──────────────────────────────────────────────────────────
    print(f"{YELLOW}── Session Parameters ──────────────────────────────────────────────────{NC}\n")

    interval_s = prompt_int(
        "Photo interval in seconds (e.g. 5)",
        min_val=1,
        max_val=3600,
    )
    duration_min = prompt_int(
        "Session duration in minutes (e.g. 30)",
        min_val=1,
        max_val=1440,  # 24 h max
    )

    # Optional: playback FPS
    print()
    use_custom_fps = input("  Custom playback FPS? [default 24, press Enter to skip]: ").strip()
    fps = 24
    if use_custom_fps:
        try:
            fps = max(1, min(60, int(use_custom_fps)))
        except ValueError:
            fps = 24
    print(f"  Playback FPS: {fps}")

    # ── Output paths ─────────────────────────────────────────────────────────
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = choose_output_dir()
    session_dir = base_dir / timestamp
    photo_dir = session_dir / "frames"
    video_path = session_dir / f"timelapse_{timestamp}.mp4"

    # ── Estimate video length ─────────────────────────────────────────────────
    total_frames = max(1, (duration_min * 60) // interval_s)
    video_seconds = total_frames / fps
    print(f"\n  Estimated video length: {human_duration(video_seconds)} at {fps} fps")
    print(f"  Output directory: {session_dir}\n")

    input(f"  {BOLD}Press Enter to start — Ctrl+C to stop early...{NC} ")

    # ── Capture ───────────────────────────────────────────────────────────────
    print(f"\n{YELLOW}── Capturing ───────────────────────────────────────────────────────────{NC}")
    captured = capture_session(interval_s, duration_min, photo_dir)

    if not captured:
        print(f"  {RED}No frames were captured. Exiting.{NC}\n")
        sys.exit(1)

    # ── Compile ───────────────────────────────────────────────────────────────
    print(f"\n{YELLOW}── Compiling Video ─────────────────────────────────────────────────────{NC}")
    try:
        compile_video(photo_dir, video_path, fps=fps)
    except (EnvironmentError, RuntimeError) as exc:
        print(f"  {RED}Compilation failed: {exc}{NC}")
        print(f"  Frames are preserved at: {photo_dir}")
        sys.exit(1)

    # ── Done ──────────────────────────────────────────────────────────────────
    print()
    print(f"{GREEN}══ All done! ═══════════════════════════════════════════════════════════{NC}")
    print(f"  Frames : {photo_dir}")
    print(f"  Video  : {video_path}")
    print()

    # Offer to delete raw frames to save SD card space
    keep = input("  Keep raw JPEG frames? [Y/n]: ").strip().lower()
    if keep in ("n", "no"):
        try:
            shutil.rmtree(photo_dir)
            print(f"  {YELLOW}Frames deleted.{NC}")
        except OSError as exc:
            print(f"  {RED}Could not delete frames: {exc}{NC}")
            print(f"  You can remove them manually: rm -rf {photo_dir}")
    else:
        print(f"  Frames kept.")
    print()


if __name__ == "__main__":
    main()
