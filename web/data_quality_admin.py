import datetime
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from flask import Blueprint, abort, jsonify, render_template, request

try:
    from config import LIBRARIES, LIBRARY_SHORT
except ImportError:
    from web.config import LIBRARIES, LIBRARY_SHORT

try:
    from db import get_db
except ImportError:
    from web.db import get_db

data_quality_bp = Blueprint("data_quality", __name__)

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT_DIR / "docs" / "reports"
DB_APPLY_STATE_FILE = ROOT_DIR / "data" / "db_apply_state.json"
PENDING_CSV_FALLBACK_HOURS = 24
DB_LOAD_SKIP_CODES = {"songpa", "yangcheon"}

ADMIN_ENABLED_VALUES = {"1", "true", "yes", "on"}
LOCAL_ADDRS = {"127.0.0.1", "::1"}

OPERATIONS = {
    "load_csv_incremental": {
        "label": "CSV 적재 + 정제 (자동)",
        "command": ["scripts/run_ingest_quality_pipeline.py"],
        "destructive": False,
        "description": "선택한 도서관을 부분 반영한 뒤 Stage1, Stage2, Stage3 후보 생성까지 자동으로 이어서 실행합니다.",
        "requires_csv_only": True,
    },
    "stage1_dryrun": {
        "label": "Stage1 점검 (dry-run)",
        "command": ["scripts/stage1_apply_exact_dedupe.py"],
        "destructive": False,
        "description": "norm 3키 exact 중복 후보와 이동량만 계산합니다.",
    },
    "stage1_apply": {
        "label": "Stage1 적용 (apply)",
        "command": [
            "scripts/stage1_apply_exact_dedupe.py",
            "--apply",
            "--scope",
            "all",
            "--dedupe-holdings",
            "--add-unique",
        ],
        "destructive": True,
        "description": "exact 중복 병합 + holdings 중복 제거 + unique lock을 적용합니다.",
    },
    "stage2_dryrun": {
        "label": "Stage2 점검 (dry-run)",
        "command": ["scripts/stage2_apply_identifier_merge.py"],
        "destructive": False,
        "description": "식별자 기준 canonical 백필/이동 예상치만 계산합니다.",
    },
    "stage2_apply": {
        "label": "Stage2 적용 (apply)",
        "command": [
            "scripts/stage2_apply_identifier_merge.py",
            "--apply",
            "--dedupe-holdings",
        ],
        "destructive": True,
        "description": "canonical 백필 + 대표 book_id 재배치 + orphan 삭제를 적용합니다.",
    },
    "stage3_build_queue": {
        "label": "Stage3 후보 생성",
        "command": ["scripts/stage3_build_review_queue.py"],
        "destructive": False,
        "description": "title_norm+author_norm 일치 후보를 리뷰 큐로 생성합니다(자동 병합 없음).",
    },
    "stage3_apply_approved": {
        "label": "Stage3 승인건 적용",
        "command": [
            "scripts/stage3_apply_approved.py",
            "--apply",
            "--dedupe-holdings",
        ],
        "destructive": True,
        "description": "리뷰 큐에서 승인된 건만 병합 적용합니다.",
    },
}

REVIEW_ALLOWED_STATUS = {"new", "hold", "approved", "rejected", "applied", "all"}

JOB_LOCK = threading.Lock()
JOB_STATE = {
    "running": False,
    "operation": None,
    "started_at": None,
    "ended_at": None,
    "exit_code": None,
    "success": None,
    "command": "",
    "stdout_tail": "",
    "stderr_tail": "",
    "result_json": None,
    "options": {},
    "error": None,
}
METRICS_CACHE = None
METRICS_CACHE_TS = None
METRICS_CACHE_TTL_SECONDS = 30


def _to_int(row, key="count"):
    if not row:
        return 0
    if isinstance(row, dict):
        value = row.get(key)
    else:
        try:
            value = row[0]
        except Exception:
            value = 0
    return int(value or 0)


def _is_admin_allowed():
    enabled = (os.environ.get("ENABLE_CURATION_ADMIN") or "").strip().lower()
    if enabled not in ADMIN_ENABLED_VALUES:
        return False
    return request.remote_addr in LOCAL_ADDRS


def _require_admin():
    if not _is_admin_allowed():
        abort(403)


def _now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _tail(text, limit=12000):
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[-limit:]


def _extract_json_payload(raw_text):
    text = (raw_text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except Exception:
        return None


def _ensure_review_tables(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS merge_review_queue (
          id BIGSERIAL PRIMARY KEY,
          pair_left_book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
          pair_right_book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
          source TEXT NOT NULL DEFAULT 'rule_auto',
          title_score INTEGER NOT NULL DEFAULT 0,
          author_score INTEGER NOT NULL DEFAULT 0,
          publisher_score INTEGER NOT NULL DEFAULT 0,
          signal_score INTEGER NOT NULL DEFAULT 0,
          total_score INTEGER NOT NULL DEFAULT 0,
          risk_flags TEXT NOT NULL DEFAULT '',
          reason TEXT,
          status TEXT NOT NULL DEFAULT 'new',
          decision_note TEXT,
          decided_by TEXT,
          decided_at TIMESTAMP,
          applied_at TIMESTAMP,
          created_at TIMESTAMP NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
          last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
          CONSTRAINT ck_merge_review_pair_order CHECK (pair_left_book_id < pair_right_book_id),
          CONSTRAINT uq_merge_review_pair UNIQUE (pair_left_book_id, pair_right_book_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_merge_review_status_score
        ON merge_review_queue (status, total_score DESC, updated_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_merge_review_last_seen
        ON merge_review_queue (last_seen_at DESC)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS merge_review_log (
          id BIGSERIAL PRIMARY KEY,
          queue_id BIGINT REFERENCES merge_review_queue(id) ON DELETE CASCADE,
          action TEXT NOT NULL,
          actor TEXT NOT NULL DEFAULT 'system',
          note TEXT,
          payload JSONB,
          created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_merge_review_log_queue_id
        ON merge_review_log (queue_id, created_at DESC)
        """
    )
    conn.commit()


def _collect_review_counts(conn):
    _ensure_review_tables(conn)
    cur = conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM merge_review_queue
        GROUP BY status
        """
    )
    rows = cur.fetchall() or []
    by_status = {r.get("status"): int(r.get("count") or 0) for r in rows if r.get("status")}
    return {
        "review_new": by_status.get("new", 0),
        "review_hold": by_status.get("hold", 0),
        "review_approved": by_status.get("approved", 0),
        "review_rejected": by_status.get("rejected", 0),
        "review_applied": by_status.get("applied", 0),
        "review_total": sum(by_status.values()),
    }


def _parse_int(value, default=0, min_value=0, max_value=1000):
    try:
        n = int(value)
    except Exception:
        n = default
    if n < min_value:
        n = min_value
    if n > max_value:
        n = max_value
    return n


def _collect_metrics():
    conn = get_db()
    try:
        review_counts = _collect_review_counts(conn)
        books_total = _to_int(conn.execute("SELECT COUNT(*) AS count FROM books").fetchone())
        holdings_total = _to_int(conn.execute("SELECT COUNT(*) AS count FROM holdings").fetchone())
        orphan_books = _to_int(
            conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM books b
                WHERE NOT EXISTS (
                    SELECT 1 FROM holdings h WHERE h.book_id = b.id
                )
                """
            ).fetchone()
        )
        books_exact_dup_groups = _to_int(
            conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM (
                    SELECT 1
                    FROM books
                    GROUP BY title_norm, author_norm, publisher_norm
                    HAVING COUNT(*) > 1
                ) t
                """
            ).fetchone()
        )
        holdings_dup_groups = _to_int(
            conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM (
                    SELECT 1
                    FROM holdings
                    GROUP BY book_id, library_code
                    HAVING COUNT(*) > 1
                ) t
                """
            ).fetchone()
        )
        holdings_no_canonical = _to_int(
            conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM holdings
                WHERE NULLIF(TRIM(canonical_id), '') IS NULL
                """
            ).fetchone()
        )
        identifier_without_canonical = _to_int(
            conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM holdings
                WHERE NULLIF(TRIM(canonical_id), '') IS NULL
                  AND (
                    NULLIF(TRIM(brcd), '') IS NOT NULL
                    OR NULLIF(TRIM(goods_id), '') IS NOT NULL
                    OR NULLIF(TRIM(content_id), '') IS NOT NULL
                  )
                """
            ).fetchone()
        )
        canonical_multi_book_groups = _to_int(
            conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM (
                    SELECT canonical_id
                    FROM holdings
                    WHERE NULLIF(TRIM(canonical_id), '') IS NOT NULL
                    GROUP BY canonical_id
                    HAVING COUNT(DISTINCT book_id) > 1
                ) t
                """
            ).fetchone()
        )
        return {
            "measured_at": _now_str(),
            "books_total": books_total,
            "holdings_total": holdings_total,
            "orphan_books": orphan_books,
            "books_exact_dup_groups": books_exact_dup_groups,
            "holdings_book_library_dup_groups": holdings_dup_groups,
            "holdings_no_canonical": holdings_no_canonical,
            "identifier_without_canonical": identifier_without_canonical,
            "canonical_multi_book_groups": canonical_multi_book_groups,
            **review_counts,
        }
    finally:
        conn.close()


def _list_recent_reports(limit=10):
    if not REPORTS_DIR.exists():
        return []
    records = []
    for path in REPORTS_DIR.glob("stage*.md"):
        try:
            stat = path.stat()
        except Exception:
            continue
        records.append(
            {
                "name": path.name,
                "path": f"docs/reports/{path.name}",
                "mtime_ts": stat.st_mtime,
                "mtime": datetime.datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            }
        )
    records.sort(key=lambda item: item["mtime_ts"], reverse=True)
    output = []
    for item in records[:limit]:
        output.append(
            {
                "name": item["name"],
                "path": item["path"],
                "mtime": item["mtime"],
            }
        )
    return output


def _current_db_target():
    host = (os.environ.get("DB_HOST") or "localhost").strip() or "localhost"
    port = (os.environ.get("DB_PORT") or "5432").strip() or "5432"
    name = (os.environ.get("DB_NAME") or "postgres").strip() or "postgres"
    return f"{host}:{port}/{name}"


def _load_apply_state():
    if not DB_APPLY_STATE_FILE.exists():
        return {"targets": {}}
    try:
        with DB_APPLY_STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("targets", {})
            return data
    except Exception:
        pass
    return {"targets": {}}


def _library_csv_catalog():
    catalog = []
    seen = set()
    for lib_code, cfg in LIBRARIES.items():
        if lib_code in DB_LOAD_SKIP_CODES or lib_code in seen:
            continue
        db_file = cfg.get("db_file")
        if not db_file:
            continue
        path = Path(db_file)
        if path.name.startswith("_tmp_") or not path.name.endswith("_db.csv"):
            continue
        try:
            stat = path.stat()
        except Exception:
            continue
        if stat.st_size <= 0:
            continue
        seen.add(lib_code)
        label = LIBRARY_SHORT.get(lib_code) or cfg.get("name") or lib_code
        catalog.append(
            {
                "code": lib_code,
                "label": label,
                "path": str(path.relative_to(ROOT_DIR)).replace("\\", "/"),
                "mtime_ts": stat.st_mtime,
                "mtime_ns": int(stat.st_mtime_ns),
                "mtime": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "size": int(stat.st_size),
            }
        )
    catalog.sort(key=lambda item: item["mtime_ts"], reverse=True)
    return catalog


def _pending_csv_updates():
    state = _load_apply_state()
    target = _current_db_target()
    target_state = (state.get("targets") or {}).get(target) or {}
    applied_by_lib = target_state.get("libraries") or {}
    catalog = _library_csv_catalog()
    pending = []

    for item in catalog:
        applied = applied_by_lib.get(item["code"])
        if applied:
            changed = (
                int(applied.get("csv_mtime_ns") or -1) != item["mtime_ns"]
                or int(applied.get("csv_size") or -1) != item["size"]
            )
            if not changed:
                continue
            reason = "csv_changed_since_last_apply"
            basis = "snapshot"
        else:
            age_hours = (datetime.datetime.now().timestamp() - item["mtime_ts"]) / 3600.0
            if age_hours > PENDING_CSV_FALLBACK_HOURS:
                continue
            if applied_by_lib:
                reason = "untracked_recent_csv"
                basis = "recent_mtime_fallback"
            else:
                reason = "recent_csv_fallback"
                basis = "recent_mtime_fallback"

        pending.append(
            {
                "code": item["code"],
                "label": item["label"],
                "path": item["path"],
                "mtime": item["mtime"],
                "reason": reason,
                "basis": basis,
                "last_applied_at": (applied or {}).get("applied_at"),
            }
        )

    return {
        "target": target,
        "last_applied_at": target_state.get("last_applied_at"),
        "has_snapshot": bool(applied_by_lib),
        "suggested_csv_only": ",".join(item["code"] for item in pending),
        "items": pending,
        "count": len(pending),
    }


def _build_runtime(operation_key, payload):
    op = OPERATIONS[operation_key]
    command = [sys.executable] + list(op["command"])
    extra_env = {}
    options = {}

    if op.get("requires_csv_only"):
        csv_only = str(payload.get("csv_only") or "").strip()
        if not csv_only:
            raise ValueError("csv_only_required")
        command.extend(["--csv-only", csv_only])
        options["csv_only"] = csv_only

    return command, extra_env, options


def _run_operation_async(operation_key, command, extra_env, options):
    runtime_env = os.environ.copy()
    runtime_env.update(extra_env or {})

    with JOB_LOCK:
        JOB_STATE.update(
            {
                "running": True,
                "operation": operation_key,
                "started_at": _now_str(),
                "ended_at": None,
                "exit_code": None,
                "success": None,
                "command": " ".join(command),
                "options": dict(options or {}),
                "stdout_tail": "",
                "stderr_tail": "",
                "result_json": None,
                "error": None,
            }
        )

    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=runtime_env,
        )
        parsed = _extract_json_payload(result.stdout) or _extract_json_payload(result.stderr)
        with JOB_LOCK:
            JOB_STATE.update(
                {
                    "running": False,
                    "ended_at": _now_str(),
                    "exit_code": int(result.returncode),
                    "success": result.returncode == 0,
                    "stdout_tail": _tail(result.stdout),
                    "stderr_tail": _tail(result.stderr),
                    "result_json": parsed,
                    "error": None,
                }
            )
    except Exception as exc:
        with JOB_LOCK:
            JOB_STATE.update(
                {
                    "running": False,
                    "ended_at": _now_str(),
                    "exit_code": -1,
                    "success": False,
                    "stderr_tail": _tail(str(exc)),
                    "error": str(exc),
                }
            )


def _status_payload(force_metrics=False):
    global METRICS_CACHE, METRICS_CACHE_TS
    with JOB_LOCK:
        job = dict(JOB_STATE)
    payload = {
        "job": job,
        "operations": [
            {
                "key": key,
                "label": cfg["label"],
                "destructive": bool(cfg["destructive"]),
                "description": cfg["description"],
                "command": " ".join([sys.executable] + cfg["command"]),
                "requires_csv_only": bool(cfg.get("requires_csv_only")),
                "force_drop": bool(cfg.get("force_drop")),
            }
            for key, cfg in OPERATIONS.items()
        ],
        "reports": _list_recent_reports(),
        "pending_updates": _pending_csv_updates(),
    }
    if job.get("running"):
        cached = dict(METRICS_CACHE or {})
        cached["deferred"] = True
        cached["measured_at"] = cached.get("measured_at") or _now_str()
        payload["metrics"] = cached or {
            "deferred": True,
            "measured_at": _now_str(),
        }
        return payload
    if not force_metrics:
        cached = dict(METRICS_CACHE or {})
        if cached:
            cached["cached"] = True
            payload["metrics"] = cached
        else:
            payload["metrics"] = {
                "deferred": True,
                "measured_at": _now_str(),
            }
        return payload
    try:
        metrics = _collect_metrics()
        METRICS_CACHE = dict(metrics)
        METRICS_CACHE_TS = datetime.datetime.now()
        payload["metrics"] = metrics
    except Exception as exc:
        payload["metrics"] = {"error": str(exc), "measured_at": _now_str()}
    return payload


def _review_summary_payload(conn):
    _ensure_review_tables(conn)
    cur = conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM merge_review_queue
        GROUP BY status
        """
    )
    rows = cur.fetchall() or []
    by_status = {r.get("status"): int(r.get("count") or 0) for r in rows if r.get("status")}
    return {
        "new": by_status.get("new", 0),
        "hold": by_status.get("hold", 0),
        "approved": by_status.get("approved", 0),
        "rejected": by_status.get("rejected", 0),
        "applied": by_status.get("applied", 0),
        "total": sum(by_status.values()),
    }


def _review_items_payload(status, limit, offset):
    conn = get_db()
    try:
        _ensure_review_tables(conn)
        total = _to_int(
            conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM merge_review_queue
                WHERE (? = 'all' OR status = ?)
                """,
                (status, status),
            ).fetchone()
        )
        cur = conn.execute(
            """
            WITH hold_counts AS (
              SELECT book_id, COUNT(*) AS holdings_count
              FROM holdings
              GROUP BY book_id
            )
            SELECT
              q.id,
              q.status,
              q.source,
              q.total_score,
              q.title_score,
              q.author_score,
              q.publisher_score,
              q.signal_score,
              q.risk_flags,
              q.reason,
              q.created_at,
              q.updated_at,
              q.decided_at,
              q.decided_by,
              q.decision_note,
              q.pair_left_book_id,
              q.pair_right_book_id,
              bl.title AS left_title,
              bl.author AS left_author,
              bl.publisher AS left_publisher,
              bl.image_url AS left_image_url,
              br.title AS right_title,
              br.author AS right_author,
              br.publisher AS right_publisher,
              br.image_url AS right_image_url,
              COALESCE(hl.holdings_count, 0) AS left_holdings_count,
              COALESCE(hr.holdings_count, 0) AS right_holdings_count
            FROM merge_review_queue q
            LEFT JOIN books bl ON bl.id = q.pair_left_book_id
            LEFT JOIN books br ON br.id = q.pair_right_book_id
            LEFT JOIN hold_counts hl ON hl.book_id = q.pair_left_book_id
            LEFT JOIN hold_counts hr ON hr.book_id = q.pair_right_book_id
            WHERE (? = 'all' OR q.status = ?)
            ORDER BY
              CASE q.status
                WHEN 'new' THEN 0
                WHEN 'hold' THEN 1
                WHEN 'approved' THEN 2
                WHEN 'rejected' THEN 3
                WHEN 'applied' THEN 4
                ELSE 5
              END ASC,
              q.total_score DESC,
              q.updated_at DESC,
              q.id DESC
            LIMIT ? OFFSET ?
            """,
            (status, status, limit, offset),
        )
        rows = cur.fetchall() or []
        items = []
        for row in rows:
            risk_flags = [
                f.strip()
                for f in (row.get("risk_flags") or "").split(",")
                if f.strip()
            ]
            items.append(
                {
                    "id": row.get("id"),
                    "status": row.get("status"),
                    "source": row.get("source"),
                    "scores": {
                        "total": int(row.get("total_score") or 0),
                        "title": int(row.get("title_score") or 0),
                        "author": int(row.get("author_score") or 0),
                        "publisher": int(row.get("publisher_score") or 0),
                        "signal": int(row.get("signal_score") or 0),
                    },
                    "risk_flags": risk_flags,
                    "reason": row.get("reason") or "",
                    "decision": {
                        "decided_at": (
                            row.get("decided_at").strftime("%Y-%m-%d %H:%M:%S")
                            if row.get("decided_at")
                            else None
                        ),
                        "decided_by": row.get("decided_by") or "",
                        "note": row.get("decision_note") or "",
                    },
                    "timestamps": {
                        "created_at": (
                            row.get("created_at").strftime("%Y-%m-%d %H:%M:%S")
                            if row.get("created_at")
                            else None
                        ),
                        "updated_at": (
                            row.get("updated_at").strftime("%Y-%m-%d %H:%M:%S")
                            if row.get("updated_at")
                            else None
                        ),
                    },
                    "left": {
                        "book_id": row.get("pair_left_book_id"),
                        "title": row.get("left_title") or "",
                        "author": row.get("left_author") or "",
                        "publisher": row.get("left_publisher") or "",
                        "image_url": row.get("left_image_url") or "",
                        "holdings_count": int(row.get("left_holdings_count") or 0),
                    },
                    "right": {
                        "book_id": row.get("pair_right_book_id"),
                        "title": row.get("right_title") or "",
                        "author": row.get("right_author") or "",
                        "publisher": row.get("right_publisher") or "",
                        "image_url": row.get("right_image_url") or "",
                        "holdings_count": int(row.get("right_holdings_count") or 0),
                    },
                }
            )
        summary = _review_summary_payload(conn)
        return {
            "status_filter": status,
            "limit": limit,
            "offset": offset,
            "total": total,
            "summary": summary,
            "items": items,
        }
    finally:
        conn.close()


@data_quality_bp.route("/admin/data-quality")
def data_quality_admin_page():
    _require_admin()
    return render_template("data_quality_admin.html", initial=_status_payload(force_metrics=False))


@data_quality_bp.route("/admin/data-quality/status")
def data_quality_admin_status():
    _require_admin()
    force_metrics = str(request.args.get("force_metrics") or "").strip().lower() in {"1", "true", "yes"}
    return jsonify(_status_payload(force_metrics=force_metrics))


@data_quality_bp.route("/admin/data-quality/run", methods=["POST"])
def data_quality_admin_run():
    _require_admin()
    payload = request.get_json(silent=True) or {}
    operation_key = (payload.get("operation") or "").strip()
    operation = OPERATIONS.get(operation_key)
    if not operation:
        return jsonify({"success": False, "error": "invalid_operation"}), 400

    if operation["destructive"] and not bool(payload.get("confirm")):
        return jsonify({"success": False, "error": "confirm_required"}), 400

    try:
        command, extra_env, options = _build_runtime(operation_key, payload)
    except ValueError as exc:
        if str(exc) == "csv_only_required":
            return jsonify({"success": False, "error": "csv_only_required"}), 400
        return jsonify({"success": False, "error": "invalid_operation_options"}), 400

    with JOB_LOCK:
        if JOB_STATE.get("running"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "job_already_running",
                        "running_operation": JOB_STATE.get("operation"),
                    }
                ),
                409,
            )

    t = threading.Thread(
        target=_run_operation_async,
        args=(operation_key, command, extra_env, options),
        daemon=True,
    )
    t.start()
    return jsonify({"success": True, "operation": operation_key, "started_at": _now_str()})


@data_quality_bp.route("/admin/data-quality/review")
def data_quality_review_page():
    _require_admin()
    payload = _review_items_payload("new", 50, 0)
    return render_template("data_quality_review.html", initial=payload)


@data_quality_bp.route("/admin/data-quality/review/items")
def data_quality_review_items():
    _require_admin()
    status = (request.args.get("status") or "new").strip().lower()
    if status not in REVIEW_ALLOWED_STATUS:
        status = "new"
    limit = _parse_int(request.args.get("limit"), default=50, min_value=1, max_value=200)
    offset = _parse_int(request.args.get("offset"), default=0, min_value=0, max_value=100000)
    return jsonify(_review_items_payload(status, limit, offset))


@data_quality_bp.route("/admin/data-quality/review/summary")
def data_quality_review_summary():
    _require_admin()
    conn = get_db()
    try:
        summary = _review_summary_payload(conn)
        return jsonify(summary)
    finally:
        conn.close()


@data_quality_bp.route("/admin/data-quality/review/decision", methods=["POST"])
def data_quality_review_decision():
    _require_admin()
    payload = request.get_json(silent=True) or {}
    queue_id = _parse_int(payload.get("id"), default=-1, min_value=-1, max_value=10**12)
    action = (payload.get("action") or "").strip().lower()
    note = (payload.get("note") or "").strip()
    if queue_id <= 0:
        return jsonify({"success": False, "error": "invalid_id"}), 400

    action_map = {
        "approve": "approved",
        "reject": "rejected",
        "hold": "hold",
        "reset": "new",
    }
    new_status = action_map.get(action)
    if not new_status:
        return jsonify({"success": False, "error": "invalid_action"}), 400

    actor = request.remote_addr or "admin"
    conn = get_db()
    try:
        _ensure_review_tables(conn)
        if new_status == "new":
            cur = conn.execute(
                """
                UPDATE merge_review_queue
                SET status = 'new',
                    decision_note = NULL,
                    decided_by = NULL,
                    decided_at = NULL,
                    updated_at = NOW()
                WHERE id = ?
                """,
                (queue_id,),
            )
        else:
            cur = conn.execute(
                """
                UPDATE merge_review_queue
                SET status = ?,
                    decision_note = ?,
                    decided_by = ?,
                    decided_at = NOW(),
                    updated_at = NOW()
                WHERE id = ?
                """,
                (new_status, note or None, actor, queue_id),
            )
        if cur.rowcount <= 0:
            conn.rollback()
            return jsonify({"success": False, "error": "not_found"}), 404

        conn.execute(
            """
            INSERT INTO merge_review_log (queue_id, action, actor, note, payload)
            VALUES (?, 'decision', ?, ?, ?::jsonb)
            """,
            (
                queue_id,
                actor,
                note or None,
                json.dumps(
                    {
                        "new_status": new_status,
                        "action": action,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        conn.commit()
        return jsonify({"success": True, "id": queue_id, "status": new_status})
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
