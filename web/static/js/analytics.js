(function () {
    const MEASUREMENT_ID = "G-WS1N5XY56P";
    const OPT_OUT_KEY = "soulib.analytics.optOut";
    const PRODUCTION_HOSTS = new Set(["soulib.kr", "www.soulib.kr"]);
    const EVENTS = new Set(["search_start", "search_result", "search_error", "detail_open", "library_outbound", "shelf_save", "report_success"]);
    const FIELDS = new Set(["title_author", "title", "author", "publisher"]);
    const ERRORS = new Set(["http", "api", "network", "invalid_response", "unknown"]);
    let initialized = false;
    let memoryOptOut = false;

    function isPrivatePath(path) {
        const section = path.split("/")[1] || "";
        return /^(?:ops|admin|api)$/i.test(section) || /(?:^|[_-])admin(?:[_.-]|$)/i.test(section);
    }

    function pageType(path) {
        if (path === "/") return "home";
        if (/^\/search\/?$/.test(path)) return "search";
        if (/^\/(?:live_book|book|books)(?:\/|$)/.test(path)) return "detail";
        if (/^\/my-shelf\/?$/.test(path)) return "shelf";
        if (/^\/shelf(?:\/|$)/.test(path)) return "shared_shelf";
        if (/^\/reports\/?$/.test(path)) return "reports";
        if (/^\/blog(?:\/|$)/.test(path)) return "blog";
        return "guide";
    }

    function safePath(path) {
        const type = pageType(path);
        if (type === "blog") return /^\/blog(?:\/[a-z0-9-]+)?\/?$/.test(path) ? path : "/blog";
        if (new Set(["/ebook-search", "/digital-library-search", "/seoul-ebook-library-search"]).has(path)) return path;
        return {home: "/", search: "/search", detail: "/live_book", shelf: "/my-shelf", shared_shelf: "/shelf/shared", reports: "/reports", guide: "/"}[type];
    }

    function referrerUrl() {
        try { return document.referrer ? new URL(document.referrer) : null; }
        catch (_) { return null; }
    }

    function optedOut() {
        try { return memoryOptOut || localStorage.getItem(OPT_OUT_KEY) === "1"; }
        catch (_) { return memoryOptOut; }
    }

    function enabled() {
        const referrer = referrerUrl();
        return PRODUCTION_HOSTS.has(window.location.hostname) && !isPrivatePath(window.location.pathname) &&
            !(referrer && PRODUCTION_HOSTS.has(referrer.hostname) && isPrivatePath(referrer.pathname)) && !optedOut();
    }

    function pageParams() {
        const referrer = referrerUrl();
        let safeReferrer = "";
        if (referrer && /^https?:$/.test(referrer.protocol)) {
            safeReferrer = PRODUCTION_HOSTS.has(referrer.hostname)
                ? `https://www.soulib.kr${safePath(referrer.pathname)}` : referrer.origin;
        }
        const type = pageType(window.location.pathname);
        return {page_location: `https://www.soulib.kr${safePath(window.location.pathname)}`,
            page_referrer: safeReferrer, page_title: `Soulib ${type}`, page_type: type};
    }

    function number(value) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? Math.max(0, Math.round(parsed)) : 0;
    }

    function eventParams(name, params) {
        const clean = pageParams();
        if (name.startsWith("search_")) {
            clean.search_term = String(params.search_term || "").trim().slice(0, 200);
            clean.field = FIELDS.has(params.field) ? params.field : "title_author";
            clean.provider_count = number(params.provider_count);
            clean.library_count = number(params.library_count);
            if (name !== "search_start") clean.duration_ms = number(params.duration_ms);
            if (name === "search_result") {
                clean.result_count = number(params.result_count);
                clean.partial = !!params.partial;
                clean.failed_library_count = number(params.failed_library_count);
            }
            if (name === "search_error") clean.error_type = ERRORS.has(params.error_type) ? params.error_type : "unknown";
        } else if (name === "library_outbound") {
            clean.provider = new Set(["교보", "YES24", "기타"]).has(params.provider) ? params.provider : "기타";
        } else if (name === "shelf_save") clean.list_count = number(params.list_count);
        else if (name === "report_success") clean.success = true;
        return clean;
    }

    function track(name, params = {}) {
        try {
            if (!initialized || !enabled() || !EVENTS.has(name)) return false;
            window.gtag("event", name, eventParams(name, params));
            return true;
        } catch (_) { return false; }
    }

    function init() {
        if (initialized || !enabled()) return;
        window["ga-disable-" + MEASUREMENT_ID] = false;
        window.dataLayer = window.dataLayer || [];
        window.gtag = window.gtag || function () { window.dataLayer.push(arguments); };
        const safe = pageParams();
        // GA stream enhanced measurement is disabled; use these explicit,
        // sanitized pageviews and events, including generic shared-shelf paths.
        window.gtag("js", new Date());
        window.gtag("set", safe);
        window.gtag("config", MEASUREMENT_ID, {...safe, send_page_view: false});
        window.gtag("event", "page_view", safe);
        initialized = true;
        const script = document.createElement("script");
        script.async = true;
        script.src = `https://www.googletagmanager.com/gtag/js?id=${MEASUREMENT_ID}`;
        document.head.appendChild(script);
    }

    function setOptOut(value = true) {
        memoryOptOut = !!value;
        try {
            if (memoryOptOut) localStorage.setItem(OPT_OUT_KEY, "1");
            else localStorage.removeItem(OPT_OUT_KEY);
        } catch (_) {}
        window["ga-disable-" + MEASUREMENT_ID] = !enabled();
        if (!memoryOptOut) init();
        return memoryOptOut;
    }

    window.SoulibAnalytics = {track, setOptOut, isEnabled: enabled};
    window.addEventListener("storage", event => {
        if (event.key === OPT_OUT_KEY) window["ga-disable-" + MEASUREMENT_ID] = !enabled();
    });
    try { init(); } catch (_) {}
    document.addEventListener("DOMContentLoaded", () => {
        if (pageType(window.location.pathname) === "detail" && document.querySelector("[data-detail-cover]")) track("detail_open");
    });
    document.addEventListener("click", event => {
        const link = event.target.closest && event.target.closest("a[data-analytics-provider]");
        if (!link || event.defaultPrevented) return;
        try {
            const url = new URL(link.href, window.location.href);
            if (/^https?:$/.test(url.protocol) && url.origin !== window.location.origin) {
                track("library_outbound", {provider: link.dataset.analyticsProvider});
            }
        } catch (_) {}
    });
})();
