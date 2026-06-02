# Windows

## Install once

| Tool | Required? | Why |
|------|-----------|-----|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | **Yes** | Runs Hearthlight (enable WSL2 if Windows asks) |
| [Git for Windows](https://git-scm.com/download/win) | **Yes** | Clone the repo and submodules (ZIP download is not enough) |
| [Python 3.11](https://www.python.org/downloads/) | **No** | Not needed for the `.bat` scripts — everything runs in Docker |

## Clone the repo

```powershell
git clone https://github.com/lauretta-io/hearthlight.git
cd hearthlight
git submodule update --init --recursive
copy example.env .env
copy shared\configs\example_config.yaml shared\configs\config.yaml
```

## Run

Start Docker Desktop, then double-click:

| Script | Purpose |
|--------|---------|
| `control-plane.bat` | Dashboard + API |
| `full-video.bat` | Video processing (CPU) |

After `full-video.bat`: http://localhost:3000 → **Settings** → **Sources** → upload a short MP4 → **Save** → **Monitor Run** → **Start**.

Troubleshooting: [docs/containers.md](../../docs/containers.md)
