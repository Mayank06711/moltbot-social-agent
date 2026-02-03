"""Pydantic models for LLM integration schemas."""

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    model: str = "llama-3.3-70b-versatile"
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=1024, gt=0)


class AnalysisResult(BaseModel):
    """Result of analyzing a post for fact-checkable claims."""

    has_checkable_claim: bool
    claim_summary: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str | None = None


class FactCheckResponse(BaseModel):
    """Generated fact-check reply to a post."""

    response_text: str = Field(..., min_length=1, max_length=5000)
    verdict: str = Field(..., description="e.g. 'misleading', 'false', 'partially true', 'true'")
    sources_used: list[str] = Field(default_factory=list)


class CommentReplyResponse(BaseModel):
    """Generated conversational reply to a comment on agent's own post."""

    response_text: str = Field(..., min_length=1, max_length=2000)


class OriginalPostContent(BaseModel):
    """Generated content for an original myth-busting post."""

    title: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1, max_length=10000)
    target_submolt: str = "science"
    topic_category: str | None = None
