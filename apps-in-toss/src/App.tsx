import { FormEvent, useEffect, useMemo, useState } from 'react';
import {
  apiErrorMessage,
  getBookDetail,
  getRecentReports,
  searchBooks,
  submitReport,
} from './api';
import { addBook, getShelf, isBookSaved, removeBook, saveShelf } from './storage';
import type { BookCounts, RecentReportsResponse, ReportPayload, SearchBook, SearchField, SearchFilters, ShelfBook } from './types';

type View = 'search' | 'detail' | 'shelf' | 'report';
type LoadState = 'idle' | 'loading' | 'done' | 'error';
type FilterTab = 'field' | 'provider' | 'library';

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

const reportCategories = ['오류', '검색 결과', '대출 상태', '화면', '기타'];

function countTotal(counts?: BookCounts) {
  return Number(counts?.total || 0);
}

function coverUrl(book: SearchBook) {
  return book.image_url || book.image_candidates?.find(Boolean) || '';
}

function libraryLabel(book: SearchBook) {
  const total = countTotal(book.counts);
  if (total > 0) return `${total}곳`;
  const libraries = book.libraries?.length || 0;
  return libraries ? `${libraries}곳` : '확인 필요';
}

function availabilityLabel(book: SearchBook) {
  const label = libraryLabel(book);
  return label === '확인 필요' ? label : `${label} 제공`;
}

function metaLabel(book: SearchBook) {
  return [book.author, book.publisher].filter(Boolean).join(' · ') || '도서 정보 확인 중';
}

function providerLabel(raw?: string) {
  const value = String(raw || '').trim();
  if (!value) return '기타';
  const lower = value.toLowerCase();
  if (value.includes('교보') || lower.includes('kyobo')) return '교보';
  if (lower.includes('yes24')) return 'YES24';
  return '기타';
}

function uniqueSorted(values: string[]) {
  return Array.from(new Set(values.filter(Boolean))).sort((a, b) => a.localeCompare(b, 'ko'));
}

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

function currentPageUrl() {
  return typeof window === 'undefined' ? '' : window.location.href;
}

function SearchIcon({ size = 18 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.3-4.3" />
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

function ReportIcon() {
  return (
    <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v5" />
      <path d="M12 16h.01" />
    </svg>
  );
}

function BackIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M15 18l-6-6 6-6" />
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
  const providers = platformLabels(book);
  const libraryStates = libraryStatusLabels(book);

  return (
    <article className="book-card">
      <button className="book-main" type="button" onClick={() => onDetail(book)}>
        <span className="book-cover">
          <BookCover book={book} />
        </span>
        <span className="book-info">
          <span className="book-title">{book.title}</span>
          <span className="book-meta">{metaLabel(book)}</span>
          <span className="book-subrow">
            <span className="book-count">{availabilityLabel(book)}</span>
            {providers.map((label) => (
              <span className="book-chip" key={label}>
                {label}
              </span>
            ))}
          </span>
          {libraryStates.length ? (
            <span className="library-preview">
              {libraryStates.map((label) => (
                <span key={label}>{label}</span>
              ))}
            </span>
          ) : null}
        </span>
      </button>
      <button
        className={saved ? 'result-shelf-btn is-saved' : 'result-shelf-btn'}
        type="button"
        onClick={() => onToggleShelf(book)}
        aria-label={saved ? `${book.title} 내 서재에서 빼기` : `${book.title} 내 서재에 담기`}
      >
        <BookmarkIcon />
      </button>
    </article>
  );
}

function SearchView({
  shelf,
  onOpenDetail,
  onToggleShelf,
}: {
  shelf: ShelfBook[];
  onOpenDetail: (book: SearchBook) => void;
  onToggleShelf: (book: SearchBook) => void;
}) {
  const [query, setQuery] = useState('');
  const [field, setField] = useState<SearchField>('title_author');
  const [draftField, setDraftField] = useState<SearchField>('title_author');
  const [state, setState] = useState<LoadState>('idle');
  const [results, setResults] = useState<SearchBook[]>([]);
  const [total, setTotal] = useState(0);
  const [message, setMessage] = useState('');
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

  const providerOptions = filterProviders;
  const libraryOptions = filterLibraries;
  const activeFilterCount = selectedProviders.length + selectedLibraries.length + (field === 'title_author' ? 0 : 1);

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
    if (state === 'loading') return '실시간으로 확인하고 있습니다.';
    if (state !== 'done') return '';
    if (!results.length) return message || '검색 결과가 없습니다.';
    const totalLabel = Number(total || results.length).toLocaleString();
    const narrowed = activeFilterCount > 0 || (refineEnabled && refineQuery.trim());
    if (narrowed) {
      return `${displayedResults.length.toLocaleString()}권 표시 · 전체 ${totalLabel}권`;
    }
    return `'${query.trim()}' 검색 결과 ${totalLabel}권`;
  }, [activeFilterCount, displayedResults.length, message, refineEnabled, refineQuery, results.length, state, total]);

  async function runSearch(
    nextQuery: string,
    nextField = field,
    filters: SearchFilters = { providers: selectedProviders, libraries: selectedLibraries },
    options: { resetRefine?: boolean } = {},
  ) {
    const cleanQuery = nextQuery.trim();
    if (!cleanQuery) {
      setMessage('검색어를 입력해 주세요.');
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
    setResults([]);
    setTotal(0);
    try {
      const data = await searchBooks(cleanQuery, nextField, nextFilters);
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

  function toggleDraftProvider(provider: string) {
    setDraftProviders((current) => (current.includes(provider) ? current.filter((item) => item !== provider) : [...current, provider]));
  }

  function toggleDraftLibrary(library: string) {
    setDraftLibraries((current) => (current.includes(library) ? current.filter((item) => item !== library) : [...current, library]));
  }

  return (
    <main className="screen search-screen">
      <form className="search-form" onSubmit={handleSearch}>
        <div className="search-top-row">
          <div className="search-top-bar">
            <span className="search-top-icon" aria-hidden="true">
              <SearchIcon />
            </span>
            <label className="sr-only" htmlFor="query">
              검색어
            </label>
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
            <button className="search-submit" type="submit" disabled={state === 'loading'} aria-label="검색">
              <SearchIcon size={16} />
            </button>
          </div>
          <button className="app-icon-button filter-summary" type="button" onClick={openFilterSheet} aria-label="필터">
            <FilterIcon />
            {activeFilterCount ? <span className="filter-count">{activeFilterCount}</span> : null}
          </button>
        </div>

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
      </form>

      {statusText || message ? (
        <section className="summary-row" aria-live="polite">
          <div className={state === 'error' ? 'status error' : 'status'}>{state === 'error' ? message : statusText || message}</div>
        </section>
      ) : null}

      <section className="book-list">
        {state === 'idle' && !message ? (
          <section className="search-empty-state" aria-live="polite">
            <div className="search-empty-icon" aria-hidden="true">
              <SearchIcon size={24} />
            </div>
            <p>책 제목이나 저자를 검색하세요.</p>
          </section>
        ) : null}
        {state === 'loading' ? <div className="panel-note">실시간으로 확인하고 있습니다.</div> : null}
        {state === 'done' && results.length > 0 && displayedResults.length === 0 ? (
          <div className="result-message empty">선택한 조건에 맞는 결과가 없습니다.</div>
        ) : null}
        {state === 'done' && results.length === 0 ? <div className="result-message empty">{message}</div> : null}
        {state === 'error' ? <div className="result-message error">{message}</div> : null}
        {displayedResults.map((book) => (
          <BookCard
            key={`${book.title}-${book.author}-${book.publisher}`}
            book={book}
            saved={isBookSaved(book, shelf)}
            onDetail={onOpenDetail}
            onToggleShelf={onToggleShelf}
          />
        ))}
      </section>

      <div className={filterOpen ? 'sheet-overlay show' : 'sheet-overlay'} onClick={closeFilterSheet} />
      <section className={filterOpen ? 'filter-sheet show' : 'filter-sheet'} aria-hidden={!filterOpen}>
        <div className="sheet-header">
          <h2>필터</h2>
          <button className="btn-link" type="button" onClick={closeFilterSheet}>
            닫기
          </button>
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
  shelf,
  onBack,
  onToggleShelf,
}: {
  book: SearchBook;
  shelf: ShelfBook[];
  onBack: () => void;
  onToggleShelf: (book: SearchBook) => void;
}) {
  const [detail, setDetail] = useState<SearchBook>(book);
  const [state, setState] = useState<LoadState>('loading');
  const [message, setMessage] = useState('');
  const saved = isBookSaved(detail, shelf);

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

  const libraries = detail.libraries || [];

  return (
    <main className="screen detail-screen">
      <div className="top-actions">
        <button className="app-icon-button" type="button" onClick={onBack} aria-label="이전 화면">
          <BackIcon />
        </button>
        <span className="top-title">상세</span>
        <button
          className={saved ? 'app-icon-button shelf-action is-active' : 'app-icon-button shelf-action'}
          type="button"
          onClick={() => onToggleShelf(detail)}
          aria-label={saved ? '내 서재에서 빼기' : '내 서재에 담기'}
        >
          <BookmarkIcon />
        </button>
      </div>

      <section className="detail-card detail-head">
        <span className="detail-cover">
          <BookCover book={detail} />
        </span>
        <div>
          <p className="detail-count">{availabilityLabel(detail)}</p>
          <h1>{detail.title}</h1>
          <p>{metaLabel(detail)}</p>
        </div>
      </section>

      {state === 'loading' ? <div className="panel-note">상세 정보를 확인하고 있습니다.</div> : null}
      {state === 'error' ? <div className="panel-note error">{message}</div> : null}

      <section className="count-strip" aria-label="제공 현황">
        <span>
          <b>{libraryLabel(detail)}</b>
          {' '}제공
        </span>
        <span>
          교보 <b>{detail.counts?.kyobo || 0}</b>
        </span>
        <span>
          YES24 <b>{detail.counts?.yes24 || 0}</b>
        </span>
        <span>
          기타 <b>{detail.counts?.other || 0}</b>
        </span>
      </section>

      <section className="library-list">
        <h2>도서관</h2>
        {libraries.length ? (
          libraries.map((library, index) => (
            <article className="library-row" key={`${library.code || library.name}-${index}`}>
              <div>
                <strong>{library.short || library.name || '도서관'}</strong>
                <span>{[providerLabel(library.provider || library.platform_code), library.service_type].filter(Boolean).join(' · ') || '전자책 서비스'}</span>
              </div>
              <span className="badge">{library.status_label || '확인'}</span>
            </article>
          ))
        ) : (
          <div className="panel-note">도서관별 상세 정보가 아직 없습니다.</div>
        )}
      </section>
    </main>
  );
}

function ShelfView({
  shelf,
  onOpenDetail,
  onRemove,
}: {
  shelf: ShelfBook[];
  onOpenDetail: (book: SearchBook) => void;
  onRemove: (key: string) => void;
}) {
  return (
    <main className="screen shelf-screen">
      <section className="section-head shelf-head">
        <div>
          <h1>내 서재</h1>
          <p>{shelf.length}권 저장됨</p>
        </div>
      </section>

      <section className="book-list">
        {shelf.length ? (
          shelf.map((book) => (
            <article className="book-card shelf-card" key={book.key}>
              <button className="book-main" type="button" onClick={() => onOpenDetail(book)}>
                <span className="book-cover">
                  <BookCover book={book} />
                </span>
                <span className="book-info">
                  <span className="book-title">{book.title}</span>
                  <span className="book-meta">{metaLabel(book)}</span>
                </span>
              </button>
              <button className="remove-button" type="button" onClick={() => onRemove(book.key)}>
                빼기
              </button>
            </article>
          ))
        ) : (
          <div className="app-empty">검색 결과에서 책을 담으면 이곳에 보관됩니다.</div>
        )}
      </section>
    </main>
  );
}

function ReportView() {
  const [recent, setRecent] = useState<RecentReportsResponse | null>(null);
  const [recentMessage, setRecentMessage] = useState('최근 접수 상태를 확인하고 있습니다.');
  const [payload, setPayload] = useState<ReportPayload>({
    category: '오류',
    message: '',
    page_url: currentPageUrl(),
  });
  const [submitState, setSubmitState] = useState<LoadState>('idle');
  const [submitMessage, setSubmitMessage] = useState('');

  useEffect(() => {
    let alive = true;
    getRecentReports()
      .then((data) => {
        if (!alive) return;
        setRecent(data);
        setRecentMessage(data.unavailable ? '최근 접수 목록 동기화가 지연되고 있습니다.' : '최근 접수 상태를 확인했습니다.');
      })
      .catch((error) => {
        if (!alive) return;
        setRecentMessage(apiErrorMessage(error, '최근 접수 상태를 불러오지 못했습니다.'));
      });
    return () => {
      alive = false;
    };
  }, []);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const message = payload.message.trim();
    if (message.length < 5) {
      setSubmitState('error');
      setSubmitMessage('문제를 조금 더 적어 주세요.');
      return;
    }
    setSubmitState('loading');
    setSubmitMessage('신고를 보내는 중입니다.');
    try {
      const data = await submitReport({ ...payload, message });
      setPayload({ category: '오류', message: '', page_url: currentPageUrl() });
      setSubmitState('done');
      setSubmitMessage(data.message || '신고를 접수했습니다.');
    } catch (error) {
      setSubmitState('error');
      setSubmitMessage(apiErrorMessage(error, '앱 안에서 신고를 보내지 못했습니다.'));
    }
  }

  return (
    <main className="screen report-screen">
      <section className="section-head report-head">
        <div>
          <h1>신고</h1>
          <p>검색 결과나 화면 문제를 남겨 주세요.</p>
        </div>
        <span className="soft-badge">{recent?.count_label || '확인 중'}</span>
      </section>
      <p className={recent?.unavailable ? 'inline-note error' : 'inline-note'}>{recentMessage}</p>

      <form className="report-form report-card" onSubmit={handleSubmit}>
        <fieldset className="category-field">
          <legend>분류</legend>
          <div className="pill-group" aria-label="신고 분류">
            {reportCategories.map((category) => (
              <button
                key={category}
                type="button"
                className={payload.category === category ? 'selected' : ''}
                onClick={() => setPayload({ ...payload, category })}
              >
                {category}
              </button>
            ))}
          </div>
        </fieldset>
        <label>
          내용
          <textarea
            value={payload.message}
            onChange={(event) => setPayload({ ...payload, message: event.target.value })}
            maxLength={1200}
            rows={6}
            placeholder="무엇이 불편했는지 적어 주세요."
          />
        </label>
        <input type="hidden" value={payload.page_url || ''} readOnly />
        <button className="btn-primary full" type="submit" disabled={submitState === 'loading'}>
          {submitState === 'loading' ? '보내는 중' : '보내기'}
        </button>
      </form>
      {submitMessage ? <div className={submitState === 'error' ? 'panel-note error' : 'panel-note'}>{submitMessage}</div> : null}
    </main>
  );
}

function NavIcon({ view }: { view: View }) {
  if (view === 'shelf') return <BookmarkIcon />;
  if (view === 'report') return <ReportIcon />;
  return <SearchIcon size={22} />;
}

function BottomNav({ view, onChange }: { view: View; onChange: (view: View) => void }) {
  const tabs: Array<{ view: View; label: string }> = [
    { view: 'search', label: '검색' },
    { view: 'shelf', label: '서재' },
    { view: 'report', label: '신고' },
  ];
  return (
    <nav className="bottom-nav" aria-label="주요 화면">
      {tabs.map((tab) => (
        <button
          type="button"
          key={tab.view}
          className={view === tab.view ? 'active' : ''}
          onClick={() => onChange(tab.view)}
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
  const [view, setView] = useState<View>('search');
  const [detailBackView, setDetailBackView] = useState<View>('search');
  const [selectedBook, setSelectedBook] = useState<SearchBook | null>(null);
  const [shelf, setShelf] = useState<ShelfBook[]>(() => getShelf());

  useEffect(() => {
    saveShelf(shelf);
  }, [shelf]);

  const activeView = selectedBook && view === 'detail' ? 'detail' : view;

  function openDetail(book: SearchBook) {
    setDetailBackView(view === 'detail' ? 'search' : view);
    setSelectedBook(book);
    setView('detail');
    window.scrollTo({ top: 0 });
  }

  function toggleShelf(book: SearchBook) {
    const saved = isBookSaved(book, shelf);
    setShelf(saved ? removeBook(book, shelf) : addBook(book, shelf));
  }

  function removeShelfBook(key: string) {
    setShelf(removeBook(key, shelf));
  }

  function changeView(nextView: View) {
    if (nextView !== 'detail') {
      setSelectedBook(null);
    }
    setView(nextView);
    window.scrollTo({ top: 0 });
  }

  return (
    <div className="app-shell">
      {activeView === 'search' ? <SearchView shelf={shelf} onOpenDetail={openDetail} onToggleShelf={toggleShelf} /> : null}
      {activeView === 'detail' && selectedBook ? (
        <DetailView book={selectedBook} shelf={shelf} onBack={() => changeView(detailBackView)} onToggleShelf={toggleShelf} />
      ) : null}
      {activeView === 'shelf' ? <ShelfView shelf={shelf} onOpenDetail={openDetail} onRemove={removeShelfBook} /> : null}
      {activeView === 'report' ? <ReportView /> : null}
      <BottomNav view={activeView === 'detail' ? detailBackView : activeView} onChange={changeView} />
    </div>
  );
}
