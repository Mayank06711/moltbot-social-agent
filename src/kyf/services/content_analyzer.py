"""Service for analyzing Moltbook posts to identify fact-checkable claims.

Single Responsibility: only handles claim detection logic.
Depends on LLMClient abstraction, not a concrete provider.
"""

from kyf.clients.llm_client import LLMClient
from kyf.core.interfaces import AbstractContentAnalyzer
from kyf.logger import get_logger
from kyf.models.llm import AnalysisResult
from kyf.models.moltbook import Post
from kyf.prompts.templates import PromptTemplates
from kyf.utils.sanitizer import InputSanitizer

logger = get_logger(__name__)


class ContentAnalyzerService(AbstractContentAnalyzer):
    """Analyzes posts to determine if they contain fact-checkable claims."""

    def __init__(self, llm: LLMClient, min_confidence: float = 0.6) -> None:
        self._llm = llm
        self._min_confidence = min_confidence

    async def analyze(self, post: Post) -> AnalysisResult:
        """Analyze a single post for checkable claims."""
        sanitized_title = InputSanitizer.sanitize(post.title)
        sanitized_body = InputSanitizer.sanitize(post.body or "")

        prompt = PromptTemplates.ANALYZE_POST.format(
            title=sanitized_title,
            body=sanitized_body,
            submolt=post.submolt or "general",
        )

        try:
            raw = await self._llm.generate_json(
                system_prompt=PromptTemplates.SYSTEM_PERSONA,
                user_prompt=prompt,
            )
            result = AnalysisResult.model_validate(raw)
            logger.info(
                "post_analyzed",
                post_id=post.id,
                has_claim=result.has_checkable_claim,
                confidence=result.confidence,
            )
            return result

        except Exception as e:
            logger.error("analysis_failed", post_id=post.id, error=str(e))
            return AnalysisResult(has_checkable_claim=False, reasoning=f"Analysis error: {e}")

    async def filter_checkable(self, posts: list[Post]) -> list[tuple[Post, AnalysisResult]]:
        """Filter a list of posts down to those with high-confidence checkable claims."""
        results: list[tuple[Post, AnalysisResult]] = []
        for post in posts:
            if InputSanitizer.is_suspicious(post.title) or InputSanitizer.is_suspicious(
                post.body or ""
            ):
                logger.warning("suspicious_post_skipped", post_id=post.id)
                continue

            analysis = await self.analyze(post)
            if analysis.has_checkable_claim and analysis.confidence >= self._min_confidence:
                results.append((post, analysis))

        logger.info("filter_complete", total=len(posts), checkable=len(results))
        return results
