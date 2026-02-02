"""Pydantic models for agent internal state tracking."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ActionType(StrEnum):
    POST_CREATED = "post_created"
    COMMENT_CREATED = "comment_created"
    COMMENT_REPLIED = "comment_replied"
    VOTE_CAST = "vote_cast"
    COMMENT_VOTE_CAST = "comment_vote_cast"
    SUBMOLT_JOINED = "submolt_joined"
    HEARTBEAT = "heartbeat"
    FEED_BROWSED = "feed_browsed"
    PROFILE_UPDATED = "profile_updated"


class ActionLog(BaseModel):
    id: int | None = None
    action_type: ActionType
    target_id: str | None = None
    details: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentState(BaseModel):
    last_heartbeat: datetime | None = None
    posts_today: int = 0
    comments_today: int = 0
    last_post_at: datetime | None = None
    last_comment_at: datetime | None = None
    seen_post_ids: set[str] = Field(default_factory=set)
    subscribed_submolts: set[str] = Field(default_factory=set)

    def can_post(self, max_posts_per_day: int) -> bool:
        return self.posts_today < max_posts_per_day

    def can_comment(self, max_comments_per_day: int) -> bool:
        return self.comments_today < max_comments_per_day

    def mark_post_seen(self, post_id: str) -> None:
        self.seen_post_ids.add(post_id)

    def is_post_seen(self, post_id: str) -> bool:
        return post_id in self.seen_post_ids
