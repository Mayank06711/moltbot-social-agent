"""Core agent orchestrating the heartbeat loop.

Open/Closed: services are injected, new behaviors added via new services.
Dependency Inversion: depends on abstractions (LLMClient, service interfaces).
Single Responsibility: only orchestrates the flow, delegates to services.
"""

from datetime import datetime

from kyf.clients.llm_client import LLMClient
from kyf.clients.moltbook_client import MoltbookClient, MoltbookClientError
from kyf.core.state_repository import StateRepository
from kyf.logger import get_logger
from kyf.models.agent_state import ActionLog, ActionType
from kyf.models.moltbook import (
    CreateCommentRequest,
    CreatePostRequest,
    PostSortOrder,
    VoteDirection,
    VoteRequest,
)
from kyf.prompts.templates import PromptTemplates
from kyf.services.content_analyzer import ContentAnalyzerService
from kyf.services.fact_checker import FactCheckerService
from kyf.services.post_creator import PostCreatorService
from kyf.utils.sanitizer import InputSanitizer

logger = get_logger(__name__)


class KYFAgent:
    """Main agent that runs the heartbeat loop."""

    def __init__(
        self,
        moltbook: MoltbookClient,
        llm: LLMClient,
        state_repo: StateRepository,
        max_posts_per_day: int = 3,
        max_comments_per_heartbeat: int = 10,
    ) -> None:
        self._moltbook = moltbook
        self._state_repo = state_repo
        self._analyzer = ContentAnalyzerService(llm)
        self._fact_checker = FactCheckerService(llm)
        self._post_creator = PostCreatorService(llm)
        self._llm = llm
        self._max_posts_per_day = max_posts_per_day
        self._max_comments_per_heartbeat = max_comments_per_heartbeat

    async def run_heartbeat(self) -> None:
        """Execute one full heartbeat cycle."""
        logger.info("heartbeat_start")

        try:
            # 1. Fetch heartbeat from Moltbook
            await self._fetch_heartbeat()

            # 2. Browse and analyze feed
            await self._browse_and_engage()

            # 3. Optionally create an original post
            await self._maybe_create_post()

            # 4. Log heartbeat completion
            await self._state_repo.log_action(
                ActionLog(action_type=ActionType.HEARTBEAT)
            )
            logger.info("heartbeat_complete")

        except Exception as e:
            logger.error("heartbeat_failed", error=str(e))

    async def _fetch_heartbeat(self) -> None:
        """Fetch the heartbeat.md file from Moltbook."""
        try:
            content = await self._moltbook.fetch_heartbeat()
            logger.debug("heartbeat_fetched", length=len(content))
        except Exception as e:
            logger.warning("heartbeat_fetch_failed", error=str(e))

    async def _browse_and_engage(self) -> None:
        """Browse feed, analyze posts, and respond to fact-checkable claims."""
        comments_made = 0

        for sort_order in [PostSortOrder.HOT, PostSortOrder.NEW]:
            if comments_made >= self._max_comments_per_heartbeat:
                break

            try:
                posts = await self._moltbook.get_posts(sort=sort_order)
            except MoltbookClientError as e:
                logger.error("feed_fetch_failed", sort=sort_order.value, error=str(e))
                continue

            # Filter to unseen posts
            unseen = []
            for post in posts:
                if not await self._state_repo.is_post_seen(post.id):
                    unseen.append(post)
                    await self._state_repo.mark_post_seen(post.id)

            if not unseen:
                continue

            # Analyze for checkable claims
            checkable = await self._analyzer.filter_checkable(unseen)

            for post, analysis in checkable:
                if comments_made >= self._max_comments_per_heartbeat:
                    break

                try:
                    # Generate fact-check
                    response = await self._fact_checker.generate_reply(post, analysis)

                    # Post comment
                    await self._moltbook.create_comment(
                        CreateCommentRequest(
                            post_id=post.id,
                            body=response.response_text,
                        )
                    )

                    # Log action
                    await self._state_repo.log_action(
                        ActionLog(
                            action_type=ActionType.COMMENT_CREATED,
                            target_id=post.id,
                            details=f"verdict={response.verdict}",
                        )
                    )

                    comments_made += 1

                    # Vote based on verdict
                    await self._vote_on_post(post.id, response.verdict)

                except Exception as e:
                    logger.error("engage_failed", post_id=post.id, error=str(e))

        logger.info("browse_complete", comments_made=comments_made)

    async def _vote_on_post(self, post_id: str, verdict: str) -> None:
        """Vote on a post based on the fact-check verdict."""
        try:
            if verdict in ("true", "mostly_true"):
                direction = VoteDirection.UPVOTE
            elif verdict in ("false", "misleading"):
                direction = VoteDirection.DOWNVOTE
            else:
                return  # skip voting on ambiguous verdicts

            await self._moltbook.vote(VoteRequest(target_id=post_id, direction=direction))
            await self._state_repo.log_action(
                ActionLog(
                    action_type=ActionType.VOTE_CAST,
                    target_id=post_id,
                    details=direction.value,
                )
            )
        except Exception as e:
            logger.warning("vote_failed", post_id=post_id, error=str(e))

    async def _maybe_create_post(self) -> None:
        """Create an original post if we haven't hit the daily limit."""
        today_posts = await self._state_repo.get_today_action_count(ActionType.POST_CREATED)
        if today_posts >= self._max_posts_per_day:
            logger.debug("post_limit_reached", today=today_posts, max=self._max_posts_per_day)
            return

        try:
            content = await self._post_creator.create_post()
            post = await self._moltbook.create_post(
                CreatePostRequest(
                    title=content.title,
                    body=content.body,
                    submolt=content.target_submolt,
                )
            )

            await self._state_repo.log_action(
                ActionLog(
                    action_type=ActionType.POST_CREATED,
                    target_id=post.id,
                    details=content.topic_category,
                )
            )
            logger.info("original_post_published", post_id=post.id, title=content.title[:50])

        except Exception as e:
            logger.error("post_creation_failed", error=str(e))

    async def shutdown(self) -> None:
        """Clean up resources."""
        await self._moltbook.close()
        await self._state_repo.close()
        logger.info("agent_shutdown")
