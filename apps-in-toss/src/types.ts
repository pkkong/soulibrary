export type SearchField = 'title_author' | 'title' | 'author' | 'publisher';

export type BookCounts = {
  kyobo?: number;
  yes24?: number;
  other?: number;
  total?: number;
};

export type LibraryItem = {
  code?: string;
  name?: string;
  short?: string;
  platform_code?: string;
  provider?: string;
  service_type?: string;
  homepage_url?: string;
  detail_url?: string;
  status_label?: string;
};

export type SearchBook = {
  book_id?: string | null;
  title: string;
  author?: string;
  publisher?: string;
  image_url?: string;
  image_candidates?: string[];
  counts?: BookCounts;
  libraries?: LibraryItem[];
  live_detail_key?: string;
  live_detail_url?: string;
  summary_url?: string;
};

export type LiveSearchResponse = {
  total?: number;
  items?: SearchBook[];
  filters?: SearchFilters;
  error?: string;
};

export type SearchFilters = {
  providers?: string[];
  libraries?: string[];
};

export type BookDetailResponse = {
  book?: SearchBook;
  counts?: BookCounts;
  live_detail_key?: string;
  error?: string;
};

export type ShelfBook = SearchBook & {
  key: string;
  savedAt: string;
};

export type RecentReportsResponse = {
  html?: string;
  count_label?: string;
  unavailable?: boolean;
};

export type ReportPayload = {
  category: string;
  message: string;
  page_url?: string;
};

export type ReportSummary = {
  id?: number;
  category?: string;
  message?: string;
  page_url?: string;
  issue_number?: number | null;
  issue_url?: string;
  status?: string;
  status_label?: string;
  created_at?: string;
  updated_at?: string;
};

export type CreateReportResponse = {
  ok?: boolean;
  message?: string;
  report?: ReportSummary | null;
  error?: string;
};
