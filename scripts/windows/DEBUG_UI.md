# Debug UI / Network pending (Windows)

Use this when the browser Network tab shows many `(pending)` requests (often `status`).

## Step 1 — Is the API alive?

Run in PowerShell from the repo folder:

```powershell
curl.exe -m 10 http://localhost:8000/readyz
curl.exe -m 10 http://localhost:8000/healthz
```

- **OK** → API process is up.
- **Fails** → `docker compose ps` and `docker compose logs --tail=80 webapp`.

## Step 2 — Which endpoint is slow?

Time each call (replace `120` with seconds to wait):

```powershell
curl.exe -m 120 -w "\nTIME_TOTAL=%{time_total}s CODE=%{http_code}\n" http://localhost:8000/status -o NUL
curl.exe -m 120 -w "\nTIME_TOTAL=%{time_total}s CODE=%{http_code}\n" http://localhost:8000/model-bindings -o NUL
curl.exe -m 120 -w "\nTIME_TOTAL=%{time_total}s CODE=%{http_code}\n" "http://localhost:3000/api/status" -o NUL
```

| Result | Meaning |
|--------|---------|
| Direct `:8000/status` **fast**, `:3000/api/status` **slow** | nginx / `reverse_proxy` issue → `docker compose logs --tail=40 reverse_proxy` |
| **Both slow** (>30s or timeout) | Backend blocked on registry DB sync (30–40s on CPU Windows). `git pull` + `docker compose restart webapp`. `/status` and `/model-bindings` should answer in under ~2s after the fix. |
| **Both fast** | Browser pile-up → close tabs, new incognito, `git pull`, restart `webapp` |

## Step 3 — Backend blocked (common on CPU)

```powershell
docker compose ps
docker compose logs --tail=100 webapp
docker compose logs --tail=40 reverse_proxy
```

Look for:

- `upstream timed out` (nginx)
- Python tracebacks (webapp)
- Containers **Restarting**

Recovery:

```powershell
docker compose restart webapp reverse_proxy
```

If still bad:

```powershell
docker compose restart webapp reverse_proxy ingestor association anomaly
```

## Step 4 — Browser

1. Close **all** `localhost:3000` tabs.
2. New **Incognito** window.
3. Open only: `http://localhost:3000/settings?tab=sources`
4. DevTools → **Network** → check **one** `status` row:
   - If it stays pending >20s, backend is still slow (Step 2).
   - If `model-bindings` returns 200, bindings dropdown should populate after `git pull`.

## Step 5 — Full stack check

```powershell
docker compose ps
curl.exe http://localhost:8000/status
```

Workers should be **Up**: `ingestor`, `association`, `anomaly`.

## Expected for first-time setup

- Admission: **at least one enabled source is required** until you save a source on **Sources**.
- Do **Sources** (upload MP4 → Update Source Settings) before **Monitor Run → Start**.
