"""
CLI helper to compare local CSV counts vs remote total counts without running the web server.

Usage:
    python scripts/check_totals.py            # check all libraries that support total_count_url/api
    python scripts/check_totals.py gangnam    # check a specific library code
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# ensure web/ is on path so "config" resolves
WEB_DIR = ROOT / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from web.crawler_manager import check_library_update  # noqa: E402
from web.config import LIBRARIES  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Check local vs remote book counts")
    parser.add_argument("lib_codes", nargs="*", help="Library code(s) to check (optional)")
    args = parser.parse_args()

    targets = args.lib_codes or []
    if targets:
        missing = [c for c in targets if c not in LIBRARIES]
        if missing:
            print(f"[오류] 존재하지 않는 라이브러리 코드: {', '.join(missing)}")
            sys.exit(1)
    else:
        # total_count_url 또는 지원되는 API가 있는 라이브러리만
        targets = [
            code
            for code, cfg in LIBRARIES.items()
            if cfg.get("total_count_url") or (cfg.get("type") == "odcloud") or (code in {"seoul", "sen_owned", "sen_subs", "mapo"})
        ]

    for code in targets:
        cfg = LIBRARIES[code]
        local, remote = check_library_update(code)
        delta = None if remote < 0 else (remote - local)
        name = cfg.get("name", code)
        if remote < 0:
            print(f"{code:12s} | {name:20s} | 로컬:{local:7d} | 원격: 오류")
        else:
            sign = "+" if delta is not None and delta > 0 else ""
            delta_str = f"{sign}{delta}" if delta is not None else "-"
            print(f"{code:12s} | {name:20s} | 로컬:{local:7d} | 원격:{remote:7d} | 차이:{delta_str}")


if __name__ == "__main__":
    main()
