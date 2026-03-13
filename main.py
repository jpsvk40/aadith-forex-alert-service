"""
main.py — entrypoint.
Starts both the FastAPI server (uvicorn, non-blocking) and the APScheduler poll loop.
"""

import logging
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
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000, log_level="warning")


if __name__ == "__main__":
    logger.info("Initialising database...")
    init_db()

    logger.info("Starting FastAPI on :8000...")
    api_thread = threading.Thread(target=_run_api, daemon=True)
    api_thread.start()

    logger.info("Starting scheduler...")
    start_scheduler()  # blocking — runs until KeyboardInterrupt
