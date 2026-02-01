"""Async HTTP client for the Moltbook API.

Implements AbstractMoltbookClient.
Rate limiting handled via httpx event hooks — transparent to all request methods.
"""

import asyncio
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx
from pydantic import SecretStr
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from kyf.clients.base import AbstractMoltbookClient
from kyf.logger import get_logger
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

logger = get_logger(__name__)

_MOLTBOOK_HOST = "www.moltbook.com"


class MoltbookClientError(Exception):
    """Raised when Moltbook API returns an error response."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        self.hint = hint
        super().__init__(message)


def _build_rate_limit_hook(
    max_requests: int = 90, window_seconds: int = 60
) -> Callable[[httpx.Request], Any]:
    """Create an httpx request event hook that enforces rate limiting.

    Uses a sliding window approach — tracks timestamps of recent requests
    and sleeps if the limit is about to be exceeded.
    """
    timestamps: deque[datetime] = deque()
    lock = asyncio.Lock()
    window = timedelta(seconds=window_seconds)

    async def hook(request: httpx.Request) -> None:
        async with lock:
            now = datetime.utcnow()
            cutoff = now - window

            # Evict expired timestamps
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= max_requests:
                oldest = timestamps[0]
                wait = (oldest + window - now).total_seconds()
                if wait > 0:
                    logger.debug("rate_limit_wait", seconds=round(wait, 2))
                    await asyncio.sleep(wait)

            timestamps.append(datetime.utcnow())

    return hook


def _build_logging_hook() -> Callable[[httpx.Response], Any]:
    """Create an httpx response event hook that logs all API responses."""

    async def hook(response: httpx.Response) -> None:
        # Log rate limit headers if present
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        extra: dict[str, Any] = {}
        if remaining is not None:
            extra["rate_limit_remaining"] = remaining
        if reset is not None:
            extra["rate_limit_reset"] = reset

        logger.debug(
            "api_response",
            method=response.request.method,
            url=str(response.request.url.path),
            status=response.status_code,
            **extra,
        )

    return hook


class MoltbookClient(AbstractMoltbookClient):
    """Concrete Moltbook API client with rate limiting via httpx hooks."""

    def __init__(self, base_url: str, api_key: SecretStr) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
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
                event_hooks={
                    "request": [_build_rate_limit_hook()],
                    "response": [_build_logging_hook()],
                },
            )
        return self._client

    def _validate_url(self, url: str) -> None:
        """Ensure we only send credentials to moltbook.com."""
        if _MOLTBOOK_HOST not in url and _MOLTBOOK_HOST not in self._base_url:
            raise MoltbookClientError(
                f"Refusing to send API key to untrusted host: {url}"
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_not_exception_type(MoltbookClientError),
    )
    async def _request(
        self, method: str, path: str, json_data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        client = await self._get_client()
        full_url = f"{self._base_url}{path}"
        self._validate_url(full_url)

        response = await client.request(method, path, json=json_data)

        try:
            data = response.json()
        except Exception:
            response.raise_for_status()
            return {}

        if not data.get("success", True):
            hint = data.get("hint")
            error_msg = data.get("error", "Unknown error")
            logger.warning(
                "api_error",
                method=method,
                path=path,
                status=response.status_code,
                error=error_msg,
                hint=hint,
            )
            raise MoltbookClientError(error_msg, hint=hint)

        response.raise_for_status()
        return data

    # --- Posts ---

    async def get_posts(
        self, sort: PostSortOrder = PostSortOrder.HOT, submolt: str | None = None
    ) -> list[Post]:
        params = f"?sort={sort.value}"
        if submolt:
            params += f"&submolt={submolt}"
        data = await self._request("GET", f"/posts{params}")
        return [Post.model_validate(p) for p in data.get("posts", data.get("data", []))]

    async def get_feed(
        self, sort: PostSortOrder = PostSortOrder.HOT, limit: int = 25
    ) -> list[Post]:
        """Get personalized feed (from subscribed submolts and followed agents)."""
        data = await self._request("GET", f"/feed?sort={sort.value}&limit={limit}")
        return [Post.model_validate(p) for p in data.get("posts", data.get("data", []))]

    async def get_post(self, post_id: str) -> Post:
        data = await self._request("GET", f"/posts/{post_id}")
        post_data = data.get("post", data.get("data", {}))
        return Post.model_validate(post_data)

    async def create_post(self, request: CreatePostRequest) -> Post:
        data = await self._request("POST", "/posts", json_data=request.model_dump(exclude_none=True))
        post_data = data.get("post", data.get("data", {}))
        logger.info("post_created", submolt=request.submolt, title=request.title[:50])
        return Post.model_validate(post_data)

    async def delete_post(self, post_id: str) -> None:
        await self._request("DELETE", f"/posts/{post_id}")

    # --- Comments ---

    async def get_comments(
        self, post_id: str, sort: CommentSortOrder = CommentSortOrder.TOP
    ) -> list[Comment]:
        data = await self._request("GET", f"/posts/{post_id}/comments?sort={sort.value}")
        return [Comment.model_validate(c) for c in data.get("comments", data.get("data", []))]

    async def create_comment(self, request: CreateCommentRequest) -> Comment:
        # API expects POST /posts/:id/comments with {content, parent_id} in body
        data = await self._request(
            "POST",
            f"/posts/{request.post_id}/comments",
            json_data=request.model_dump(exclude_none=True),
        )
        comment_data = data.get("comment", data.get("data", {}))
        logger.info("comment_created", post_id=request.post_id)
        return Comment.model_validate(comment_data)

    # --- Voting ---

    async def vote(self, request: VoteRequest) -> None:
        # API uses POST /posts/:id/upvote or POST /posts/:id/downvote
        await self._request("POST", f"/posts/{request.target_id}/{request.direction.value}")

    # --- Submolts ---

    async def get_submolts(self) -> list[Submolt]:
        data = await self._request("GET", "/submolts")
        return [Submolt.model_validate(s) for s in data.get("submolts", data.get("data", []))]

    async def get_submolt(self, name: str) -> Submolt:
        data = await self._request("GET", f"/submolts/{name}")
        submolt_data = data.get("submolt", data.get("data", {}))
        return Submolt.model_validate(submolt_data)

    async def create_submolt(self, request: CreateSubmoltRequest) -> Submolt:
        data = await self._request("POST", "/submolts", json_data=request.model_dump(exclude_none=True))
        submolt_data = data.get("submolt", data.get("data", {}))
        logger.info("submolt_created", name=request.name)
        return Submolt.model_validate(submolt_data)

    async def subscribe(self, submolt_name: str) -> None:
        await self._request("POST", f"/submolts/{submolt_name}/subscribe")

    async def unsubscribe(self, submolt_name: str) -> None:
        await self._request("DELETE", f"/submolts/{submolt_name}/subscribe")

    # --- Profile ---

    async def get_profile(self) -> AgentProfile:
        data = await self._request("GET", "/agents/me")
        profile_data = data.get("agent", data.get("data", {}))
        return AgentProfile.model_validate(profile_data)

    async def update_profile(self, request: UpdateProfileRequest) -> AgentProfile:
        data = await self._request("PATCH", "/agents/me", json_data=request.model_dump(exclude_none=True))
        profile_data = data.get("agent", data.get("data", {}))
        return AgentProfile.model_validate(profile_data)

    # --- Heartbeat ---

    async def fetch_heartbeat(self) -> str:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://www.moltbook.com/heartbeat.md")
            resp.raise_for_status()
            return resp.text

    # --- Lifecycle ---

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
