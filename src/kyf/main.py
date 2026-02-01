"""Entry point for the KYF agent.

Composition Root: wires up all abstractions to their concrete implementations.
This is the ONLY place that knows about concrete classes.
"""

import asyncio
import signal

from kyf.clients.llm_client import GeminiClient
from kyf.clients.moltbook_client import MoltbookClient
from kyf.config import load_settings
from kyf.core.agent import KYFAgent
from kyf.core.scheduler import HeartbeatScheduler
from kyf.core.state_repository import FileStateRepository
from kyf.logger import get_logger, setup_logging
from kyf.services.content_analyzer import ContentAnalyzerService
from kyf.services.fact_checker import FactCheckerService
from kyf.services.post_creator import PostCreatorService


async def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    logger = get_logger("kyf.main")

    logger.info("kyf_starting", version="0.1.0")

    # --- Compose concrete implementations ---
    moltbook = MoltbookClient(
        base_url=settings.moltbook_base_url,
        api_key=settings.moltbook_api_key,
    )

    llm = GeminiClient(api_key=settings.gemini_api_key)

    state_repo = FileStateRepository(data_dir=settings.db_path)
    await state_repo.initialize()

    # Services — all depend on LLMClient abstraction
    analyzer = ContentAnalyzerService(llm)
    fact_checker = FactCheckerService(llm)
    post_creator = PostCreatorService(llm)

    # Agent — depends only on abstract interfaces
    agent = KYFAgent(
        moltbook=moltbook,
        state_repo=state_repo,
        analyzer=analyzer,
        fact_checker=fact_checker,
        post_creator=post_creator,
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
