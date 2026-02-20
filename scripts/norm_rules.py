"""
Frozen DB normalization rules (v1).

This module is the single source of truth for:
- books.title_norm
- books.author_norm
- books.publisher_norm

Change policy:
- Do not edit v1 rules in-place once released.
- Add a new module/version and run a planned migration when rules change.
"""

import re


NORM_RULE_VERSION = "db_norm_v1_2026-02-11"


def normalize_text(value: str) -> str:
    if not value:
        return ""
    text = str(value).lower()
    text = re.sub(r"[\u200b\ufeff]", "", text)
    text = re.sub(r"[\s\[\]\(\){}<>.,/|\\\-_:\;\"'`~!?]", "", text)
    return text


def normalize_author(value: str) -> str:
    if not value:
        return ""
    text = str(value)
    text = re.sub(r"(지은이|저자|저|역|옮긴이|편|엮음|그림|삽화|해설)", " ", text)
    text = re.sub(r"[:：]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return normalize_text(text)


def normalize_title(value: str) -> str:
    if not value:
        return ""
    text = str(value)
    text = re.sub(r"\[.*?\]|\(.*?\)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return normalize_text(text)


def normalize_publisher(value: str) -> str:
    if not value:
        return ""
    text = str(value)
    text = re.sub(r"(주식회사|\(주\)|㈜|출판사)$", "", text).strip()
    return normalize_text(text)
