# Windows

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it.
2. Clone with submodules:

```powershell
git clone https://github.com/lauretta-io/hearthlight.git
cd hearthlight
git submodule update --init --recursive
```

3. Double-click a script in this folder:

| Script | Purpose |
|--------|---------|
| `control-plane.bat` | Dashboard + API |
| `full-video.bat` | Video processing (CPU) |

After `full-video.bat`: open http://localhost:3000 → **Settings** → **Sources** → upload a short MP4 → **Save** → **Monitor Run** → **Start**.

Troubleshooting: [docs/containers.md](../../docs/containers.md)
