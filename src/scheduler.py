"""每天定時執行所有資料擷取來源，並刻意錯開執行時間以尊重各家 API 的速率限制。

這是本機開發用的排程器：執行 `python scheduler.py` 後讓這個程序持續在背景跑著即可。
等專案正式部署到真正的環境時，同一套排程邏輯會被搬到別的地方執行——可能是
後端伺服器裡常駐的 APScheduler，或是部署平台自帶的排程功能（GitHub Actions /
Render Cron 等），但呼叫的仍然是同一批 ingest_*.main() 函式。
"""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import classify
import embed
import ingest_arxiv
import ingest_github
import ingest_hf
import trend

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("scheduler")


def run_job(name: str, ingest_module) -> None:
    """執行單一個 pipeline 步驟，並確保單一步驟失敗不會讓整個排程器程序崩潰。

    用 try/except 包住每個步驟，是因為這是一個長駐程序：如果某天某個來源的 API
    暫時掛掉，只應該讓那一個步驟失敗、記錄錯誤，其餘步驟跟明天的排程都要能正常繼續，
    而不是讓一次例外就終止整個 scheduler。
    """
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


def run_embed() -> None:
    run_job("embed", embed)


def run_classify() -> None:
    run_job("classify", classify)


def run_trend() -> None:
    run_job("trend", trend)


def build_scheduler() -> BlockingScheduler:
    """組出每日排程表：先跑三個資料擷取來源（時間錯開，避免同時打各家 API），
    接著依序是 embed -> classify -> trend，每個步驟之間都留了足夠的時間間隔，
    確保前一步驟真正執行完畢、寫好資料後，下一步驟才會開始讀取它的輸出。
    """
    scheduler = BlockingScheduler()
    scheduler.add_job(run_arxiv, CronTrigger(hour=2, minute=0), id="arxiv")
    scheduler.add_job(run_github, CronTrigger(hour=2, minute=10), id="github")
    scheduler.add_job(run_hf, CronTrigger(hour=2, minute=20), id="huggingface")
    scheduler.add_job(run_embed, CronTrigger(hour=2, minute=40), id="embed")
    scheduler.add_job(run_classify, CronTrigger(hour=2, minute=50), id="classify")
    scheduler.add_job(run_trend, CronTrigger(hour=3, minute=0), id="trend")
    return scheduler


if __name__ == "__main__":
    scheduler = build_scheduler()
    logger.info("Scheduler started. Jobs: %s", [job.id for job in scheduler.get_jobs()])
    scheduler.start()
