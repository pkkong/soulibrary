import argparse
import json
import sys
from datetime import date
from pathlib import Path


QUERY_THEMES = {
    "library_access": ("도서관", "전자도서관", "서울도서관", "소장", "대출"),
    "ebook": ("전자책", "ebook", "e-book", "오디오북"),
    "book_discovery": ("책 추천", "추천도서", "베스트셀러", "신간", "읽을만한"),
    "availability": ("예약", "대출가능", "대출 가능", "소장도서"),
}


ROLE_MAP = {
    "indexing": ("Technical SEO Worker", "QA/Release Worker"),
    "index_monitor": ("Growth Analyst", "QA/Release Worker"),
    "technical": ("Technical SEO Worker", "QA/Release Worker"),
    "ctr": ("Growth Analyst", "UX/UI Designer", "Editor/Fact Checker", "QA/Release Worker"),
    "ranking": ("Growth Analyst", "Technical SEO Worker", "Editor/Fact Checker"),
    "query_theme": ("Growth Analyst", "Content Writer", "Editor/Fact Checker"),
    "target_page": ("Growth Analyst", "UX/UI Designer", "Technical SEO Worker"),
    "target_keyword": ("Growth Analyst", "Technical SEO Worker", "Editor/Fact Checker"),
    "query_mapping": ("Growth Analyst", "Technical SEO Worker", "Content Writer"),
    "search_ux": ("Growth Analyst", "UX/UI Designer", "QA/Release Worker"),
}


CHECK_MAP = {
    "indexing": ("seo_growth_audit.py weekly URL Inspection", "production sitemap/canonical check"),
    "index_monitor": ("seo_growth_audit.py weekly URL Inspection",),
    "technical": ("seo_growth_audit.py technical checks", "scripts/smoke_test.py", "git diff --check"),
    "ctr": ("Search Console query-page review", "snippet/content review", "scripts/smoke_test.py"),
    "ranking": ("Search Console query-page review", "internal link review", "scripts/smoke_test.py"),
    "query_theme": ("content/blog/_README.md gate", "blog_quality_check.py --strict"),
    "target_page": ("Search Console target page review", "mobile/desktop UX review"),
    "target_keyword": ("Search Console target keyword review", "query-page intent review"),
    "query_mapping": ("existing landing/blog duplicate check", "Editor/Fact Checker review"),
    "search_ux": ("production search flow review", "mobile search result review"),
}


AUTOMATION_LEVEL = {
    "indexing": "auto_patch_candidate",
    "index_monitor": "auto_check",
    "technical": "auto_patch_candidate",
    "ctr": "draft_only",
    "ranking": "draft_only",
    "query_theme": "draft_only",
    "target_page": "draft_only",
    "target_keyword": "draft_only",
    "query_mapping": "draft_only",
    "search_ux": "draft_only",
}


def fail(message, exit_code=2):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def load_audit(path):
    if path == "-":
        return json.load(sys.stdin)
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def get_period(audit, days):
    for period in audit.get("search_console", {}).get("periods", []):
        if period.get("days") == days:
            return period
    return {}


def score_priority(kind, evidence):
    impressions = int(evidence.get("impressions") or 0)
    position = float(evidence.get("position") or 0)
    ctr = float(evidence.get("ctr") or 0)
    if kind == "indexing":
        if int(evidence.get("unindexed_days") or 0) < 14:
            return "P3"
        return "P1"
    if kind == "index_monitor":
        return "P3"
    if kind == "technical":
        return "P1" if not evidence.get("ok", True) else "P2"
    if impressions >= 500 and (ctr < 0.015 or 4 <= position <= 12):
        return "P1"
    if impressions >= 100:
        return "P2"
    return "P3"


def make_opportunity(kind, title, rationale, evidence, suggested_action):
    priority = score_priority(kind, evidence)
    seed = f"{kind}:{title}".lower().replace(" ", "-")
    safe_id = "".join(ch for ch in seed if ch.isalnum() or ch in "-_:")[:80]
    return {
        "id": safe_id,
        "type": kind,
        "priority": priority,
        "title": title,
        "rationale": rationale,
        "evidence": evidence,
        "suggested_action": suggested_action,
        "automation_level": AUTOMATION_LEVEL.get(kind, "draft_only"),
        "required_roles": list(ROLE_MAP.get(kind, ("Growth Analyst", "QA/Release Worker"))),
        "required_checks": list(CHECK_MAP.get(kind, ("scripts/smoke_test.py", "git diff --check"))),
        "guardrails": [
            "블로그, 랜딩 문구, 이미지, UI 변경은 자동 발행하지 않습니다.",
            "페이지나 콘텐츠 변경은 smoke test와 사람 검토 게이트를 통과해야 합니다.",
        ],
    }


def public_automation_label(value):
    return {
        "auto_check": "자동 점검",
        "auto_patch_candidate": "저위험 수정 검토 후보",
        "draft_only": "사람 검토용 초안",
    }.get(value or "", value or "사람 검토용 초안")


def public_type_label(value):
    return {
        "indexing": "색인 문제",
        "index_monitor": "색인 관찰",
        "technical": "기술 점검",
        "ctr": "검색 결과 문구",
        "ranking": "순위 개선",
        "query_theme": "검색 의도 묶음",
        "target_page": "목표 페이지",
        "target_keyword": "목표 키워드",
        "query_mapping": "검색어-페이지 연결",
        "search_ux": "검색 사용자 경험",
    }.get(value or "", value or "검토 항목")


def public_title(item, index):
    kind = item.get("type")
    titles = {
        "ctr": "검색 결과 문구 개선 후보",
        "ranking": "순위 상승 후보",
        "query_mapping": "검색어-페이지 연결 개선 후보",
        "search_ux": "검색 사용자 경험 점검 후보",
        "target_keyword": "목표 키워드 개선 후보",
    }
    if kind in {"ctr", "ranking", "query_mapping", "search_ux", "target_keyword"}:
        return f"{index}. [{item['priority']}] {titles.get(kind, public_type_label(kind))}"
    return f"{index}. [{item['priority']}] {item['title']}"


def indexing_opportunities(audit, min_unindexed_days):
    opportunities = []
    for item in audit.get("url_inspection", {}).get("inspected", []):
        if item.get("error"):
            opportunities.append(
                make_opportunity(
                    "index_monitor",
                    f"URL Inspection API error for {item.get('url')}",
                    "URL Inspection API가 색인 상태를 확인하지 못했습니다.",
                    item,
                    "Search Console 권한, 쿼터, 일시 오류 여부를 확인한 뒤 주간 점검을 다시 실행하세요.",
                )
            )
            continue
        verdict = item.get("verdict")
        coverage = item.get("coverage_state")
        if verdict and verdict != "PASS":
            unindexed_days = int(item.get("unindexed_days") or 0)
            if unindexed_days < min_unindexed_days:
                opportunities.append(
                    make_opportunity(
                        "index_monitor",
                        f"Monitor indexing for {item.get('url')}",
                        f"Google이 아직 이 URL을 색인하지 않았지만 추적 기간은 {unindexed_days}일입니다.",
                        item,
                        "14일 기준에 도달하기 전까지는 콘텐츠를 흔들지 말고 계속 관찰하세요.",
                    )
                )
                continue
            opportunities.append(
                make_opportunity(
                    "indexing",
                    f"Fix indexing verdict for {item.get('url')}",
                    f"Google 색인 상태가 정상 통과가 아니며, 미색인 추적 기간은 {unindexed_days}일입니다.",
                    item,
                    "canonical, robots, fetch 상태, 내부 링크를 먼저 점검한 뒤 필요한 경우 색인 요청을 검토하세요.",
                )
            )
    return opportunities


def technical_opportunities(audit):
    opportunities = []
    checks = audit.get("technical_checks", {})
    for item in checks.get("pages", []):
        if not item.get("ok", True):
            opportunities.append(
                make_opportunity(
                    "technical",
                    f"Production check failed for {item.get('url')}",
                    "감시 대상 production URL이 정상 응답을 주지 않았습니다.",
                    item,
                    "production 응답을 고치거나 오래된 URL이면 감시 대상에서 제외하세요.",
                )
            )
        elif not item.get("indexable", True):
            opportunities.append(
                make_opportunity(
                    "technical",
                    f"Indexability blocked for {item.get('url')}",
                    "페이지는 200을 반환하지만 noindex 또는 색인 차단 신호가 있습니다.",
                    item,
                    "색인 대상 페이지가 맞는지 확인하고 필요하면 robots metadata를 조정하세요.",
                )
            )
        elif not item.get("meta_description_present"):
            opportunities.append(
                make_opportunity(
                    "technical",
                    f"Meta description missing for {item.get('url')}",
                    "감시 대상 페이지에 meta description이 없으면 검색 결과 문구 품질이 떨어질 수 있습니다.",
                    item,
                    "일반 UI/콘텐츠 리뷰 절차로 page description을 추가하거나 개선하세요.",
                )
            )
        page_type = item.get("page_type")
        if (
            item.get("indexable", True)
            and item.get("canonical_matches_final_url") is False
            and page_type != "search"
        ):
            opportunities.append(
                make_opportunity(
                    "technical",
                    f"Review canonical for {item.get('url')}",
                    "색인 대상 페이지의 canonical이 최종 URL과 다릅니다.",
                    item,
                    "의도한 대표 URL인지 확인하고, 잘못된 canonical이면 수정하세요.",
                )
            )
        if (
            item.get("indexable", True)
            and item.get("in_static_sitemap") is False
            and page_type != "search"
        ):
            opportunities.append(
                make_opportunity(
                    "technical",
                    f"Review sitemap coverage for {item.get('url')}",
                    "색인 대상 페이지가 static sitemap에서 확인되지 않았습니다.",
                    item,
                    "sitemap 생성 로직 또는 감시 대상 URL이 맞는지 확인하세요.",
                )
            )
        if item.get("broken_images"):
            opportunities.append(
                make_opportunity(
                    "technical",
                    f"Fix broken images on {item.get('url')}",
                    "감시 대상 페이지에 production에서 깨지는 로컬 이미지가 있습니다.",
                    {
                        "url": item.get("url"),
                        "broken_images": item.get("broken_images"),
                        "impressions": 0,
                    },
                    "깨진 이미지 경로를 교체하거나 제거한 뒤 production 기술 점검을 다시 실행하세요.",
                )
            )
        if item.get("broken_internal_links"):
            opportunities.append(
                make_opportunity(
                    "technical",
                    f"Fix broken internal links on {item.get('url')}",
                    "감시 대상 페이지에 production에서 실패하는 내부 링크가 있습니다.",
                    {
                        "url": item.get("url"),
                        "broken_internal_links": item.get("broken_internal_links"),
                        "impressions": 0,
                    },
                    "내부 링크를 고치거나 오래된 링크를 제거한 뒤 smoke와 production 점검을 다시 실행하세요.",
                )
            )
    for item in checks.get("supporting_files", []):
        if not item.get("ok", True):
            opportunities.append(
                make_opportunity(
                    "technical",
                    f"Supporting SEO file check failed for {item.get('url')}",
                    "robots.txt 또는 sitemap.xml이 점검 시점에 정상 응답하지 않았습니다.",
                    item,
                    "지원 파일 응답을 복구하고 production에서 다시 확인하세요.",
                )
            )
    return opportunities


def ctr_opportunities(period, min_impressions, low_ctr):
    opportunities = []
    for row in period.get("top_queries", []):
        if row.get("impressions", 0) >= min_impressions and row.get("ctr", 0) < low_ctr:
            opportunities.append(
                make_opportunity(
                    "ctr",
                    f"Improve CTR for query '{row.get('query')}'",
                    "노출이 의미 있게 발생했지만 클릭률이 낮습니다.",
                    row,
                    "순위 페이지의 제목, 설명, 검색 의도 일치를 검토한 뒤 문구 개선안을 만드세요.",
                )
            )
    for row in period.get("top_pages", []):
        if row.get("impressions", 0) >= min_impressions and row.get("ctr", 0) < low_ctr:
            opportunities.append(
                make_opportunity(
                    "ctr",
                    f"Improve CTR for page {row.get('page')}",
                    "검색에는 노출되지만 클릭으로 이어지는 비율이 낮습니다.",
                    row,
                    "이 페이지의 주요 검색어를 비교하고 snippet 또는 내부 링크 개선안을 검토하세요.",
                )
            )
    return opportunities


def position_opportunities(period, min_impressions):
    opportunities = []
    for row in period.get("top_queries", []):
        position = row.get("position", 0)
        if (
            row.get("impressions", 0) >= min_impressions
            and 8 <= position <= 30
            and row.get("delta_impressions", 0) > 0
        ):
            opportunities.append(
                make_opportunity(
                    "ranking",
                    f"Move striking-distance query '{row.get('query')}' upward",
                    "검색어가 8~30위 범위에 있고 노출이 늘고 있습니다.",
                    row,
                    "순위 URL을 확인하고 의도 보강과 관련 내부 링크를 검토하세요.",
                )
            )
    return opportunities


def is_existing_seo_destination(page):
    page = page or ""
    return any(
        token in page
        for token in (
            "/ebook-search",
            "/digital-library-search",
            "/seoul-ebook-library-search",
            "/blog/",
            "/books/",
        )
    )


def query_mapping_opportunities(period, min_query_impressions):
    opportunities = []
    seen_queries = set()
    for row in period.get("top_page_queries", []):
        query = row.get("query") or ""
        page = row.get("page") or ""
        if query in seen_queries or row.get("impressions", 0) < min_query_impressions:
            continue
        if is_existing_seo_destination(page):
            continue
        seen_queries.add(query)
        opportunities.append(
            make_opportunity(
                "query_mapping",
                f"Map visible query '{query}' to a better SEO destination",
                "이 검색어가 노출되고 있지만 너무 넓거나 덜 구체적인 페이지로 연결됩니다.",
                row,
                "기존 랜딩/블로그로 내부 링크를 보강할지, 검토된 안내 글 초안이 필요한지 확인하세요.",
            )
        )
    return opportunities


def search_ux_opportunities(period):
    opportunities = []
    for row in period.get("top_page_queries", []):
        if row.get("clicks", 0) <= 0:
            continue
        page = row.get("page") or ""
        if "/search" not in page:
            continue
        opportunities.append(
            make_opportunity(
                "search_ux",
                f"Review clicked search result UX for '{row.get('query')}'",
                "Google 사용자가 Soulib 검색 결과 페이지로 들어왔으므로 첫 결과 경험을 확인해야 합니다.",
                row,
                "모바일에서 해당 검색 URL을 열어 결과 적합성, 빈 상태, 다음 행동을 확인하세요.",
            )
        )
    return opportunities


def query_theme_opportunities(period, min_impressions):
    buckets = {theme: {"queries": [], "impressions": 0, "clicks": 0} for theme in QUERY_THEMES}
    for row in period.get("top_queries", []):
        query = (row.get("query") or "").lower()
        for theme, tokens in QUERY_THEMES.items():
            if any(token.lower() in query for token in tokens):
                buckets[theme]["queries"].append(row)
                buckets[theme]["impressions"] += row.get("impressions", 0)
                buckets[theme]["clicks"] += row.get("clicks", 0)
    opportunities = []
    for theme, data in buckets.items():
        if data["impressions"] < min_impressions:
            continue
        ctr = data["clicks"] / data["impressions"] if data["impressions"] else 0
        evidence = {
            "theme": theme,
            "query_count": len(data["queries"]),
            "impressions": data["impressions"],
            "clicks": data["clicks"],
            "ctr": round(ctr, 4),
            "sample_queries": [row.get("query") for row in data["queries"][:5]],
        }
        opportunities.append(
            make_opportunity(
                "query_theme",
                f"Plan reviewed SEO improvement for {theme}",
                "관련 검색어들이 함께 노출되고 있어 하나의 검토된 개선 작업으로 묶을 수 있습니다.",
                evidence,
                "페이지, snippet, 내부 링크 개선안을 사람 검토용 이슈로 정리하세요. 콘텐츠 자동 발행은 하지 않습니다.",
            )
        )
    return opportunities


def target_opportunities(audit, min_impressions, low_ctr):
    opportunities = []
    targets = audit.get("search_console", {}).get("targets", {})
    for page in targets.get("pages", []):
        metrics = page.get("periods", {}).get("28", {})
        if metrics.get("impressions", 0) >= min_impressions and metrics.get("ctr", 0) < low_ctr:
            evidence = {"page": page.get("page"), **metrics}
            opportunities.append(
                make_opportunity(
                    "target_page",
                    f"Target page opportunity: {page.get('page')}",
                    "추적 중인 목표 페이지가 노출은 되지만 클릭률이 낮습니다.",
                    evidence,
                    "검색 결과 문구, 제목 적합성, 내부 검색 연결을 UX/SEO 관점에서 검토하세요.",
                )
            )
    for keyword in targets.get("keywords", []):
        metrics = keyword.get("periods", {}).get("28", {})
        if metrics.get("impressions", 0) >= min_impressions and (
            metrics.get("ctr", 0) < low_ctr or 4 <= metrics.get("position", 0) <= 15
        ):
            evidence = {"query": keyword.get("query"), **metrics}
            opportunities.append(
                make_opportunity(
                    "target_keyword",
                    f"Target keyword opportunity: {keyword.get('query')}",
                    "추적 중인 목표 키워드가 이미 노출되고 있어 개선 계획을 세울 수 있습니다.",
                    evidence,
                    "검색어와 순위 URL을 연결한 뒤 제목, snippet, 내부 링크 개선안을 검토하세요.",
                )
            )
    return opportunities


def sort_opportunities(opportunities):
    rank = {"P1": 0, "P2": 1, "P3": 2}
    return sorted(
        opportunities,
        key=lambda item: (
            rank.get(item["priority"], 9),
            -int(item.get("evidence", {}).get("impressions") or 0),
            item["title"],
        ),
    )


def build_plan(audit, args):
    period = get_period(audit, args.period_days) or get_period(audit, 28)
    opportunities = []
    opportunities.extend(indexing_opportunities(audit, args.min_unindexed_days))
    opportunities.extend(technical_opportunities(audit))
    opportunities.extend(ctr_opportunities(period, args.min_impressions, args.low_ctr))
    opportunities.extend(position_opportunities(period, args.min_impressions))
    opportunities.extend(query_mapping_opportunities(period, args.min_query_impressions))
    opportunities.extend(search_ux_opportunities(period))
    opportunities.extend(query_theme_opportunities(period, args.min_theme_impressions))
    opportunities.extend(target_opportunities(audit, args.min_impressions, args.low_ctr))
    return {
        "schema_version": "seo_opportunity_plan.v1",
        "generated_date": date.today().isoformat(),
        "source_audit_generated_at": audit.get("generated_at"),
        "site_url": audit.get("site_url"),
        "base_url": audit.get("base_url"),
        "period_days": period.get("days"),
        "dry_run_source": bool(audit.get("dry_run")),
        "opportunities": sort_opportunities(opportunities)[: args.max_opportunities],
        "guardrails": [
            "블로그, 랜딩 문구, 이미지, UI 변경은 자동 발행하지 않습니다.",
            "이 계획은 사람 검토용 SEO 작업 큐이며 발행 결정이 아닙니다.",
        ],
    }


def evidence_line(evidence, public=False):
    pieces = []
    if public:
        if "impressions" in evidence:
            impressions = int(evidence.get("impressions") or 0)
            if impressions >= 500:
                pieces.append("노출: 500회 이상")
            elif impressions >= 100:
                pieces.append("노출: 100회 이상")
            elif impressions >= 20:
                pieces.append("노출: 20회 이상")
            elif impressions > 0:
                pieces.append("노출: 20회 미만")
        if "clicks" in evidence:
            clicks = int(evidence.get("clicks") or 0)
            pieces.append("클릭 있음" if clicks > 0 else "클릭 없음")
        if "position" in evidence:
            position = float(evidence.get("position") or 0)
            if position and position <= 3:
                pieces.append("순위: 상위권")
            elif position and position <= 10:
                pieces.append("순위: 1페이지권")
            elif position and position <= 30:
                pieces.append("순위: 개선 여지 있음")
            elif position:
                pieces.append("순위: 낮음")
        for key in ("verdict", "coverage_state", "unindexed_days", "status_code"):
            if key in evidence and evidence[key] not in (None, ""):
                pieces.append(f"{key}: {evidence[key]}")
        if evidence.get("broken_images"):
            pieces.append(f"broken images: {len(evidence['broken_images'])}")
        if evidence.get("broken_internal_links"):
            pieces.append(f"broken internal links: {len(evidence['broken_internal_links'])}")
        return "; ".join(pieces) or "요약 근거만 공개 표시합니다."
    for key in (
        "impressions",
        "clicks",
        "ctr_percent",
        "position",
        "delta_impressions",
        "delta_position",
        "verdict",
        "coverage_state",
        "unindexed_days",
        "status_code",
    ):
        if key in evidence and evidence[key] not in (None, ""):
            pieces.append(f"{key}: {evidence[key]}")
    if evidence.get("broken_images"):
        pieces.append(f"broken images: {len(evidence['broken_images'])}")
    if evidence.get("broken_internal_links"):
        pieces.append(f"broken internal links: {len(evidence['broken_internal_links'])}")
    if evidence.get("sample_queries"):
        pieces.append("sample queries: " + ", ".join(evidence["sample_queries"]))
    return "; ".join(pieces) or "See JSON evidence."


def render_markdown(plan, public=False):
    lines = [
        f"# SEO Growth Queue - {plan['generated_date']}",
        "",
        f"- Site: `{plan.get('site_url') or 'unknown'}`",
        f"- Base URL: `{plan.get('base_url') or 'unknown'}`",
        f"- Source audit: `{plan.get('source_audit_generated_at') or 'unknown'}`",
        f"- Period: `{plan.get('period_days') or 'unknown'}` days",
        f"- Dry-run source: `{str(plan.get('dry_run_source')).lower()}`",
        "",
        "## Notice",
        "",
        "- 이 이슈는 공개 저장소에 올라가도 되도록 Search Console 원시 검색어/페이지 지표를 제거하거나 요약합니다.",
        "- 원본 Search Console JSON은 GitHub Actions artifact, issue, PR, 저장소에 남기지 않습니다.",
        "",
        "## Guardrails",
        "",
    ]
    lines.extend(f"- {item}" for item in plan["guardrails"])
    lines.extend(["", "## Opportunities", ""])
    if not plan["opportunities"]:
        lines.append("No opportunities crossed the configured thresholds in this run.")
    for index, item in enumerate(plan["opportunities"], start=1):
        heading = (
            public_title(item, index)
            if public
            else f"{index}. [{item['priority']}] {item['title']}"
        )
        lines.extend(
            [
                f"### {heading}",
                "",
                f"- 유형: {public_type_label(item['type'])} (`{item['type']}`)",
                f"- 자동화 수준: {public_automation_label(item.get('automation_level'))} (`{item.get('automation_level')}`)",
                f"- 담당 역할: {', '.join(item.get('required_roles') or [])}",
                f"- 항목별 확인: {', '.join(item.get('required_checks') or [])}",
                "- 공통 게이트: scripts/smoke_test.py, git diff --check, production live smoke after merge",
                f"- 왜 중요한가: {item['rationale']}",
                f"- 근거: {evidence_line(item.get('evidence', {}), public=public)}",
                f"- 다음 행동: {item['suggested_action']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def sanitize_plan(plan):
    sanitized = {key: value for key, value in plan.items() if key != "opportunities"}
    sanitized["opportunities"] = []
    for index, item in enumerate(plan.get("opportunities", []), start=1):
        public_item = {
            key: value
            for key, value in item.items()
            if key not in {"evidence", "title", "rationale", "suggested_action"}
        }
        public_item["title"] = public_title(item, index).split("] ", 1)[-1]
        public_item["rationale"] = item.get("rationale")
        public_item["suggested_action"] = item.get("suggested_action")
        public_item["evidence_summary"] = evidence_line(item.get("evidence", {}), public=True)
        sanitized["opportunities"].append(public_item)
    return sanitized


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create reviewed SEO opportunities from seo_growth_audit.py JSON."
    )
    parser.add_argument("audit_json", help="Audit JSON path, or '-' for stdin.")
    parser.add_argument("--period-days", type=int, default=28)
    parser.add_argument("--min-impressions", type=int, default=50)
    parser.add_argument("--min-query-impressions", type=int, default=20)
    parser.add_argument("--min-theme-impressions", type=int, default=100)
    parser.add_argument("--min-unindexed-days", type=int, default=14)
    parser.add_argument("--low-ctr", type=float, default=0.02)
    parser.add_argument("--max-opportunities", type=int, default=20)
    parser.add_argument("--markdown", action="store_true", help="Print GitHub Issue-style Markdown.")
    parser.add_argument(
        "--public-summary",
        action="store_true",
        help="Summarize raw Search Console evidence for public issue/PR text.",
    )
    parser.add_argument("--github-issue-md", help="Write GitHub Issue-style Markdown to this path.")
    parser.add_argument("--json-output", help="Write JSON plan to this path.")
    parser.add_argument("--public-json-output", help="Write sanitized JSON plan to this path.")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.max_opportunities < 1:
        fail("--max-opportunities must be at least 1.")
    audit = load_audit(args.audit_json)
    plan = build_plan(audit, args)
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.public_json_output:
        Path(args.public_json_output).write_text(
            json.dumps(sanitize_plan(plan), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.github_issue_md:
        Path(args.github_issue_md).write_text(
            render_markdown(plan, public=args.public_summary), encoding="utf-8"
        )
    if args.markdown:
        print(render_markdown(plan, public=args.public_summary), end="")
    else:
        print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
