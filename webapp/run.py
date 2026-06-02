import os

import uvicorn


if __name__ == "__main__":
    reload = bool(os.environ.get("RELOAD"))
    workers = int(os.environ.get("WEBAPP_WORKERS", "1"))
    if reload:
        workers = 1
    uvicorn.run(
        "src.webapp.main:app",
        host="0.0.0.0",
        port=8000,
        reload=reload,
        workers=workers,
        log_level="warning",
    )
