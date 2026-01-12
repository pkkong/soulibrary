const PAGE_SIZE = 30;
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
        const providers = r.provider ? [providerLabel(r.provider)] : [];
        const libs = extractLibraries(r).map(l => l.short || l.name);
        const provOk = selectedProviders.size === 0 || providers.some(p => selectedProviders.has(p));
        const libOk = selectedLibraries.size === 0 || libs.some(l => selectedLibraries.has(l));
        return provOk && libOk;
    });
    renderIndex = 0;
    document.getElementById('results').innerHTML = "";
    renderMore();
    document.getElementById('status').innerText = `검색 결과 ${filteredResults.length}권`;
    updateFilterSummary();
}

function search() {
    const query = document.getElementById('query').value.trim();
    if (!query) return alert("검색어를 입력해 주세요.");
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
    const params = new URLSearchParams();
    params.set("query", query);
    params.set("field", selectedField);
    fetch(`/search?${params.toString()}`)
        .then(res => res.json())
        .then(data => {
            loader.style.display = "none";
            if (data.error) { statusDiv.innerText = "오류: " + data.error; return; }
            if (data.length === 0) { statusDiv.innerHTML = `<div style="padding:20px;">'${query}' 결과가 없습니다.</div>`; return; }
            currentResults = data;
            buildFilters(data);
            applyFilters();
            if (filterBar) filterBar.style.display = "flex"; // 결과가 있을 때만 노출
        })
        .catch(err => {
            loader.style.display = "none";
            statusDiv.innerText = "검색 중 오류가 발생했습니다.";
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
        const imgHtml = book.image_url
            ? `<img src="${book.image_url}" loading="lazy" onerror="this.onerror=null;this.parentElement.innerHTML='<div class=\\'no-img\\'>이미지 없음</div>'">`
            : `<div class="no-img">이미지 없음</div>`;

    const libs = uniqueLibraries(book);
    const groups = groupLibraries(libs);
    const groupLines = [];
    const providerLbl = providerLabel(book.provider);
    const onlyKyobo = groups.kyobo.length && !groups.yes24.length && !groups.other.length;
    const onlyYes = groups.yes24.length && !groups.kyobo.length && !groups.other.length;
    if (groups.kyobo.length) {
        groupLines.push(`<div class="lib-group"><span class="badge-label kyobo">교보</span>${renderLibraryBadges(groups.kyobo)}</div>`);
    }
    if (groups.yes24.length) {
        groupLines.push(`<div class="lib-group"><span class="badge-label yes24">YES24</span>${renderLibraryBadges(groups.yes24)}</div>`);
    }
    if (groups.other.length) {
        groupLines.push(`<div class="lib-group"><span class="badge-label other">기타</span>${renderLibraryBadges(groups.other)}</div>`);
    }
    if (groups.special.length) {
        groupLines.push(`<div class="lib-group"><span class="badge-label special">서울도서관·교육청</span>${renderLibraryBadges(groups.special)}</div>`);
    }
    const libBadges = groupLines.join("");

    const html = `
        <div class="card">
            <div class="thumb">${imgHtml}</div>
            <div class="info">
                <h3 class="title" title="${book.title}">${book.title}</h3>
                <div class="meta">${book.author || ""}${book.publisher ? ` | ${book.publisher}` : ""}</div>
                <div class="badges">${libBadges}</div>
            </div>
        </div>
    `;
        resultsDiv.insertAdjacentHTML('beforeend', html);
    });
    renderIndex += slice.length;
    loadMoreBtn.style.display = renderIndex < filteredResults.length ? "block" : "none";
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
