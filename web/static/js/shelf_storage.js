(function () {
    const STORAGE_KEY = "soulib.myShelf.v1";
    const DEFAULT_LIST_ID = "default";
    const DEFAULT_LIST_NAME = "기본 서재";
    const BACKUP_FORMAT = "soulib-shelf-backup";
    const BACKUP_MAX_BYTES = 5 * 1024 * 1024;
    const preparedRestores = new WeakMap();

    function cleanText(value) {
        return String(value || "").trim();
    }

    function normalizeKeyPart(value) {
        return cleanText(value).toLowerCase().replace(/[\s\[\]\(\){}<>.,/|\\\-_:;"'`~!?]/g, "");
    }

    function canonicalKeyFor(book) {
        const title = normalizeKeyPart(book && book.title);
        if (!title) return "";
        const author = normalizeKeyPart(book && book.author);
        const publisher = normalizeKeyPart(book && book.publisher);
        const secondary = author || publisher;
        return secondary ? `meta:${title}|${secondary}` : `meta:${title}`;
    }

    function nowIso() {
        return new Date().toISOString();
    }

    function uid() {
        if (window.crypto && typeof window.crypto.randomUUID === "function") {
            return window.crypto.randomUUID().slice(0, 13);
        }
        return `shelf-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    }

    function emptyState() {
        const now = nowIso();
        return {
            version: 2,
            lists: [
                {
                    id: DEFAULT_LIST_ID,
                    name: DEFAULT_LIST_NAME,
                    description: "",
                    created_at: now,
                    updated_at: now,
                    book_keys: [],
                },
            ],
            books: {},
        };
    }

    function normalizeList(list) {
        const id = cleanText(list && list.id) || uid();
        const now = nowIso();
        const keys = Array.isArray(list && list.book_keys) ? list.book_keys : [];
        return {
            id,
            name: cleanText(list && list.name) || DEFAULT_LIST_NAME,
            description: cleanText(list && list.description),
            created_at: cleanText(list && list.created_at) || now,
            updated_at: cleanText(list && list.updated_at) || now,
            book_keys: [...new Set(keys.map(cleanText).filter(Boolean))],
            ...(typeof list?.import_ref === "string" && /^[a-f0-9]{64}:.{1,160}$/.test(list.import_ref)
                ? {import_ref: list.import_ref} : {}),
        };
    }

    function migrateLegacyArray(raw) {
        const state = emptyState();
        const books = {};
        const keys = [];
        raw.forEach(book => {
            if (!book || !book.title) return;
            const item = toShelfBook(book);
            books[item.key] = item;
            keys.push(item.key);
        });
        state.books = books;
        state.lists[0].book_keys = [...new Set(keys)];
        return state;
    }

    function normalizeState(raw) {
        if (Array.isArray(raw)) return migrateLegacyArray(raw);
        if (!raw || typeof raw !== "object") return emptyState();
        if (raw.version !== 2 || !Array.isArray(raw.lists) || !raw.books || typeof raw.books !== "object") {
            return emptyState();
        }

        const state = {
            version: 2,
            lists: raw.lists.map(normalizeList),
            books: {},
        };
        const keyMap = new Map();
        Object.entries(raw.books).forEach(([key, book]) => {
            const item = toShelfBook({ ...book, key });
            if (item.title) {
                state.books[item.key] = item;
                keyMap.set(cleanText(key), item.key);
            }
        });
        if (!state.lists.length) state.lists = emptyState().lists;
        state.lists.forEach(list => {
            list.book_keys = [...new Set(list.book_keys.map(key => keyMap.get(key) || key).filter(Boolean))];
        });
        const knownKeys = new Set(Object.keys(state.books));
        state.lists.forEach(list => {
            list.book_keys = list.book_keys.filter(key => knownKeys.has(key));
        });
        pruneUnlistedBooks(state);
        return state;
    }

    function loadState() {
        try {
            return normalizeState(JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"));
        } catch (err) {
            console.error(err);
            return emptyState();
        }
    }

    function saveState(state) {
        const normalized = normalizeState(state);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
        return normalized;
    }

    function pruneUnlistedBooks(state) {
        const referenced = new Set();
        state.lists.forEach(list => {
            list.book_keys.forEach(key => referenced.add(key));
        });
        Object.keys(state.books).forEach(key => {
            if (!referenced.has(key)) delete state.books[key];
        });
    }

    function keyFor(book) {
        const canonicalKey = canonicalKeyFor(book);
        if (canonicalKey) return canonicalKey;
        const directKey = cleanText(book && book.key);
        if (directKey) return directKey;
        const liveKey = cleanText(book && book.live_detail_key);
        if (liveKey) return `live:${liveKey}`;
        const bookId = cleanText(book && book.book_id);
        if (bookId) return `book:${bookId}`;
        return "";
    }

    function detailUrl(book) {
        if (book && book.live_detail_url) return book.live_detail_url;
        if (book && book.book_id) return `/book/${encodeURIComponent(book.book_id)}`;
        const title = cleanText(book && book.title);
        if (!title) return "/search";
        const params = new URLSearchParams();
        params.set("title", title);
        const author = cleanText(book && book.author);
        const publisher = cleanText(book && book.publisher);
        const liveKey = cleanText(book && book.live_detail_key);
        if (author) params.set("author", author);
        if (publisher) params.set("publisher", publisher);
        if (liveKey) params.set("key", liveKey);
        return `/live_book?${params.toString()}`;
    }

    function countLabel(book) {
        const counts = (book && book.counts) || {};
        const total = Number(counts.total || 0);
        if (!Number.isFinite(total) || total <= 0) return "소장 정보 확인 필요";
        const parts = [];
        const kyobo = Number(counts.kyobo || 0);
        const yes24 = Number(counts.yes24 || 0);
        const other = Number(counts.other || 0);
        if (kyobo > 0) parts.push(`교보 ${kyobo}`);
        if (yes24 > 0) parts.push(`YES24 ${yes24}`);
        if (other > 0) parts.push(`기타 ${other}`);
        return `도서관 ${total}곳${parts.length ? ` · ${parts.join(" · ")}` : ""}`;
    }

    function normalizeCoverCandidates(book) {
        const urls = [];
        function addUrl(value) {
            const url = cleanText(value);
            if (!url || urls.includes(url)) return;
            if (!/^https?:\/\//i.test(url) && !url.startsWith("//")) return;
            urls.push(url.startsWith("//") ? `https:${url}` : url);
        }
        addUrl(book && book.image_url);
        const candidates = Array.isArray(book && book.image_candidates) ? book.image_candidates : [];
        candidates.forEach(candidate => {
            addUrl(typeof candidate === "string" ? candidate : candidate && (candidate.url || candidate.image_url));
        });
        return urls.slice(0, 8).map(url => ({ url }));
    }

    function toShelfBook(book) {
        const key = keyFor(book || {});
        return {
            key,
            title: cleanText(book && book.title),
            author: cleanText(book && book.author),
            publisher: cleanText(book && book.publisher),
            image_url: cleanText(book && book.image_url),
            image_candidates: normalizeCoverCandidates(book || {}),
            live_detail_key: cleanText(book && book.live_detail_key),
            live_detail_url: detailUrl(book || {}),
            book_id: (book && book.book_id) || null,
            counts: (book && book.counts) || {},
            added_at: cleanText(book && book.added_at) || nowIso(),
            updated_at: cleanText(book && book.updated_at) || nowIso(),
        };
    }

    function listAll() {
        return loadState().lists;
    }

    function getList(listId) {
        const state = loadState();
        return state.lists.find(list => list.id === listId) || state.lists[0];
    }

    function createList(name, description) {
        const state = loadState();
        const cleanName = cleanText(name);
        if (!cleanName) return null;
        const now = nowIso();
        const list = {
            id: uid(),
            name: cleanName.slice(0, 80),
            description: cleanText(description).slice(0, 200),
            created_at: now,
            updated_at: now,
            book_keys: [],
        };
        state.lists.push(list);
        saveState(state);
        emitChanged("create-list", { list });
        return list;
    }

    function renameList(listId, name) {
        const state = loadState();
        const list = state.lists.find(item => item.id === listId);
        const cleanName = cleanText(name);
        if (!list || !cleanName) return null;
        list.name = cleanName.slice(0, 80);
        list.updated_at = nowIso();
        saveState(state);
        emitChanged("rename-list", { list });
        return list;
    }

    function deleteList(listId) {
        const state = loadState();
        if (state.lists.length <= 1) return false;
        const idx = state.lists.findIndex(item => item.id === listId);
        if (idx < 0) return false;
        const [list] = state.lists.splice(idx, 1);
        pruneUnlistedBooks(state);
        saveState(state);
        emitChanged("delete-list", { list });
        return true;
    }

    function listsForBook(key) {
        const state = loadState();
        return state.lists.filter(list => list.book_keys.includes(key));
    }

    function has(key, listId) {
        const state = loadState();
        if (listId) {
            const list = state.lists.find(item => item.id === listId);
            return !!(list && list.book_keys.includes(key));
        }
        return state.lists.some(list => list.book_keys.includes(key));
    }

    function add(book, listId) {
        const state = loadState();
        const item = toShelfBook(book || {});
        if (!item.title) return null;
        const existing = state.books[item.key];
        if (existing && existing.added_at) {
            item.added_at = existing.added_at;
            item.image_candidates = normalizeCoverCandidates({
                image_url: item.image_url || existing.image_url,
                image_candidates: [...(item.image_candidates || []), ...(existing.image_candidates || [])],
            });
            if (!item.image_url && existing.image_url) item.image_url = existing.image_url;
        }
        const targetId = listId || state.lists[0].id;
        let list = state.lists.find(entry => entry.id === targetId);
        if (!list) list = state.lists[0];
        state.books[item.key] = item;
        list.book_keys = [item.key, ...list.book_keys.filter(key => key !== item.key)];
        list.updated_at = nowIso();
        saveState(state);
        emitChanged("add", { item, list });
        return item;
    }

    function removeFromList(key, listId) {
        const state = loadState();
        const list = state.lists.find(item => item.id === listId);
        if (!list) return;
        list.book_keys = list.book_keys.filter(itemKey => itemKey !== key);
        list.updated_at = nowIso();
        pruneUnlistedBooks(state);
        saveState(state);
        emitChanged("remove", { key, list });
    }

    function removeFromAll(key) {
        const state = loadState();
        state.lists.forEach(list => {
            list.book_keys = list.book_keys.filter(itemKey => itemKey !== key);
        });
        delete state.books[key];
        saveState(state);
        emitChanged("remove-all", { key });
    }

    function updateCover(key, imageUrl) {
        const cleanKey = cleanText(key);
        const url = cleanText(imageUrl);
        if (!cleanKey || !url) return false;
        const state = loadState();
        const book = state.books[cleanKey];
        if (!book || book.image_url === url) return false;
        book.image_url = url;
        book.image_candidates = normalizeCoverCandidates(book);
        book.updated_at = nowIso();
        saveState(state);
        return true;
    }

    function booksForList(listId) {
        const state = loadState();
        const list = state.lists.find(item => item.id === listId) || state.lists[0];
        return list.book_keys.map(key => state.books[key]).filter(Boolean);
    }

    function emitChanged(action, detail) {
        window.dispatchEvent(new CustomEvent("soulib:shelf-changed", { detail: { action, ...(detail || {}) } }));
    }

    function backupError(code) { return new Error(code || "backup_invalid"); }

    function backupText(value, limit, required = false) {
        if (typeof value !== "string" || value.length > limit || (required && !value.trim())) throw backupError();
        return value.trim();
    }

    function safeImage(value) {
        if (!value) return "";
        const text = backupText(value, 2048);
        try {
            const url = new URL(text);
            return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : "";
        } catch (_) { return ""; }
    }

    function backupDate(value, required = false) {
        const text = backupText(value || "", 50);
        if (required && !text) throw backupError();
        if (text && (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})$/.test(text) || !Number.isFinite(Date.parse(text)))) throw backupError();
        return text;
    }

    function checkBackupTree(value, depth = 0, count = {value: 0}) {
        if (++count.value > 200000 || depth > 12) throw backupError();
        if (!value || typeof value !== "object") return;
        Object.keys(value).forEach(key => {
            if (["__proto__", "constructor", "prototype"].includes(key)) throw backupError();
            checkBackupTree(value[key], depth + 1, count);
        });
    }

    function backupBook(book, key) {
        if (!book || typeof book !== "object" || Array.isArray(book)) throw backupError();
        const title = backupText(book.title, 500, true);
        const author = backupText(book.author || "", 300);
        const publisher = backupText(book.publisher || "", 300);
        const canonicalKey = canonicalKeyFor({title, author, publisher});
        if (key !== canonicalKey || (book.key !== undefined && book.key !== key)) throw backupError();
        const counts = {};
        if (book.counts !== undefined && (!book.counts || typeof book.counts !== "object" || Array.isArray(book.counts))) throw backupError();
        ["kyobo", "yes24", "other", "total"].forEach(name => {
            const number = book.counts?.[name] ?? 0;
            if (!Number.isInteger(number) || number < 0 || number > 10000000) throw backupError();
            counts[name] = number;
        });
        if (book.image_candidates !== undefined && (!Array.isArray(book.image_candidates) || book.image_candidates.length > 8)) throw backupError();
        const candidates = (book.image_candidates || []).map(candidate => {
            if (typeof candidate === "string") return safeImage(candidate);
            if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) throw backupError();
            return safeImage(candidate.url || candidate.image_url || "");
        }).filter(Boolean);
        const image = safeImage(book.image_url || "");
        const added = backupDate(book.added_at, true);
        const updated = backupDate(book.updated_at, true);
        // Imported links and IDs never determine navigation. Build a local detail
        // address from the validated text, and copy only the book fields we use.
        return toShelfBook({title, author, publisher, image_url: image,
            image_candidates: candidates.map(url => ({url})), counts, added_at: added, updated_at: updated});
    }

    function validateBackup(value) {
        checkBackupTree(value);
        if (!value || value.format !== BACKUP_FORMAT || value.version !== 1 || !value.state || value.state.version !== 2) throw backupError();
        const source = value.state;
        if (!Array.isArray(source.lists) || !source.lists.length || source.lists.length > 100 ||
            !source.books || typeof source.books !== "object" || Array.isArray(source.books)) throw backupError();
        const keys = Object.keys(source.books);
        if (keys.length > 10000) throw backupError();
        const books = Object.create(null);
        keys.forEach(key => {
            backupText(key, 1200, true);
            books[key] = backupBook(source.books[key], key);
        });
        const seen = new Set();
        let references = 0;
        const lists = source.lists.map(list => {
            if (!list || typeof list !== "object" || Array.isArray(list)) throw backupError();
            const id = backupText(list.id, 160, true);
            if (seen.has(id)) throw backupError();
            seen.add(id);
            if (list.import_ref !== undefined && (typeof list.import_ref !== "string" || !/^[a-f0-9]{64}:.{1,160}$/.test(list.import_ref))) throw backupError();
            if (!Array.isArray(list.book_keys) || list.book_keys.length > 10000) throw backupError();
            references += list.book_keys.length;
            if (references > 100000) throw backupError();
            const bookKeys = list.book_keys.map(key => {
                backupText(key, 1200, true);
                if (!Object.hasOwn(books, key)) throw backupError();
                return key;
            });
            if (new Set(bookKeys).size !== bookKeys.length) throw backupError();
            return {id, name: backupText(list.name, 80, true), description: backupText(list.description || "", 200), book_keys: bookKeys,
                created_at: backupDate(list.created_at, true), updated_at: backupDate(list.updated_at, true)};
        });
        const referenced = new Set(lists.flatMap(list => list.book_keys));
        if (keys.some(key => !referenced.has(key))) throw backupError();
        return {version: 2, lists, books};
    }

    function backupSize(text) { return new TextEncoder().encode(text).byteLength; }

    function createBackup() {
        const state = stateForRestore();
        const value = {format: BACKUP_FORMAT, version: 1, exported_at: nowIso(), state};
        // The same strict format is used for our own files and imported files.
        const checked = validateBackup(value);
        const text = JSON.stringify({...value, state: checked}, null, 2);
        if (backupSize(text) > BACKUP_MAX_BYTES) throw backupError("backup_too_large");
        return text;
    }

    function stateForRestore() {
        let value;
        try { value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"); }
        catch (_) { throw backupError("backup_save_failed"); }
        if (value !== null && !Array.isArray(value)) {
            try { validateBackup({format: BACKUP_FORMAT, version: 1, state: value}); }
            catch (_) { throw backupError("backup_save_failed"); }
        }
        return normalizeState(value);
    }

    async function prepareRestore(text) {
        if (typeof text !== "string" || backupSize(text) > BACKUP_MAX_BYTES) throw backupError();
        let value;
        try { value = JSON.parse(text); } catch (_) { throw backupError(); }
        const state = validateBackup(value);
        const signature = {
            lists: state.lists.map(list => ({...list})).sort((a, b) => a.id.localeCompare(b.id)),
            books: Object.keys(state.books).sort().map(key => {
                const book = state.books[key];
                return {key, title: book.title, author: book.author, publisher: book.publisher,
                    image_url: book.image_url, image_candidates: book.image_candidates, counts: book.counts};
            }),
        };
        const digest = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(signature)));
        const fingerprint = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
        const existing = stateForRestore();
        const newLists = state.lists.filter(list => !existing.lists.some(item => item.import_ref === `${fingerprint}:${list.id}`));
        const plan = Object.freeze({listCount: newLists.length, bookCount: new Set(newLists.flatMap(list => list.book_keys)).size, duplicate: !newLists.length});
        preparedRestores.set(plan, {state, fingerprint});
        return plan;
    }

    function restoreBackup(plan) {
        const prepared = preparedRestores.get(plan);
        if (!prepared) throw backupError();
        const {state: incoming, fingerprint} = prepared;
        const state = stateForRestore();
        const existingIds = new Set(state.lists.map(list => list.id));
        const existingNames = new Set(state.lists.map(list => list.name));
        const newLists = incoming.lists.filter(list => !state.lists.some(item => item.import_ref === `${fingerprint}:${list.id}`));
        if (!newLists.length) return {status: "duplicate", listCount: 0};
        newLists.forEach(source => {
            let id;
            do { id = uid(); } while (existingIds.has(id));
            existingIds.add(id);
            let name = source.name;
            let suffix = 1;
            while (existingNames.has(name)) {
                const marker = suffix === 1 ? " (복원)" : ` (복원 ${suffix})`;
                name = source.name.slice(0, 80 - marker.length) + marker;
                suffix += 1;
            }
            existingNames.add(name);
            source.book_keys.forEach(key => {
                if (!Object.hasOwn(state.books, key)) state.books[key] = incoming.books[key];
            });
            state.lists.push({id, name, description: source.description, created_at: source.created_at, updated_at: source.updated_at,
                book_keys: source.book_keys.slice(), import_ref: `${fingerprint}:${source.id}`});
        });
        // setItem is atomic: a quota/storage failure leaves the previous value.
        try { saveState(state); } catch (_) { throw backupError("backup_save_failed"); }
        emitChanged("restore", {listCount: newLists.length});
        return {status: "imported", listCount: newLists.length};
    }

    window.SoulibShelf = {
        add,
        booksForList,
        countLabel,
        createList,
        deleteList,
        detailUrl,
        getList,
        has,
        keyFor,
        listAll,
        listsForBook,
        loadState,
        removeFromAll,
        removeFromList,
        renameList,
        saveState,
        toShelfBook,
        updateCover,
        createBackup,
        prepareRestore,
        restoreBackup,
        BACKUP_MAX_BYTES,
    };
})();
