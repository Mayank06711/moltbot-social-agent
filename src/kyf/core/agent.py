"""Core agent orchestrating the heartbeat loop.

Open/Closed: services are injected, new behaviors added via new services.
Dependency Inversion: depends on abstractions, not concrete implementations.
Single Responsibility: only orchestrates the flow, delegates to services.
"""

from kyf.clients.base import AbstractMoltbookClient
from kyf.clients.moltbook_client import MoltbookClientError
from kyf.core.interfaces import (
    AbstractContentAnalyzer,
    AbstractFactChecker,
    AbstractPostCreator,
    AbstractStateRepository,
)
from kyf.logger import get_logger
from kyf.models.agent_state import ActionLog, ActionType
from kyf.models.moltbook import (
    CreateCommentRequest,
    CreatePostRequest,
    PostSortOrder,
    VoteDirection,
    VoteRequest,
)

logger = get_logger(__name__)


class KYFAgent:
    """Main agent that runs the heartbeat loop.

    All dependencies are injected — nothing is constructed internally.
    """

    def __init__(
        self,
        moltbook: AbstractMoltbookClient,
        state_repo: AbstractStateRepository,
        analyzer: AbstractContentAnalyzer,
        fact_checker: AbstractFactChecker,
        post_creator: AbstractPostCreator,
        max_posts_per_day: int = 3,
        max_comments_per_heartbeat: int = 10,
    ) -> None:
        self._moltbook = moltbook
        self._state_repo = state_repo
        self._analyzer = analyzer
        self._fact_checker = fact_checker
        self._post_creator = post_creator
        self._max_posts_per_day = max_posts_per_day
        self._max_comments_per_heartbeat = max_comments_per_heartbeat

    async def run_heartbeat(self) -> None:
        """Execute one full heartbeat cycle."""
        logger.info("heartbeat_start")

        try:
            await self._fetch_heartbeat()
            await self._browse_and_engage()
            await self._maybe_create_post()

            await self._state_repo.log_action(
                ActionLog(action_type=ActionType.HEARTBEAT)
            )
            logger.info("heartbeat_complete")

        except Exception as e:
            logger.error("heartbeat_failed", error=str(e))

    async def _fetch_heartbeat(self) -> None:
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

            unseen = []
            for post in posts:
                if not await self._state_repo.is_post_seen(post.id):
                    unseen.append(post)
                    await self._state_repo.mark_post_seen(post.id)

            if not unseen:
                continue

            checkable = await self._analyzer.filter_checkable(unseen)

            for post, analysis in checkable:
                if comments_made >= self._max_comments_per_heartbeat:
                    break

                try:
                    response = await self._fact_checker.generate_reply(post, analysis)

                    await self._moltbook.create_comment(
                        CreateCommentRequest(
                            post_id=post.id,
                            body=response.response_text,
                        )
                    )

                    await self._state_repo.log_action(
                        ActionLog(
                            action_type=ActionType.COMMENT_CREATED,
                            target_id=post.id,
                            details=f"verdict={response.verdict}",
                        )
                    )

                    comments_made += 1
                    await self._vote_on_post(post.id, response.verdict)

                except Exception as e:
                    logger.error("engage_failed", post_id=post.id, error=str(e))

        logger.info("browse_complete", comments_made=comments_made)

    async def _vote_on_post(self, post_id: str, verdict: str) -> None:
        try:
            if verdict in ("true", "mostly_true"):
                direction = VoteDirection.UPVOTE
            elif verdict in ("false", "misleading"):
                direction = VoteDirection.DOWNVOTE
            else:
                return

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
        await self._moltbook.close()
        await self._state_repo.close()
        logger.info("agent_shutdown")
