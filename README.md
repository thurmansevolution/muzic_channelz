# muzic channelz

**Music channel streaming** with Azuracast integration, overlay graphics (song, artist, art, bio), built in tv tuner, and M3U/YML output. One app to run multiple “TV-style” music channels from your Azuracast stations.

- **Free to download, use, and fork** — [MIT License](LICENSE)
- Default port: **8484** → open `http://localhost:8484`

---

## Quick start (Docker)

Requires Docker and Docker Compose. Builds a Debian-based image (tagged as `1.0`).

```bash
git clone https://github.com/thurmansevolution/muzic_channelz.git
cd muzic_channelz
docker compose up -d
```

Then open **http://localhost:8484**. Data (channels, backgrounds, logs) is stored in a Docker volume.
When using docker, additional settings (hardware accel, etc) are found in the docker-compose.yml


---

## Run from source (Debian / Linux)

- **Python 3.11+**, **Node 18+** (for frontend build), **FFmpeg**

Run all commands from the **project root** (the folder that contains `app/`, `frontend/`, and `requirements.txt`).

```bash
git clone https://github.com/thurmansevolution/muzic_channelz.git
cd muzic_channelz
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
uvicorn app.main:app --host 0.0.0.0 --port 8484
```

Or from project root: `./start.sh`

**If the app fails to start:** ensure you are in the project root, the virtualenv is activated (`source .venv/bin/activate`), and `frontend/dist` exists (run `npm run build` in `frontend/` if not). If port 8484 is in use, set `MUZIC_PORT` or stop the other process.


---

## What’s inside

| Section           | Purpose |
|------------------|--------|
| **Channelz**     | Grid of channels: live stream, background, cusom logo upload, M3U/YML download |
| **Administration** | Azuracast stations, metadata providers (artist bio), FFmpeg profiles, tv tuner setup, start/stop service |
| **Background Editor** | Upload images, place overlays (song, artist, art, bio), assign to channels |
| **Live Logs**    | Per-channel FFmpeg and app logs |

Data lives under `data/` (channels, backgrounds, logs).

---

## License

This project is open source under the **MIT License**. You can use, modify, and distribute it freely. See [LICENSE](LICENSE) for the full text.
