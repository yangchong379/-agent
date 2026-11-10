import re


_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_ID_CARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"system\s+prompt",
        r"developer\s+message",
        r"忽略.{0,8}(之前|以上).{0,8}(指令|要求)",
        r"输出.{0,8}(系统提示词|system prompt)",
        r"你现在是.{0,20}(管理员|开发者)",
    )
)


def redact_pii(text: str) -> str:
    value = _EMAIL.sub("[EMAIL_REDACTED]", text)
    value = _PHONE.sub("[PHONE_REDACTED]", value)
    return _ID_CARD.sub("[ID_REDACTED]", value)


def detect_prompt_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


def safe_text(text: str, max_chars: int) -> str:
    value = text.replace("\x00", "").strip()
    if not value:
        raise ValueError("text must not be empty")
    if len(value) > max_chars:
        raise ValueError(f"text exceeds the {max_chars}-character limit")
    return value

