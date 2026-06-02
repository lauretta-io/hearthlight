# Windows

## Install once (no website downloads)

Open the **Microsoft Store** and install:

| App | Required? |
|-----|-----------|
| **Docker Desktop** | **Yes** — enable WSL2 if Windows asks |
| **App Installer** | Only if `winget` is missing (usually preinstalled on Windows 11) |

**Git** is not in the Store. In PowerShell, run:

```powershell
winget install --id Git.Git -e
```

**Python** is not required for the `.bat` scripts (everything runs in Docker). Optional: install **Python 3.11** from the Store only if you want the `hearthlight` CLI on the host.

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
