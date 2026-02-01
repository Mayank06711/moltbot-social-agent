"""Abstract interfaces for all external clients.

Dependency Inversion Principle: high-level modules depend on these
abstractions, not on concrete HTTP/API implementations.
"""

from abc import ABC, abstractmethod

from kyf.models.moltbook import (
    AgentProfile,
    Comment,
    CommentSortOrder,
    CreateCommentRequest,
    CreatePostRequest,
    CreateSubmoltRequest,
    Post,
    PostSortOrder,
    Submolt,
    UpdateProfileRequest,
    VoteRequest,
)


class AbstractMoltbookClient(ABC):
    """Interface for Moltbook API operations."""

    # --- Posts ---

    @abstractmethod
    async def get_posts(
        self, sort: PostSortOrder = PostSortOrder.HOT, submolt: str | None = None
    ) -> list[Post]: ...

    @abstractmethod
    async def get_post(self, post_id: str) -> Post: ...

    @abstractmethod
    async def create_post(self, request: CreatePostRequest) -> Post: ...

    @abstractmethod
    async def delete_post(self, post_id: str) -> None: ...

    # --- Comments ---

    @abstractmethod
    async def get_comments(
        self, post_id: str, sort: CommentSortOrder = CommentSortOrder.TOP
    ) -> list[Comment]: ...

    @abstractmethod
    async def create_comment(self, request: CreateCommentRequest) -> Comment: ...

    # --- Voting ---

    @abstractmethod
    async def vote(self, request: VoteRequest) -> None: ...

    # --- Submolts ---

    @abstractmethod
    async def get_submolts(self) -> list[Submolt]: ...

    @abstractmethod
    async def get_submolt(self, name: str) -> Submolt: ...

    @abstractmethod
    async def create_submolt(self, request: CreateSubmoltRequest) -> Submolt: ...

    @abstractmethod
    async def subscribe(self, submolt_name: str) -> None: ...

    @abstractmethod
    async def unsubscribe(self, submolt_name: str) -> None: ...

    # --- Profile ---

    @abstractmethod
    async def get_profile(self) -> AgentProfile: ...

    @abstractmethod
    async def update_profile(self, request: UpdateProfileRequest) -> AgentProfile: ...

    # --- Heartbeat ---

    @abstractmethod
    async def fetch_heartbeat(self) -> str: ...

    # --- Lifecycle ---

    @abstractmethod
    async def close(self) -> None: ...
