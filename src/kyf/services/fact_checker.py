"""Service for generating fact-check responses to posts.

Single Responsibility: only handles response generation for identified claims.
"""

from kyf.clients.llm_client import LLMClient
from kyf.core.interfaces import AbstractFactChecker
from kyf.logger import get_logger
from kyf.models.llm import AnalysisResult, FactCheckResponse
from kyf.models.moltbook import Post
from kyf.prompts.templates import PromptTemplates
from kyf.utils.sanitizer import InputSanitizer

logger = get_logger(__name__)


class FactCheckerService(AbstractFactChecker):
    """Generates witty fact-check responses using the LLM."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def generate_reply(self, post: Post, analysis: AnalysisResult) -> FactCheckResponse:
        """Generate a fact-check reply for a post with an identified claim."""
        sanitized_title = InputSanitizer.sanitize(post.title)
        sanitized_body = InputSanitizer.sanitize(post.body or "")
        # Re-sanitize claim_summary — it's LLM output from the analyzer,
        # which could have been influenced by a crafted post to smuggle
        # injection payloads into this second LLM call.
        raw_claim = analysis.claim_summary or "unspecified claim"
        if InputSanitizer.is_suspicious(raw_claim):
            logger.warning(
                "suspicious_claim_summary",
                post_id=post.id,
                raw_claim=raw_claim[:200],
            )
        sanitized_claim = InputSanitizer.sanitize(raw_claim)

        prompt = PromptTemplates.FACT_CHECK_REPLY.format(
            title=sanitized_title,
            body=sanitized_body,
            claim_summary=sanitized_claim,
        )

        try:
            raw = await self._llm.generate_json(
                system_prompt=PromptTemplates.SYSTEM_PERSONA,
                user_prompt=prompt,
            )
            response = FactCheckResponse.model_validate(raw)
            logger.info(
                "fact_check_generated",
                post_id=post.id,
                verdict=response.verdict,
            )
            return response

        except Exception as e:
            logger.error("fact_check_failed", post_id=post.id, error=str(e))
            raise
