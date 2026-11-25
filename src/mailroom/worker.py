"""Worker: kör pipelinen var N:e minut. Startas som egen process/container."""
from __future__ import annotations

import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler

from mailroom.config import settings
from mailroom.db.session import init_db
from mailroom.pipeline import run_once

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("mailroom.worker")


def main() -> None:
    init_db()
    log.info("Startar worker. shadow_mode=%s, intervall=%s min",
             settings.shadow_mode, settings.graph_poll_minutes)
    run_once()  # direkt vid start
    sched = BackgroundScheduler()
    sched.add_job(run_once, "interval", minutes=settings.graph_poll_minutes,
                  max_instances=1, coalesce=True)
    sched.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        sched.shutdown()


if __name__ == "__main__":
    main()
