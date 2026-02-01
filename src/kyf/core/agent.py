"""Core agent orchestrating the heartbeat loop.

Open/Closed: services are injected, new behaviors added via new services.
Dependency Inversion: depends on abstractions, not concrete implementations.
Single Responsibility: only orchestrates the flow, delegates to services.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from kyf.clients.base import AbstractMoltbookClient
from kyf.clients.llm_client import LLMRateLimitError
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
        data_dir: str = "data",
    ) -> None:
        self._moltbook = moltbook
        self._state_repo = state_repo
        self._analyzer = analyzer
        self._fact_checker = fact_checker
        self._post_creator = post_creator
        self._max_posts_per_day = max_posts_per_day
        self._max_comments_per_heartbeat = max_comments_per_heartbeat
        self._data_dir = Path(data_dir)
        self._llm_limited = False

    def _write_llm_limits(self, error: LLMRateLimitError, phase: str) -> None:
        """Write rate limit details to llm-limits.json for later inspection."""
        limits_path = self._data_dir / "llm-limits.json"
        entry = {
            "hit_at": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "error": str(error),
            "retry_after_seconds": error.retry_after,
        }

        # Append to existing entries if file exists
        entries: list[dict] = []
        if limits_path.exists():
            try:
                entries = json.loads(limits_path.read_text())
            except (json.JSONDecodeError, OSError):
                entries = []

        entries.append(entry)
        limits_path.write_text(json.dumps(entries, indent=2))
        logger.warning(
            "llm_limit_logged",
            path=str(limits_path),
            phase=phase,
            retry_after=error.retry_after,
        )

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

        except LLMRateLimitError as e:
            self._llm_limited = True
            self._write_llm_limits(e, phase="heartbeat")
            logger.error("heartbeat_aborted_llm_limit", error=str(e))

        except Exception as e:
            logger.error("heartbeat_failed", error=str(e), error_type=type(e).__name__)

    async def _fetch_heartbeat(self) -> None:
        try:
            content = await self._moltbook.fetch_heartbeat()
            logger.info("heartbeat_fetched", length=len(content))
        except Exception as e:
            logger.warning("heartbeat_fetch_failed", error=str(e))

    async def _browse_and_engage(self) -> None:
        """Browse feed, analyze posts, and respond to fact-checkable claims."""
        comments_made = 0

        for sort_order in [PostSortOrder.HOT, PostSortOrder.NEW]:
            if comments_made >= self._max_comments_per_heartbeat:
                break

            try:
                # Try personalized feed first, fall back to global posts
                try:
                    posts = await self._moltbook.get_feed(sort=sort_order)
                    logger.info("feed_fetched", source="personalized", sort=sort_order.value, post_count=len(posts))
                except Exception:
                    posts = await self._moltbook.get_posts(sort=sort_order)
                    logger.info("feed_fetched", source="global", sort=sort_order.value, post_count=len(posts))
            except MoltbookClientError as e:
                logger.error("feed_fetch_failed", sort=sort_order.value, error=str(e))
                continue

            if not posts:
                logger.info("feed_empty", sort=sort_order.value)
                continue

            unseen = []
            for post in posts:
                if not await self._state_repo.is_post_seen(post.id):
                    unseen.append(post)
                    await self._state_repo.mark_post_seen(post.id)

            logger.info(
                "feed_filtered",
                sort=sort_order.value,
                total=len(posts),
                unseen=len(unseen),
                already_seen=len(posts) - len(unseen),
            )

            if not unseen:
                continue

            for p in unseen[:5]:
                logger.info(
                    "unseen_post",
                    post_id=p.id,
                    title=p.title[:80],
                    author=p.author_name or "unknown",
                    submolt=p.submolt or "none",
                )

            # LLMRateLimitError bubbles up to run_heartbeat — stops the whole cycle
            checkable = await self._analyzer.filter_checkable(unseen)
            logger.info("analysis_complete", unseen=len(unseen), checkable=len(checkable))

            for post, analysis in checkable:
                if comments_made >= self._max_comments_per_heartbeat:
                    break

                try:
                    logger.info(
                        "fact_checking_post",
                        post_id=post.id,
                        title=post.title[:60],
                        confidence=analysis.confidence,
                        claim=analysis.claim_summary or "none",
                    )
                    response = await self._fact_checker.generate_reply(post, analysis)

                    await self._moltbook.create_comment(
                        CreateCommentRequest(
                            post_id=post.id,
                            content=response.response_text,
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
                    logger.info("comment_posted", post_id=post.id, verdict=response.verdict)
                    await self._vote_on_post(post.id, response.verdict)

                except LLMRateLimitError:
                    raise  # let it bubble up

                except Exception as e:
                    logger.error("engage_failed", post_id=post.id, error=str(e), error_type=type(e).__name__)

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
        remaining = self._max_posts_per_day - today_posts
        logger.info("post_budget", today_posts=today_posts, max=self._max_posts_per_day, remaining=remaining)

        if today_posts >= self._max_posts_per_day:
            return

        try:
            content = await self._post_creator.create_post()
            logger.info(
                "post_generated",
                title=content.title[:60],
                body_len=len(content.body),
                submolt=content.target_submolt,
                category=content.topic_category,
            )

            # Strip m/ prefix if the LLM included it
            submolt_name = content.target_submolt.removeprefix("m/")

            post = await self._moltbook.create_post(
                CreatePostRequest(
                    title=content.title,
                    content=content.body,
                    submolt=submolt_name,
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

        except LLMRateLimitError:
            raise  # let it bubble up

        except Exception as e:
            logger.error("post_creation_failed", error=str(e), error_type=type(e).__name__)

    async def shutdown(self) -> None:
        await self._moltbook.close()
        await self._state_repo.close()
        logger.info("agent_shutdown")
