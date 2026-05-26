(function () {
    const cards = Array.from(document.querySelectorAll(".blog-search-card[data-search-query]"));
    if (!cards.length) return;

    const MAX_HYDRATED_CARDS = 8;
    const MIN_COVER_SOURCE_WIDTH = 120;

    function normalize(value) {
        return String(value || "").toLowerCase().replace(/[^0-9a-z가-힣]/g, "");
    }

    function escapeAttr(value) {
        return String(value || "")
            .replaceAll("&", "&amp;")
            .replaceAll('"', "&quot;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;");
    }

    function coverCandidateUrls(book) {
        const urls = [];
        function addUrl(value) {
            const url = String(value || "").trim();
            if (!url || urls.includes(url)) return;
            if (!/^https?:\/\//i.test(url) && !url.startsWith("//")) return;
            urls.push(url.startsWith("//") ? `https:${url}` : url);
        }
        addUrl(book && book.image_url);
        (Array.isArray(book && book.image_candidates) ? book.image_candidates : []).forEach(candidate => {
            addUrl(typeof candidate === "string" ? candidate : candidate && (candidate.url || candidate.image_url));
        });
        return urls;
    }

    function scoreBook(book, targetTitle, targetMeta) {
        const title = normalize(book && book.title);
        const author = normalize(book && book.author);
        const publisher = normalize(book && book.publisher);
        const wantedTitle = normalize(targetTitle);
        const wantedMeta = normalize(targetMeta);
        let score = 0;
        if (wantedTitle && title === wantedTitle) score += 100;
        else if (wantedTitle && (title.includes(wantedTitle) || wantedTitle.includes(title))) score += 60;
        if (wantedMeta && author && (author.includes(wantedMeta) || wantedMeta.includes(author))) score += 35;
        if (wantedMeta && publisher && (publisher.includes(wantedMeta) || wantedMeta.includes(publisher))) score += 10;
        if (coverCandidateUrls(book).length) score += 15;
        return score;
    }

    function bestBook(items, targetTitle, targetMeta) {
        return (items || [])
            .slice()
            .sort((left, right) => scoreBook(right, targetTitle, targetMeta) - scoreBook(left, targetTitle, targetMeta))[0];
    }

    function bestBookWithCover(items, targetTitle, targetMeta) {
        const withCover = (items || []).filter(book => coverCandidateUrls(book).length);
        if (!withCover.length) return null;
        return bestBook(withCover, targetTitle, targetMeta);
    }

    async function fetchBooks(query) {
        const params = new URLSearchParams({ query, field: "title_author", limit: "8" });
        const response = await fetch(`/api/live_search?${params.toString()}`, {
            headers: { "Accept": "application/json" },
        });
        if (!response.ok) return [];
        const payload = await response.json();
        return payload.items || [];
    }

    function installCover(card, urls, title) {
        const cover = card.querySelector(".blog-search-card-cover");
        if (!cover || !urls.length) return;
        let index = 0;
        function useNext() {
            const url = urls[index];
            if (!url) return;
            cover.innerHTML = `<img src="${escapeAttr(url)}" alt="" loading="lazy">`;
            const img = cover.querySelector("img");
            img.addEventListener("error", () => {
                index += 1;
                useNext();
            });
            img.addEventListener("load", () => {
                if (img.naturalWidth > 0 && img.naturalWidth < MIN_COVER_SOURCE_WIDTH && urls[index + 1]) {
                    index += 1;
                    useNext();
                }
            });
            card.dataset.coverReady = "1";
            card.setAttribute("aria-label", `Soulib에서 ${title || "도서"} 검색`);
        }
        useNext();
    }

    async function hydrateCard(card) {
        const query = card.dataset.searchQuery || "";
        const title = card.dataset.searchTitle || "";
        const meta = card.dataset.searchMeta || "";
        if (!query) return;
        try {
            let items = await fetchBooks(query);
            let book = bestBookWithCover(items, title, meta) || bestBook(items, title, meta);
            let urls = coverCandidateUrls(book);
            if (!urls.length && title && title !== query) {
                items = await fetchBooks(title);
                book = bestBookWithCover(items, title, meta) || bestBook(items, title, meta);
                urls = coverCandidateUrls(book);
            }
            installCover(card, urls, title);
        } catch (error) {
            // Blog content remains usable as a text search card if live cover hydration fails.
        }
    }

    function start() {
        cards.slice(0, MAX_HYDRATED_CARDS).forEach((card, index) => {
            window.setTimeout(() => hydrateCard(card), index * 120);
        });
    }

    if ("requestIdleCallback" in window) {
        window.requestIdleCallback(start, { timeout: 1200 });
    } else {
        window.setTimeout(start, 300);
    }
})();
