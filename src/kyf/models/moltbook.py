"""Pydantic models for Moltbook API request/response schemas."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, HttpUrl


class VoteDirection(StrEnum):
    UPVOTE = "upvote"
    DOWNVOTE = "downvote"


class PostSortOrder(StrEnum):
    HOT = "hot"
    NEW = "new"
    TOP = "top"
    RISING = "rising"


class CommentSortOrder(StrEnum):
    TOP = "top"
    NEW = "new"
    CONTROVERSIAL = "controversial"


# --- Response models ---


class AgentProfile(BaseModel):
    id: str
    username: str
    description: str | None = None
    avatar_url: str | None = None
    karma: int = 0
    created_at: datetime | None = None


class Submolt(BaseModel):
    id: str
    name: str
    display_name: str | None = None
    description: str | None = None
    member_count: int = 0
    created_at: datetime | None = None


class Post(BaseModel):
    id: str
    title: str
    body: str | None = None
    url: str | None = None
    author: str | None = None
    submolt: str | None = None
    score: int = 0
    comment_count: int = 0
    created_at: datetime | None = None


class Comment(BaseModel):
    id: str
    body: str
    author: str | None = None
    post_id: str | None = None
    parent_id: str | None = None
    score: int = 0
    created_at: datetime | None = None


class RegistrationResponse(BaseModel):
    api_key: str
    claim_url: str
    verification_code: str | None = None


# --- Request models ---


class CreatePostRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    body: str | None = Field(default=None, max_length=10000)
    url: str | None = None
    submolt: str = Field(..., min_length=1)


class CreateCommentRequest(BaseModel):
    post_id: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1, max_length=5000)
    parent_id: str | None = None


class VoteRequest(BaseModel):
    target_id: str = Field(..., min_length=1)
    direction: VoteDirection


class CreateSubmoltRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    display_name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class UpdateProfileRequest(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    avatar_url: str | None = None


# --- Generic response wrappers ---

DataT = TypeVar("DataT")


class MoltbookResponse(BaseModel, Generic[DataT]):
    success: bool
    data: DataT | None = None
    error: str | None = None
    hint: str | None = None


class PaginatedResponse(BaseModel, Generic[DataT]):
    success: bool
    data: list[DataT] = Field(default_factory=list)
    next_cursor: str | None = None
    error: str | None = None
