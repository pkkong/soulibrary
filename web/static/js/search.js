const PAGE_SIZE = 40;
const PROVIDER_LABELS = {
    "교보": "교보",
    "교보문고": "교보",
    "yes24": "YES24",
    "YES24": "YES24",
    "알라딘": "알라딘",
    "알라딘커뮤니케이션": "알라딘",
    "인터파크": "인터파크",
    "웅진OPMS": "웅진OPMS",
    "Y2Books": "Y2Books",
    "ECO": "ECO",
};

const PROVIDER_LOGOS = {};

let currentResults = [];
let filteredResults = [];
let renderIndex = 0;
let totalCount = 0;
let currentQueryText = "";
let refineQueryText = "";
let selectedProviders = new Set();
let selectedLibraries = new Set();
let selectedField = "title_author"; // 기본: 제목+저자
let tempSelectedProviders = new Set();
let tempSelectedLibraries = new Set();
let tempSelectedField = "title_author";
const filterBar = document.querySelector(".filter-bar");
if (filterBar) filterBar.style.display = "none"; // 초기에는 숨김
const filterSummary = document.getElementById("filter-summary");
const filterSummaryText = document.getElementById("filter-summary-text");
if (filterSummary) filterSummary.style.display = "none";

function _isValidSearchField(value) {
    return value === "title_author" || value === "title" || value === "author" || value === "publisher";
}

function showResultsMessage(text, kind = "empty") {
    const resultsDiv = document.getElementById('results');
    if (!resultsDiv) return;
    resultsDiv.innerHTML = "";
    const el = document.createElement("div");
    el.className = `card result-message ${kind}`;
    el.innerText = text || "";
    resultsDiv.appendChild(el);
}

function providerLabel(raw) {
    if (!raw) return "기타";
    return PROVIDER_LABELS[raw] || raw;
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

function buildFilters(results) {
    const providerSet = new Set();
    const libSet = new Set();
    results.forEach(r => {
        if (r.provider) providerSet.add(providerLabel(r.provider));
        extractLibraries(r).forEach(l => libSet.add(l.short || l.name));
    });
    renderFilterList("platform-filters", [...providerSet].sort(), "provider");
    renderFilterList("library-filters", [...libSet].sort(), "library");
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

function applyFilters() {
    filteredResults = currentResults.filter(r => {
        if (refineQueryText) {
            const hay = `${r.title || ""} ${r.author || ""} ${r.publisher || ""}`.toLowerCase();
            if (!hay.includes(refineQueryText)) return false;
        }
        const providers = r.provider ? [providerLabel(r.provider)] : [];
        const libs = extractLibraries(r).map(l => l.short || l.name);
        const provOk = selectedProviders.size === 0 || providers.some(p => selectedProviders.has(p));
        const libOk = selectedLibraries.size === 0 || libs.some(l => selectedLibraries.has(l));
        return provOk && libOk;
    });
    filteredResults.sort((a, b) => {
        const diff = getLibraryCount(b) - getLibraryCount(a);
        if (diff !== 0) return diff;
        const at = (a.title || "").toString();
        const bt = (b.title || "").toString();
        return at.localeCompare(bt, "ko");
    });
    renderIndex = 0;
    document.getElementById('results').innerHTML = "";
    const countText = totalCount ? totalCount.toLocaleString() : filteredResults.length.toLocaleString();
    const prefix = currentQueryText ? `'${currentQueryText}' ` : "";
    document.getElementById('status').innerText = `${prefix}검색 결과 ${countText}권`;
    updateFilterSummary();

    const loadMoreBtn = document.getElementById('load-more');
    if (filteredResults.length === 0) {
        if (loadMoreBtn) loadMoreBtn.style.display = "none";
        if (currentResults.length > 0) showResultsMessage("필터 결과가 없습니다.", "empty");
        return;
    }

    renderMore();
}

function search() {
    const query = document.getElementById('query').value.trim();
    if (!query) return alert("검색어를 입력해 주세요.");
    currentQueryText = query;
    const statusDiv = document.getElementById('status');
    const resultsDiv = document.getElementById('results');
    const loader = document.getElementById('loading-spinner');
    const loadMoreBtn = document.getElementById('load-more');
    statusDiv.innerText = "";
    resultsDiv.innerHTML = "";
    loader.style.display = "block";
    loadMoreBtn.style.display = "none";
    renderIndex = 0;
    currentResults = [];
    filteredResults = [];
    totalCount = 0;
    refineQueryText = "";
    const refineInput = document.getElementById("refine-query");
    if (refineInput) refineInput.value = "";
    const params = new URLSearchParams();
    params.set("query", query);
    params.set("field", selectedField);
    params.set("limit", PAGE_SIZE.toString());
    params.set("offset", "0");
    fetch(`/api/search?${params.toString()}`)
        .then(res => res.json())
        .then(data => {
            loader.style.display = "none";
            if (data.error) {
                showResultsMessage("오류: " + data.error, "error");
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
            buildFilters(items);
            applyFilters();
            if (loadMoreBtn) loadMoreBtn.onclick = loadMoreFromServer;
            if (filterBar) filterBar.style.display = "flex"; // 결과가 있을 때만 노출
        })
        .catch(err => {
            loader.style.display = "none";
            showResultsMessage("검색 중 오류가 발생했습니다.", "error");
            console.error(err);
        });
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

const SPECIAL_LIBRARY_CODES = new Set(["seoul", "sen_owned", "sen_subs"]);
const LIB_COUNT_CACHE = new WeakMap();

function getLibraryCount(book) {
    if (!book || typeof book !== "object") return 0;
    const cached = LIB_COUNT_CACHE.get(book);
    if (cached !== undefined) return cached;
    const count = uniqueLibraries(book).length;
    LIB_COUNT_CACHE.set(book, count);
    return count;
}

function groupLibraries(libs) {
    const groups = { kyobo: [], yes24: [], other: [], special: [] };
    libs.forEach(lib => {
        const code = lib.code || "";
        if (SPECIAL_LIBRARY_CODES.has(code)) {
            groups.special.push(lib);
            return;
        }
        const platform = lib.platform_code || "";
        if (platform === "YES24") groups.yes24.push(lib);
        else if (platform === "Kyobo" || platform === "Kyobo_New") groups.kyobo.push(lib);
        else groups.other.push(lib);
    });
    return groups;
}

function renderLibraryBadges(libs) {
    return libs.map(lib => {
        const name = lib.short || lib.name;
        const url = lib.homepage_url || LIB_URLS[name] || "#";
        return `<a class="badge" href="${url}" target="_blank" rel="noopener noreferrer">${name}</a>`;
    }).join("");
}

function renderMore() {
    const resultsDiv = document.getElementById('results');
    const loadMoreBtn = document.getElementById('load-more');
    const slice = filteredResults.slice(renderIndex, renderIndex + PAGE_SIZE);
    if (slice.length === 0) { loadMoreBtn.style.display = "none"; return; }

    slice.forEach(book => {
        const bookId = book.book_id || "";
        const imgHtml = book.image_url
            ? `<img src="${book.image_url}" loading="lazy" onerror="this.onerror=null;this.parentElement.innerHTML='<div class=\\'no-img\\'>이미지 없음</div>'">`
            : `<div class="no-img">이미지 없음</div>`;

    const libs = uniqueLibraries(book);
    const groups = groupLibraries(libs);
    const kyoboCount = groups.kyobo.length;
    const yes24Count = groups.yes24.length;
    const otherCount = groups.other.length + groups.special.length;
    const totalLibs = kyoboCount + yes24Count + otherCount;
    const kyoboOn = kyoboCount > 0;
    const yes24On = yes24Count > 0;
    const otherOn = otherCount > 0;
    const libBadges = `
        <div class="supply-summary">
            <div class="prov-grid">
                <div class="prov-item ${kyoboOn ? "" : "is-off"}">
                    <div class="prov-chip kyobo"><img src="/static/img/kyobo.webp" alt="교보" loading="lazy"></div>
                    <div class="prov-count">${kyoboCount || "-"}</div>
                </div>
                <div class="prov-item ${yes24On ? "" : "is-off"}">
                    <div class="prov-chip yes24"><img src="/static/img/yes24.webp" alt="YES24" loading="lazy"></div>
                    <div class="prov-count">${yes24Count || "-"}</div>
                </div>
                <div class="prov-item ${otherOn ? "" : "is-off"}">
                    <div class="prov-chip other">기타</div>
                    <div class="prov-count">${otherCount || "-"}</div>
                </div>
            </div>
        </div>
    `;

    const html = `
        <div class="card js-book-card" ${bookId ? `data-book-id="${bookId}"` : ""}>
            <div class="thumb">${imgHtml}</div>
            <div class="info">
                <h3 class="title" title="${book.title}">${book.title}</h3>
                <div class="meta">
                    <div class="meta-author">${book.author || ""}</div>
                    ${book.publisher ? `<div class="meta-publisher">${book.publisher}</div>` : ""}
                </div>
                <div class="badges">${libBadges}</div>
            </div>
        </div>
    `;
        resultsDiv.insertAdjacentHTML('beforeend', html);
    });
    renderIndex += slice.length;
    const loaded = currentResults.length;
    const canLoadMore = totalCount === 0 ? renderIndex < filteredResults.length : loaded < totalCount;
    loadMoreBtn.style.display = canLoadMore ? "block" : "none";
}

function loadMoreFromServer() {
    if (!currentQueryText) return;
    const loader = document.getElementById('loading-spinner');
    const params = new URLSearchParams();
    params.set("query", currentQueryText);
    params.set("field", selectedField);
    params.set("limit", PAGE_SIZE.toString());
    params.set("offset", String(currentResults.length));
    loader.style.display = "block";
    fetch(`/api/search?${params.toString()}`)
        .then(res => res.json())
        .then(data => {
            loader.style.display = "none";
            if (data.error) {
                showResultsMessage("오류: " + data.error, "error");
                return;
            }
            const items = Array.isArray(data.items) ? data.items : [];
            if (items.length === 0) {
                const loadMoreBtn = document.getElementById('load-more');
                if (loadMoreBtn) loadMoreBtn.style.display = "none";
                return;
            }
            const totalValue = Number(data.total);
            if (Number.isFinite(totalValue)) {
                totalCount = totalValue;
            }
            currentResults = currentResults.concat(items);
            buildFilters(currentResults);
            applyFilters();
        })
        .catch(err => {
            loader.style.display = "none";
            showResultsMessage("검색 중 오류가 발생했습니다.", "error");
            console.error(err);
        });
}

document.addEventListener("click", (event) => {
    const card = event.target.closest(".js-book-card");
    if (!card) return;
    const id = card.getAttribute("data-book-id");
    if (!id) return;
    window.location.href = `/book/${id}`;
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

const refineInput = document.getElementById("refine-query");
const refineApply = document.getElementById("refine-apply");
function applyRefineQuery() {
    if (!refineInput) return;
    refineQueryText = (refineInput.value || "").trim().toLowerCase();
    applyFilters();
}
if (refineApply) {
    refineApply.addEventListener("click", applyRefineQuery);
}
if (refineInput) {
    refineInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") applyRefineQuery();
    });
}

function toggleFilters() {
}

// 필터 시트
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

    // 다중 선택: 기존 상태 유지, applySheet에서만 반영
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
    applyFilters();
}

function renderSheetOptions(type) {
    const labelEl = document.getElementById("sheet-label");
    const optsEl = document.getElementById("sheet-options");
    labelEl.textContent = SHEET_LABELS[type] || "";
    optsEl.innerHTML = "";
    if (type === "field") {
        const options = [
            { value: "title_author", label: "제목+저자 (기본)" },
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
        const items = Array.from(new Set(currentResults.map(r => r.provider).filter(Boolean).map(providerLabel))).sort();
        items.forEach(val => {
            const checked = tempSelectedProviders.has(val) ? "checked" : "";
            optsEl.insertAdjacentHTML("beforeend", `
                <label><input type="checkbox" data-type="provider" value="${val}" ${checked} /> ${val}</label>
            `);
        });
    } else if (type === "library") {
        const items = Array.from(new Set(currentResults.flatMap(r => extractLibraries(r).map(l => l.short || l.name)))).sort();
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

document.getElementById('query').addEventListener('keypress', (e) => { if (e.key === 'Enter') search(); });

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
    // 요약은 단순히 "필터 ▾"만 표시
    filterSummaryText.innerText = "필터 ▾";
    filterSummary.style.display = "flex";
}
