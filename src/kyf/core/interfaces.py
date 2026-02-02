"""Abstract interfaces for core services and state persistence.

These define the contracts that the agent depends on.
Concrete implementations can be swapped without touching the agent.
"""

from abc import ABC, abstractmethod

from kyf.models.agent_state import ActionLog, ActionType, AgentState
from kyf.models.llm import AnalysisResult, FactCheckResponse, OriginalPostContent
from kyf.models.moltbook import Post


class AbstractStateRepository(ABC):
    """Interface for agent state persistence."""

    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def load_state(self) -> AgentState: ...

    @abstractmethod
    async def save_state(self, state: AgentState) -> None: ...

    @abstractmethod
    async def mark_post_seen(self, post_id: str) -> None: ...

    @abstractmethod
    async def is_post_seen(self, post_id: str) -> bool: ...

    @abstractmethod
    async def log_action(self, action: ActionLog) -> None: ...

    @abstractmethod
    async def get_today_action_count(self, action_type: ActionType) -> int: ...

    @abstractmethod
    async def mark_comment_replied(self, comment_id: str) -> None: ...

    @abstractmethod
    async def is_comment_replied(self, comment_id: str) -> bool: ...

    @abstractmethod
    async def get_action_target_ids(self, action_type: ActionType) -> list[str]: ...

    @abstractmethod
    async def close(self) -> None: ...


class AbstractContentAnalyzer(ABC):
    """Interface for post analysis."""

    @abstractmethod
    async def analyze(self, post: Post) -> AnalysisResult: ...

    @abstractmethod
    async def filter_checkable(
        self, posts: list[Post]
    ) -> list[tuple[Post, AnalysisResult]]: ...


class AbstractFactChecker(ABC):
    """Interface for fact-check response generation."""

    @abstractmethod
    async def generate_reply(
        self, post: Post, analysis: AnalysisResult
    ) -> FactCheckResponse: ...


class AbstractPostCreator(ABC):
    """Interface for original post generation."""

    @abstractmethod
    async def create_post(
        self, category: str | None = None, submolt: str = "knowyourfacts"
    ) -> OriginalPostContent: ...
