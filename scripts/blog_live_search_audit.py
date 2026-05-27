#!/usr/bin/env python3
"""Audit Soulib blog search cards against live search results."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "web"
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from live_search.normalizer import normalize_author, normalize_title_for_group  # noqa: E402
from live_search.service import live_search  # noqa: E402


CARD_RE = re.compile(r"\[\[soulib-search:([^\]]+)\]\]")
GUIDE_TITLE_RE = re.compile(
    r"(가이드|길잡이|공략|리뷰|요약|해설|해제|독후감|서평|노트|문제집|워크북|필사|따라쓰기|사전|"
    r"줄거리|읽기자료|논술|토론|퀴즈|분석|중심으로|우리가\s*읽은|"
    r"summary|review|guide|workbook|notes?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SearchCard:
    path: Path
    line_no: int
    title: str
    author: str
    note: str
    label: str


@dataclass(frozen=True)
class AuditFailure:
    card: SearchCard
    reason: str
    results: list[dict]


def parse_cards(path: Path) -> list[SearchCard]:
    text = path.read_text(encoding="utf-8")
    cards: list[SearchCard] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in CARD_RE.finditer(line):
            parts = [part.strip() for part in match.group(1).split("|")]
            if len(parts) < 3:
                raise ValueError(f"{path}:{line_no}: malformed soulib-search card")
            title, author, note = parts[:3]
            label = parts[3] if len(parts) >= 4 else title
            if not title or not author:
                raise ValueError(f"{path}:{line_no}: card must include title and author")
            cards.append(
                SearchCard(path=path, line_no=line_no, title=title, author=author, note=note, label=label)
            )
    return cards


def normalized_title(value: str) -> str:
    return normalize_title_for_group(value)


def is_exact_book_match(item: dict, card: SearchCard) -> bool:
    return (
        normalized_title(item.get("title") or "") == normalized_title(card.title)
        and normalize_author(item.get("author") or "") == normalize_author(card.author)
    )


def guide_like_results(results: Iterable[dict]) -> list[dict]:
    return [item for item in results if GUIDE_TITLE_RE.search(str(item.get("title") or ""))]


def audit_card(card: SearchCard) -> AuditFailure | None:
    payload = live_search(card.title, "title", limit=10, refine=card.author)
    results = list(payload.get("items") or [])
    if any(is_exact_book_match(item, card) for item in results):
        return None

    if results and len(guide_like_results(results)) == len(results):
        reason = "only guide/explanation/note-like results were returned"
    elif results:
        reason = "no top result matched both main-book title and author"
    else:
        reason = "no live search results after author refine"
    return AuditFailure(card=card, reason=reason, results=results)


def format_result(item: dict) -> str:
    title = str(item.get("title") or "").strip() or "(no title)"
    author = str(item.get("author") or "").strip() or "(no author)"
    counts = item.get("counts") or {}
    total = counts.get("total")
    suffix = f", libraries={total}" if total is not None else ""
    return f"{title} / {author}{suffix}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify [[soulib-search:title|author|...|label]] cards against Soulib live search."
    )
    parser.add_argument("markdown", nargs="+", type=Path, help="Markdown blog files to audit")
    args = parser.parse_args(argv)

    cards: list[SearchCard] = []
    for path in args.markdown:
        if not path.exists():
            parser.error(f"file not found: {path}")
        cards.extend(parse_cards(path))

    if not cards:
        print("No soulib-search cards found.")
        return 0

    failures: list[AuditFailure] = []
    for card in cards:
        try:
            failure = audit_card(card)
        except Exception as exc:
            failure = AuditFailure(card=card, reason=f"live search error: {exc}", results=[])
        if failure:
            failures.append(failure)
            print(f"FAIL {card.path}:{card.line_no} {card.title} / {card.author}: {failure.reason}")
            for item in failure.results[:5]:
                print(f"  - {format_result(item)}")
        else:
            print(f"OK   {card.path}:{card.line_no} {card.title} / {card.author}")

    if failures:
        print(f"\nAudit failed: {len(failures)} of {len(cards)} cards did not resolve to the main book.")
        return 1

    print(f"\nAudit passed: {len(cards)} cards resolved to matching main books.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
