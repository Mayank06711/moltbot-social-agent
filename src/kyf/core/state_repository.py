"""SQLite-backed state persistence for the agent.

Single Responsibility: only handles read/write of agent state to disk.
Interface Segregation: exposes only the operations the agent needs.
"""

import json
from datetime import datetime
from pathlib import Path

import aiosqlite

from kyf.logger import get_logger
from kyf.models.agent_state import ActionLog, ActionType, AgentState

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    target_id TEXT,
    details TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seen_posts (
    post_id TEXT PRIMARY KEY,
    seen_at TEXT NOT NULL
);
"""


class StateRepository:
    """Persists agent state and action logs to SQLite."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create database and tables if they don't exist."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("state_db_initialized", path=self._db_path)

    async def _get_db(self) -> aiosqlite.Connection:
        if self._db is None:
            await self.initialize()
        assert self._db is not None
        return self._db

    # --- Agent State ---

    async def load_state(self) -> AgentState:
        """Load the current agent state from the database."""
        db = await self._get_db()
        cursor = await db.execute("SELECT value FROM agent_state WHERE key = 'state'")
        row = await cursor.fetchone()
        if row:
            return AgentState.model_validate_json(row[0])

        # Load seen posts into a fresh state
        state = AgentState()
        cursor = await db.execute("SELECT post_id FROM seen_posts")
        rows = await cursor.fetchall()
        state.seen_post_ids = {r[0] for r in rows}
        return state

    async def save_state(self, state: AgentState) -> None:
        """Persist the current agent state."""
        db = await self._get_db()
        now = datetime.utcnow().isoformat()
        await db.execute(
            "INSERT OR REPLACE INTO agent_state (key, value, updated_at) VALUES (?, ?, ?)",
            ("state", state.model_dump_json(), now),
        )
        await db.commit()

    async def mark_post_seen(self, post_id: str) -> None:
        """Record that a post has been seen."""
        db = await self._get_db()
        now = datetime.utcnow().isoformat()
        await db.execute(
            "INSERT OR IGNORE INTO seen_posts (post_id, seen_at) VALUES (?, ?)",
            (post_id, now),
        )
        await db.commit()

    async def is_post_seen(self, post_id: str) -> bool:
        """Check if a post has already been processed."""
        db = await self._get_db()
        cursor = await db.execute("SELECT 1 FROM seen_posts WHERE post_id = ?", (post_id,))
        return await cursor.fetchone() is not None

    # --- Action Log ---

    async def log_action(self, action: ActionLog) -> None:
        """Record an agent action for auditing."""
        db = await self._get_db()
        await db.execute(
            "INSERT INTO action_log (action_type, target_id, details, created_at) VALUES (?, ?, ?, ?)",
            (
                action.action_type.value,
                action.target_id,
                action.details,
                action.created_at.isoformat(),
            ),
        )
        await db.commit()

    async def get_today_action_count(self, action_type: ActionType) -> int:
        """Count how many actions of a type were performed today."""
        db = await self._get_db()
        today = datetime.utcnow().date().isoformat()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM action_log WHERE action_type = ? AND created_at >= ?",
            (action_type.value, today),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    # --- Cleanup ---

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None
