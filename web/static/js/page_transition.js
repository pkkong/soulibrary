(function () {
    const DETAIL_LOADING_TEXT = "상세 페이지 여는 중";
    const DETAIL_PATHS = ["/book/", "/books/", "/live_book"];
    const REPORT_PATH = "/reports";
    const SEARCH_PATH = "/search";
    const QUICK_SEARCH_ID = "quick-search-overlay";

    function getLoader() {
        return document.getElementById("page-loading");
    }

    function isModifiedClick(event) {
        return event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
    }

    function isDetailUrl(href) {
        if (!href) return false;
        try {
            const url = new URL(href, window.location.href);
            if (url.origin !== window.location.origin) return false;
            return DETAIL_PATHS.some(path => url.pathname === path || url.pathname.startsWith(path));
        } catch (err) {
            return false;
        }
    }

    function isReportUrl(href) {
        if (!href) return false;
        try {
            const url = new URL(href, window.location.href);
            return url.origin === window.location.origin && url.pathname === REPORT_PATH;
        } catch (err) {
            return false;
        }
    }

    function currentReportUrl() {
        const target = new URL(REPORT_PATH, window.location.origin);
        if (window.location.pathname !== REPORT_PATH) {
            target.searchParams.set("url", window.location.href);
        }
        return `${target.pathname}${target.search}`;
    }

    function isSearchUrl(href) {
        if (!href) return false;
        try {
            const url = new URL(href, window.location.href);
            return url.origin === window.location.origin && url.pathname === SEARCH_PATH;
        } catch (err) {
            return false;
        }
    }

    function isSearchNavLink(link) {
        return !!(link && link.classList && link.classList.contains("nav-item-search") && isSearchUrl(link.href));
    }

    function syncReportLinks() {
        document.querySelectorAll('a[href="/reports"], a.nav-item-report').forEach(link => {
            if (isReportUrl(link.href)) {
                link.setAttribute("href", currentReportUrl());
            }
        });
    }

    function show(label) {
        const loader = getLoader();
        if (!loader) return;
        const text = loader.querySelector("[data-page-loading-text]");
        if (text) text.textContent = label || DETAIL_LOADING_TEXT;
        loader.removeAttribute("aria-hidden");
        document.body.classList.add("is-page-loading");
    }

    function hide() {
        const loader = getLoader();
        if (loader) loader.setAttribute("aria-hidden", "true");
        document.body.classList.remove("is-page-loading");
    }

    function navigate(url, label) {
        if (!url) return;
        show(label);
        window.location.href = url;
    }

    function focusInput(input) {
        if (!input) return false;
        input.focus({ preventScroll: true });
        if (typeof input.select === "function" && input.value) input.select();
        return document.activeElement === input;
    }

    function focusSearchPageInput() {
        const input = document.getElementById("query");
        if (!input) return false;
        input.scrollIntoView({ block: "center", inline: "nearest" });
        focusInput(input);
        window.setTimeout(() => focusInput(input), 60);
        window.setTimeout(() => focusInput(input), 180);
        return true;
    }

    function closeQuickSearch() {
        const overlay = document.getElementById(QUICK_SEARCH_ID);
        if (overlay) overlay.hidden = true;
        document.body.classList.remove("is-quick-search-open");
    }

    function quickSearchUrl(value) {
        const query = String(value || "").trim();
        if (!query) return SEARCH_PATH;
        const params = new URLSearchParams();
        params.set("q", query);
        return `${SEARCH_PATH}?${params.toString()}`;
    }

    function ensureQuickSearch() {
        let overlay = document.getElementById(QUICK_SEARCH_ID);
        if (overlay) return overlay;
        document.body.insertAdjacentHTML("beforeend", `
            <div class="quick-search-overlay" id="${QUICK_SEARCH_ID}" hidden>
                <form class="quick-search-box" id="quick-search-form" role="search">
                    <span class="quick-search-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="11" cy="11" r="7"></circle>
                            <path d="M21 21l-4.3-4.3"></path>
                        </svg>
                    </span>
                    <label class="sr-only" for="quick-search-input">검색어</label>
                    <input id="quick-search-input" type="search" autocomplete="off" enterkeyhint="search" placeholder="책 제목, 저자 검색">
                    <button class="quick-search-close" type="button" aria-label="닫기">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true">
                            <path d="M6 6l12 12"></path>
                            <path d="M18 6 6 18"></path>
                        </svg>
                    </button>
                </form>
            </div>
        `);
        overlay = document.getElementById(QUICK_SEARCH_ID);
        const form = overlay.querySelector("#quick-search-form");
        const input = overlay.querySelector("#quick-search-input");
        const submitQuickSearch = () => navigate(quickSearchUrl(input.value), "검색 중");
        overlay.addEventListener("click", event => {
            if (event.target === overlay) closeQuickSearch();
        });
        overlay.querySelector(".quick-search-close").addEventListener("click", closeQuickSearch);
        form.addEventListener("submit", event => {
            event.preventDefault();
            submitQuickSearch();
        });
        input.addEventListener("keydown", event => {
            if (event.key !== "Enter") return;
            event.preventDefault();
            submitQuickSearch();
        });
        return overlay;
    }

    function openQuickSearch() {
        const overlay = ensureQuickSearch();
        const input = overlay.querySelector("#quick-search-input");
        const pageInput = document.getElementById("query");
        if (pageInput && pageInput.value && !input.value) input.value = pageInput.value;
        overlay.hidden = false;
        document.body.classList.add("is-quick-search-open");
        focusInput(input);
        window.setTimeout(() => focusInput(input), 60);
    }

    document.addEventListener("click", event => {
        if (event.defaultPrevented || isModifiedClick(event)) return;
        const link = event.target.closest && event.target.closest("a[href]");
        if (!link) return;
        if (link.target && link.target !== "_self") return;
        if (link.hasAttribute("download")) return;
        if (isSearchNavLink(link)) {
            event.preventDefault();
            if (window.location.pathname === SEARCH_PATH) {
                focusSearchPageInput();
                return;
            }
            openQuickSearch();
            return;
        }
        if (isReportUrl(link.href)) {
            link.setAttribute("href", currentReportUrl());
            return;
        }
        if (!isDetailUrl(link.href)) return;
        show(DETAIL_LOADING_TEXT);
    }, true);

    document.addEventListener("DOMContentLoaded", syncReportLinks);
    document.addEventListener("keydown", event => {
        if (event.key === "Escape") closeQuickSearch();
    });
    window.addEventListener("pageshow", () => {
        hide();
        closeQuickSearch();
        syncReportLinks();
    });

    window.SoulibPageLoading = {
        closeQuickSearch,
        focusSearchPageInput,
        hide,
        isDetailUrl,
        navigate,
        openQuickSearch,
        syncReportLinks,
        show,
    };
})();
