"""Async HTTP client for the Moltbook API.

Follows Single Responsibility: only handles HTTP transport and response parsing.
Depends on abstractions (Pydantic models) not concrete implementations.
"""

from typing import Any

import httpx
from pydantic import SecretStr
from tenacity import retry, stop_after_attempt, wait_exponential

from kyf.logger import get_logger
from kyf.models.moltbook import (
    AgentProfile,
    Comment,
    CommentSortOrder,
    CreateCommentRequest,
    CreatePostRequest,
    CreateSubmoltRequest,
    MoltbookResponse,
    PaginatedResponse,
    Post,
    PostSortOrder,
    Submolt,
    UpdateProfileRequest,
    VoteRequest,
)
from kyf.utils.rate_limiter import RateLimiter

logger = get_logger(__name__)

_MOLTBOOK_HOST = "www.moltbook.com"


class MoltbookClientError(Exception):
    """Raised when Moltbook API returns an error response."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        self.hint = hint
        super().__init__(message)


class MoltbookClient:
    """Async client for Moltbook REST API."""

    def __init__(self, base_url: str, api_key: SecretStr) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._rate_limiter = RateLimiter(max_requests=90, window_seconds=60)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "Authorization": f"Bearer {self._api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    def _validate_url(self, url: str) -> None:
        """Ensure we only send credentials to moltbook.com."""
        if _MOLTBOOK_HOST not in url and _MOLTBOOK_HOST not in self._base_url:
            raise MoltbookClientError(
                f"Refusing to send API key to untrusted host: {url}"
            )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def _request(
        self, method: str, path: str, json_data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        await self._rate_limiter.acquire()
        client = await self._get_client()
        full_url = f"{self._base_url}{path}"
        self._validate_url(full_url)

        response = await client.request(method, path, json=json_data)
        response.raise_for_status()
        data = response.json()

        if not data.get("success", True):
            raise MoltbookClientError(
                data.get("error", "Unknown error"),
                hint=data.get("hint"),
            )

        logger.debug("api_request", method=method, path=path, status=response.status_code)
        return data

    # --- Posts ---

    async def get_posts(
        self, sort: PostSortOrder = PostSortOrder.HOT, submolt: str | None = None
    ) -> list[Post]:
        params = f"?sort={sort.value}"
        if submolt:
            params += f"&submolt={submolt}"
        data = await self._request("GET", f"/posts{params}")
        return [Post.model_validate(p) for p in data.get("data", [])]

    async def get_post(self, post_id: str) -> Post:
        data = await self._request("GET", f"/posts/{post_id}")
        return Post.model_validate(data.get("data", {}))

    async def create_post(self, request: CreatePostRequest) -> Post:
        data = await self._request("POST", "/posts", json_data=request.model_dump())
        logger.info("post_created", submolt=request.submolt, title=request.title[:50])
        return Post.model_validate(data.get("data", {}))

    async def delete_post(self, post_id: str) -> None:
        await self._request("DELETE", f"/posts/{post_id}")

    # --- Comments ---

    async def get_comments(
        self, post_id: str, sort: CommentSortOrder = CommentSortOrder.TOP
    ) -> list[Comment]:
        data = await self._request("GET", f"/posts/{post_id}/comments?sort={sort.value}")
        return [Comment.model_validate(c) for c in data.get("data", [])]

    async def create_comment(self, request: CreateCommentRequest) -> Comment:
        data = await self._request("POST", "/comments", json_data=request.model_dump(exclude_none=True))
        logger.info("comment_created", post_id=request.post_id)
        return Comment.model_validate(data.get("data", {}))

    # --- Voting ---

    async def vote(self, request: VoteRequest) -> None:
        await self._request("POST", "/vote", json_data=request.model_dump())

    # --- Submolts ---

    async def get_submolts(self) -> list[Submolt]:
        data = await self._request("GET", "/submolts")
        return [Submolt.model_validate(s) for s in data.get("data", [])]

    async def get_submolt(self, name: str) -> Submolt:
        data = await self._request("GET", f"/submolts/{name}")
        return Submolt.model_validate(data.get("data", {}))

    async def create_submolt(self, request: CreateSubmoltRequest) -> Submolt:
        data = await self._request("POST", "/submolts", json_data=request.model_dump(exclude_none=True))
        logger.info("submolt_created", name=request.name)
        return Submolt.model_validate(data.get("data", {}))

    async def subscribe(self, submolt_name: str) -> None:
        await self._request("POST", f"/submolts/{submolt_name}/subscribe")

    async def unsubscribe(self, submolt_name: str) -> None:
        await self._request("POST", f"/submolts/{submolt_name}/unsubscribe")

    # --- Profile ---

    async def get_profile(self) -> AgentProfile:
        data = await self._request("GET", "/agents/me")
        return AgentProfile.model_validate(data.get("data", {}))

    async def update_profile(self, request: UpdateProfileRequest) -> AgentProfile:
        data = await self._request("PATCH", "/agents/me", json_data=request.model_dump(exclude_none=True))
        return AgentProfile.model_validate(data.get("data", {}))

    # --- Heartbeat ---

    async def fetch_heartbeat(self) -> str:
        """Fetch heartbeat.md — uses a separate unauthenticated request."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://www.moltbook.com/heartbeat.md")
            resp.raise_for_status()
            return resp.text

    # --- Cleanup ---

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
