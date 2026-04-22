import csv
import json
import re
from pathlib import Path

from .kyobo_new_base import CLICK_PATTERN, KyoboNewBaseSpider


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _make_item_key(item: dict) -> str:
    brcd = _normalize_text(item.get("brcd", ""))
    if brcd:
        return f"brcd:{brcd}"

    ctts_dvsn_code = _normalize_text(item.get("ctts_dvsn_code", ""))
    ctgr_id = _normalize_text(item.get("ctgr_id", ""))
    title = _normalize_text(item.get("title", ""))
    author = _normalize_text(item.get("author", ""))
    publisher = _normalize_text(item.get("publisher", ""))
    if ctts_dvsn_code or ctgr_id:
        return f"meta:{ctts_dvsn_code}|{ctgr_id}|{title}|{author}|{publisher}"
    return f"fallback:{title}|{author}|{publisher}"


class KyoboIncrementalSpider(KyoboNewBaseSpider):
    name = "kyobo_incremental"

    def __init__(
        self,
        lib_code="",
        base_url="",
        library_name="",
        existing_csv="",
        report_file="",
        min_pages="12",
        max_scan_pages="40",
        stop_after_known_pages="3",
        target_new_items="0",
        diff_count="0",
        expected_pages="1",
        page_size="80",
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        root = Path(__file__).resolve().parents[3]
        self.lib_code = lib_code or "unknown"
        self.base_url = base_url
        self.library_name = library_name or self.lib_code
        self.page_size = max(1, int(page_size or self.page_size))
        self.existing_csv = Path(existing_csv) if existing_csv else root / "data" / f"{self.lib_code}_db.csv"
        self.report_file = Path(report_file) if report_file else root / "data" / f"{self.lib_code}_incremental_report.json"
        self.min_pages = max(1, int(min_pages or 1))
        self.max_scan_pages = max(self.min_pages, int(max_scan_pages or self.min_pages))
        self.stop_after_known_pages = max(1, int(stop_after_known_pages or 1))
        self.target_new_items = max(0, int(target_new_items or 0))
        self.diff_count = max(0, int(diff_count or 0))
        self.expected_pages = max(1, int(expected_pages or 1))

        self.known_keys = self._load_existing_keys(self.existing_csv)
        self.new_keys = set()
        self.page_stats = []
        self.pages_scanned = 0
        self.consecutive_known_pages = 0
        self.stop_reason = ""
        self.total_pages = None

    async def start(self):
        yield self._make_request(1)

    def _load_existing_keys(self, csv_path: Path):
        keys = set()
        if not csv_path.exists():
            return keys
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = _make_item_key(row)
                if key:
                    keys.add(key)
        return keys

    def _record_stop_reason(self, reason: str) -> None:
        if not self.stop_reason:
            self.stop_reason = reason

    def _build_item(self, book):
        title = book.css("li.tit a::text").get()
        writer_texts = book.css("li.writer::text").getall()
        author = writer_texts[0].strip() if writer_texts else ""
        publisher = book.css("li.writer span::text").get() or ""
        provider = book.css("span.store::text").get() or self.provider
        onclick = book.css("a[onclick*='fnContentClick']::attr(onclick)").get() or ""
        ctts_dvsn_code = ""
        brcd = ""
        ctgr_id = ""
        match = CLICK_PATTERN.search(onclick)
        if match:
            ctts_dvsn_code, brcd, ctgr_id = match.groups()

        image_url = book.css("div.img a img::attr(src)").get()
        if image_url:
            if image_url.startswith("//"):
                image_url = "https:" + image_url
            elif self.image_prefix and image_url.startswith("/"):
                image_url = f"{self.image_prefix}{image_url}"
        if not brcd and image_url:
            match = re.search(r"/ebook/(\d{10,13}|[A-Za-z0-9]{10,})/", image_url)
            if match:
                brcd = match.group(1)

        if not title:
            return None

        return {
            "title": title.strip(),
            "author": author,
            "publisher": publisher,
            "library": self.library_name,
            "platform": self.platform,
            "provider": provider,
            "image_url": image_url or "",
            "isbn": "",
            "brcd": brcd,
            "ctts_dvsn_code": ctts_dvsn_code,
            "ctgr_id": ctgr_id,
        }

    def parse(self, response):
        page = int(response.meta.get("page", 1))
        if self.total_pages is None and page == 1:
            detected_total = self._extract_total_pages(response)
            if detected_total:
                self.total_pages = detected_total
                self.logger.info("[incremental:%s] total_pages=%s", self.lib_code, self.total_pages)

        books = response.xpath('//li[.//li[@class="tit"]]') or []
        if not books:
            self._record_stop_reason(f"empty_page:{page}")
            return

        page_new = 0
        page_known = 0
        for book in books:
            item = self._build_item(book)
            if not item:
                continue
            item_key = _make_item_key(item)
            if item_key in self.known_keys or item_key in self.new_keys:
                page_known += 1
                continue
            self.new_keys.add(item_key)
            page_new += 1
            yield item

        self.pages_scanned += 1
        self.page_stats.append(
            {
                "page": page,
                "books": len(books),
                "new_items": page_new,
                "known_items": page_known,
            }
        )
        self.consecutive_known_pages = self.consecutive_known_pages + 1 if page_new == 0 else 0

        self.logger.info(
            "[incremental:%s] page=%s books=%s new=%s known=%s known_streak=%s",
            self.lib_code,
            page,
            len(books),
            page_new,
            page_known,
            self.consecutive_known_pages,
        )

        if page >= self.max_scan_pages:
            self._record_stop_reason(f"max_scan_pages:{self.max_scan_pages}")
            return

        target_met = self.target_new_items <= 0 or len(self.new_keys) >= self.target_new_items
        if (
            page >= self.min_pages
            and self.consecutive_known_pages >= self.stop_after_known_pages
            and target_met
        ):
            self._record_stop_reason(f"known_page_streak:{self.consecutive_known_pages}")
            return

        next_page = page + 1
        page_limit = self.total_pages or self.max_pages_cap
        if next_page <= page_limit:
            yield self._make_request(next_page)
        else:
            self._record_stop_reason("remote_total_pages_reached")

    def closed(self, reason):
        report = {
            "library": self.lib_code,
            "kind": "kyobo_new_subs",
            "existing_csv": str(self.existing_csv),
            "existing_key_count": len(self.known_keys),
            "page_size": self.page_size,
            "diff_count": self.diff_count,
            "target_new_items": self.target_new_items,
            "target_reached": len(self.new_keys) >= self.target_new_items if self.target_new_items > 0 else None,
            "expected_pages": self.expected_pages,
            "min_pages": self.min_pages,
            "max_scan_pages": self.max_scan_pages,
            "stop_after_known_pages": self.stop_after_known_pages,
            "pages_scanned": self.pages_scanned,
            "new_items_found": len(self.new_keys),
            "consecutive_known_pages": self.consecutive_known_pages,
            "stop_reason": self.stop_reason or reason,
            "total_pages_detected": self.total_pages,
            "page_stats": self.page_stats,
        }
        self.report_file.parent.mkdir(parents=True, exist_ok=True)
        with self.report_file.open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
