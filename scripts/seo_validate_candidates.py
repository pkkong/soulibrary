import argparse
import json
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
sys.path.insert(0, str(WEB_DIR))

os.environ.setdefault("LIVE_SEARCH_TOTAL_TIMEOUT", "8")
os.environ.setdefault("LIVE_SEARCH_LIBRARY_TIMEOUT", "3")

from live_search.service import live_search  # noqa: E402
from seo_books import review_seo_candidates  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Validate collected SEO book candidates.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--auto-publish", action="store_true", help="Publish candidates that pass the publish threshold.")
    parser.add_argument("--approve-threshold", type=int, default=70)
    parser.add_argument("--publish-threshold", type=int, default=85)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    summary = review_seo_candidates(
        live_search,
        limit=args.limit,
        auto_publish=args.auto_publish,
        approve_threshold=args.approve_threshold,
        publish_threshold=args.publish_threshold,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
