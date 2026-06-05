import { FormEvent, useEffect, useState } from 'react';
import {
  apiErrorMessage,
  getBookDetail,
  getRecentReports,
  searchBooks,
  submitReport,
} from './api';
import { addBook, getShelf, isBookSaved, removeBook, saveShelf } from './storage';
import type { BookCounts, RecentReportsResponse, ReportPayload, SearchBook, SearchField, ShelfBook } from './types';

type View = 'search' | 'detail' | 'shelf' | 'report';
type LoadState = 'idle' | 'loading' | 'done' | 'error';

const fieldOptions: Array<{ value: SearchField; label: string }> = [
  { value: 'title_author', label: '전체' },
  { value: 'title', label: '제목' },
  { value: 'author', label: '저자' },
  { value: 'publisher', label: '출판사' },
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

function platformLabels(book: SearchBook) {
  const labels = new Set<string>();
  (book.libraries || []).forEach((library) => {
    const provider = library.provider || library.platform_code || library.service_type;
    if (provider) labels.add(provider);
  });
  return Array.from(labels).slice(0, 3);
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
    <article className="book-card">
      <button className="book-main" type="button" onClick={() => onDetail(book)}>
        <span className="book-cover">
          <BookCover book={book} />
        </span>
        <span className="book-info">
          <span className="book-title">{book.title}</span>
          <span className="book-meta">{[book.author, book.publisher].filter(Boolean).join(' · ') || '정보 확인 중'}</span>
          <span className="book-badges">
            <span className="badge strong">{libraryLabel(book)}</span>
            {platformLabels(book).map((label) => (
              <span className="badge" key={label}>
                {label}
              </span>
            ))}
          </span>
        </span>
      </button>
      <button className={saved ? 'small-button active' : 'small-button'} type="button" onClick={() => onToggleShelf(book)}>
        {saved ? '저장됨' : '담기'}
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
  const [state, setState] = useState<LoadState>('idle');
  const [results, setResults] = useState<SearchBook[]>([]);
  const [total, setTotal] = useState(0);
  const [message, setMessage] = useState('');

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    const cleanQuery = query.trim();
    if (!cleanQuery) {
      setMessage('검색어를 입력해 주세요.');
      return;
    }
    setState('loading');
    setMessage('');
    try {
      const data = await searchBooks(cleanQuery, field);
      const items = Array.isArray(data.items) ? data.items : [];
      setResults(items);
      setTotal(Number(data.total || items.length || 0));
      setState('done');
      setMessage(items.length ? '' : '검색 결과가 없습니다.');
    } catch (error) {
      setResults([]);
      setTotal(0);
      setState('error');
      setMessage(apiErrorMessage(error, '검색 결과를 불러오지 못했습니다.'));
    }
  }

  return (
    <main className="screen">
      <section className="hero">
        <p className="eyebrow">Soulib</p>
        <h1>서울 전자책 찾기</h1>
        <p>서울 공공 전자책 서비스를 한 번에 확인합니다.</p>
      </section>

      <form className="search-form" onSubmit={handleSearch}>
        <label className="search-label" htmlFor="query">
          검색어
        </label>
        <div className="search-row">
          <input
            id="query"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="책 제목이나 저자"
            enterKeyHint="search"
          />
          <button className="primary-button" type="submit" disabled={state === 'loading'}>
            {state === 'loading' ? '검색 중' : '검색'}
          </button>
        </div>
        <div className="segmented" aria-label="검색 범위">
          {fieldOptions.map((option) => (
            <button
              key={option.value}
              type="button"
              className={field === option.value ? 'selected' : ''}
              onClick={() => setField(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </form>

      <section className="result-head" aria-live="polite">
        {state === 'done' && results.length > 0 ? <h2>{total}권</h2> : <h2>검색</h2>}
        {message ? <p className={state === 'error' ? 'status error' : 'status'}>{message}</p> : null}
      </section>

      <section className="book-list">
        {state === 'loading' ? <div className="panel-note">실시간으로 확인하고 있습니다.</div> : null}
        {results.map((book) => (
          <BookCard
            key={`${book.title}-${book.author}-${book.publisher}`}
            book={book}
            saved={isBookSaved(book, shelf)}
            onDetail={onOpenDetail}
            onToggleShelf={onToggleShelf}
          />
        ))}
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
        <button className="text-button" type="button" onClick={onBack}>
          이전
        </button>
        <button className={saved ? 'small-button active' : 'small-button'} type="button" onClick={() => onToggleShelf(detail)}>
          {saved ? '저장됨' : '서재 담기'}
        </button>
      </div>

      <section className="detail-head">
        <span className="detail-cover">
          <BookCover book={detail} />
        </span>
        <div>
          <p className="eyebrow">{libraryLabel(detail)}</p>
          <h1>{detail.title}</h1>
          <p>{[detail.author, detail.publisher].filter(Boolean).join(' · ') || '도서 정보 확인 중'}</p>
        </div>
      </section>

      {state === 'loading' ? <div className="panel-note">상세 정보를 확인하고 있습니다.</div> : null}
      {state === 'error' ? <div className="panel-note error">{message}</div> : null}

      <section className="count-strip" aria-label="제공 현황">
        <span>
          <b>{detail.counts?.kyobo || 0}</b>
          교보
        </span>
        <span>
          <b>{detail.counts?.yes24 || 0}</b>
          YES24
        </span>
        <span>
          <b>{detail.counts?.other || 0}</b>
          기타
        </span>
      </section>

      <section className="library-list">
        <h2>도서관</h2>
        {libraries.length ? (
          libraries.map((library, index) => (
            <article className="library-row" key={`${library.code || library.name}-${index}`}>
              <div>
                <strong>{library.short || library.name || '도서관'}</strong>
                <span>{[library.provider, library.service_type].filter(Boolean).join(' · ') || '전자책 서비스'}</span>
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
    <main className="screen">
      <section className="section-head">
        <div>
          <p className="eyebrow">내 서재</p>
          <h1>{shelf.length}권</h1>
        </div>
      </section>

      <section className="book-list">
        {shelf.length ? (
          shelf.map((book) => (
            <article className="book-card" key={book.key}>
              <button className="book-main" type="button" onClick={() => onOpenDetail(book)}>
                <span className="book-cover">
                  <BookCover book={book} />
                </span>
                <span className="book-info">
                  <span className="book-title">{book.title}</span>
                  <span className="book-meta">{[book.author, book.publisher].filter(Boolean).join(' · ') || '정보 확인 중'}</span>
                </span>
              </button>
              <button className="small-button" type="button" onClick={() => onRemove(book.key)}>
                빼기
              </button>
            </article>
          ))
        ) : (
          <div className="panel-note">검색 결과에서 책을 담으면 이곳에 보관됩니다.</div>
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
    page_url: '',
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
      setPayload({ category: '오류', message: '', page_url: '' });
      setSubmitState('done');
      setSubmitMessage(data.message || '신고를 접수했습니다.');
    } catch (error) {
      setSubmitState('error');
      setSubmitMessage(apiErrorMessage(error, '앱 안에서 신고를 보내지 못했습니다.'));
    }
  }

  return (
    <main className="screen">
      <section className="section-head">
        <div>
          <p className="eyebrow">오류 신고</p>
          <h1>문제 남기기</h1>
        </div>
        <span className="badge">{recent?.count_label || '확인 중'}</span>
      </section>
      <div className={recent?.unavailable ? 'panel-note error' : 'panel-note'}>{recentMessage}</div>

      <form className="report-form" onSubmit={handleSubmit}>
        <label>
          분류
          <select value={payload.category} onChange={(event) => setPayload({ ...payload, category: event.target.value })}>
            {reportCategories.map((category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ))}
          </select>
        </label>
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
        <label>
          문제가 있던 화면
          <input
            value={payload.page_url || ''}
            onChange={(event) => setPayload({ ...payload, page_url: event.target.value })}
            placeholder="선택 입력"
            inputMode="url"
          />
        </label>
        <button className="primary-button full" type="submit" disabled={submitState === 'loading'}>
          {submitState === 'loading' ? '보내는 중' : '보내기'}
        </button>
      </form>
      {submitMessage ? <div className={submitState === 'error' ? 'panel-note error' : 'panel-note'}>{submitMessage}</div> : null}
    </main>
  );
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
          {tab.label}
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
      <BottomNav view={activeView} onChange={changeView} />
    </div>
  );
}
