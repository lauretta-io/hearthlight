# Windows quick start

Read this on GitHub — no download needed:  
https://github.com/lauretta-io/hearthlight/tree/main/scripts/windows

## Before you run a `.bat` file

1. Install **Docker Desktop** and start it (enable WSL2 if prompted).
2. Install **Git for Windows**.
3. Clone the repo (**ZIP is not enough** — submodules are required):

```powershell
git clone https://github.com/lauretta-io/hearthlight.git
cd hearthlight
git submodule update --init --recursive
```

## Pick one script (double-click)

| File | What you get |
|------|----------------|
| **`1-control-plane.bat`** | Dashboard + API only — fastest sanity check |
| **`2-full-video-cpu.bat`** | Full CPU video pipeline (ingestor, association, anomaly) |

Each script prints the same steps in the command window when it runs.

## After `2-full-video-cpu.bat` finishes

1. Browser opens **http://localhost:3000**
2. **Settings** → **Sources** → add **Uploaded Video** → choose a short MP4 → **Save**
3. **Monitor Run** → **Start**
4. Wait several minutes on CPU for a short clip

## Check it worked

```powershell
docker compose ps
curl.exe http://localhost:8000/readyz
```

You want `ingestor`, `association`, and `anomaly` **Up** (not Restarting).

## More help

- [docs/containers.md](../../docs/containers.md) — troubleshooting
- Release **v0.8.1** also attaches these `.bat` files if you prefer download-only
