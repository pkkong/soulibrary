(function () {
    const cards = Array.from(document.querySelectorAll(".blog-search-card"))
        .filter(card => card.dataset.searchQuery || card.dataset.coverUrl || card.dataset.coverUrls);
    if (!cards.length) return;

    const MAX_HYDRATED_CARDS = 8;
    const MIN_COVER_SOURCE_WIDTH = 120;

    function normalize(value) {
        return String(value || "").toLowerCase().replace(/[^0-9a-z가-힣]/g, "");
    }

    function addCoverUrl(urls, value, allowRelative) {
        const url = String(value || "").trim();
        let normalized = "";
        if (!url) return;
        if (/^https?:\/\//i.test(url) || url.startsWith("//")) {
            normalized = url.startsWith("//") ? `https:${url}` : url;
        } else if (allowRelative && (/^(\/|\.\/|\.\.\/)/.test(url) || /^data:image\//i.test(url))) {
            normalized = url;
        }
        if (!normalized || urls.includes(normalized)) return;
        urls.push(normalized);
    }

    function coverCandidateUrls(book) {
        const urls = [];
        addCoverUrl(urls, book && book.image_url, false);
        (Array.isArray(book && book.image_candidates) ? book.image_candidates : []).forEach(candidate => {
            addCoverUrl(urls, typeof candidate === "string" ? candidate : candidate && (candidate.url || candidate.image_url), false);
        });
        return urls;
    }

    function cardCoverUrls(card) {
        const urls = [];
        addCoverUrl(urls, card.dataset.coverUrl, true);
        const coverUrls = String(card.dataset.coverUrls || "").trim();
        if (!coverUrls) return urls;
        if (coverUrls.startsWith("[")) {
            try {
                const parsed = JSON.parse(coverUrls);
                if (Array.isArray(parsed)) {
                    parsed.forEach(url => addCoverUrl(urls, url, true));
                    return urls;
                }
            } catch (error) {
                // Fall through to delimiter parsing below.
            }
        }
        coverUrls.split(/[\n,|]+/).forEach(url => addCoverUrl(urls, url, true));
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

    async function fetchBooks(query, refine) {
        const params = new URLSearchParams({ query, field: "title", limit: "8" });
        if (refine) params.set("refine", refine);
        const response = await fetch(`/api/live_search?${params.toString()}`, {
            headers: { "Accept": "application/json" },
        });
        if (!response.ok) return [];
        const payload = await response.json();
        return payload.items || [];
    }

    function resetCover(card) {
        const cover = card.querySelector(".blog-search-card-cover");
        if (cover) {
            cover.replaceChildren();
        }
        card.style.removeProperty("--blog-search-card-cover-bg");
        delete card.dataset.coverReady;
    }

    function createCoverImage(url) {
        const img = new Image();
        img.alt = "";
        img.loading = "lazy";
        img.decoding = "async";
        img.src = url;
        return img;
    }

    function waitForCover(img, preferNext) {
        return new Promise(resolve => {
            function finish() {
                if (preferNext && img.naturalWidth > 0 && img.naturalWidth < MIN_COVER_SOURCE_WIDTH) {
                    resolve(false);
                    return;
                }
                resolve(img.naturalWidth > 0);
            }
            if (img.complete) {
                finish();
                return;
            }
            img.addEventListener("load", finish, { once: true });
            img.addEventListener("error", () => resolve(false), { once: true });
        });
    }

    function coverBackgroundValue(url) {
        return `url(${JSON.stringify(String(url || ""))})`;
    }

    function markCoverReady(card, cover, img, title) {
        cover.replaceChildren(img);
        card.style.setProperty("--blog-search-card-cover-bg", coverBackgroundValue(img.currentSrc || img.src));
        card.dataset.coverReady = "1";
        card.setAttribute("aria-label", `Soulib에서 ${title || "도서"} 검색`);
    }

    async function loadCover(url, preferNext) {
        const img = createCoverImage(url);
        return await waitForCover(img, preferNext) ? img : null;
    }

    async function installCover(card, urls, title) {
        const cover = card.querySelector(".blog-search-card-cover");
        if (!cover || !urls.length) {
            resetCover(card);
            return false;
        }
        for (let index = 0; index < urls.length; index += 1) {
            const img = await loadCover(urls[index], index < urls.length - 1);
            if (!img) continue;
            markCoverReady(card, cover, img, title);
            return true;
        }
        resetCover(card);
        return false;
    }

    async function installLocalCover(card, urls, title) {
        const cover = card.querySelector(".blog-search-card-cover");
        if (!cover || !urls.length) return false;
        for (let index = 0; index < urls.length; index += 1) {
            const img = createCoverImage(urls[index]);
            markCoverReady(card, cover, img, title);
            if (await waitForCover(img, index < urls.length - 1)) return true;
            resetCover(card);
        }
        return false;
    }

    async function hydrateCard(card, options) {
        const allowRemote = !options || options.allowRemote !== false;
        const query = card.dataset.searchQuery || "";
        const title = card.dataset.searchTitle || "";
        const meta = card.dataset.searchMeta || "";
        const localUrls = cardCoverUrls(card);
        if (localUrls.length) {
            const installedLocalCover = await installLocalCover(card, localUrls, title);
            if (installedLocalCover || !allowRemote) return;
        }
        if (!allowRemote) return;
        if (!query) return;
        try {
            let items = await fetchBooks(query, meta);
            let book = bestBookWithCover(items, title, meta) || bestBook(items, title, meta);
            let urls = coverCandidateUrls(book);
            if (!urls.length && title && title !== query) {
                items = await fetchBooks(title, meta);
                book = bestBookWithCover(items, title, meta) || bestBook(items, title, meta);
                urls = coverCandidateUrls(book);
            }
            await installCover(card, urls, title);
        } catch (error) {
            // Blog content remains usable as a text search card if live cover hydration fails.
            resetCover(card);
        }
    }

    function start() {
        const remoteCards = cards.filter(card => card.dataset.searchQuery).slice(0, MAX_HYDRATED_CARDS);
        const remoteCardSet = new Set(remoteCards);
        cards.forEach((card) => {
            const localUrls = cardCoverUrls(card);
            if (!localUrls.length && !remoteCardSet.has(card)) return;
            const remoteIndex = remoteCards.indexOf(card);
            const delay = remoteIndex >= 0 ? remoteIndex * 120 : 0;
            window.setTimeout(() => hydrateCard(card, { allowRemote: remoteCardSet.has(card) }), delay);
        });
    }

    if ("requestIdleCallback" in window) {
        window.requestIdleCallback(start, { timeout: 1200 });
    } else {
        window.setTimeout(start, 300);
    }
})();
