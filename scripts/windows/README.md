# Windows

## Install once (no website downloads)

Open the **Microsoft Store** and install:

| App | Required? |
|-----|-----------|
| **Docker Desktop** | **Yes** — needs WSL2 on most PCs (see below if Docker never prompts you) |
| **App Installer** | Only if `winget` is missing (usually preinstalled on Windows 11) |

**Git** is not in the Store. In PowerShell, run:

```powershell
winget install --id Git.Git -e
```

**Python** is not required for the `.bat` scripts (everything runs in Docker). Optional: install **Python 3.11** from the Store only if you want the `hearthlight` CLI on the host.

### WSL2 (if Docker does not ask, or Docker will not start)

Docker Desktop on Windows usually needs **WSL2**. If you never got a prompt, or Docker says the engine is not running:

1. Open **PowerShell as Administrator** and run:

```powershell
wsl --install
```

2. **Reboot** when Windows asks you to.
3. After reboot, check:

```powershell
wsl --status
wsl -l -v
```

You want a Linux distro (often **Ubuntu**) with **VERSION 2**.

4. Open **Docker Desktop** → **Settings** → **General** → turn on **Use the WSL 2 based engine**.
5. **Settings** → **Resources** → **WSL Integration** → enable your distro (e.g. Ubuntu).
6. Wait until Docker Desktop shows **Engine running**, then run the `.bat` script again.

If `wsl --install` fails, run `wsl --update` in Admin PowerShell, reboot, and retry.

## Clone the repo

```powershell
git clone https://github.com/lauretta-io/hearthlight.git
cd hearthlight
git submodule update --init --recursive
copy example.env .env
copy shared\configs\example_config.yaml shared\configs\config.yaml
```

## Run

The `.bat` scripts start **Postgres first**, run **`reset_db` before webapp/workers** (creates `control` and `runtime` schemas), then start the rest. If you see `schema "control" does not exist`, run:

```powershell
docker compose up -d db
docker compose run --rm reset_db
```

Start Docker Desktop, then double-click:

| Script | Purpose |
|--------|---------|
| `control-plane.bat` | Dashboard + API |
| `full-video.bat` | Video processing (CPU) |

After `full-video.bat`: http://localhost:3000 → **Settings** → **Sources** (do this tab first) → upload a short MP4 → **Save** → **Monitor Run** → **Start**.

Open **Sources** before **Monitor Run** — the overview poll is heavy on CPU and will block the UI if no source is saved yet.

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| Network tab all **pending**, then **504** | Too many background API polls. `git pull`, `docker compose restart webapp reverse_proxy`, open a **new incognito** window to http://localhost:3000/settings?tab=sources . Stay on Sources first; avoid opening every nav tab at once. |
| Docker engine not running | WSL2 section above, then restart Docker Desktop |
| `docker` not recognized | Start Docker Desktop; open a **new** PowerShell window |
| Script fails immediately | Run from a cloned repo folder, not a lone downloaded `.bat` |
| Workers keep restarting | `docker compose logs --tail=120 ingestor` |

More detail: [docs/containers.md](../../docs/containers.md)
