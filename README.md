# syncslide_for_OBS

SyncSlide for OBS is a lightweight desktop tool that creates a live-updating slideshow for OBS using a Browser Source.

## Features

- Auto-updating slideshow
- Multi-folder playlist
- Shuffle mode
- Adjustable slide duration
- Adjustable fade duration
- Contain / cover fit mode
- Local Browser Source URL for OBS

## Shuffle mode

Shuffle mode shuffles the full image list once, plays through it without immediate repeats, and reshuffles automatically when the list ends.

## Local development

```bash
pip install -r requirements.txt
python syncslide_obs_app.py
```

## GitHub Actions builds

This repo includes GitHub Actions workflows for:

- Windows EXE
- macOS APP + DMG

You can run them from the Actions tab or create a version tag like `v1.0.0`.

## OBS usage

1. Start the app
2. Add your image folders
3. Click Start
4. In OBS, add a Browser Source using:

```text
http://127.0.0.1:3210
```
