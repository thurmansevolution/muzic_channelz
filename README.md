# muzic channelz

**Music channel streaming** with Azuracast integration, overlay graphics (song, artist, art, bio), and ErsatzTV-ready M3U/YML output. One app to run multiple “TV-style” music channels from your Azuracast stations.

- **Free to download, use, and fork** — [MIT License](LICENSE)
- Default port: **8484** → open `http://localhost:8484`

---

## Quick start (Docker)

Requires Docker and Docker Compose. Builds a Debian-based image (tagged as `1.0`).

```bash
git clone https://github.com/thurmansevolution/muzic_channelz.git
cd muzic-channelz
docker compose up -d
```

Then open **http://localhost:8484**. Data (channels, backgrounds, logs) is stored in a Docker volume.

---

## Run from source (Debian / Linux)

- **Python 3.11+**, **Node 18+** (for frontend build), **FFmpeg**

```bash
git clone https://github.com/thurmansevolution/muzic_channelz.git
cd muzic-channelz
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
uvicorn app.main:app --host 0.0.0.0 --port 8484
```


---

## What’s inside

| Section           | Purpose |
|------------------|--------|
| **Channelz**     | Grid of channels: live stream, background, M3U/ErsatzTV YML download |
| **Administration** | Azuracast stations, metadata providers (artist bio), FFmpeg profiles, start/stop service |
| **Background Editor** | Upload images, place overlays (song, artist, art, bio), assign to channels |
| **Live Logs**    | Per-channel FFmpeg and app logs |

Data lives under `data/` (channels, backgrounds, logs).

---

## License

This project is open source under the **MIT License**. You can use, modify, and distribute it freely. See [LICENSE](LICENSE) for the full text.
