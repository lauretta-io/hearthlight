import os

import uvicorn


if __name__ == "__main__":
    reload = bool(os.environ.get("RELOAD"))
    uvicorn.run("src.webapp.main:app", host="0.0.0.0", port=8000, reload=reload, log_level="warning")
