"""Token counting utility."""
import re
from typing import List

# Precompile regex for CJK character detection (much faster than char-by-char)
_CJK_RE = re.compile(
    r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]'
)


def estimate_tokens(text: str) -> int:
    """
    Simple heuristic: ~4 chars per token for English, ~2 chars for CJK.
    This is a fast local estimate before the API call.
    Uses regex for O(1)-per-match counting instead of char-by-char iteration.
    """
    if not text:
        return 0
    cjk_count = len(_CJK_RE.findall(text))
    other_count = len(text) - cjk_count
    return cjk_count // 2 + other_count // 4 + 1


def count_messages_tokens(messages: List[dict]) -> int:
    """Estimate total token count for a list of messages."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content) + 4  # per-message overhead
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    total += estimate_tokens(part.get("text", ""))
                elif part.get("type") == "image_url":
                    total += 1024  # rough vision token estimate for detail:auto
    return total


def trim_messages_by_rounds(messages: List[dict], max_rounds: int) -> List[dict]:
    """Keep the last N rounds (user+assistant pairs) but always keep system."""
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    # Group into pairs
    pairs = []
    i = 0
    while i < len(non_system):
        if non_system[i].get("role") == "user":
            pair = [non_system[i]]
            if i + 1 < len(non_system) and non_system[i + 1].get("role") == "assistant":
                pair.append(non_system[i + 1])
                i += 2
            else:
                i += 1
            pairs.append(pair)
        else:
            i += 1

    kept_pairs = pairs[-max_rounds:] if len(pairs) > max_rounds else pairs
    kept_msgs = []
    for pair in kept_pairs:
        kept_msgs.extend(pair)

    return system_msgs + kept_msgs


def trim_messages_by_tokens(messages: List[dict], token_threshold: int) -> List[dict]:
    """Sliding window: drop oldest non-system messages until under threshold."""
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    while non_system and count_messages_tokens(system_msgs + non_system) > token_threshold:
        non_system.pop(0)

    return system_msgs + non_system


def truncate_text_by_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to fit within max_tokens (estimated), breaking at paragraph/sentence boundary.

    Returns the original text if it fits, or a truncated version with a notice appended.
    """
    if not text:
        return text
    
    original_tokens = estimate_tokens(text)
    if original_tokens <= max_tokens:
        return text

    # Estimate chars needed based on character composition
    cjk_count = len(_CJK_RE.findall(text))
    total_chars = len(text)
    cjk_ratio = cjk_count / total_chars if total_chars > 0 else 0
    
    # Weighted chars-per-token estimate
    chars_per_token = 2.0 * cjk_ratio + 4.0 * (1 - cjk_ratio)
    approx_chars = int(max_tokens * chars_per_token * 0.95)  # 5% safety margin
    
    if approx_chars >= total_chars:
        approx_chars = total_chars - 1

    candidate = text[:approx_chars]

    # Quick check and shrink if still over
    while estimate_tokens(candidate) > max_tokens and len(candidate) > 100:
        approx_chars = int(len(candidate) * 0.85)
        candidate = text[:approx_chars]

    # Try to find a clean break point (paragraph > sentence > any)
    clean = candidate
    for sep in ["\n\n", "\n", "。", ".", "！", "!", "？", "?"]:
        idx = candidate.rfind(sep)
        if idx > len(candidate) // 2:  # don't cut more than half
            clean = candidate[:idx + len(sep)]
            break

    truncated_tokens = estimate_tokens(clean)
    notice = f"\n\n[...内容已截断，原文约 {original_tokens} tokens，已保留前 {truncated_tokens} tokens...]"
    return clean + notice
