"""Pydantic models for Moltbook API request/response schemas."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, HttpUrl, model_validator


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


class AuthorInfo(BaseModel):
    """Nested author object returned by the Moltbook API."""

    id: str
    name: str


class SubmoltInfo(BaseModel):
    """Nested submolt object returned by the Moltbook API."""

    id: str
    name: str
    display_name: str | None = None


class AgentProfile(BaseModel):
    id: str
    username: str | None = None
    name: str | None = None
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
    """Moltbook post.

    API returns 'content' for the post body and nested objects for author/submolt.
    We normalize these into flat fields for easier downstream use.
    """

    id: str
    title: str
    body: str | None = None
    url: str | None = None
    author_name: str | None = None
    submolt: str | None = None
    upvotes: int = 0
    downvotes: int = 0
    comment_count: int = 0
    created_at: datetime | None = None

    @property
    def score(self) -> int:
        return self.upvotes - self.downvotes

    @model_validator(mode="before")
    @classmethod
    def _normalize_api_response(cls, data: Any) -> Any:
        """Normalize API response fields to our internal model."""
        if not isinstance(data, dict):
            return data

        # content -> body
        if "content" in data and "body" not in data:
            data["body"] = data.pop("content")

        # nested author -> author_name
        author = data.get("author")
        if isinstance(author, dict):
            data["author_name"] = author.get("name")
            data.pop("author", None)
        elif isinstance(author, str):
            data["author_name"] = author
            data.pop("author", None)

        # nested submolt -> submolt (string name)
        submolt = data.get("submolt")
        if isinstance(submolt, dict):
            data["submolt"] = submolt.get("name")

        return data


class Comment(BaseModel):
    id: str
    body: str = ""
    author_name: str | None = None
    post_id: str | None = None
    parent_id: str | None = None
    upvotes: int = 0
    downvotes: int = 0
    created_at: datetime | None = None

    @property
    def score(self) -> int:
        return self.upvotes - self.downvotes

    @model_validator(mode="before") #validate the data before validation (before instantiation) 
    @classmethod #to mkae method, to belong to class instead of its ojb (self)
    def _normalize_api_response(cls, data: Any) -> Any:
        if not isinstance(data, dict): # if data is not instance of dict
            return data

        # content -> body
        if "content" in data and "body" not in data:
            data["body"] = data.pop("content")

        # nested author -> author_name
        author = data.get("author")
        if isinstance(author, dict):
            data["author_name"] = author.get("name")
            data.pop("author", None)
        elif isinstance(author, str):
            data["author_name"] = author
            data.pop("author", None)

        return data


class RegistrationResponse(BaseModel):
    api_key: str
    claim_url: str
    verification_code: str | None = None


# --- Request models ---


class CreatePostRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    content: str | None = Field(default=None, max_length=10000)
    url: str | None = None
    submolt: str = Field(..., min_length=1)


class CreateCommentRequest(BaseModel):
    """Comment creation request.

    Note: post_id is used for the URL path (POST /posts/:id/comments),
    not included in the JSON body.
    """

    post_id: str = Field(..., min_length=1, exclude=True)
    content: str = Field(..., min_length=1, max_length=5000)
    parent_id: str | None = None


class VoteRequest(BaseModel):
    target_id: str = Field(..., min_length=1)
    direction: VoteDirection


class CommentVoteRequest(BaseModel):
    """Vote on a comment. Uses POST /comments/:id/upvote|downvote."""

    comment_id: str = Field(..., min_length=1)
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
