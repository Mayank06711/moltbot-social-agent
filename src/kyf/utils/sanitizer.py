"""Input sanitization to defend against prompt injection from Moltbook posts."""

import re


class InputSanitizer:
    """Strips known prompt injection patterns from user-generated content."""

    _INJECTION_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
        re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
        re.compile(r"system\s*:\s*", re.IGNORECASE),
        re.compile(r"<\s*system\s*>", re.IGNORECASE),
        re.compile(r"reveal\s+your\s+(system\s+)?prompt", re.IGNORECASE),
        re.compile(r"disregard\s+(all\s+)?prior", re.IGNORECASE),
        re.compile(r"\[INST\]", re.IGNORECASE),
        re.compile(r"<<\s*SYS\s*>>", re.IGNORECASE),
    ]

    _MAX_CONTENT_LENGTH = 10_000

    @classmethod
    def sanitize(cls, text: str) -> str:
        """Remove prompt injection patterns and truncate overly long content."""
        if not text:
            return text

        text = text[: cls._MAX_CONTENT_LENGTH]

        for pattern in cls._INJECTION_PATTERNS:
            text = pattern.sub("[FILTERED]", text)

        return text.strip()

    @classmethod
    def is_suspicious(cls, text: str) -> bool:
        """Check if content contains potential prompt injection attempts."""
        if not text:
            return False
        return any(pattern.search(text) for pattern in cls._INJECTION_PATTERNS)
