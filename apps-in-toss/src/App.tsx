import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import {
  apiErrorMessage,
  getBookDetail,
  getLibraryStatus,
  searchBooks,
} from './api';
import { createShelf, getShelves, isBookInShelf, isBookSaved, removeBook, saveShelves, setBookInShelf } from './storage';
import type {
  BookShelf,
  LibraryItem,
  LibraryStatusKind,
  SearchBook,
  SearchField,
  SearchFilters,
} from './types';

type View = 'home' | 'search' | 'detail' | 'shelf';
type LoadState = 'idle' | 'loading' | 'done' | 'error';
type FilterTab = 'field' | 'provider' | 'library';
type ShelfViewMode = 'grid3' | 'grid2' | 'list';
type SearchSeed = { query: string; token: number } | null;

const APP_LOGO_URL = new URL('../assets/app-logo-600.png', import.meta.url).href;

const fieldOptions: Array<{ value: SearchField; label: string; sheetLabel: string }> = [
  { value: 'title_author', label: '제목+저자', sheetLabel: '제목+저자(기본)' },
  { value: 'title', label: '제목', sheetLabel: '제목' },
  { value: 'author', label: '저자', sheetLabel: '저자' },
  { value: 'publisher', label: '출판사', sheetLabel: '출판사' },
];

const filterTabs: Array<{ value: FilterTab; label: string }> = [
  { value: 'field', label: '검색 대상' },
  { value: 'provider', label: '공급사' },
  { value: 'library', label: '도서관' },
];

const SEARCH_PAGE_SIZE = 20;

type DetailStatusTone = 'loading' | 'available' | 'reservable' | 'unknown' | 'subscription';
type DetailLibraryStatus = {
  tone: DetailStatusTone;
  text: string;
  reserved: number;
  order: string;
};

type DetailLibraryGroup = {
  label: string;
  rows: Array<{ library: LibraryItem; key: string; tone: DetailStatusTone; text: string; reserved: number; order: string }>;
};

const DETAIL_STATUS_TEXT = {
  loading: '조회 중',
  subscription: '구독형',
  unknown: '확인 필요',
  available: '대출가능',
  reservable: '예약',
};

const DETAIL_STATUS_CLASS: Record<DetailStatusTone, 'status-available' | 'status-reserved' | 'status-unknown'> = {
  loading: 'status-unknown',
  available: 'status-available',
  reservable: 'status-reserved',
  unknown: 'status-unknown',
  subscription: 'status-available',
};

const DETAIL_LIBRARY_GROUP_ORDER = {
  교보: 0,
  YES24: 1,
  기타: 2,
};

function coverUrl(book: SearchBook) {
  return book.image_url || book.image_candidates?.find(Boolean) || '';
}

function savedAtLabel(value?: string) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return `${date.getMonth() + 1}.${date.getDate()} 담음`;
}

function providerLabel(raw?: string) {
  const value = String(raw || '').trim();
  if (!value) return '기타';
  const lower = value.toLowerCase();
  if (value.includes('교보') || lower.includes('kyobo')) return '교보';
  if (lower.includes('yes24')) return 'YES24';
  return '기타';
}

function normalizedProvider(raw?: string) {
  const value = String(raw || '').trim();
  if (!value) return '기타';
  const lower = value.toLowerCase();
  if (value.includes('교보') || lower.includes('kyobo') || lower.includes('dobong')) return '교보';
  if (lower.includes('yes24')) return 'YES24';
  return '기타';
}

function uniqueSorted(values: string[]) {
  return Array.from(new Set(values.filter(Boolean))).sort((a, b) => a.localeCompare(b, 'ko'));
}

function inferStatusKind(library: LibraryItem): LibraryStatusKind {
  const kind = library.status_kind || '';
  if (kind) return kind;
  const platform = library.platform_code || '';
  const code = library.code || '';
  if (platform === 'Kyobo_New') return 'kyobo';
  if (platform === 'Kyobo' || code === 'dobong') return 'dobong';
  if (platform === 'YES24') return 'yes24';
  if (platform === 'Bookcube') return 'bookcube';
  if (code === 'gangnam' || platform === 'Gangnam') return 'gangnam';
  if (code === 'eunpyeong' || platform === 'Eunpyeong') return 'eunpyeong';
  if (code === 'seoul' || platform === 'SeoulLibrary') return 'seoul';
  if (code === 'sen_owned' || code === 'sen_subs' || platform === 'SeoulEducation') return 'sen';
  return '';
}

function statusOrder(text: string) {
  if (text === 'available') return '0';
  if (text === 'reservable') return '1';
  return '2';
}

function statusClassFromTone(tone: DetailStatusTone) {
  return DETAIL_STATUS_CLASS[tone];
}

function toStatusClassName(tone: DetailStatusTone) {
  return statusClassFromTone(tone);
}

function statusSupportedForKind(library: LibraryItem, kind: LibraryStatusKind) {
  if (library.service_type === 'Subscription') return false;
  const brcd = (library.brcd || '').trim();
  const code = (library.code || '').trim();
  const goodsId = (library.goods_id || '').trim();
  const contentId = (library.content_id || '').trim();
  if (kind === 'kyobo') return Boolean(code && brcd);
  if (kind === 'dobong') return Boolean(brcd);
  if (kind === 'yes24') return Boolean(code && goodsId);
  if (kind === 'bookcube') return Boolean(code && contentId);
  if (kind === 'gangnam') return Boolean(code && contentId);
  if (kind === 'eunpyeong') return Boolean(contentId);
  if (kind === 'seoul') return Boolean(contentId);
  if (kind === 'sen') return Boolean(code && contentId);
  return false;
}

function formatAvailability(status: { loaned?: number; total?: number; owned?: number; reserved?: number }) {
  const loaned = Number(status.loaned || 0);
  const total = Number(status.total ?? status.owned ?? 0);
  const reserved = Number(status.reserved || 0);
  const hasTotal = status.total !== undefined || status.owned !== undefined;
  if (!hasTotal) {
    return { tone: 'unknown' as const, text: DETAIL_STATUS_TEXT.unknown, reserved: 0 };
  }
  if (total > loaned && reserved === 0) {
    return {
      tone: 'available' as const,
      text: `${DETAIL_STATUS_TEXT.available} (${Math.max(total - loaned, 0)}/${total})`,
      reserved,
    };
  }
  return {
    tone: 'reservable' as const,
    text: `${DETAIL_STATUS_TEXT.reservable} ${reserved}`,
    reserved,
  };
}

function makeLibraryKey(library: LibraryItem, index = 0) {
  return `${library.code || ''}|${library.brcd || ''}|${library.goods_id || ''}|${library.content_id || ''}|${index}`;
}

type NormalizedLibraryItem = LibraryItem & {
  statusKind: LibraryStatusKind;
  statusSupported: boolean;
  statusKey: string;
};

function platformLabels(book: SearchBook) {
  const labels: string[] = [];
  const bookProvider = (book as SearchBook & { provider?: string }).provider;
  const mappedBookProvider = providerLabel(bookProvider);
  if (mappedBookProvider) labels.push(mappedBookProvider);
  (book.libraries || []).forEach((library) => {
    const provider = providerLabel(library.provider || library.platform_code || library.service_type);
    if (provider) labels.push(provider);
  });
  return uniqueSorted(labels).slice(0, 3);
}

function providerSummary(book: SearchBook) {
  const libraries = book.libraries || [];
  const fallbackCounts = libraries.reduce(
    (counts, library) => {
      const provider = normalizedProvider(library.provider || library.platform_code || library.service_type);
      if (provider === '교보') counts.kyobo += 1;
      else if (provider === 'YES24') counts.yes24 += 1;
      else counts.other += 1;
      counts.total += 1;
      return counts;
    },
    { kyobo: 0, yes24: 0, other: 0, total: 0 },
  );
  const counts = book.counts || {};
  const total = Number(counts.total ?? fallbackCounts.total);
  const kyobo = Number(counts.kyobo ?? fallbackCounts.kyobo);
  const yes24 = Number(counts.yes24 ?? fallbackCounts.yes24);
  const other = Number(counts.other ?? fallbackCounts.other);

  const summary = total > 0 ? [`${total.toLocaleString()}곳 제공`] : ['상세 제공 현황'];
  if (kyobo > 0) summary.push(`교보 ${kyobo.toLocaleString()}`);
  if (yes24 > 0) summary.push(`YES24 ${yes24.toLocaleString()}`);
  if (other > 0) summary.push(`기타 ${other.toLocaleString()}`);
  return summary;
}

function libraryNames(book: SearchBook) {
  return uniqueSorted((book.libraries || []).map((library) => library.short || library.name || ''));
}

function libraryStatusLabels(book: SearchBook) {
  const seen = new Set<string>();
  const labels: string[] = [];
  (book.libraries || []).forEach((library) => {
    const name = library.short || library.name;
    if (!name || seen.has(name)) return;
    seen.add(name);
    labels.push(library.status_label ? `${name} · ${library.status_label}` : name);
  });
  return labels.slice(0, 2);
}

function searchableText(book: SearchBook) {
  return [
    book.title,
    book.author,
    book.publisher,
    ...platformLabels(book),
    ...libraryNames(book),
    ...libraryStatusLabels(book),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

function SearchIcon({ size = 18 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.3-4.3" />
    </svg>
  );
}

function HomeIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 11.5 12 4l9 7.5" />
      <path d="M5 10.5V20h14v-9.5" />
    </svg>
  );
}

function PlusIcon({ size = 19 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </svg>
  );
}

function MoreIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true">
      <path d="M5 12h.01" />
      <path d="M12 12h.01" />
      <path d="M19 12h.01" />
    </svg>
  );
}

function PencilIcon() {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
    </svg>
  );
}

function GridIcon({ columns }: { columns: 2 | 3 }) {
  const bars = columns === 3 ? [3, 10, 17] : [5, 14];
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="currentColor" aria-hidden="true">
      {bars.map((x) => (
        <rect key={x} x={x} y="4" width={columns === 3 ? 4 : 5} height="16" rx="1.2" />
      ))}
    </svg>
  );
}

function ListIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true">
      <rect x="4" y="5" width="3" height="3" rx="0.8" />
      <rect x="9" y="5.5" width="11" height="2" rx="1" />
      <rect x="4" y="10.5" width="3" height="3" rx="0.8" />
      <rect x="9" y="11" width="11" height="2" rx="1" />
      <rect x="4" y="16" width="3" height="3" rx="0.8" />
      <rect x="9" y="16.5" width="11" height="2" rx="1" />
    </svg>
  );
}

function FilterIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 4h18" />
      <path d="M7 12h10" />
      <path d="M10 20h4" />
    </svg>
  );
}

function BookmarkIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 4h12a1 1 0 0 1 1 1v15l-7-4-7 4V5a1 1 0 0 1 1-1Z" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 18 18 6" />
      <path d="M6 6 18 18" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M5 6V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v1" />
      <path d="M8 6l1 14h6l1-14" />
    </svg>
  );
}

function EmptyCover() {
  return <span className="empty-cover" aria-hidden="true" />;
}

function BookCover({ book }: { book: SearchBook }) {
  const url = coverUrl(book);
  if (!url) return <EmptyCover />;
  return <img src={url} alt="" loading="lazy" />;
}

function BookCard({
  book,
  saved,
  onDetail,
  onToggleShelf,
}: {
  book: SearchBook;
  saved: boolean;
  onDetail: (book: SearchBook) => void;
  onToggleShelf: (book: SearchBook) => void;
}) {
  return (
    <article className="card js-book-card">
      <button className="book-main" type="button" onClick={() => onDetail(book)} aria-label={`${book.title} 상세 보기`}>
        <span className="thumb-wrap thumb">
          <BookCover book={book} />
        </span>
        <span className="book-info">
          <span className="book-title title">{book.title}</span>
          <span className="book-meta meta">
            <span className="meta-author">{book.author || '저자 정보 없음'}</span>
            {book.publisher ? <span className="meta-publisher">{book.publisher}</span> : null}
          </span>
        </span>
      </button>
      <button
        className={saved ? 'result-shelf-btn is-saved' : 'result-shelf-btn'}
        type="button"
        onClick={() => onToggleShelf(book)}
        aria-label={saved ? `${book.title} 서재 선택 열기, 담김` : `${book.title} 서재 선택 열기`}
      >
        <BookmarkIcon />
      </button>
    </article>
  );
}

function HomeView({ onSearch }: { onSearch: (query: string) => void }) {
  const [query, setQuery] = useState('');

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    onSearch(query);
  }

  return (
    <main className="screen home-screen page-landing">
      <section className="landing-shell" aria-label="서비스 소개">
        <div className="landing-phone">
          <div className="landing-center">
            <div className="landing-copy">
              <h1 className="landing-title">서울 전자도서관 통합검색</h1>
              <p className="landing-sub">
                서울의 전자도서관을 한 번에 검색합니다.<br />
                책이 있는 곳과 대출 가능 여부를 함께 확인하세요.
              </p>
            </div>

            <form className="landing-search" onSubmit={submitSearch}>
              <label className="sr-only" htmlFor="landing-query">
                검색어
              </label>
              <span className="landing-search-brand" aria-hidden="true">
                <img src={APP_LOGO_URL} alt="" />
              </span>
              <input
                id="landing-query"
                name="q"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                autoComplete="off"
                enterKeyHint="search"
                placeholder="책 제목, 저자 검색"
              />
              <button type="submit" aria-label="검색">
                <SearchIcon />
              </button>
            </form>
          </div>
        </div>
      </section>
    </main>
  );
}

function SearchView({
  shelves,
  onOpenDetail,
  onToggleShelf,
  searchSeed,
}: {
  shelves: BookShelf[];
  onOpenDetail: (book: SearchBook) => void;
  onToggleShelf: (book: SearchBook) => void;
  searchSeed: SearchSeed;
}) {
  const [query, setQuery] = useState('');
  const [field, setField] = useState<SearchField>('title_author');
  const [draftField, setDraftField] = useState<SearchField>('title_author');
  const [state, setState] = useState<LoadState>('idle');
  const [results, setResults] = useState<SearchBook[]>([]);
  const [total, setTotal] = useState(0);
  const [message, setMessage] = useState('');
  const [loadingMore, setLoadingMore] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);
  const [filterTab, setFilterTab] = useState<FilterTab>('field');
  const [selectedProviders, setSelectedProviders] = useState<string[]>([]);
  const [selectedLibraries, setSelectedLibraries] = useState<string[]>([]);
  const [draftProviders, setDraftProviders] = useState<string[]>([]);
  const [draftLibraries, setDraftLibraries] = useState<string[]>([]);
  const [refineEnabled, setRefineEnabled] = useState(false);
  const [refineQuery, setRefineQuery] = useState('');
  const [filterProviders, setFilterProviders] = useState<string[]>([]);
  const [filterLibraries, setFilterLibraries] = useState<string[]>([]);
  const lastSearchSeedToken = useRef(0);

  const providerOptions = filterProviders;
  const libraryOptions = filterLibraries;
  const activeFilterCount = selectedProviders.length + selectedLibraries.length + (field === 'title_author' ? 0 : 1);
  const activeFilterLabels = [
    field === 'title_author' ? '' : fieldOptions.find((option) => option.value === field)?.label || '',
    ...selectedProviders.map((provider) => `공급사 ${provider}`),
    ...selectedLibraries.map((library) => `도서관 ${library}`),
  ].filter(Boolean);

  const displayedResults = useMemo(() => {
    const refine = refineEnabled ? refineQuery.trim().toLowerCase() : '';
    return results.filter((book) => {
      const providers = platformLabels(book);
      const libraries = libraryNames(book);
      const providerMatch = selectedProviders.length === 0 || selectedProviders.some((provider) => providers.includes(provider));
      const libraryMatch = selectedLibraries.length === 0 || selectedLibraries.some((library) => libraries.includes(library));
      const refineMatch = !refine || searchableText(book).includes(refine);
      return providerMatch && libraryMatch && refineMatch;
    });
  }, [refineEnabled, refineQuery, results, selectedLibraries, selectedProviders]);

  const statusText = useMemo(() => {
    if (state === 'loading') return '';
    if (state !== 'done') return '';
    if (!results.length) return message || '검색 결과가 없습니다.';
    const totalLabel = Number(total || results.length).toLocaleString();
    const narrowed = activeFilterCount > 0 || (refineEnabled && refineQuery.trim());
    if (narrowed) {
      return `${displayedResults.length.toLocaleString()}권 표시 · 전체 ${totalLabel}권`;
    }
    return `'${query.trim()}' 검색 결과 ${totalLabel}권`;
  }, [activeFilterCount, displayedResults.length, message, query, refineEnabled, refineQuery, results.length, state, total]);

  async function runSearch(
    nextQuery: string,
    nextField = field,
    filters: SearchFilters = { providers: selectedProviders, libraries: selectedLibraries },
    options: { resetRefine?: boolean } = {},
  ) {
    const cleanQuery = nextQuery.trim();
    if (!cleanQuery) {
      setMessage('검색어를 입력해 주세요.');
      setState('idle');
      setResults([]);
      setTotal(0);
      return;
    }
    const nextFilters = {
      providers: filters.providers?.filter(Boolean) || [],
      libraries: filters.libraries?.filter(Boolean) || [],
    };
    if (options.resetRefine !== false) {
      setRefineQuery('');
    }
    setState('loading');
    setMessage('');
    setLoadingMore(false);
    setResults([]);
    setTotal(0);
    try {
      const data = await searchBooks(cleanQuery, nextField, nextFilters, { limit: SEARCH_PAGE_SIZE, offset: 0 });
      const items = Array.isArray(data.items) ? data.items : [];
      setFilterProviders(uniqueSorted((data.filters?.providers || []).map((provider) => providerLabel(provider))));
      setFilterLibraries(uniqueSorted(data.filters?.libraries || []));
      setResults(items);
      setTotal(Number(data.total || items.length || 0));
      setState('done');
      setMessage(items.length ? '' : '검색 결과가 없습니다.');
    } catch (error) {
      setResults([]);
      setTotal(0);
      setFilterProviders([]);
      setFilterLibraries([]);
      setState('error');
      setMessage(apiErrorMessage(error, '검색 결과를 불러오지 못했습니다.'));
    }
  }

  async function loadMoreResults() {
    const cleanQuery = query.trim();
    if (!cleanQuery || loadingMore || state !== 'done') return;
    const nextFilters = {
      providers: selectedProviders.filter(Boolean),
      libraries: selectedLibraries.filter(Boolean),
    };
    setLoadingMore(true);
    try {
      const data = await searchBooks(cleanQuery, field, nextFilters, { limit: SEARCH_PAGE_SIZE, offset: results.length });
      const items = Array.isArray(data.items) ? data.items : [];
      setResults((current) => [...current, ...items]);
      setTotal(Number(data.total || total || results.length + items.length || 0));
      if (!items.length) {
        setMessage('더 불러올 결과가 없습니다.');
      }
    } catch (error) {
      setMessage(apiErrorMessage(error, '추가 결과를 불러오지 못했습니다.'));
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    await runSearch(query, field, { providers: selectedProviders, libraries: selectedLibraries });
  }

  function openFilterSheet() {
    setDraftField(field);
    setDraftProviders(selectedProviders);
    setDraftLibraries(selectedLibraries);
    setFilterTab('field');
    setFilterOpen(true);
  }

  function closeFilterSheet() {
    setFilterOpen(false);
  }

  function applyFilterSheet() {
    const nextFilters = { providers: draftProviders, libraries: draftLibraries };
    setField(draftField);
    setSelectedProviders(draftProviders);
    setSelectedLibraries(draftLibraries);
    setFilterOpen(false);
    if (query.trim()) {
      void runSearch(query, draftField, nextFilters, { resetRefine: false });
    }
  }

  function resetFilterSheet() {
    setDraftField('title_author');
    setDraftProviders([]);
    setDraftLibraries([]);
  }

  function clearAppliedFilters() {
    const nextFilters = { providers: [], libraries: [] };
    setField('title_author');
    setSelectedProviders([]);
    setSelectedLibraries([]);
    setDraftField('title_author');
    setDraftProviders([]);
    setDraftLibraries([]);
    if (query.trim()) {
      void runSearch(query, 'title_author', nextFilters, { resetRefine: false });
    }
  }

  useEffect(() => {
    if (!searchSeed || searchSeed.token === lastSearchSeedToken.current) return;
    lastSearchSeedToken.current = searchSeed.token;
    const cleanQuery = searchSeed.query.trim();
    setQuery(cleanQuery);
    setField('title_author');
    setDraftField('title_author');
    setSelectedProviders([]);
    setSelectedLibraries([]);
    setDraftProviders([]);
    setDraftLibraries([]);
    setRefineEnabled(false);
    setRefineQuery('');
    if (cleanQuery) {
      void runSearch(cleanQuery, 'title_author', { providers: [], libraries: [] });
    }
  }, [searchSeed]);

  function toggleDraftProvider(provider: string) {
    setDraftProviders((current) => (current.includes(provider) ? current.filter((item) => item !== provider) : [...current, provider]));
  }

  function toggleDraftLibrary(library: string) {
    setDraftLibraries((current) => (current.includes(library) ? current.filter((item) => item !== library) : [...current, library]));
  }

  return (
    <main className="screen search-screen page-search">
      <section className={state === 'done' ? 'search-top has-results' : 'search-top'}>
        <form className="search-top-row" onSubmit={handleSearch}>
          <label className="sr-only" htmlFor="query">
            검색어
          </label>
          <div className="search-top-bar">
            <button className="search-icon-submit" type="submit" disabled={state === 'loading'} aria-label="검색">
              <SearchIcon />
            </button>
            <input
              id="query"
              className="search-top-input"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="검색어를 입력하세요"
              autoComplete="off"
              enterKeyHint="search"
            />
          </div>
          <button
            className="app-icon-button filter-summary"
            type="button"
            onClick={openFilterSheet}
            aria-label="필터"
          >
            <FilterIcon />
            <span className="sr-only">필터</span>
            {activeFilterCount ? <span className="filter-count">{activeFilterCount}</span> : null}
          </button>
        </form>

        <div className="refine-toggle">
          <label className="toggle">
            <input
              type="checkbox"
              checked={refineEnabled}
              onChange={(event) => setRefineEnabled(event.target.checked)}
            />
            <span className="toggle-ui" aria-hidden="true" />
            <span className="toggle-label">결과 내 재검색</span>
          </label>
        </div>
        {refineEnabled ? (
          <label className="refine-input-wrap">
            <span className="refine-icon" aria-hidden="true">
              <SearchIcon size={16} />
            </span>
            <span className="sr-only">결과 내 재검색어</span>
            <input
              className="refine-input"
              value={refineQuery}
              onChange={(event) => setRefineQuery(event.target.value)}
              placeholder="현재 결과에서 다시 찾기"
              autoComplete="off"
            />
          </label>
        ) : null}
      </section>

      {statusText || message ? (
        <section className="summary-row" aria-live="polite">
          <div className={state === 'error' ? 'status error' : 'status'}>
            {state === 'error' ? message : statusText || message}
          </div>
        </section>
      ) : null}

      {activeFilterLabels.length ? (
        <section className="active-filter-row" aria-label="적용된 필터">
          <div className="active-filter-scroll">
            {activeFilterLabels.map((label) => (
              <span className="active-filter-chip" key={label}>
                {label}
              </span>
            ))}
          </div>
          <button className="filter-clear-button" type="button" onClick={clearAppliedFilters}>
            해제
          </button>
        </section>
      ) : null}

      <section className="content">
        <section className="book-list">
          {state === 'idle' && !message ? (
            <section className="search-empty-state" aria-live="polite">
              <div className="search-empty-icon" aria-hidden="true">
                <SearchIcon size={24} />
              </div>
              <p>책 제목이나 저자를 검색하세요.</p>
            </section>
          ) : null}
          {state === 'loading' ? (
            <div className="result-message panel-note loading-panel" role="status">
              <span className="loading-spinner" aria-hidden="true" />
              <span className="sr-only">실시간으로 확인하고 있습니다.</span>
            </div>
          ) : null}
          {state === 'done' && results.length > 0 && displayedResults.length === 0 ? (
            <div className="result-message empty">선택한 조건에 맞는 결과가 없습니다.</div>
          ) : null}
          {state === 'done' && results.length === 0 ? <div className="result-message empty">{message}</div> : null}
          {state === 'error' ? <div className="result-message error">{message}</div> : null}
          {displayedResults.map((book) => (
            <BookCard
              key={`${book.title}-${book.author}-${book.publisher}`}
              book={book}
              saved={isBookSaved(book, shelves)}
              onDetail={onOpenDetail}
              onToggleShelf={onToggleShelf}
            />
          ))}
          {state === 'done' && total > results.length ? (
            <button className="load-more-button" type="button" onClick={loadMoreResults} disabled={loadingMore}>
              {loadingMore ? '불러오는 중...' : '더 보기'}
            </button>
          ) : null}
        </section>
      </section>

      <div className={filterOpen ? 'sheet-overlay show' : 'sheet-overlay'} onClick={closeFilterSheet} />
      <section className={filterOpen ? 'filter-sheet show' : 'filter-sheet'} aria-hidden={!filterOpen}>
        <div className="sheet-header">
          <h2>필터</h2>
          <div className="sheet-header-actions">
            <button className="btn-link" type="button" onClick={resetFilterSheet}>
              초기화
            </button>
            <button className="btn-link" type="button" onClick={closeFilterSheet}>
              닫기
            </button>
          </div>
        </div>
        <div className="sheet-body">
          <div className="sheet-left">
            {filterTabs.map((tab) => (
              <button
                className={filterTab === tab.value ? 'sheet-tab active' : 'sheet-tab'}
                type="button"
                key={tab.value}
                onClick={() => setFilterTab(tab.value)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="sheet-right">
            <div className="sheet-label">{filterTabs.find((tab) => tab.value === filterTab)?.label}</div>
            <div className="sheet-options">
              {filterTab === 'field'
                ? fieldOptions.map((option) => (
                    <label key={option.value}>
                      <input
                        type="radio"
                        name="sheet-field"
                        value={option.value}
                        checked={draftField === option.value}
                        onChange={() => setDraftField(option.value)}
                      />
                      <span>{option.sheetLabel}</span>
                    </label>
                  ))
                : null}
              {filterTab === 'provider' ? (
                <>
                  <label className="sheet-option-all">
                    <input
                      type="checkbox"
                      checked={draftProviders.length === 0}
                      onChange={() => setDraftProviders([])}
                    />
                    <span>전체</span>
                  </label>
                  {providerOptions.length === 0 ? <div className="sheet-empty">검색 결과에 공급사 필터가 없습니다.</div> : null}
                  {providerOptions.map((provider) => (
                    <label key={provider}>
                      <input
                        type="checkbox"
                        value={provider}
                        checked={draftProviders.includes(provider)}
                        onChange={() => toggleDraftProvider(provider)}
                      />
                      <span>{provider}</span>
                    </label>
                  ))}
                </>
              ) : null}
              {filterTab === 'library' ? (
                <>
                  <label className="sheet-option-all">
                    <input
                      type="checkbox"
                      checked={draftLibraries.length === 0}
                      onChange={() => setDraftLibraries([])}
                    />
                    <span>전체</span>
                  </label>
                  {libraryOptions.length === 0 ? <div className="sheet-empty">검색 결과에 도서관 필터가 없습니다.</div> : null}
                  {libraryOptions.map((library) => (
                    <label key={library}>
                      <input
                        type="checkbox"
                        value={library}
                        checked={draftLibraries.includes(library)}
                        onChange={() => toggleDraftLibrary(library)}
                      />
                      <span>{library}</span>
                    </label>
                  ))}
                </>
              ) : null}
            </div>
          </div>
        </div>
        <div className="sheet-actions">
          <button className="btn-secondary" type="button" onClick={closeFilterSheet}>
            취소
          </button>
          <button className="btn-primary" type="button" onClick={applyFilterSheet}>
            확인
          </button>
        </div>
      </section>
    </main>
  );
}

function DetailView({
  book,
  shelves,
  onBack,
  onToggleShelf,
}: {
  book: SearchBook;
  shelves: BookShelf[];
  onBack: () => void;
  onToggleShelf: (book: SearchBook) => void;
}) {
  const [detail, setDetail] = useState<SearchBook>(book);
  const [state, setState] = useState<LoadState>('loading');
  const [message, setMessage] = useState('');
  const [libraryStatuses, setLibraryStatuses] = useState<Record<string, DetailLibraryStatus>>({});
  const saved = isBookSaved(detail, shelves);

  const normalizedLibraries = useMemo(() => {
    return (detail.libraries || []).map((library, index) => {
      const statusKind = inferStatusKind(library);
      return {
        ...library,
        statusKind,
        statusSupported: library.status_supported ?? statusSupportedForKind(library, statusKind),
        statusKey: makeLibraryKey(library, index),
      } satisfies NormalizedLibraryItem;
    });
  }, [detail.libraries]);

  useEffect(() => {
    const seed: Record<string, DetailLibraryStatus> = {};
    normalizedLibraries.forEach((library) => {
      if (library.service_type === 'Subscription') {
        seed[library.statusKey] = {
          tone: 'subscription',
          text: DETAIL_STATUS_TEXT.subscription,
          reserved: 0,
          order: statusOrder('available'),
        };
        return;
      }

      if (library.statusSupported) {
        seed[library.statusKey] = {
          tone: 'loading',
          text: DETAIL_STATUS_TEXT.loading,
          reserved: 0,
          order: statusOrder('reservable'),
        };
        return;
      }

      seed[library.statusKey] = {
        tone: 'unknown',
        text: library.status_label || DETAIL_STATUS_TEXT.unknown,
        reserved: 0,
        order: statusOrder('reservable'),
      };
    });
    setLibraryStatuses(seed);

    let canceled = false;
    const supportedLibraries = normalizedLibraries.filter((library) => library.statusSupported && library.service_type !== 'Subscription');

    async function fetchStatuses() {
      await Promise.all(
        supportedLibraries.map((library) => {
          const { statusKey } = library;
          return getLibraryStatus(library)
            .then((status) => {
              if (canceled) return;
              const formatted = formatAvailability(status);
              setLibraryStatuses((current) => ({
                ...current,
                [statusKey]: {
                  tone: formatted.tone,
                  text: formatted.text,
                  reserved: formatted.reserved,
                  order: statusOrder(formatted.tone),
                },
              }));
            })
            .catch(() => {
              if (canceled) return;
              setLibraryStatuses((current) => ({
                ...current,
                [statusKey]: {
                  tone: 'unknown',
                  text: DETAIL_STATUS_TEXT.unknown,
                  reserved: 0,
                  order: statusOrder('reservable'),
                },
              }));
            });
        }),
      );
    }

    fetchStatuses();

    return () => {
      canceled = true;
    };
  }, [normalizedLibraries]);

  useEffect(() => {
    let alive = true;
    setDetail(book);
    setState('loading');
    setMessage('');
    getBookDetail(book)
      .then((data) => {
        if (!alive) return;
        const nextBook = data.book ? { ...book, ...data.book, live_detail_key: data.live_detail_key || data.book.live_detail_key } : book;
        setDetail(nextBook);
        setState('done');
      })
      .catch((error) => {
        if (!alive) return;
        setState('error');
        setMessage(apiErrorMessage(error, '상세 정보를 불러오지 못했습니다.'));
      });
    return () => {
      alive = false;
    };
  }, [book]);

  const libraryGroups = useMemo(() => {
    const grouped: Record<string, DetailLibraryGroup> = {};
    const orderByLabel = (label: string) => {
      return DETAIL_LIBRARY_GROUP_ORDER[label as keyof typeof DETAIL_LIBRARY_GROUP_ORDER] ?? 99;
    };

    normalizedLibraries.forEach((library) => {
      const status = libraryStatuses[library.statusKey] || {
        tone: 'unknown',
        text: library.status_label || DETAIL_STATUS_TEXT.unknown,
        reserved: 0,
        order: statusOrder('reservable'),
      };
      const group = normalizedProvider(library.provider || library.platform_code);
      if (!grouped[group]) {
        grouped[group] = { label: group, rows: [] };
      }
      grouped[group].rows.push({
        library,
        key: library.statusKey,
        tone: status.tone,
        text: status.text,
        reserved: status.reserved,
        order: status.order,
      });
    });

    return Object.values(grouped)
      .map((group) => ({
        ...group,
        rows: group.rows
          .slice()
          .sort((left, right) => {
            if (left.order !== right.order) return left.order.localeCompare(right.order);
            if (left.reserved !== right.reserved) return left.reserved - right.reserved;
            const leftName = (left.library.short || left.library.name || '').localeCompare(
              right.library.short || right.library.name || '',
              'ko',
            );
            return leftName;
          }),
      }))
      .sort((left, right) => orderByLabel(left.label) - orderByLabel(right.label));
  }, [normalizedLibraries, libraryStatuses]);

  const detailProviderSummary = providerSummary(detail);

  return (
    <main className="screen detail-screen page-detail">
      <section className="detail-hero">
        <div
          className={detail.image_url || coverUrl(detail) ? 'detail-bg' : 'detail-bg detail-bg-fallback'}
          style={detail.image_url || coverUrl(detail) ? { backgroundImage: `url(${coverUrl(detail)})` } : undefined}
          aria-hidden="true"
        />
        <div className="detail-topbar">
          <button className="detail-icon-btn" type="button" onClick={onBack} aria-label="이전 화면">
            <CloseIcon />
          </button>
          <button
            className={saved ? 'detail-icon-btn detail-shelf-btn is-saved' : 'detail-icon-btn detail-shelf-btn'}
            type="button"
            onClick={() => onToggleShelf(detail)}
            aria-label={saved ? '서재 선택 열기, 담김' : '서재 선택 열기'}
          >
            <BookmarkIcon />
          </button>
        </div>
        <div className="detail-cover-wrap">
          <span className="detail-cover">
            <BookCover book={detail} />
          </span>
        </div>
      </section>

      <section className="detail-sheet">
        <div className="detail-inner">
          <section className="detail-panel detail-info">
            <h2 className="detail-title">{detail.title}</h2>
            <div className="detail-meta">
              <div className="detail-meta-row">
                <span className="detail-meta-k">저자</span>
                <span className="detail-meta-v">
                  <span className="detail-meta-text">{detail.author || '저자 정보 없음'}</span>
                </span>
              </div>
              <div className="detail-meta-row">
                <span className="detail-meta-k">출판</span>
                <span className="detail-meta-v">
                  <span className="detail-meta-text">{detail.publisher || '출판사 정보 없음'}</span>
                </span>
              </div>
            </div>
            <div className="detail-supply">
              <div className="count-strip" aria-label="전자도서관별 대출 상태 요약">
                {detailProviderSummary.map((label, index) => (
                  <span className={index === 0 ? 'count-total' : undefined} key={label}>
                    {index === 0 ? <b>{label}</b> : label}
                  </span>
                ))}
              </div>
            </div>
          </section>

          <section className="detail-panel detail-libs">
            <div className="detail-section-head">
              <span className="detail-section-title">소장 도서관</span>
            </div>
            {state === 'error' ? <div className="lib-inline-note error">{message}</div> : null}
            {libraryGroups.length ? (
              <div className="lib-groups">
                {libraryGroups.map((group) => {
                  const provider = group.label;
                  return (
                    <article className="lib-group-row" key={group.label}>
                      <div className="lib-group-title">{provider}</div>
                      <div className="lib-grid">
                        {group.rows.map((row) => {
                          const statusNode =
                            row.tone === 'loading' ? (
                              <span className="lib-status lib-status-loading" role="status">
                                <span className="mini-spinner" aria-hidden="true" />
                                <span className="sr-only">도서관 조회 중</span>
                              </span>
                            ) : (
                              <span className={`lib-status ${toStatusClassName(row.tone)}`} aria-label={row.text}>
                                {row.text}
                              </span>
                            );
                          if (row.library.detail_url) {
                            return (
                              <a className={`lib-card ${toStatusClassName(row.tone)}`} key={row.key} href={row.library.detail_url} target="_blank" rel="noopener noreferrer">
                                <span className="lib-badge-name">{row.library.short || row.library.name || '도서관'}</span>
                                {statusNode}
                              </a>
                            );
                          }
                          return (
                            <div className={`lib-card ${toStatusClassName(row.tone)}`} key={row.key}>
                              <span className="lib-badge-name">{row.library.short || row.library.name || '도서관'}</span>
                              {statusNode}
                            </div>
                          );
                        })}
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="panel-note">도서관별 상세 정보가 아직 없습니다.</div>
            )}
          </section>
        </div>
      </section>
    </main>
  );
}

function ShelfView({
  shelves,
  activeShelfId,
  onSelectShelf,
  onCreateShelf,
  onRenameShelf,
  onClearShelf,
  onDeleteShelf,
  onOpenDetail,
  onRemove,
  onSearch,
}: {
  shelves: BookShelf[];
  activeShelfId: string;
  onSelectShelf: (shelfId: string) => void;
  onCreateShelf: (name: string) => void;
  onRenameShelf: (shelfId: string, name: string) => void;
  onClearShelf: (shelfId: string) => void;
  onDeleteShelf: (shelfId: string) => void;
  onOpenDetail: (book: SearchBook) => void;
  onRemove: (shelfId: string, key: string) => void;
  onSearch: () => void;
}) {
  const [creatingShelf, setCreatingShelf] = useState(false);
  const [managingShelf, setManagingShelf] = useState(false);
  const [viewMode, setViewMode] = useState<ShelfViewMode>('grid3');
  const [newShelfName, setNewShelfName] = useState('');
  const [shareStatus, setShareStatus] = useState('');
  const activeShelf = shelves.find((item) => item.id === activeShelfId) || shelves[0];
  const activeBooks = activeShelf?.books || [];
  const activeName = activeShelf?.name || '기본 서재';
  const canDeleteCurrent = Boolean(activeShelf && !activeShelf.isDefault && shelves.length > 1);
  const canManageCurrent = Boolean(activeShelf);

  function submitNewShelf(event: FormEvent) {
    event.preventDefault();
    onCreateShelf(newShelfName);
    setNewShelfName('');
    setCreatingShelf(false);
  }

  function renameCurrentShelf() {
    if (!activeShelf) return;
    const nextName = window.prompt('서재 이름을 입력하세요.', activeName)?.trim();
    if (!nextName || nextName === activeName) return;
    onRenameShelf(activeShelf.id, nextName);
  }

  function clearCurrentShelf() {
    if (!activeShelf || !activeBooks.length) return;
    if (!window.confirm(`${activeName}의 책을 모두 비울까요?`)) return;
    onClearShelf(activeShelf.id);
  }

  function deleteCurrentShelf() {
    if (!activeShelf || !canDeleteCurrent) return;
    if (!window.confirm(`${activeName} 서재를 삭제할까요?`)) return;
    onDeleteShelf(activeShelf.id);
  }

  async function shareCurrentShelf() {
    if (!activeShelf) return;
    const lines = activeBooks.length
      ? activeBooks.map((book, index) => `${index + 1}. ${book.title}${book.author ? ` - ${book.author}` : ''}`)
      : ['담은 책이 없습니다.'];
    const text = [`${activeName}`, ...lines].join('\n');
    try {
      if (navigator.share) {
        await navigator.share({ title: activeName, text });
        setShareStatus('공유 화면을 열었습니다.');
        return;
      }
      await navigator.clipboard.writeText(text);
      setShareStatus('서재 목록을 복사했습니다.');
    } catch {
      setShareStatus('공유를 완료하지 못했습니다.');
    }
  }

  const shelfItemsClassName = viewMode === 'list' ? 'shelf-items' : `shelf-items is-card is-${viewMode}${managingShelf ? ' is-managing' : ''}`;

  return (
    <main className="screen shelf-screen page-my-shelf">
      <section className="app-page-head shelf-head" aria-labelledby="shelf-title">
        <h1 className="app-page-title" id="shelf-title">
          내 서재
        </h1>
        <div className="app-head-actions shelf-head-actions">
          <button
            className="app-icon-button shelf-icon-button"
            type="button"
            onClick={() => setCreatingShelf((current) => !current)}
            aria-label="새 서재 만들기"
            aria-expanded={creatingShelf}
          >
            <PlusIcon />
          </button>
          <button
            className="app-icon-button shelf-icon-button"
            type="button"
            onClick={() => setManagingShelf((current) => !current)}
            aria-label="서재 관리"
            aria-expanded={managingShelf}
          >
            <MoreIcon />
          </button>
        </div>
      </section>

      <section className="app-section shelf-panel shelf-manager" aria-label="서재 목록">
        <div className="shelf-manager-row">
          <div className="shelf-list-tabs" role="tablist" aria-label="서재 목록">
          {shelves.map((shelf) => {
            const active = shelf.id === activeShelf?.id;
            return (
              <button
                  className={active ? 'shelf-list-tab is-active' : 'shelf-list-tab'}
                type="button"
                role="tab"
                aria-selected={active}
                key={shelf.id}
                onClick={() => onSelectShelf(shelf.id)}
              >
                  <span>{shelf.name}</span>
                  <small>{shelf.books.length}권</small>
              </button>
            );
          })}
          </div>
          <span className="shelf-muted shelf-list-count">{shelves.length}개</span>
        </div>
        {managingShelf ? (
          <div className="shelf-manage-actions">
            <button className="shelf-action-button" type="button" onClick={shareCurrentShelf} disabled={!canManageCurrent} aria-label="공유" title="공유">
              <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="18" cy="5" r="3" />
                <circle cx="6" cy="12" r="3" />
                <circle cx="18" cy="19" r="3" />
                <path d="M8.6 10.7 15.4 6.3" />
                <path d="M8.6 13.3 15.4 17.7" />
              </svg>
            </button>
            <button className="shelf-action-button" type="button" onClick={renameCurrentShelf} disabled={!canManageCurrent} aria-label="이름 변경" title="이름 변경">
              <PencilIcon />
            </button>
            <button className="shelf-action-button" type="button" onClick={clearCurrentShelf} disabled={!activeBooks.length} aria-label="현재 서재 비우기" title="현재 서재 비우기">
              <TrashIcon />
            </button>
            <button className="shelf-action-button danger" type="button" onClick={deleteCurrentShelf} disabled={!canDeleteCurrent} aria-label="서재 삭제" title="서재 삭제">
              <BookmarkIcon />
            </button>
          </div>
        ) : null}
        {creatingShelf ? (
          <form className="shelf-create-form" onSubmit={submitNewShelf}>
            <label className="sr-only" htmlFor="new-shelf-name">
              새 서재 이름
            </label>
            <input
              id="new-shelf-name"
              value={newShelfName}
              onChange={(event) => setNewShelfName(event.target.value)}
              maxLength={18}
              placeholder="새 서재 이름"
            />
            <button type="submit" aria-label="새 서재 추가">
              <PlusIcon size={20} />
            </button>
          </form>
        ) : null}
        {shareStatus ? <div className="shelf-share-status" aria-live="polite">{shareStatus}</div> : null}
      </section>

      <section className="app-section shelf-panel" aria-labelledby="shelf-list-title">
        <div className="app-section-head shelf-section-head">
          <div>
            <h2 id="shelf-list-title">담은 책</h2>
            <p className="shelf-active-desc">{activeName}</p>
          </div>
          <div className="shelf-view-tools">
            <span className="shelf-muted">{activeBooks.length}권</span>
            <div className="shelf-view-switch" role="group" aria-label="서재 보기 방식">
              <button type="button" onClick={() => setViewMode('grid3')} aria-label="3열 카드 보기" aria-pressed={viewMode === 'grid3'} className={viewMode === 'grid3' ? 'is-active' : undefined}>
                <GridIcon columns={3} />
              </button>
              <button type="button" onClick={() => setViewMode('grid2')} aria-label="2열 카드 보기" aria-pressed={viewMode === 'grid2'} className={viewMode === 'grid2' ? 'is-active' : undefined}>
                <GridIcon columns={2} />
              </button>
              <button type="button" onClick={() => setViewMode('list')} aria-label="목록 보기" aria-pressed={viewMode === 'list'} className={viewMode === 'list' ? 'is-active' : undefined}>
                <ListIcon />
              </button>
            </div>
          </div>
        </div>
        {activeBooks.length ? (
          <div className={shelfItemsClassName}>
            {activeBooks.map((book) => (
              <article className="shelf-item" key={book.key}>
                <button className="shelf-item-link" type="button" onClick={() => onOpenDetail(book)} aria-label={`${book.title} 상세 보기`}>
                  <span className="shelf-item-cover">
                    <BookCover book={book} />
                  </span>
                  <span className="shelf-book-main">
                    <span className="shelf-book-title">{book.title}</span>
                    <span className="shelf-book-meta">
                      <span className="shelf-book-author">{book.author || '저자 정보 없음'}</span>
                      {book.publisher ? <span className="shelf-book-publisher">{book.publisher}</span> : null}
                      {savedAtLabel(book.savedAt) ? <span className="shelf-book-holding">{savedAtLabel(book.savedAt)}</span> : null}
                    </span>
                  </span>
                </button>
                <button
                  className="shelf-remove-button"
                  type="button"
                  onClick={() => activeShelf && onRemove(activeShelf.id, book.key)}
                  aria-label={`${book.title} ${activeName}에서 제거`}
                >
                  <span className="remove-icon" aria-hidden="true">
                    <TrashIcon />
                  </span>
                </button>
              </article>
            ))}
          </div>
        ) : (
          <div className="shelf-empty">
            <div className="shelf-empty-icon" aria-hidden="true">
              <BookmarkIcon />
            </div>
            <div className="shelf-empty-title">이 서재에 담은 책이 없습니다.</div>
            <button className="shelf-empty-link" type="button" onClick={onSearch}>
              검색하기
            </button>
          </div>
        )}
      </section>
    </main>
  );
}

function ShelfPickerSheet({
  book,
  shelves,
  onClose,
  onToggleShelf,
  onCreateShelf,
}: {
  book: SearchBook;
  shelves: BookShelf[];
  onClose: () => void;
  onToggleShelf: (shelfId: string, selected: boolean) => void;
  onCreateShelf: (name: string) => void;
}) {
  const [newShelfName, setNewShelfName] = useState('');

  function submitNewShelf(event: FormEvent) {
    event.preventDefault();
    onCreateShelf(newShelfName);
    setNewShelfName('');
  }

  return (
    <>
      <div className="sheet-overlay show" onClick={onClose} />
      <section className="shelf-picker-sheet show" role="dialog" aria-modal="true" aria-labelledby="shelf-picker-title">
        <div className="sheet-header">
          <div>
            <h2 id="shelf-picker-title">서재 선택</h2>
            <p className="sheet-subtitle">{book.title}</p>
          </div>
          <button className="btn-link" type="button" onClick={onClose} aria-label="서재 선택 닫기">
            닫기
          </button>
        </div>

        <div className="shelf-picker-options" aria-label="담을 서재">
          {shelves.map((shelf) => {
            const checked = isBookInShelf(book, shelf);
            return (
              <label className="shelf-picker-option" key={shelf.id}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(event) => onToggleShelf(shelf.id, event.target.checked)}
                  aria-label={`${shelf.name} ${checked ? '선택됨' : '선택 안 됨'}`}
                />
                <span className="shelf-picker-name">{shelf.name}</span>
                <span className="shelf-picker-count">{shelf.books.length}권</span>
              </label>
            );
          })}
        </div>

        <form className="shelf-create-form shelf-picker-create" onSubmit={submitNewShelf}>
          <label className="sr-only" htmlFor="picker-new-shelf-name">
            새 서재 이름
          </label>
          <input
            id="picker-new-shelf-name"
            value={newShelfName}
            onChange={(event) => setNewShelfName(event.target.value)}
            maxLength={18}
            placeholder="새 서재 이름"
          />
          <button type="submit">추가</button>
        </form>
      </section>
    </>
  );
}

function NavIcon({ view }: { view: View }) {
  if (view === 'home') return <HomeIcon />;
  if (view === 'shelf') return <BookmarkIcon />;
  return <SearchIcon size={22} />;
}

function BottomNav({ view, onChange }: { view: View; onChange: (view: View) => void }) {
  const tabs: Array<{ view: View; label: string; center?: boolean }> = [
    { view: 'home', label: '홈' },
    { view: 'search', label: '검색', center: true },
    { view: 'shelf', label: '서재' },
  ];
  return (
    <nav className="bottom-nav bottom-nav-app" aria-label="주요 화면">
      {tabs.map((tab) => (
        <button
          type="button"
          key={tab.view}
          className={`${view === tab.view ? 'is-active ' : ''}${tab.center ? 'nav-item-search ' : ''}nav-item nav-item-${tab.view}`}
          onClick={() => onChange(tab.view)}
          aria-label={tab.label}
        >
          <span className="nav-icon" aria-hidden="true">
            <NavIcon view={tab.view} />
          </span>
          <span className="nav-label">{tab.label}</span>
        </button>
      ))}
    </nav>
  );
}

export default function App() {
  const [view, setView] = useState<View>('home');
  const [detailBackView, setDetailBackView] = useState<View>('search');
  const [selectedBook, setSelectedBook] = useState<SearchBook | null>(null);
  const [searchSeed, setSearchSeed] = useState<SearchSeed>(null);
  const [shelves, setShelves] = useState<BookShelf[]>(() => getShelves());
  const [activeShelfId, setActiveShelfId] = useState('default');
  const [shelfSheetBook, setShelfSheetBook] = useState<SearchBook | null>(null);

  useEffect(() => {
    saveShelves(shelves);
  }, [shelves]);

  useEffect(() => {
    if (!shelves.some((shelf) => shelf.id === activeShelfId)) {
      setActiveShelfId(shelves[0]?.id || 'default');
    }
  }, [activeShelfId, shelves]);

  const activeView = selectedBook && view === 'detail' ? 'detail' : view;

  function openDetail(book: SearchBook) {
    setDetailBackView(view === 'detail' ? 'search' : view);
    setSelectedBook(book);
    setView('detail');
    window.scrollTo({ top: 0 });
  }

  function toggleShelf(book: SearchBook) {
    setShelfSheetBook(book);
  }

  function toggleBookInShelf(shelfId: string, book: SearchBook, selected: boolean) {
    setShelves((current) => current.map((shelf) => (shelf.id === shelfId ? setBookInShelf(book, shelf, selected) : shelf)));
  }

  function createNewShelf(name: string, book?: SearchBook) {
    const nextShelf = createShelf(name, shelves);
    const shelfToSave = book ? setBookInShelf(book, nextShelf, true) : nextShelf;
    setShelves((current) => [...current, shelfToSave]);
    setActiveShelfId(nextShelf.id);
  }

  function renameShelf(shelfId: string, name: string) {
    const cleanName = name.trim();
    if (!cleanName) return;
    setShelves((current) =>
      current.map((shelf) =>
        shelf.id === shelfId
          ? {
              ...shelf,
              name: cleanName,
              updatedAt: new Date().toISOString(),
            }
          : shelf,
      ),
    );
  }

  function clearShelf(shelfId: string) {
    setShelves((current) =>
      current.map((shelf) =>
        shelf.id === shelfId
          ? {
              ...shelf,
              books: [],
              updatedAt: new Date().toISOString(),
            }
          : shelf,
      ),
    );
  }

  function deleteShelf(shelfId: string) {
    const targetShelf = shelves.find((shelf) => shelf.id === shelfId);
    if (!targetShelf || targetShelf.isDefault || shelves.length <= 1) return;
    const nextShelves = shelves.filter((shelf) => shelf.id !== shelfId);
    setShelves(nextShelves);
    if (activeShelfId === shelfId) {
      setActiveShelfId(nextShelves[0]?.id || 'default');
    }
  }

  function removeShelfBook(shelfId: string, key: string) {
    setShelves((current) =>
      current.map((shelf) =>
        shelf.id === shelfId
          ? {
              ...shelf,
              books: removeBook(key, shelf.books),
              updatedAt: new Date().toISOString(),
            }
          : shelf,
      ),
    );
  }

  function changeView(nextView: View) {
    if (nextView !== 'detail') {
      setSelectedBook(null);
    }
    setView(nextView);
    window.scrollTo({ top: 0 });
  }

  function startSearch(query = '') {
    const cleanQuery = query.trim();
    setSelectedBook(null);
    if (cleanQuery) {
      setSearchSeed({ query: cleanQuery, token: Date.now() });
    }
    setView('search');
    window.scrollTo({ top: 0 });
  }

  return (
    <div className="app-shell">
      {activeView === 'home' ? <HomeView onSearch={startSearch} /> : null}
      {activeView === 'search' ? (
        <SearchView shelves={shelves} onOpenDetail={openDetail} onToggleShelf={toggleShelf} searchSeed={searchSeed} />
      ) : null}
      {activeView === 'detail' && selectedBook ? (
        <DetailView book={selectedBook} shelves={shelves} onBack={() => changeView(detailBackView)} onToggleShelf={toggleShelf} />
      ) : null}
      {activeView === 'shelf' ? (
        <ShelfView
          shelves={shelves}
          activeShelfId={activeShelfId}
          onSelectShelf={setActiveShelfId}
          onCreateShelf={createNewShelf}
          onRenameShelf={renameShelf}
          onClearShelf={clearShelf}
          onDeleteShelf={deleteShelf}
          onOpenDetail={openDetail}
          onRemove={removeShelfBook}
          onSearch={() => startSearch()}
        />
      ) : null}
      {shelfSheetBook ? (
        <ShelfPickerSheet
          book={shelfSheetBook}
          shelves={shelves}
          onClose={() => setShelfSheetBook(null)}
          onToggleShelf={(shelfId, selected) => toggleBookInShelf(shelfId, shelfSheetBook, selected)}
          onCreateShelf={(name) => createNewShelf(name, shelfSheetBook)}
        />
      ) : null}
      <BottomNav view={activeView === 'detail' ? detailBackView : activeView} onChange={changeView} />
    </div>
  );
}
