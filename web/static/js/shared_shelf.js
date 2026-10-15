const sharedShelf = window.__SHARED_SHELF__ || {};
const sharedItems = document.getElementById("shared-shelf-items");
const sharedCopyList = document.getElementById("shared-copy-list");
const sharedCopyStatus = document.getElementById("shared-copy-status");
const shelf = window.SoulibShelf;

function cleanText(value) {
    return String(value || "").trim();
}

function escapeHtml(value) {
    return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
    return escapeHtml(value).replaceAll("`", "&#96;");
}

function coverHtml(book, className) {
    const imageUrl = cleanText(book.image_url);
    if (!imageUrl) return `<div class="${className} shelf-no-cover">표지 없음</div>`;
    return `
        <div class="${className}">
            <img src="${escapeAttr(imageUrl)}" alt="" loading="lazy" onerror="this.remove(); this.parentElement.classList.add('shelf-no-cover'); this.parentElement.textContent='표지 없음';">
        </div>
    `;
}

function renderBooks() {
    const books = Array.isArray(sharedShelf.books) ? sharedShelf.books : [];
    if (!sharedItems) return;
    if (!books.length) {
        sharedItems.innerHTML = `<div class="shelf-empty">표시할 책이 없습니다.</div>`;
        return;
    }
    sharedItems.innerHTML = books.map(book => {
        const title = cleanText(book.title) || "제목 없음";
        return `
            <article class="shelf-item">
                <a class="shelf-item-link" href="${escapeAttr(shelf.detailUrl(book))}" aria-label="${escapeAttr(`${title} 상세로 이동`)}">
                    ${coverHtml(book, "shelf-item-cover")}
                    <div class="shelf-book-main">
                        <h3 title="${escapeAttr(title)}">${escapeHtml(title)}</h3>
                        <div class="shelf-book-meta">
                            ${book.author ? `<span class="shelf-book-author">${escapeHtml(book.author)}</span>` : ""}
                            ${book.publisher ? `<span class="shelf-book-publisher">${escapeHtml(book.publisher)}</span>` : ""}
                        </div>
                    </div>
                </a>
            </article>
        `;
    }).join("");
}

function copySharedListToShelf() {
    const books = Array.isArray(sharedShelf.books) ? sharedShelf.books : [];
    if (!books.length) return;
    const list = shelf.createList(sharedShelf.title || "공유 서재", sharedShelf.description || "");
    if (!list) return;
    books.forEach(book => shelf.add(book, list.id));
    if (sharedCopyStatus) {
        sharedCopyStatus.textContent = `'${list.name}' 서재에 복사했습니다.`;
    }
}

sharedCopyList?.addEventListener("click", copySharedListToShelf);
renderBooks();
