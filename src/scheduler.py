"""Run all ingestion sources on a daily schedule, staggered to respect API rate limits.

This is a local-dev scheduler: run `python scheduler.py` and leave the process running.
When the project moves to a real deploy target, this same job logic gets re-hosted as
either an in-process APScheduler inside the backend server, or the platform's own cron
feature (GitHub Actions / Render Cron / etc) calling the same ingest_*.main() functions.
"""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import ingest_arxiv
import ingest_github
import ingest_hf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("scheduler")


def run_job(name: str, ingest_module) -> None:
    logger.info("Starting %s ingestion", name)
    try:
        ingest_module.main()
    except Exception:
        logger.exception("%s ingestion failed", name)
    else:
        logger.info("Finished %s ingestion", name)


def run_arxiv() -> None:
    run_job("arxiv", ingest_arxiv)


def run_github() -> None:
    run_job("github", ingest_github)


def run_hf() -> None:
    run_job("huggingface", ingest_hf)


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler()
    # Staggered start times so the three sources don't hit their APIs at once.
    scheduler.add_job(run_arxiv, CronTrigger(hour=2, minute=0), id="arxiv")
    scheduler.add_job(run_github, CronTrigger(hour=2, minute=10), id="github")
    scheduler.add_job(run_hf, CronTrigger(hour=2, minute=20), id="huggingface")
    return scheduler


if __name__ == "__main__":
    scheduler = build_scheduler()
    logger.info("Scheduler started. Jobs: %s", [job.id for job in scheduler.get_jobs()])
    scheduler.start()
