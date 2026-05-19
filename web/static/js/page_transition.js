(function () {
    const DETAIL_LOADING_TEXT = "상세 페이지 여는 중";
    const DETAIL_PATHS = ["/book/", "/live_book"];
    const REPORT_PATH = "/reports";

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

    document.addEventListener("click", event => {
        if (event.defaultPrevented || isModifiedClick(event)) return;
        const link = event.target.closest && event.target.closest("a[href]");
        if (!link) return;
        if (link.target && link.target !== "_self") return;
        if (link.hasAttribute("download")) return;
        if (isReportUrl(link.href)) {
            link.setAttribute("href", currentReportUrl());
            return;
        }
        if (!isDetailUrl(link.href)) return;
        show(DETAIL_LOADING_TEXT);
    }, true);

    document.addEventListener("DOMContentLoaded", syncReportLinks);
    window.addEventListener("pageshow", () => {
        hide();
        syncReportLinks();
    });

    window.SoulibPageLoading = {
        hide,
        isDetailUrl,
        navigate,
        syncReportLinks,
        show,
    };
})();
