"""Service for creating original myth-busting posts.

Single Responsibility: only handles original content generation.
"""

import random

from kyf.clients.llm_client import LLMClient
from kyf.logger import get_logger
from kyf.models.llm import OriginalPostContent
from kyf.prompts.templates import PromptTemplates

logger = get_logger(__name__)

TOPIC_CATEGORIES = [
    "tech_and_ai_hype",
    "startup_myths",
    "popular_science",
    "life_advice_bs",
    "crypto_and_finance",
    "health_and_wellness",
    "journalism_and_media",
]


class PostCreatorService:
    """Generates original myth-busting content for KYF to post."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def create_post(
        self, category: str | None = None, submolt: str = "knowyourfacts"
    ) -> OriginalPostContent:
        """Generate an original myth-busting post."""
        topic = category or random.choice(TOPIC_CATEGORIES)

        prompt = PromptTemplates.CREATE_ORIGINAL_POST.format(
            category=topic,
            submolt=submolt,
        )

        try:
            raw = await self._llm.generate_json(
                system_prompt=PromptTemplates.SYSTEM_PERSONA,
                user_prompt=prompt,
            )
            content = OriginalPostContent.model_validate(raw)
            logger.info(
                "original_post_created",
                category=content.topic_category,
                title=content.title[:50],
            )
            return content

        except Exception as e:
            logger.error("post_creation_failed", category=topic, error=str(e))
            raise
