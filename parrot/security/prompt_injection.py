"""
Prompt Injection Detection and Protection.
"""
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
import re
from datetime import datetime, timezone
from navconfig.logging import logging


class ThreatLevel(Enum):
    """Severity levels for detected threats."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PromptInjectionException(Exception):
    """Raised when a critical prompt injection is detected in strict mode."""
    def __init__(self, message: str, threats: List[Dict], original_input: str):
        super().__init__(message)
        self.threats = threats
        self.original_input = original_input


class PromptInjectionDetector:
    """
    Detects and mitigates prompt injection attempts in user questions.
    """

    # CRITICAL: Direct instruction override attempts
    CRITICAL_PATTERNS = [
        (
            re.compile(r'ignore\s+(all\s+)?(previous|above|prior)\s+instructions?', re.IGNORECASE),
            "Direct instruction override"
        ),
        (
            re.compile(r'forget\s+(everything|all|your\s+(instructions?|rules?|prompt))', re.IGNORECASE),
            "Memory wipe attempt"
        ),
        (
            re.compile(r'you\s+are\s+now\s+(a|an|no\s+longer)', re.IGNORECASE),
            "Role hijacking"
        ),
        (
            re.compile(r'disregard\s+(all\s+)?(previous|above|prior|your)', re.IGNORECASE),
            "Disregard command"
        ),
    ]

    # HIGH: System impersonation
    HIGH_PATTERNS = [
        (
            re.compile(r'system\s*:\s*', re.IGNORECASE),
            "System role impersonation"
        ),
        (
            re.compile(r'<\s*/?system\s*>', re.IGNORECASE),
            "System tag injection"
        ),
        (
            re.compile(r'\[SYSTEM\]|\(SYSTEM\)|【SYSTEM】', re.IGNORECASE),
            "System marker injection"
        ),
        (
            re.compile(r'new\s+instructions?:\s*', re.IGNORECASE),
            "Instruction replacement"
        ),
        (
            re.compile(r'assistant\s*:\s*ignore', re.IGNORECASE),
            "Assistant role injection"
        ),
    ]

    # MEDIUM: Prompt extraction attempts
    MEDIUM_PATTERNS = [
        (
            re.compile(r'(reveal|show|print|display|output)\s+(your\s+)?(prompt|instructions|system\s+message)', re.IGNORECASE),
            "Prompt extraction attempt"
        ),
        (
            re.compile(r'what\s+(is|are)\s+your\s+(original\s+)?(instructions?|prompt|rules?)', re.IGNORECASE),
            "Instruction disclosure request"
        ),
    ]

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)

    def detect_threats(self, text: str) -> List[Dict[str, Any]]:
        """
        Scan text for prompt injection patterns.

        Returns:
            List of detected threats with details
        """
        if not text or not isinstance(text, str):
            return []

        threats = []

        # Check CRITICAL patterns
        for pattern, description in self.CRITICAL_PATTERNS:
            if match := pattern.search(text):
                threats.append({
                    'level': ThreatLevel.CRITICAL,
                    'pattern': pattern.pattern,
                    'description': description,
                    'matched_text': match.group(0),
                    'position': match.span()
                })

        # Check HIGH patterns
        for pattern, description in self.HIGH_PATTERNS:
            if match := pattern.search(text):
                threats.append({
                    'level': ThreatLevel.HIGH,
                    'pattern': pattern.pattern,
                    'description': description,
                    'matched_text': match.group(0),
                    'position': match.span()
                })

        # Check MEDIUM patterns
        for pattern, description in self.MEDIUM_PATTERNS:
            if match := pattern.search(text):
                threats.append({
                    'level': ThreatLevel.MEDIUM,
                    'pattern': pattern.pattern,
                    'description': description,
                    'matched_text': match.group(0),
                    'position': match.span()
                })

        return threats

    def sanitize(
        self,
        text: str,
        strict: bool = True,
        replacement: str = "[FILTERED_CONTENT]"
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Sanitize text by replacing detected patterns.

        Args:
            text: Input text to sanitize
            strict: If True, replace patterns; if False, only detect
            replacement: Text to use for replacements

        Returns:
            Tuple of (sanitized_text, detected_threats)
        """
        threats = self.detect_threats(text)

        if not strict or not threats:
            return text, threats

        sanitized = text

        # In strict mode, replace CRITICAL and HIGH patterns
        for pattern, _ in self.CRITICAL_PATTERNS + self.HIGH_PATTERNS:
            sanitized = pattern.sub(replacement, sanitized)

        return sanitized, threats


class SecurityEventLogger:
    """
    Logs security events with session tracking.
    """

    def __init__(self, db_pool=None, logger: Optional[logging.Logger] = None):
        self.db_pool = db_pool
        self.logger = logger or logging.getLogger(__name__)

    async def log_injection_attempt(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: str,
        threats: List[Dict[str, Any]],
        original_input: str,
        sanitized_input: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log a detected prompt injection attempt.
        """
        max_severity = max(
            (t['level'] for t in threats),
            default=ThreatLevel.LOW
        )

        # Always log to application logger
        for threat in threats:
            self.logger.warning(
                f"🔒 SECURITY: Prompt injection detected | "
                f"Severity: {threat['level'].value.upper()} | "
                f"User: {user_id} | Session: {session_id} | "
                f"Bot: {chatbot_id} | "
                f"Type: {threat['description']} | "
                f"Pattern: '{threat['matched_text']}'"
            )

        # Log to database if pool available
        if self.db_pool:
            await self._log_to_database(
                user_id=user_id,
                session_id=session_id,
                chatbot_id=chatbot_id,
                threats=threats,
                original_input=original_input,
                sanitized_input=sanitized_input,
                max_severity=max_severity,
                metadata=metadata or {}
            )

    async def _log_to_database(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: str,
        threats: List[Dict[str, Any]],
        original_input: str,
        sanitized_input: str,
        max_severity: ThreatLevel,
        metadata: Dict[str, Any]
    ):
        """Store security event in database."""
        try:
            query = """
            INSERT INTO navigator.security_events (
                event_type,
                user_id,
                session_id,
                chatbot_id,
                severity,
                threat_details,
                original_input,
                sanitized_input,
                metadata,
                created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """

            async with await self.db_pool.acquire() as conn:
                await conn.execute(
                    query,
                    'prompt_injection',
                    user_id,
                    session_id,
                    chatbot_id,
                    max_severity.value,
                    threats,  # PostgreSQL JSONB
                    original_input[:2000],  # Truncate for storage
                    sanitized_input[:2000],
                    metadata,
                    datetime.now(timezone.utc),
                )

            self.logger.info(
                f"Security event logged to database for user {user_id}"
            )

        except Exception as e:
            self.logger.error(f"Failed to log security event to database: {e}")
