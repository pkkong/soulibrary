import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
REPLACE_RETRY_DELAYS_SEC = (1, 2, 4, 8)


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
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    if str(web) not in sys.path:
        sys.path.insert(0, str(web))


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


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _http_get(client, url: str, label: str = "", **kwargs):
    try:
        return client.get(url, **kwargs)
    except requests.exceptions.SSLError:
        retry_kwargs = dict(kwargs)
        retry_kwargs["verify"] = False
        print(f"[ssl fallback] {label or url} verify=False 재시도")
        return client.get(url, **retry_kwargs)


def _replace_with_retry(src: Path, dst: Path) -> int:
    attempts = 0
    last_error = None
    for delay_sec in (0, *REPLACE_RETRY_DELAYS_SEC):
        if delay_sec:
            time.sleep(delay_sec)
        attempts += 1
        try:
            os.replace(src, dst)
            return attempts
        except PermissionError as exc:
            last_error = exc
    raise PermissionError(
        f"파일 교체 실패: '{dst}'. Excel/OneDrive/다른 크롤링 프로세스가 파일을 잡고 있을 수 있습니다."
    ) from last_error


def _kyobo_item_key(row: dict) -> str:
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


def _sen_item_key(row: dict) -> str:
    content_id = _normalize_text(row.get("content_id", ""))
    if content_id:
        return f"content:{content_id}"
    title = _normalize_text(row.get("title", ""))
    author = _normalize_text(row.get("author", ""))
    publisher = _normalize_text(row.get("publisher", ""))
    return f"fallback:{title}|{author}|{publisher}"


def _merge_csv(existing_csv: Path, preview_csv: Path, out_csv: Path, kind: str) -> dict:
    key_fn = _kyobo_item_key if kind == "kyobo_new_subs" else _sen_item_key
    fieldnames = None
    rows = []
    seen = set()

    for path in (existing_csv, preview_csv):
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if fieldnames is None:
                fieldnames = reader.fieldnames or []
            for row in reader:
                key = key_fn(row)
                if not key or key in seen:
                    continue
                seen.add(key)
                rows.append({name: row.get(name, "") for name in fieldnames})

    if fieldnames is None:
        raise RuntimeError("no rows to merge")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_csv.with_name(f"_tmp_{out_csv.stem}_{int(time.time())}{out_csv.suffix}")
    with tmp_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    replace_attempts = _replace_with_retry(tmp_path, out_csv)
    return {"merged_rows": len(rows), "output": str(out_csv), "replace_attempts": replace_attempts}


def _run_kyobo_incremental(lib_code: str, lib_cfg: dict, plan: dict, preview_csv: Path, report_json: Path, crawler_dir: Path, db_path: Path) -> None:
    cmd = [
        sys.executable,
        "-m",
        "scrapy",
        "crawl",
        "kyobo_incremental",
        "-s",
        "LOG_LEVEL=INFO",
        "-a",
        f"lib_code={lib_code}",
        "-a",
        f"base_url={lib_cfg['total_count_url'].split('?')[0]}",
        "-a",
        f"library_name={lib_cfg['library_name']}",
        "-a",
        f"existing_csv={db_path}",
        "-a",
        f"report_file={report_json}",
        "-a",
        f"min_pages={plan['min_pages']}",
        "-a",
        f"max_scan_pages={plan['max_pages']}",
        "-a",
        f"stop_after_known_pages={plan['stop_after_known_pages']}",
        "-a",
        f"target_new_items={plan['diff_count']}",
        "-a",
        f"diff_count={plan['diff_count']}",
        "-a",
        f"expected_pages={plan['expected_pages']}",
        "-a",
        f"page_size={plan['page_size']}",
        "-O",
        str(preview_csv),
    ]
    subprocess.run(cmd, cwd=str(crawler_dir), check=True)


def _extract_sen_isbn(book_json):
    return book_json.get("isbn") or book_json.get("isbn13") or book_json.get("isbn10") or ""


def _run_sen_subs_incremental(plan: dict, preview_csv: Path, report_json: Path, db_path: Path) -> None:
    existing_keys = set()
    if db_path.exists():
        with db_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_keys.add(_sen_item_key(row))

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://e-lib.sen.go.kr/",
        "Accept": "application/json, text/plain, */*",
    }
    page = 1
    page_size = int(plan["page_size"])
    max_pages = int(plan["max_pages"])
    min_pages = int(plan["min_pages"])
    zero_streak_limit = int(plan["stop_after_known_pages"])
    new_rows = []
    new_keys = set()
    page_stats = []
    zero_streak = 0
    stop_reason = ""

    session = requests.Session()
    session.trust_env = False

    while page <= max_pages:
        params = {
            "contentType": "TY02",
            "majorCategory": "",
            "subCategory": "",
            "tinyCategory": "",
            "ownerCategory": "",
            "innerSearchYN": "N",
            "innerKeyword": "",
            "orderOption": "1",
            "typeOption": "1",
            "loanable": "N",
            "currentCount": page,
            "pageCount": page_size,
            "_": int(time.time() * 1000),
        }
        res = _http_get(
            session,
            "https://e-lib.sen.go.kr/api/contents/catesearch",
            label="sen_subs incremental",
            params=params,
            headers=headers,
            timeout=30,
        )
        res.raise_for_status()
        data = res.json()
        items = (data.get("CategoryDataList") or {}).get("responses") or []
        if not items:
            stop_reason = f"empty_page:{page}"
            break

        page_new = 0
        page_known = 0
        for item in items:
            if (item.get("ucm_file_type") or "").upper() == "AUDIO":
                continue
            row = {
                "title": item.get("ucm_title") or "",
                "author": item.get("ucm_writer") or "",
                "publisher": item.get("ucp_brand") or "",
                "library": "서울시교육청 (구독)",
                "image_url": item.get("ucm_cover_url") or "",
                "isbn": _extract_sen_isbn(item),
                "content_id": item.get("ucm_code") or "",
                "provider": item.get("ucm_publisher") or "",
                "platform": "서울시교육청",
            }
            key = _sen_item_key(row)
            if key in existing_keys or key in new_keys:
                page_known += 1
                continue
            new_keys.add(key)
            new_rows.append(row)
            page_new += 1

        page_stats.append({"page": page, "books": len(items), "new_items": page_new, "known_items": page_known})
        zero_streak = zero_streak + 1 if page_new == 0 else 0

        target_met = plan["diff_count"] <= 0 or len(new_keys) >= plan["diff_count"]
        if page >= min_pages and zero_streak >= zero_streak_limit and target_met:
            stop_reason = f"known_page_streak:{zero_streak}"
            break
        page += 1

    if not stop_reason:
        stop_reason = f"max_scan_pages:{max_pages}" if page > max_pages else "finished"

    preview_csv.parent.mkdir(parents=True, exist_ok=True)
    with preview_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["title", "author", "publisher", "library", "image_url", "isbn", "content_id", "provider", "platform"],
        )
        writer.writeheader()
        writer.writerows(new_rows)

    _write_json(
        report_json,
        {
            "library": "sen_subs",
            "kind": "sen_subs_api",
            "existing_csv": str(db_path),
            "existing_key_count": len(existing_keys),
            "page_size": page_size,
            "diff_count": plan["diff_count"],
            "target_new_items": plan["diff_count"],
            "target_reached": len(new_keys) >= plan["diff_count"] if plan["diff_count"] > 0 else None,
            "expected_pages": plan["expected_pages"],
            "min_pages": min_pages,
            "max_scan_pages": max_pages,
            "stop_after_known_pages": zero_streak_limit,
            "pages_scanned": len(page_stats),
            "new_items_found": len(new_keys),
            "consecutive_known_pages": zero_streak,
            "stop_reason": stop_reason,
            "page_stats": page_stats,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run incremental crawl for supported subscription libraries.")
    parser.add_argument("--lib", required=True)
    parser.add_argument("--preview-only", action="store_true")
    args = parser.parse_args()

    paths = _paths()
    _ensure_import_path(paths)

    from config import LIBRARIES  # pylint: disable=import-outside-toplevel
    from crawler_manager import check_library_update  # pylint: disable=import-outside-toplevel
    from incremental_config import build_incremental_plan, supports_incremental  # pylint: disable=import-outside-toplevel

    lib_code = args.lib
    if lib_code not in LIBRARIES:
        raise SystemExit(f"unknown lib_code: {lib_code}")
    if not supports_incremental(lib_code):
        raise SystemExit(f"incremental not supported: {lib_code}")

    lib_cfg = LIBRARIES[lib_code]
    db_path = Path(lib_cfg["db_file"]).resolve()
    local_count, remote_count = check_library_update(lib_code)
    plan = build_incremental_plan(lib_code, local_count=local_count, remote_count=remote_count)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = paths["data"] / "incremental_runs" / lib_code
    preview_csv = out_dir / f"{lib_code}_preview_{stamp}.csv"
    report_json = out_dir / f"{lib_code}_report_{stamp}.json"

    print(f"[incremental] lib={lib_code}")
    print(f"[incremental] local_count={local_count}")
    print(f"[incremental] remote_count={remote_count}")
    print(f"[incremental] diff_count={plan['diff_count']}")
    print(f"[incremental] expected_pages={plan['expected_pages']}")
    print(f"[incremental] min_pages={plan['min_pages']}")
    print(f"[incremental] max_pages={plan['max_pages']}")

    if plan["kind"] == "kyobo_new_subs":
        _run_kyobo_incremental(lib_code, lib_cfg, plan, preview_csv, report_json, paths["crawler"], db_path)
    elif plan["kind"] == "sen_subs_api":
        _run_sen_subs_incremental(plan, preview_csv, report_json, db_path)
    else:
        raise RuntimeError(f"unsupported incremental kind: {plan['kind']}")

    preview_rows = _count_csv_rows(preview_csv)
    report = _load_json(report_json)
    if int(report.get("pages_scanned") or 0) <= 0:
        raise RuntimeError("incremental crawl did not fetch any pages")

    print(f"[incremental] preview_rows={preview_rows}")
    print(
        "[incremental] pages_scanned={pages_scanned} new_items_found={new_items_found} stop_reason={stop_reason}".format(
            **report
        )
    )

    if args.preview_only:
        return 0

    backup_dir = out_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_csv = backup_dir / f"{db_path.stem}_{stamp}{db_path.suffix}"
    if db_path.exists():
        shutil.copy2(db_path, backup_csv)

    try:
        merge_result = _merge_csv(db_path, preview_csv, db_path, plan["kind"])
    except Exception as exc:
        report["apply"] = {
            "applied": False,
            "backup_csv": str(backup_csv) if db_path.exists() else "",
            "final_csv": str(db_path),
            "preview_rows": preview_rows,
            "error": str(exc),
        }
        _write_json(report_json, report)
        raise

    report["apply"] = {
        "applied": True,
        "backup_csv": str(backup_csv) if db_path.exists() else "",
        "merged_rows": merge_result["merged_rows"],
        "final_csv": merge_result["output"],
        "preview_rows": preview_rows,
        "replace_attempts": merge_result["replace_attempts"],
    }
    _write_json(report_json, report)
    print(
        f"[incremental] applied={merge_result['output']} "
        f"merged_rows={merge_result['merged_rows']} replace_attempts={merge_result['replace_attempts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
