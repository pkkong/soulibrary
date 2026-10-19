/* Offline tests of the shipped preference and shelf backup code. No network. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const source = name => fs.readFileSync(path.join(__dirname, '../web/', name), 'utf8');
const shelfSource = source('static/js/shelf_storage.js');
const preferenceSource = source('static/js/library_preferences.js');
const searchSource = source('static/js/search.js');
const shelfUiSource = source('static/js/my_shelf.js');
const STORAGE_KEY = 'soulib.myShelf.v1';
const PREF_KEY = 'soulib.libraryPreferences.v1';

function environment() {
    const values = new Map(), listeners = new Map();
    const io = {reads: 0, writes: 0, network: 0, analytics: 0, blocked: false, quota: false};
    const localStorage = {
        getItem(key) { io.reads++; if (io.blocked) throw Error('blocked'); return values.get(key) ?? null; },
        setItem(key, value) { if (io.blocked || io.quota) throw Error('quota'); io.writes++; values.set(key, String(value)); },
        removeItem(key) { if (io.blocked) throw Error('blocked'); io.writes++; values.delete(key); },
    };
    const window = {crypto: webcrypto,
        addEventListener(name, callback) { if (!listeners.has(name)) listeners.set(name, []); listeners.get(name).push(callback); },
        dispatchEvent(event) { (listeners.get(event.type) || []).forEach(callback => callback(event)); },
        SoulibAnalytics: {track() { io.analytics++; }},
    };
    const context = vm.createContext({window, localStorage, console, URL, URLSearchParams, TextEncoder, Uint8Array,
        CustomEvent: class {constructor(type, options) {this.type = type; this.detail = options?.detail;}},
        fetch() { io.network++; throw Error('network forbidden'); }, setTimeout});
    vm.runInContext(preferenceSource + '\n' + shelfSource, context);
    window.SoulibLibraryPreferences.configure([{code: 'mapo', name: '마포'}, {code: 'songpa_owned', name: '송파'}, {code: 'songpa_subs', name: '송파'}]);
    return {values, io, localStorage, window, context, shelf: window.SoulibShelf, prefs: window.SoulibLibraryPreferences};
}
const plain = value => JSON.parse(JSON.stringify(value));

function fakeElement() {
    return {hidden: true, value: '', checked: false, textContent: '', innerHTML: '', style: {}, dataset: {}, listeners: {},
        classList: {add() {}, remove() {}, toggle() {}},
        addEventListener(name, callback) { this.listeners[name] = callback; },
        querySelectorAll() { return []; },
        setAttribute() {}, removeAttribute() {}, focus() {},
        insertAdjacentHTML(position, html) { this.innerHTML += html; }};
}

function searchPage(env, query = '') {
    const elements = new Map(), ready = [];
    const get = id => { if (!elements.has(id)) elements.set(id, fakeElement()); return elements.get(id); };
    const document = {getElementById: get, querySelector: selector => selector === '.search-page' ? get('page') : null,
        querySelectorAll: () => [], addEventListener(name, callback) { if (name === 'DOMContentLoaded') ready.push(callback); }};
    env.window.location = new URL('https://www.soulib.kr/search' + query);
    env.window.history = {replaceState(state, title, url) { env.lastUrl = url; }};
    env.context.document = document;
    env.context.LIB_URLS = {};
    vm.runInContext(searchSource + '\nfetchSearch = function() {}; applyFilters = function() {};', env.context);
    ready.forEach(callback => callback());
    return {get, run: code => vm.runInContext(code, env.context)};
}

function copyFunction(text, name) {
    let start = text.indexOf(`function ${name}(`);
    assert(start >= 0, name);
    if (text.slice(start - 6, start) === 'async ') start -= 6;
    const body = text.slice(start).match(/\)\s*\{/);
    let end = start + body.index + body[0].indexOf('{'), depth = 1;
    while (depth && ++end < text.length) {
        if (text[end] === '{') depth++;
        else if (text[end] === '}') depth--;
    }
    return text.slice(start, end + 1);
}

async function main() {
    const env = environment(), {prefs} = env;
    assert.deepEqual(plain(prefs.selection(new URLSearchParams())), []);
    const page = searchPage(env);
    page.run('openFilterSheet("library")');
    assert.match(page.get('sheet-options').innerHTML, /마포/);
    assert.match(page.get('sheet-options').innerHTML, /송파/);
    page.run('tempSelectedLibraries.add("마포"); tempRememberLibraries=true; tempLibrariesDirty=true; closeSheet();');
    assert.equal(env.values.has(PREF_KEY), false, 'cancel does not save a draft');
    page.run('openFilterSheet("library"); tempSelectedLibraries.add("마포"); tempRememberLibraries=true; tempLibrariesDirty=true; applySheet();');
    assert.deepEqual(plain(prefs.names()), ['마포']);
    assert.equal(page.get('library-scope').hidden, false);
    assert.equal(page.get('status').textContent, '', 'initial filter confirmation is not a zero-result search');
    assert.equal(page.get('search-feedback').hidden, true);
    assert.equal(page.get('search-empty-state').hidden, false);
    assert.deepEqual(Object.keys(JSON.parse(env.values.get(PREF_KEY))).sort(), ['libraries', 'version']);
    assert.deepEqual(Object.keys(JSON.parse(env.values.get(PREF_KEY)).libraries[0]).sort(), ['code', 'name']);
    const remembered = env.values.get(PREF_KEY);
    page.get('library-scope-all').listeners.click();
    assert.match(env.lastUrl, /libraries=$/);
    assert.equal(env.values.get(PREF_KEY), remembered, 'view all keeps the remembered list');
    page.run('openFilterSheet("provider"); tempSelectedProviders.add("교보"); applySheet();');
    assert.equal(env.values.get(PREF_KEY), remembered, 'provider-only confirm after view all preserves memory');
    page.run('openFilterSheet("field"); tempSelectedField="author"; applySheet();');
    assert.equal(env.values.get(PREF_KEY), remembered, 'field-only confirm preserves memory');
    page.run('openFilterSheet("library");');
    page.get('remember-libraries').listeners.change({target: {checked: false}});
    page.run('applySheet();');
    assert.equal(env.values.has(PREF_KEY), false, 'uncheck and confirm deletes memory');
    prefs.save(['송파'], true);
    assert.deepEqual(plain(prefs.selection(new URLSearchParams('libraries='))), []);
    assert.deepEqual(plain(prefs.selection(new URLSearchParams('libraries=mapo'))), ['마포']);
    assert.deepEqual(plain(prefs.options([], ['결과없는 기관'])), ['결과없는 기관', '마포', '송파']);
    assert.equal(JSON.parse(env.values.get(PREF_KEY)).libraries.length, 2, 'one named institution includes owned/subscription codes');
    const reloaded = environment();
    reloaded.values.set(PREF_KEY, env.values.get(PREF_KEY));
    const reloadPage = searchPage(reloaded, '?libraries=송파');
    assert.equal(reloadPage.get('library-scope').hidden, false, 'explicit URL and reload retain visible scope');
    assert.equal(reloadPage.get('library-scope-label').textContent, '도서관 1곳');
    const blocked = environment(); blocked.io.blocked = true;
    assert.equal(blocked.prefs.save(['마포'], true), false);
    assert.deepEqual(plain(blocked.prefs.selection(new URLSearchParams())), []);

    // Execute the actual detail comparator. Preferred cards retain provider groups.
    const card = (name, code, order, reserved = 0) => ({dataset: {libraryName: name, libraryCode: code, statusOrder: String(order), reserved: String(reserved)}, querySelector: () => ({textContent: name})});
    const cards = [card('마포', 'mapo', 0), card('송파', 'songpa_owned', 2), card('송파', 'songpa_subs', 0)];
    const group = {querySelectorAll: () => cards.slice(), appendChild(item) { cards.splice(cards.indexOf(item), 1); cards.push(item); }};
    env.context.group = group;
    vm.runInContext(copyFunction(source('templates/live_book.html'), 'sortGroup') + '\nsortGroup(group);', env.context);
    assert.deepEqual(cards.map(item => item.dataset.libraryCode), ['songpa_subs', 'songpa_owned', 'mapo']);
    prefs.save(['마포'], true);
    vm.runInContext('sortGroup(group)', env.context);
    assert.equal(cards[0].dataset.libraryCode, 'mapo', 'sorting rereads changed memory');
    assert.equal(cards.length, 3, 'other institutions are never hidden');

    const original = environment();
    original.shelf.add({title: '첫 책', author: '저자', publisher: '출판사', image_url: 'https://example.com/cover.jpg', counts: {total: 2}});
    const second = original.shelf.createList('다른 서재', '설명');
    original.shelf.add({title: '둘째 책', author: '다른 저자'}, second.id);
    const dated = original.shelf.loadState();
    dated.lists[0].created_at = '2025-01-02T03:04:05.000Z';
    dated.lists[0].updated_at = '2025-02-03T04:05:06.000Z';
    const firstKey = dated.lists[0].book_keys[0];
    dated.books[firstKey].added_at = '2025-01-02T03:04:05.000Z';
    dated.books[firstKey].updated_at = '2025-02-03T04:05:06.000Z';
    original.shelf.saveState(dated);
    const text = original.shelf.createBackup(), backup = JSON.parse(text);
    assert.equal(backup.state.lists.length, 2);
    assert.equal(Object.keys(backup.state.books).length, 2);
    assert.equal(backup.state.lists[0].created_at, dated.lists[0].created_at);
    assert.equal(backup.state.books[firstKey].updated_at, dated.books[firstKey].updated_at);
    const target = environment();
    target.shelf.add({title: '첫 책', author: '저자', publisher: '출판사', image_url: 'https://example.com/existing.jpg', counts: {total: 9}});
    const beforeBook = plain(target.shelf.loadState().books[firstKey]);
    const plan = await target.shelf.prepareRestore(text);
    assert.equal(plan.listCount, 2); assert.equal(plan.bookCount, 2);
    const beforeRestoreWrites = target.io.writes;
    const imported = target.shelf.restoreBackup(plan);
    assert.equal(imported.listCount, 2);
    assert.equal(target.io.writes, beforeRestoreWrites + 1, 'one atomic localStorage write');
    const restored = target.shelf.loadState();
    assert.equal(restored.lists.length, 3);
    assert.equal(restored.lists[1].name, '기본 서재 (복원)');
    assert.notEqual(restored.lists[1].id, backup.state.lists[0].id);
    assert.equal(restored.lists[1].created_at, backup.state.lists[0].created_at);
    assert.equal(restored.lists[1].updated_at, backup.state.lists[0].updated_at);
    assert.deepEqual(plain(restored.books[firstKey]), beforeBook, 'existing same-key metadata is preserved');
    const identical = target.values.get(STORAGE_KEY), writeCount = target.io.writes;
    const repeatPlan = await target.shelf.prepareRestore(text);
    assert.equal(repeatPlan.duplicate, true);
    assert.equal(target.shelf.restoreBackup(repeatPlan).status, 'duplicate');
    assert.equal(target.values.get(STORAGE_KEY), identical); assert.equal(target.io.writes, writeCount);
    const roundtrip = environment();
    roundtrip.shelf.restoreBackup(await roundtrip.shelf.prepareRestore(target.shelf.createBackup()));
    assert.equal(roundtrip.shelf.listAll().length, 4, 'all restored lists can be backed up again');

    for (const mutate of [
        file => { file.version = 99; }, file => { file.format = 'other'; },
        file => { file.state.lists[0].book_keys.push('missing'); },
        file => { file.state.lists.push(file.state.lists[0]); },
        file => { file.state.lists[0].book_keys.push(file.state.lists[0].book_keys[0]); },
        file => { file.state.lists[0].created_at = 'yesterday'; },
        file => { file.state.books[firstKey].updated_at = 'bad-date'; },
        file => { file.state.books[firstKey].title = 'x'.repeat(501); },
        file => { file.state.books[firstKey].counts.total = -1; },
    ]) {
        const invalid = JSON.parse(text); mutate(invalid);
        await assert.rejects(target.shelf.prepareRestore(JSON.stringify(invalid)));
        assert.equal(target.values.get(STORAGE_KEY), identical);
    }
    for (const invalid of ['{bad', text.replace('"format":', '"__proto__": {"polluted": true}, "format":'), ' '.repeat(5 * 1024 * 1024 + 1)]) {
        await assert.rejects(target.shelf.prepareRestore(invalid));
        assert.equal(target.values.get(STORAGE_KEY), identical);
    }
    assert.equal({}.polluted, undefined);
    const quota = environment(), quotaBefore = quota.values.get(STORAGE_KEY);
    const quotaPlan = await quota.shelf.prepareRestore(text); quota.io.quota = true;
    assert.throws(() => quota.shelf.restoreBackup(quotaPlan), /backup_save_failed/);
    assert.equal(quota.values.get(STORAGE_KEY), quotaBefore);
    const corrupt = environment(); corrupt.values.set(STORAGE_KEY, '{broken');
    assert.throws(() => corrupt.shelf.createBackup(), /backup_save_failed/);
    assert.equal(corrupt.values.get(STORAGE_KEY), '{broken');
    const dangling = environment();
    const brokenState = JSON.parse(original.values.get(STORAGE_KEY));
    brokenState.lists[0].book_keys.push('missing:old-reference');
    dangling.values.set(STORAGE_KEY, JSON.stringify(brokenState));
    const brokenOriginal = dangling.values.get(STORAGE_KEY);
    assert.throws(() => dangling.shelf.createBackup(), /backup_save_failed/);
    await assert.rejects(dangling.shelf.prepareRestore(text), /backup_save_failed/);
    assert.equal(dangling.values.get(STORAGE_KEY), brokenOriginal, 'dangling existing references never normalize away during import/export');
    assert.equal(dangling.io.writes, 0);
    blocked.io.blocked = true;
    assert.throws(() => blocked.shelf.createBackup(), /backup_save_failed/);

    const unsafe = JSON.parse(text);
    unsafe.state.books[firstKey].live_detail_url = 'javascript:alert(1)';
    unsafe.state.books[firstKey].image_url = 'javascript:alert(1)';
    unsafe.state.books[firstKey].image_candidates = [{url: 'data:text/html,<script>alert(1)</script>'}];
    const safe = environment(); safe.shelf.restoreBackup(await safe.shelf.prepareRestore(JSON.stringify(unsafe)));
    const safeBook = safe.shelf.loadState().books[firstKey];
    assert.match(safeBook.live_detail_url, /^\/live_book\?/);
    assert.equal(safeBook.image_url, ''); assert.equal(safeBook.image_candidates.length, 0);

    // Run the actual file handler: cancel and quota failure cannot modify a shelf.
    const ui = environment(), uiElements = {shelfRestore: fakeElement(), shelfBackupStatus: fakeElement(), shelfRestoreFile: fakeElement()};
    let restoreFocusCount = 0;
    uiElements.shelfRestore.focus = () => { restoreFocusCount++; };
    Object.assign(ui.context, uiElements, {shelf: ui.shelf});
    ui.window.confirm = () => false;
    vm.runInContext(copyFunction(shelfUiSource, 'restoreShelfFile'), ui.context);
    const file = {size: Buffer.byteLength(text), text: async () => text};
    ui.context.file = file;
    const untouched = ui.values.get(STORAGE_KEY);
    await vm.runInContext('restoreShelfFile(file)', ui.context);
    assert.equal(ui.values.get(STORAGE_KEY), untouched); assert.equal(ui.io.writes, 0);
    assert.equal(restoreFocusCount, 1, 'cancel returns focus to the restore trigger');
    ui.window.confirm = prompt => { assert.match(prompt, /既存|既|기존 서재는 그대로 유지됩니다/); return true; };
    ui.io.quota = true;
    await vm.runInContext('restoreShelfFile(file)', ui.context);
    assert.equal(ui.values.get(STORAGE_KEY), untouched);
    assert.equal(uiElements.shelfBackupStatus.textContent, '서재를 저장하지 못했습니다. 기존 서재는 그대로입니다.');
    assert.equal(restoreFocusCount, 2, 'save failure returns focus to the restore trigger');
    ui.io.quota = false;
    await vm.runInContext('restoreShelfFile(file)', ui.context);
    assert.equal(restoreFocusCount, 3, 'successful restore returns focus to the trigger');
    assert.equal(uiElements.shelfBackupStatus.textContent, '서재 2개를 추가했습니다.');
    await vm.runInContext('restoreShelfFile(file)', ui.context);
    assert.equal(restoreFocusCount, 4, 'duplicate restore returns focus to the trigger');
    assert.equal(uiElements.shelfBackupStatus.textContent, '이미 가져온 서재입니다.');

    const reports = source('templates/reports.html');
    const reportBranch = reports.slice(reports.indexOf('.then(async (res)'), reports.indexOf('.catch(() =>'));
    assert(!reportBranch.includes('!res.ok || data.unavailable'));
    const accept = reportBranch.match(/\.then\(async \(res\) => \{([\s\S]*?)\}\)/)[1];
    const receive = vm.runInNewContext(`(async function(res) {${accept}})`);
    const incomplete = {html: '<div>확인된 신고</div><div>확인 지연</div>', unavailable: true};
    assert.equal(await receive({ok: false, json: async () => incomplete}), incomplete);
    await assert.rejects(receive({ok: false, json: async () => ({})}));
    for (const item of [env, reloaded, blocked, original, target, roundtrip, quota, corrupt, dangling, safe, ui]) {
        assert.equal(item.io.network, 0); assert.equal(item.io.analytics, 0);
    }
    console.log('convenience_regression_test: ok (preferences, URL precedence, cancellation, detail ordering, all-shelf backup, strict import, atomic preservation, duplicates, quota, safe links, partial reports, zero network/analytics)');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
