# Raspberry Pi Zero 2W — Timelapse Camera

A self-contained timelapse application for the Pi Zero 2W + Pi Camera (v1, v2, or HQ).

---

## Hardware

| Component | Notes |
|-----------|-------|
| Raspberry Pi Zero 2W | Any OS revision |
| Pi Camera (v1/v2/HQ) | Connected via ribbon cable |
| microSD card | ≥16 GB recommended |
| Power supply | 5 V / 2 A micro-USB |

---

## First-Time Setup (run once)

Boot the Pi (Raspberry Pi OS Lite recommended), open a terminal, and run:

```bash
sudo bash setup.sh
```

The script will:
1. Prompt for your **WiFi SSID and password** and write the configuration
2. Enable and start **SSH** (connect with `ssh pi@<ip>` afterward)
3. Install system dependencies: `picamera2`, `ffmpeg`, `tqdm`
4. Optionally install a **systemd service** so you can start the app with
   `sudo systemctl start timelapse`

> **Country code** — if prompted, enter your two-letter ISO country code (e.g.
> `US`, `GB`, `CA`). This is required for WiFi to be enabled on Pi OS Lite.

---

## Running the App

```bash
python3 timelapse.py
```

The app will prompt for:

| Parameter | Example | Description |
|-----------|---------|-------------|
| Interval (seconds) | `10` | Time between photos |
| Duration (minutes) | `60` | Total session length |
| Playback FPS | `24` | Frames per second in the output video |

After the session completes, the frames are compiled into an **H.264 MP4** and
saved on the SD card (or a USB drive if one is mounted under `/media`).

---

## Output

```
~/timelapse/
└── 20241215_143022/
    ├── frames/
    │   ├── frame_000001.jpg
    │   ├── frame_000002.jpg
    │   └── ...
    └── timelapse_20241215_143022.mp4
```

If an external drive is mounted under `/media`, the session directory is written
there instead to spare the SD card.

---

## SSH Access

After `setup.sh` runs:

```bash
# Find the Pi's IP address (from another machine on the same network)
ping raspberrypi.local

# Connect
ssh pi@raspberrypi.local

# Copy the finished video to your laptop
scp pi@raspberrypi.local:~/timelapse/20241215_143022/timelapse_20241215_143022.mp4 ~/Desktop/
```

---

## Stopping Early

Press **Ctrl+C** during capture. The app will finish the current photo, stop
cleanly, and still compile whatever frames were captured.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `picamera2` import error | Run `setup.sh`, or: `sudo apt install python3-picamera2` |
| `ffmpeg not found` | `sudo apt install ffmpeg` |
| Black frames | Allow the camera 2 s to auto-expose; bright scene helps |
| WiFi not connecting (Bullseye) | Check `/etc/wpa_supplicant/wpa_supplicant.conf`; verify country code |
| WiFi not connecting (Bookworm+) | `nmcli device wifi list` to see available networks |
| Setup flag missing | Delete `.setup_complete` and re-run `setup.sh` |
