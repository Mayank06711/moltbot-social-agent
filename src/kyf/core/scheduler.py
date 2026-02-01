"""Heartbeat scheduler that triggers the agent loop on a fixed interval.

Single Responsibility: only handles scheduling, delegates execution to the agent.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from kyf.core.agent import KYFAgent
from kyf.logger import get_logger

logger = get_logger(__name__)


class HeartbeatScheduler:
    """Schedules the agent heartbeat at a configurable interval."""

    def __init__(self, agent: KYFAgent, interval_hours: int = 4) -> None:
        self._agent = agent
        self._interval_hours = interval_hours
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        """Start the scheduler and run the first heartbeat immediately."""
        self._scheduler.add_job(
            self._agent.run_heartbeat,
            trigger=IntervalTrigger(hours=self._interval_hours),
            id="kyf_heartbeat",
            name="KYF Heartbeat",
            next_run_time=None,  # won't auto-run; we trigger manually first
        )
        self._scheduler.start()
        logger.info("scheduler_started", interval_hours=self._interval_hours)

    async def run_initial_heartbeat(self) -> None:
        """Run the first heartbeat immediately on startup."""
        logger.info("initial_heartbeat_triggered")
        await self._agent.run_heartbeat()

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self._scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")
