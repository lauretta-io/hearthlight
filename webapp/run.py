import os
import faulthandler
import signal

import uvicorn


def int_env(name: str, default: int) -> int:
    try:
        parsed = int(os.environ.get(name, str(default)) or str(default))
    except ValueError:
        return default
    return parsed if parsed > 0 else default


if __name__ == "__main__":
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    reload = bool(os.environ.get("RELOAD"))
    workers = 1 if reload else int_env("API_WEB_CONCURRENCY", 1)
    uvicorn.run(
        "src.webapp.main:app",
        host="0.0.0.0",
        port=8000,
        reload=reload,
        workers=workers,
        log_level="warning",
    )
