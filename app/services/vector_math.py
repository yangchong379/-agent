import math
import re
from collections import Counter


def tokens(text: str) -> list[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    chars = [char for char in normalized if not char.isspace()]
    unigrams = chars
    bigrams = ["".join(chars[index : index + 2]) for index in range(len(chars) - 1)]
    words = re.findall(r"[a-z0-9_+#.-]+", text.lower())
    return unigrams + bigrams + words


def cosine_similarity(left: str, right: str) -> float:
    left_counts = Counter(tokens(left))
    right_counts = Counter(tokens(right))
    if not left_counts or not right_counts:
        return 0.0
    numerator = sum(value * right_counts.get(key, 0) for key, value in left_counts.items())
    left_norm = math.sqrt(sum(value * value for value in left_counts.values()))
    right_norm = math.sqrt(sum(value * value for value in right_counts.values()))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0

