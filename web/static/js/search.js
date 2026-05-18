const PAGE_SIZE = 20;
const SEARCH_PARAMS = new URLSearchParams(window.location.search);
const SEARCH_API_ENDPOINT = "/api/live_search";
const PROVIDER_LABELS = {
    "교보": "교보",
    "교보문고": "교보",
    "yes24": "YES24",
    "YES24": "YES24",
    "Bookcube": "기타",
    "북큐브": "기타",
    "FxLibrary": "기타",
    "알라딘": "알라딘",
    "알라딘커뮤니케이션": "알라딘",
    "인터파크": "인터파크",
    "오픈OPMS": "오픈OPMS",
    "Y2Books": "Y2Books",
    "ECO": "ECO",
    "기타": "기타",
    "기타 도서관": "기타",
};

const PROVIDER_LOGOS = {};
const MSG_NO_RESULTS = "검색 결과가 없습니다.";
const MSG_ERROR = "검색 중 오류가 발생했습니다.";
const MSG_ERROR_PREFIX = "오류: ";
const CARD_SUMMARY_HYDRATE_LIMIT = 5;

let currentResults = [];
let filteredResults = [];
let renderIndex = 0;
let totalCount = 0;
let currentQueryText = "";
let refineQueryText = "";
let loadMoreInFlight = false;
let currentFilters = { providers: [], libraries: [] };
let selectedProviders = new Set();
let selectedLibraries = new Set();
let selectedField = "title_author"; // search field: title+author
let tempSelectedProviders = new Set();
let tempSelectedLibraries = new Set();
let tempSelectedField = "title_author";
const summaryHydrateStarted = new Set();
const filterBar = document.querySelector(".filter-bar");
if (filterBar) filterBar.style.display = "none"; // legacy filter bar hidden
const filterSummary = document.getElementById("filter-summary");
const filterSummaryText = document.getElementById("filter-summary-text");
const searchPageEl = document.querySelector(".search-page");
const searchEmptyState = document.getElementById("search-empty-state");

function _isValidSearchField(value) {
    return value === "title_author" || value === "title" || value === "author" || value === "publisher";
}

function showResultsMessage(text, kind) {
    const resultsDiv = document.getElementById("results");
    if (!resultsDiv) return;
    setSearchEmpty(false);
    resultsDiv.innerHTML = "";
    const el = document.createElement("div");
    el.className = `card result-message ${kind}`;
    el.innerText = text || "";
    resultsDiv.appendChild(el);
}

function providerLabel(raw) {
    if (!raw) return "기타";
    const mapped = PROVIDER_LABELS[raw];
    if (mapped === "교보" || mapped === "YES24") return mapped;
    const value = String(raw).trim().toLowerCase();
    if (value.includes("교보") || value.includes("kyobo")) return "교보";
    if (value.includes("yes24")) return "YES24";
    return "기타";
}

function setSearchEmpty(visible) {
    if (!searchEmptyState) return;
    searchEmptyState.hidden = !visible;
}

function escapeAttr(value) {
    return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll('"', "&quot;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

function escapeHtml(value) {
    return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function liveDetailUrlForBook(book) {
    if (book.live_detail_url) return book.live_detail_url;
    if (book.book_id) return "";
    const title = String(book.title || "").trim();
    if (!title) return "";
    const params = new URLSearchParams();
    params.set("title", title);
    params.set("author", String(book.author || "").trim());
    params.set("publisher", String(book.publisher || "").trim());
    return `/live_book?${params.toString()}`;
}

function extractLibraries(book) {
    if (Array.isArray(book.libraries)) return book.libraries;
    const libField = book.library;
    if (!libField) return [];
    if (typeof libField === "object") {
        const arr = [];
        Object.values(libField).forEach(v => {
            if (Array.isArray(v)) {
                v.forEach(name => arr.push({ short: name, name, homepage_url: LIB_URLS[name] || "#" }));
            }
        });
        return arr;
    }
    return [{ short: String(libField), name: String(libField), homepage_url: LIB_URLS[libField] || "#" }];
}

function buildFilters(results, filters) {
    const providerSet = new Set();
    const libSet = new Set();
    if (filters && Array.isArray(filters.providers)) {
        filters.providers.forEach(p => providerSet.add(providerLabel(p)));
    } else {
        results.forEach(r => {
            if (r.provider) providerSet.add(providerLabel(r.provider));
        });
    }
    if (filters && Array.isArray(filters.libraries)) {
        filters.libraries.forEach(l => libSet.add(l));
    } else {
        results.forEach(r => {
            extractLibraries(r).forEach(l => libSet.add(l.short || l.name));
        });
    }
    currentFilters = {
        providers: [...providerSet].sort(),
        libraries: [...libSet].sort(),
    };
}

function renderFilterList(containerId, items, type) {
    const box = document.getElementById(containerId);
    if (!box) return;
    box.innerHTML = items.map(val => `
        <label>
            <input type="checkbox" value="${val}" data-type="${type}" />
            <span>${val}</span>
        </label>
    `).join("");
    box.querySelectorAll("input").forEach(input => {
        input.addEventListener("change", (e) => {
            const value = e.target.value;
            if (type === "provider") {
                if (e.target.checked) selectedProviders.add(value);
                else selectedProviders.delete(value);
            } else {
                if (e.target.checked) selectedLibraries.add(value);
                else selectedLibraries.delete(value);
            }
        });
    });
}

function resetFilters() {
    selectedProviders.clear();
    selectedLibraries.clear();
    document.querySelectorAll("#platform-filters input, #library-filters input").forEach(i => i.checked = false);
    applyFilters();
}

function applyFilters(reset = true) {
    filteredResults = currentResults.slice();
    if (searchPageEl) {
        searchPageEl.classList.toggle("has-results", filteredResults.length > 0);
    }
    if (reset) {
        renderIndex = 0;
        document.getElementById('results').innerHTML = "";
    }
    const countText = totalCount ? totalCount.toLocaleString() : filteredResults.length.toLocaleString();
    const prefix = currentQueryText ? `'${currentQueryText}'` : "";
    const refineLabel = refineQueryText ? ` + '${refineQueryText}'` : "";
    const label = prefix ? `${prefix}${refineLabel} ` : "";
    document.getElementById('status').innerText = `${label}검색 결과 ${countText}권`;
    updateFilterSummary();

    const loadMoreBtn = document.getElementById('load-more');
    if (filteredResults.length === 0) {
        if (loadMoreBtn) loadMoreBtn.style.display = "none";
        showResultsMessage(MSG_NO_RESULTS, "empty");
        return;
    }

    renderMore();
}

function fetchSearch(query, refine) {
    const statusDiv = document.getElementById('status');
    const resultsDiv = document.getElementById('results');
    const loader = document.getElementById('loading-spinner');
    const loadMoreBtn = document.getElementById('load-more');
    setSearchEmpty(false);
    if (searchPageEl) searchPageEl.classList.remove("has-results");
    statusDiv.innerText = "";
    resultsDiv.innerHTML = "";
    loader.style.display = "block";
    loadMoreBtn.style.display = "none";
    renderIndex = 0;
    currentResults = [];
    filteredResults = [];
    totalCount = 0;
    summaryHydrateStarted.clear();
    const params = new URLSearchParams();
    params.set("query", query);
    params.set("field", selectedField);
    params.set("limit", PAGE_SIZE.toString());
    params.set("offset", "0");
    if (refine) params.set("refine", refine);
    if (selectedProviders.size > 0) {
        params.set("providers", [...selectedProviders].join(","));
    }
    if (selectedLibraries.size > 0) {
        params.set("libraries", [...selectedLibraries].join(","));
    }
    fetch(`${SEARCH_API_ENDPOINT}?${params.toString()}`)
        .then(res => res.json())
        .then(data => {
            loader.style.display = "none";
            if (data.error) {
                showResultsMessage(MSG_ERROR_PREFIX + data.error, "error");
                return;
            }
            const items = Array.isArray(data.items) ? data.items : [];
            const totalValue = Number(data.total);
            totalCount = Number.isFinite(totalValue) ? totalValue : 0;
            if (items.length === 0) {
                statusDiv.innerText = `'${query}' 검색 결과 0권`;
                return;
            }
            currentResults = items;
            buildFilters(items, data.filters || null);
            applyFilters();
            if (loadMoreBtn) loadMoreBtn.onclick = loadMoreFromServer;
            if (filterBar) filterBar.style.display = "flex";
        })
        .catch(err => {
            loader.style.display = "none";
            showResultsMessage(MSG_ERROR, "error");
            console.error(err);
        });
}

function search() {
    const query = document.getElementById('query').value.trim();
    if (!query) return alert("검색어를 입력해주세요.");
    currentQueryText = query;
    refineQueryText = "";
    fetchSearch(query, "");
}

function uniqueLibraries(book) {
    const seen = new Set();
    const libs = [];
    extractLibraries(book).forEach(l => {
        const key = l.code || l.short || l.name;
        if (seen.has(key)) return;
        seen.add(key);
        libs.push(l);
    });
    return libs;
}

function renderMore() {
    const resultsDiv = document.getElementById('results');
    const loadMoreBtn = document.getElementById('load-more');
    const slice = filteredResults.slice(renderIndex, renderIndex + PAGE_SIZE);
    if (slice.length === 0) {
        if (loadMoreBtn) {
            setLoadMoreLoading(false);
            loadMoreBtn.style.display = "none";
        }
        return;
    }

    slice.forEach(book => {
        const bookId = book.book_id || "";
        const liveDetailUrl = liveDetailUrlForBook(book);
        const title = String(book.title || "");
        const author = String(book.author || "");
        const publisher = String(book.publisher || "");
        const ariaLabel = `${title || "도서"} 상세로 이동`;
        const imgHtml = book.image_url
            ? `<img src="${book.image_url}" loading="lazy" onerror="this.onerror=null;this.parentElement.innerHTML='<div class=\'no-img\'>이미지 없음</div>'">`
            : `<div class="no-img">이미지 없음</div>`;

    const html = `
        <div class="card js-book-card" role="link" tabindex="0" aria-label="${escapeAttr(ariaLabel)}" ${bookId ? `data-book-id="${bookId}"` : ""} ${liveDetailUrl ? `data-live-detail-url="${escapeAttr(liveDetailUrl)}"` : ""} ${book.summary_url ? `data-summary-url="${escapeAttr(book.summary_url)}"` : ""}>
            <div class="thumb">${imgHtml}</div>
            <div class="info">
                <h3 class="title" title="${escapeAttr(title)}">${escapeHtml(title)}</h3>
                <div class="meta">
                    <div class="meta-author">${escapeHtml(author)}</div>
                    ${publisher ? `<div class="meta-publisher">${escapeHtml(publisher)}</div>` : ""}
                </div>
            </div>
            <span class="result-chevron" aria-hidden="true">
                <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M9 18l6-6-6-6"></path>
                </svg>
            </span>
        </div>
    `;
        resultsDiv.insertAdjacentHTML('beforeend', html);
    });
    hydrateSearchCardSummaries();
    renderIndex += slice.length;
    const loaded = currentResults.length;
    const canLoadMore = totalCount === 0 ? renderIndex < filteredResults.length : loaded < totalCount;
    loadMoreBtn.style.display = canLoadMore ? "block" : "none";
    if (!canLoadMore) setLoadMoreLoading(false);
}

function hydrateSearchCardSummaries() {
    const cards = Array.from(document.querySelectorAll(".js-book-card[data-summary-url]"))
        .filter(card => !summaryHydrateStarted.has(card.dataset.summaryUrl))
        .slice(0, CARD_SUMMARY_HYDRATE_LIMIT);

    cards.forEach(card => {
        const summaryUrl = card.dataset.summaryUrl;
        if (!summaryUrl) return;
        summaryHydrateStarted.add(summaryUrl);
        fetch(summaryUrl)
            .then(res => res.ok ? res.json() : null)
            .then(data => {
                if (!data) return;
                if (data.live_detail_url) {
                    card.dataset.liveDetailUrl = data.live_detail_url;
                }
                card.removeAttribute("data-summary-url");
            })
            .catch(err => console.error(err));
    });
}

function setLoadMoreLoading(isLoading) {
    const loadMoreBtn = document.getElementById('load-more');
    if (!loadMoreBtn) return;
    if (!loadMoreBtn.dataset.label) {
        loadMoreBtn.dataset.label = loadMoreBtn.textContent.trim();
    }
    if (isLoading) {
        loadMoreBtn.classList.add("is-loading");
        loadMoreBtn.disabled = true;
        loadMoreBtn.innerHTML = '<span class="load-more-spinner" aria-hidden="true"></span><span class="load-more-text">불러오는 중...</span>';
    } else {
        loadMoreBtn.classList.remove("is-loading");
        loadMoreBtn.disabled = false;
        loadMoreBtn.textContent = loadMoreBtn.dataset.label || "더 보기";
    }
}

function loadMoreFromServer() {
    if (!currentQueryText) return;
    if (loadMoreInFlight) return;
    loadMoreInFlight = true;
    setLoadMoreLoading(true);
    const params = new URLSearchParams();
    params.set("query", currentQueryText);
    params.set("field", selectedField);
    params.set("limit", PAGE_SIZE.toString());
    params.set("offset", String(currentResults.length));
    if (refineQueryText) params.set("refine", refineQueryText);
    if (selectedProviders.size > 0) {
        params.set("providers", [...selectedProviders].join(","));
    }
    if (selectedLibraries.size > 0) {
        params.set("libraries", [...selectedLibraries].join(","));
    }
    fetch(`${SEARCH_API_ENDPOINT}?${params.toString()}`)
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                showResultsMessage(MSG_ERROR_PREFIX + data.error, "error");
                setLoadMoreLoading(false);
                loadMoreInFlight = false;
                return;
            }
            const items = Array.isArray(data.items) ? data.items : [];
            if (items.length === 0) {
                const loadMoreBtn = document.getElementById('load-more');
                if (loadMoreBtn) loadMoreBtn.style.display = "none";
                setLoadMoreLoading(false);
                loadMoreInFlight = false;
                return;
            }
            const totalValue = Number(data.total);
            if (Number.isFinite(totalValue)) {
                totalCount = totalValue;
            }
            currentResults = currentResults.concat(items);
            buildFilters(currentResults, data.filters || null);
            applyFilters(false);
            setLoadMoreLoading(false);
            loadMoreInFlight = false;
        })
        .catch(err => {
            showResultsMessage(MSG_ERROR, "error");
            console.error(err);
            setLoadMoreLoading(false);
            loadMoreInFlight = false;
        });
}

document.addEventListener("click", (event) => {
    const card = event.target.closest(".js-book-card");
    if (!card) return;
    const liveUrl = card.getAttribute("data-live-detail-url");
    if (liveUrl) {
        window.location.href = liveUrl;
        return;
    }
    const id = card.getAttribute("data-book-id");
    if (!id) return;
    window.location.href = `/book/${id}`;
});

document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".js-book-card");
    if (!card) return;
    event.preventDefault();
    card.click();
});

document.addEventListener("DOMContentLoaded", () => {
    const params = new URLSearchParams(window.location.search);
    const q = (params.get("q") || "").trim();
    if (!q) return;

    const field = (params.get("field") || "").trim();
    if (_isValidSearchField(field)) selectedField = field;

    const input = document.getElementById("query");
    if (input) input.value = q;
    search();
});

const refineToggle = document.getElementById("refine-toggle");
const searchTopInput = document.getElementById("query");
const searchTopBtn = document.querySelector(".search-top-btn");

function isRefineMode() {
    return !!(refineToggle && refineToggle.checked);
}

function syncRefineUI() {
    if (!searchTopInput) return;
    if (isRefineMode()) {
        searchTopInput.placeholder = "결과 내 재검색";
        if (searchTopBtn) searchTopBtn.textContent = "재검색";
        if (currentQueryText && searchTopInput.value.trim() === currentQueryText) {
            searchTopInput.value = refineQueryText || "";
        }
        searchTopInput.focus();
    } else {
        searchTopInput.placeholder = "검색어를 입력하세요";
        if (searchTopBtn) searchTopBtn.textContent = "검색";
        if (currentQueryText) searchTopInput.value = currentQueryText;
        if (currentQueryText && refineQueryText) {
            refineQueryText = "";
            fetchSearch(currentQueryText, "");
        }
    }
}

function runTopSearch() {
    if (!searchTopInput) return;
    const value = searchTopInput.value.trim();
    if (isRefineMode()) {
        if (!currentQueryText) {
            alert("먼저 검색어를 입력해 검색을 시작해주세요.");
            return;
        }
        if (!value) {
            alert("결과 내 재검색어를 입력해주세요.");
            return;
        }
        refineQueryText = value;
        fetchSearch(currentQueryText, refineQueryText);
        return;
    }
    search();
}

if (refineToggle) {
    refineToggle.addEventListener("change", syncRefineUI);
    syncRefineUI();
}

function toggleFilters() {
}

// filter sheet
let currentSheet = null; // field, provider, library

const SHEET_LABELS = {
    field: "검색 대상",
    provider: "공급사",
    library: "도서관",
};

function openFilterSheet(type) {
    currentSheet = type || "field";
    tempSelectedProviders = new Set(selectedProviders);
    tempSelectedLibraries = new Set(selectedLibraries);
    tempSelectedField = selectedField;
    const titleEl = document.getElementById("sheet-title");
    const labelEl = document.getElementById("sheet-label");
    const optsEl = document.getElementById("sheet-options");
    titleEl.textContent = "필터";
    labelEl.textContent = SHEET_LABELS[currentSheet] || "";
    optsEl.innerHTML = "";

    document.querySelectorAll(".sheet-tab").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.type === currentSheet);
    });

    renderSheetOptions(currentSheet);

    // temp selection applies only on confirm
    document.getElementById("sheet-overlay").classList.add("show");
    document.getElementById("filter-sheet").classList.add("show");
}

function closeSheet() {
    document.getElementById("sheet-overlay").classList.remove("show");
    document.getElementById("filter-sheet").classList.remove("show");
    currentSheet = null;
}

function applySheet() {
    if (!currentSheet) return closeSheet();
    selectedField = tempSelectedField || "title_author";
    selectedProviders = new Set(tempSelectedProviders);
    selectedLibraries = new Set(tempSelectedLibraries);
    closeSheet();
    if (currentQueryText) {
        fetchSearch(currentQueryText, refineQueryText);
    } else {
        applyFilters();
    }
}

function renderSheetOptions(type) {
    const labelEl = document.getElementById("sheet-label");
    const optsEl = document.getElementById("sheet-options");
    labelEl.textContent = SHEET_LABELS[type] || "";
    optsEl.innerHTML = "";
    if (type === "field") {
        const options = [
            { value: "title_author", label: "제목+저자(기본)" },
            { value: "title", label: "제목" },
            { value: "author", label: "저자" },
            { value: "publisher", label: "출판사" },
        ];
        options.forEach(opt => {
            optsEl.insertAdjacentHTML("beforeend", `
                <label><input type="radio" name="sheet-field" data-type="field" value="${opt.value}" ${tempSelectedField===opt.value?'checked':''} />
                ${opt.label}</label>
            `);
        });
    } else if (type === "provider") {
        const items = currentFilters.providers.length
            ? currentFilters.providers
            : Array.from(new Set(currentResults.map(r => r.provider).filter(Boolean).map(providerLabel))).sort();
        items.forEach(val => {
            const checked = tempSelectedProviders.has(val) ? "checked" : "";
            optsEl.insertAdjacentHTML("beforeend", `
                <label><input type="checkbox" data-type="provider" value="${val}" ${checked} /> ${val}</label>
            `);
        });
    } else if (type === "library") {
        const items = currentFilters.libraries.length
            ? currentFilters.libraries
            : Array.from(new Set(currentResults.flatMap(r => extractLibraries(r).map(l => l.short || l.name)))).sort();
        items.forEach(val => {
            const checked = tempSelectedLibraries.has(val) ? "checked" : "";
            optsEl.insertAdjacentHTML("beforeend", `
                <label><input type="checkbox" data-type="library" value="${val}" ${checked} /> ${val}</label>
            `);
        });
    }
    optsEl.querySelectorAll("input").forEach(input => {
        input.addEventListener("change", (e) => {
            const value = e.target.value;
            const t = e.target.dataset.type;
            if (t === "field") {
                tempSelectedField = value;
            } else if (t === "provider") {
                if (e.target.checked) tempSelectedProviders.add(value);
                else tempSelectedProviders.delete(value);
            } else if (t === "library") {
                if (e.target.checked) tempSelectedLibraries.add(value);
                else tempSelectedLibraries.delete(value);
            }
        });
    });
}

const queryInput = document.getElementById('query');
const searchTopForm = document.getElementById('search-top-form');
if (searchTopForm) {
    searchTopForm.addEventListener('submit', (e) => {
        e.preventDefault();
        runTopSearch();
    });
}

document.querySelectorAll(".sheet-tab").forEach(btn => {
    btn.addEventListener("click", () => {
        currentSheet = btn.dataset.type;
        document.querySelectorAll(".sheet-tab").forEach(b => {
            b.classList.toggle("active", b.dataset.type === currentSheet);
        });
        renderSheetOptions(currentSheet);
    });
});

function updateFilterSummary() {
    if (!filterSummary || !filterSummaryText) return;
    const titleEl = filterSummary.querySelector(".filter-title");
    if (titleEl) titleEl.remove();
    filterSummaryText.innerText = "필터";
    filterSummary.style.display = "flex";
}


