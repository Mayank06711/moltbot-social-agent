"""Input sanitization to defend against prompt injection from Moltbook posts.

Handles direct instruction injection, Unicode homoglyph evasion,
and LLM-output-to-LLM-input smuggling.
"""

import re
import unicodedata


class InputSanitizer:
    """Strips known prompt injection patterns from user-generated content.

    Defense layers:
    1. Unicode normalization (NFKC) to collapse homoglyphs before matching
    2. Regex-based pattern filtering for known injection phrases
    3. Structural marker removal (role tags, delimiters)
    """

    _INJECTION_PATTERNS: list[re.Pattern[str]] = [
        # Direct instruction overrides
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
        re.compile(r"disregard\s+(all\s+)?(prior|previous|above)", re.IGNORECASE),
        re.compile(r"forget\s+(all\s+)?(previous|prior|above|your)\s+\w+", re.IGNORECASE),
        re.compile(r"override\s+(your\s+)?(system|instructions|rules)", re.IGNORECASE),
        re.compile(r"do\s+not\s+follow\s+(your|the)\s+(previous|original)", re.IGNORECASE),
        # Role manipulation
        re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
        re.compile(r"pretend\s+(you\s+are|to\s+be)", re.IGNORECASE),
        re.compile(r"act\s+as\s+(if\s+you\s+are|a|an)", re.IGNORECASE),
        re.compile(r"switch\s+to\s+\w+\s+mode", re.IGNORECASE),
        re.compile(r"enter\s+(developer|debug|admin|god)\s+mode", re.IGNORECASE),
        # Prompt extraction
        re.compile(r"reveal\s+your\s+(system\s+)?prompt", re.IGNORECASE),
        re.compile(r"(show|print|output|repeat)\s+(your\s+)?(system\s+)?(prompt|instructions)", re.IGNORECASE),
        re.compile(r"what\s+(are|is)\s+your\s+(system\s+)?(prompt|instructions)", re.IGNORECASE),
        # Structural markers (LLM role tags)
        re.compile(r"system\s*:", re.IGNORECASE),
        re.compile(r"<\s*/?\s*system\s*>", re.IGNORECASE),
        re.compile(r"\[/?INST\]", re.IGNORECASE),
        re.compile(r"<<\s*/?SYS\s*>>", re.IGNORECASE),
        re.compile(r"<\s*\|im_start\|.*?\|im_end\|?\s*>", re.IGNORECASE | re.DOTALL),
        re.compile(r"###\s*(System|Human|Assistant)\s*:", re.IGNORECASE),
        # Encoded / obfuscated attempts
        re.compile(r"base64\s*[:\-]\s*[A-Za-z0-9+/=]{20,}", re.IGNORECASE),
        re.compile(r"eval\s*\(", re.IGNORECASE),
        # Output manipulation
        re.compile(r"respond\s+with\s+(only|exactly|just)", re.IGNORECASE),
        re.compile(r"your\s+(response|output|reply)\s+must\s+(be|start|begin|contain)", re.IGNORECASE),
    ]

    _MAX_CONTENT_LENGTH = 10_000

    @classmethod
    def _normalize_unicode(cls, text: str) -> str:
        """Normalize Unicode to NFKC form to collapse homoglyphs.

        Converts lookalike characters (e.g., Cyrillic 'а' -> Latin 'a',
        fullwidth 'ｉｇｎｏｒｅ' -> 'ignore') so regex patterns match
        regardless of character encoding tricks.
        """
        return unicodedata.normalize("NFKC", text)

    @classmethod
    def sanitize(cls, text: str) -> str:
        """Remove prompt injection patterns and truncate overly long content.

        Applies Unicode normalization before pattern matching to prevent
        homoglyph-based evasion.
        """
        if not text:
            return text

        text = text[: cls._MAX_CONTENT_LENGTH]
        text = cls._normalize_unicode(text)

        for pattern in cls._INJECTION_PATTERNS:
            text = pattern.sub("[FILTERED]", text)

        return text.strip()

    @classmethod
    def is_suspicious(cls, text: str) -> bool:
        """Check if content contains potential prompt injection attempts."""
        if not text:
            return False
        normalized = cls._normalize_unicode(text)
        return any(pattern.search(normalized) for pattern in cls._INJECTION_PATTERNS)
