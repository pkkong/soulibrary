/* Analytics contract regression without a browser, network, or dependencies. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../web/static/js/analytics.js'), 'utf8');

function page(url, referrer = '', options = {}) {
    const events = [];
    const scripts = [];
    const storage = new Map(options.optOut ? [['soulib.analytics.optOut', '1']] : []);
    const listeners = {};
    const window = {
        location: new URL(url),
        gtag: (...args) => events.push(args),
        addEventListener: (name, handler) => { listeners[name] = handler; },
    };
    const document = {
        referrer,
        head: {appendChild: script => scripts.push(script)},
        createElement: () => ({}),
        addEventListener: (name, handler) => { listeners[name] = handler; },
        querySelector: () => null,
    };
    const localStorage = {
        getItem(key) { if (options.blockStorage) throw new Error('storage blocked'); return storage.get(key); },
        setItem(key, value) { if (options.blockStorage) throw new Error('storage blocked'); storage.set(key, value); },
        removeItem(key) { if (options.blockStorage) throw new Error('storage blocked'); storage.delete(key); },
    };
    vm.runInNewContext(source, {window, document, localStorage, URL, Set, Date});
    return {window, events, scripts, listeners, analytics: window.SoulibAnalytics};
}

const production = page('https://www.soulib.kr/search?q=URL_SECRET&contact=CONTACT_SECRET', 'https://example.com/article/private?token=REFERRER_SECRET');
assert.equal(production.analytics.isEnabled(), true);
assert.equal(production.scripts.length, 1);
assert.equal(production.events.filter(event => event[0] === 'event' && event[1] === 'page_view').length, 1);
assert(!JSON.stringify(production.events).includes('URL_SECRET'));
assert(!JSON.stringify(production.events).includes('REFERRER_SECRET'));
assert(production.analytics.track('search_result', {
    search_term: '허용된 검색어', field: 'author', provider_count: 1, library_count: 2,
    result_count: 3, duration_ms: 25, partial: true, failed_library_count: 1,
    contact: 'CONTACT_SECRET', page_url: 'https://example.com/PRIVATE_URL', slug: 'SHARED_SECRET',
}));
const sent = production.events.at(-1)[2];
assert.equal(sent.search_term, '허용된 검색어');
assert.equal(sent.failed_library_count, 1);
assert.equal(sent.partial, true);
assert.equal(sent.page_location, 'https://www.soulib.kr/search');
assert.equal(sent.page_referrer, 'https://example.com');
assert(!JSON.stringify(production.events).includes('CONTACT_SECRET'));
assert(!JSON.stringify(production.events).includes('SHARED_SECRET'));
assert(!JSON.stringify(production.events).includes('PRIVATE_URL'));
assert.equal(production.analytics.track('unknown_event', {}), false);
production.analytics.track('search_error', {search_term: '허용된 검색어', error_type: 'secret response text', duration_ms: NaN});
assert.equal(production.events.at(-1)[2].error_type, 'unknown');
assert.equal(production.events.at(-1)[2].duration_ms, 0);

for (const url of [
    'http://localhost:5012/search?q=private',
    'http://127.0.0.1:5012/search',
    'https://preview.vercel.app/search',
    'https://www.soulib.kr/ops/health',
    'https://www.soulib.kr/admin',
    'https://www.soulib.kr/data_quality_admin',
]) {
    const disabled = page(url);
    assert.equal(disabled.analytics.isEnabled(), false, url);
    assert.equal(disabled.events.length, 0, url);
    assert.equal(disabled.scripts.length, 0, url);
    assert.equal(disabled.analytics.track('search_start', {search_term: 'private'}), false, url);
}
const sharedReferrer = page('https://www.soulib.kr/search', 'https://www.soulib.kr/shelf/SHARED_SECRET');
assert.equal(sharedReferrer.scripts.length, 1);
assert.equal(sharedReferrer.events.at(-1)[2].page_referrer, 'https://www.soulib.kr/shelf/shared');
assert(!JSON.stringify(sharedReferrer.events).includes('SHARED_SECRET'));
const shared = page('https://www.soulib.kr/shelf/SHARED_SECRET?token=PRIVATE_QUERY');
assert.equal(shared.analytics.isEnabled(), true);
assert.equal(shared.events.at(-1)[2].page_type, 'shared_shelf');
assert.equal(shared.events.at(-1)[2].page_location, 'https://www.soulib.kr/shelf/shared');
assert(!JSON.stringify(shared.events).includes('SHARED_SECRET'));
assert(!JSON.stringify(shared.events).includes('PRIVATE_QUERY'));
const opsReferrer = page('https://www.soulib.kr/search', 'https://www.soulib.kr/ops/health');
assert.equal(opsReferrer.events.length, 0);
assert.equal(opsReferrer.scripts.length, 0);
const optedOut = page('https://soulib.kr/search', '', {optOut: true});
assert.equal(optedOut.events.length, 0);
assert.equal(optedOut.analytics.isEnabled(), false);
const blockedStorage = page('https://soulib.kr/search', '', {blockStorage: true});
blockedStorage.analytics.setOptOut();
const before = blockedStorage.events.length;
assert.equal(blockedStorage.analytics.track('search_start', {search_term: 'private'}), false);
assert.equal(blockedStorage.events.length, before);
const detail = page('https://www.soulib.kr/live_book?key=PRIVATE_KEY&title=PRIVATE_TITLE');
detail.analytics.track('detail_open');
assert.equal(detail.events.at(-1)[2].page_location, 'https://www.soulib.kr/live_book');
assert(!JSON.stringify(detail.events).includes('PRIVATE_KEY'));
assert(!JSON.stringify(detail.events).includes('PRIVATE_TITLE'));
for (const publicPath of ['/blog/soulib-guide', '/ebook-search', '/digital-library-search', '/seoul-ebook-library-search']) {
    const publicPage = page(`https://www.soulib.kr${publicPath}?token=PRIVATE_QUERY`);
    assert.equal(publicPage.events.at(-1)[2].page_location, `https://www.soulib.kr${publicPath}`);
    assert(!JSON.stringify(publicPage.events).includes('PRIVATE_QUERY'));
}
production.analytics.setOptOut();
assert.equal(production.analytics.track('report_success'), false);
production.analytics.setOptOut(false);
assert.equal(production.analytics.track('report_success'), true);
assert.equal(production.events.at(-1)[2].success, true);
console.log('frontend_regression_test: ok (analytics isolation, redaction, allowed search terms, opt-out)');
