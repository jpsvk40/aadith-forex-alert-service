"""
main.py — entrypoint.
Starts both the FastAPI server (uvicorn, non-blocking) and the APScheduler poll loop.
"""

import logging
import os
import threading
import uvicorn

from app.signal_repository import init_db
from app.api import app as fastapi_app
from app.scheduler import start as start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _run_api():
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    logger.info("Initialising database...")
    init_db()

    logger.info("Starting FastAPI on :%d...", port)
    api_thread = threading.Thread(target=_run_api, daemon=True)
    api_thread.start()

    logger.info("Starting scheduler...")
    start_scheduler()  # blocking — runs until KeyboardInterrupt
