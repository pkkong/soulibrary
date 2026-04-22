import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PAGE_SIZE = 80
MIN_SCAN_PAGES = 8
STOP_AFTER_KNOWN_PAGES = 3


def _paths():
    root = Path(__file__).resolve().parents[1]
    return {
        "root": root,
        "crawler": root / "crawler",
        "data": root / "data",
    }


def _ensure_import_path(paths):
    root = paths["root"]
    web = root / "web"
    if str(web) not in sys.path:
        sys.path.insert(0, str(web))
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        return sum(1 for _ in reader)


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _make_item_key(row: dict) -> str:
    brcd = _normalize_text(row.get("brcd", ""))
    if brcd:
        return f"brcd:{brcd}"

    ctts_dvsn_code = _normalize_text(row.get("ctts_dvsn_code", ""))
    ctgr_id = _normalize_text(row.get("ctgr_id", ""))
    title = _normalize_text(row.get("title", ""))
    author = _normalize_text(row.get("author", ""))
    publisher = _normalize_text(row.get("publisher", ""))

    if ctts_dvsn_code or ctgr_id:
        return f"meta:{ctts_dvsn_code}|{ctgr_id}|{title}|{author}|{publisher}"
    return f"fallback:{title}|{author}|{publisher}"


def _merge_preview(existing_csv: Path, preview_csv: Path, out_csv: Path) -> dict:
    rows = []
    seen = set()

    for path in (existing_csv, preview_csv):
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            for row in reader:
                key = _make_item_key(row)
                if not key or key in seen:
                    continue
                seen.add(key)
                rows.append({name: row.get(name, "") for name in fieldnames})

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_csv.with_name(f"_tmp_{out_csv.stem}_{int(datetime.now().timestamp())}{out_csv.suffix}")
    fieldnames = [
        "title",
        "author",
        "publisher",
        "library",
        "platform",
        "provider",
        "image_url",
        "isbn",
        "brcd",
        "ctts_dvsn_code",
        "ctgr_id",
    ]
    with tmp_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, out_csv)
    return {
        "merged_rows": len(rows),
        "output": str(out_csv),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an incremental crawl test for gangdong_subs.")
    parser.add_argument("--diff-count", type=int, default=-1, help="Override remote-local difference count.")
    parser.add_argument("--min-pages", type=int, default=MIN_SCAN_PAGES)
    parser.add_argument("--stop-after-known-pages", type=int, default=STOP_AFTER_KNOWN_PAGES)
    parser.add_argument("--max-scan-pages", type=int, default=0, help="0 means auto-calculate")
    parser.add_argument("--apply", action="store_true", help="Merge preview rows into a separate applied CSV copy.")
    args = parser.parse_args()

    paths = _paths()
    _ensure_import_path(paths)

    from crawler_manager import check_library_update  # pylint: disable=import-outside-toplevel
    from config import LIBRARIES  # pylint: disable=import-outside-toplevel

    lib_code = "gangdong_subs"
    db_path = Path(LIBRARIES[lib_code]["db_file"]).resolve()
    local_count = _count_csv_rows(db_path)
    if args.diff_count >= 0:
        remote_local = local_count
        remote_count = -1
        diff_count = args.diff_count
    else:
        remote_local, remote_count = check_library_update(lib_code)
        diff_count = max(remote_count - remote_local, 0)
    expected_pages = max(1, math.ceil(diff_count / PAGE_SIZE)) if diff_count > 0 else 1
    max_scan_pages = args.max_scan_pages if args.max_scan_pages > 0 else max(args.min_pages, expected_pages * 4 + 6)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = paths["data"] / "incremental_tests"
    preview_csv = out_dir / f"gangdong_subs_incremental_preview_{stamp}.csv"
    report_json = out_dir / f"gangdong_subs_incremental_report_{stamp}.json"

    cmd = [
        sys.executable,
        "-m",
        "scrapy",
        "crawl",
        "gangdong_kyobo_incremental",
        "-s",
        "LOG_LEVEL=INFO",
        "-a",
        f"existing_csv={db_path}",
        "-a",
        f"report_file={report_json}",
        "-a",
        f"min_pages={args.min_pages}",
        "-a",
        f"max_scan_pages={max_scan_pages}",
        "-a",
        f"stop_after_known_pages={args.stop_after_known_pages}",
        "-a",
        f"diff_count={diff_count}",
        "-a",
        f"expected_pages={expected_pages}",
        "-O",
        str(preview_csv),
    ]

    print(f"[gangdong-incremental] db_path={db_path}")
    print(f"[gangdong-incremental] local_count={local_count}")
    print(f"[gangdong-incremental] remote_count={remote_count}")
    print(f"[gangdong-incremental] diff_count={diff_count}")
    print(f"[gangdong-incremental] expected_pages={expected_pages}")
    print(f"[gangdong-incremental] min_pages={args.min_pages}")
    print(f"[gangdong-incremental] max_scan_pages={max_scan_pages}")
    print(f"[gangdong-incremental] preview_csv={preview_csv}")
    print(f"[gangdong-incremental] report_json={report_json}")

    subprocess.run(cmd, cwd=str(paths["crawler"]), check=True)

    preview_rows = _count_csv_rows(preview_csv)
    report = _load_json(report_json)
    print(f"[gangdong-incremental] preview_rows={preview_rows}")
    print(
        "[gangdong-incremental] pages_scanned={pages_scanned} "
        "new_items_found={new_items_found} stop_reason={stop_reason}".format(**report)
    )

    if int(report.get("pages_scanned") or 0) <= 0:
        raise RuntimeError("incremental crawl did not fetch any pages")

    if args.apply:
        applied_csv = out_dir / f"gangdong_subs_incremental_applied_{stamp}.csv"
        merge_result = _merge_preview(db_path, preview_csv, applied_csv)
        backup_csv = out_dir / f"gangdong_subs_before_incremental_{stamp}.csv"
        shutil.copy2(db_path, backup_csv)
        print(f"[gangdong-incremental] backup_csv={backup_csv}")
        print(f"[gangdong-incremental] applied_csv={merge_result['output']}")
        print(f"[gangdong-incremental] merged_rows={merge_result['merged_rows']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
