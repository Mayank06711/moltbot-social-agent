"""Entry point for the KYF agent.

Wires up all dependencies (Composition Root) and starts the heartbeat loop.
"""

import asyncio
import signal
import sys

from kyf.clients.llm_client import GeminiClient
from kyf.clients.moltbook_client import MoltbookClient
from kyf.config import load_settings
from kyf.core.agent import KYFAgent
from kyf.core.scheduler import HeartbeatScheduler
from kyf.core.state_repository import StateRepository
from kyf.logger import get_logger, setup_logging


async def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    logger = get_logger("kyf.main")

    logger.info("kyf_starting", version="0.1.0")

    # --- Compose dependencies ---
    moltbook = MoltbookClient(
        base_url=settings.moltbook_base_url,
        api_key=settings.moltbook_api_key,
    )

    llm = GeminiClient(
        api_key=settings.gemini_api_key,
    )

    state_repo = StateRepository(db_path=settings.db_path)
    await state_repo.initialize()

    agent = KYFAgent(
        moltbook=moltbook,
        llm=llm,
        state_repo=state_repo,
        max_posts_per_day=settings.max_posts_per_day,
        max_comments_per_heartbeat=settings.max_comments_per_heartbeat,
    )

    scheduler = HeartbeatScheduler(
        agent=agent,
        interval_hours=settings.heartbeat_interval_hours,
    )

    # --- Graceful shutdown ---
    shutdown_event = asyncio.Event()

    def _signal_handler(sig: int, frame: object) -> None:
        logger.info("shutdown_signal_received", signal=sig)
        shutdown_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # --- Run ---
    try:
        scheduler.start()
        await scheduler.run_initial_heartbeat()
        logger.info("kyf_running", interval=f"every {settings.heartbeat_interval_hours}h")
        await shutdown_event.wait()
    finally:
        scheduler.stop()
        await agent.shutdown()
        logger.info("kyf_stopped")


if __name__ == "__main__":
    asyncio.run(main())
