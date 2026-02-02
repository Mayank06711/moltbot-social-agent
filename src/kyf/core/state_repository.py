"""File-based state persistence using JSON + JSONL.

Implements AbstractStateRepository.
- state.json: agent state (seen posts, counters) — overwritten each save
- actions.jsonl: append-only action log — one JSON object per line
"""

import asyncio
import json
from datetime import datetime, date
from pathlib import Path

from kyf.core.interfaces import AbstractStateRepository
from kyf.logger import get_logger
from kyf.models.agent_state import ActionLog, ActionType, AgentState

logger = get_logger(__name__)


class FileStateRepository(AbstractStateRepository):
    """Persists agent state to JSON files on disk."""

    def __init__(self, data_dir: str) -> None:
        self._data_dir = Path(data_dir)
        self._state_path = self._data_dir / "state.json"
        self._actions_path = self._data_dir / "actions.jsonl"
        self._seen_path = self._data_dir / "seen_posts.json"
        self._replied_path = self._data_dir / "replied_comments.json"
        self._lock = asyncio.Lock()
        self._seen_ids: set[str] = set()
        self._replied_ids: set[str] = set()

    async def initialize(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Load seen post IDs into memory for fast lookup
        if self._seen_path.exists():
            raw = self._seen_path.read_text(encoding="utf-8")
            self._seen_ids = set(json.loads(raw)) if raw.strip() else set()

        # Load replied comment IDs into memory for fast lookup
        if self._replied_path.exists():
            raw = self._replied_path.read_text(encoding="utf-8")
            self._replied_ids = set(json.loads(raw)) if raw.strip() else set()

        # Ensure action log file exists
        if not self._actions_path.exists():
            self._actions_path.touch()

        logger.info("file_state_initialized", data_dir=str(self._data_dir))

    # --- Agent State ---

    async def load_state(self) -> AgentState:
        async with self._lock:
            if not self._state_path.exists():
                return AgentState(seen_post_ids=self._seen_ids)

            raw = self._state_path.read_text(encoding="utf-8")
            if not raw.strip():
                return AgentState(seen_post_ids=self._seen_ids)

            state = AgentState.model_validate_json(raw)
            state.seen_post_ids = self._seen_ids
            return state

    async def save_state(self, state: AgentState) -> None:
        async with self._lock:
            # Save state (without seen_ids — those live in their own file)
            state_data = state.model_dump(exclude={"seen_post_ids"})
            self._state_path.write_text(
                json.dumps(state_data, indent=2, default=str),
                encoding="utf-8",
            )

    # --- Seen Posts ---

    async def mark_post_seen(self, post_id: str) -> None:
        async with self._lock:
            self._seen_ids.add(post_id)
            self._seen_path.write_text(
                json.dumps(list(self._seen_ids)),
                encoding="utf-8",
            )

    async def is_post_seen(self, post_id: str) -> bool:
        return post_id in self._seen_ids

    # --- Replied Comments ---

    async def mark_comment_replied(self, comment_id: str) -> None:
        async with self._lock:
            self._replied_ids.add(comment_id)
            self._replied_path.write_text(
                json.dumps(list(self._replied_ids)),
                encoding="utf-8",
            )

    async def is_comment_replied(self, comment_id: str) -> bool:
        return comment_id in self._replied_ids

    # --- Action Log (JSONL append-only) ---

    async def log_action(self, action: ActionLog) -> None:
        async with self._lock:
            line = json.dumps({
                "action_type": action.action_type.value,
                "target_id": action.target_id,
                "details": action.details,
                "created_at": action.created_at.isoformat(),
            })
            with self._actions_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    async def get_today_action_count(self, action_type: ActionType) -> int:
        today = date.today().isoformat()
        count = 0

        if not self._actions_path.exists():
            return 0

        async with self._lock:
            for line in self._actions_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                if (
                    entry.get("action_type") == action_type.value
                    and entry.get("created_at", "").startswith(today)
                ):
                    count += 1

        return count

    async def get_action_target_ids(self, action_type: ActionType) -> list[str]:
        """Return all target_ids for a given action type from the action log."""
        ids: list[str] = []
        if not self._actions_path.exists():
            return ids
        async with self._lock:
            for line in self._actions_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("action_type") == action_type.value and entry.get("target_id"):
                    ids.append(entry["target_id"])
        return ids

    # --- Lifecycle ---

    async def close(self) -> None:
        logger.info("file_state_closed")
