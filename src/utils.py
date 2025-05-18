# standard library imports
from typing import List


def max_string_length(strings: List[str]) -> int:
    max_chars = 0
    for s in strings:
        max_chars = max(max_chars, len(s))
    return max_chars
