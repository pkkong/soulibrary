export type SearchField = 'title_author' | 'title' | 'author' | 'publisher';

export type BookCounts = {
  kyobo?: number;
  yes24?: number;
  other?: number;
  total?: number;
};

export type LibraryStatusKind = 'kyobo' | 'dobong' | 'yes24' | 'bookcube' | 'gangnam' | 'eunpyeong' | 'seoul' | 'sen' | '';

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
  status_kind?: LibraryStatusKind;
  status_supported?: boolean;

  brcd?: string;
  goods_id?: string;
  content_id?: string;
  ctts_dvsn_code?: string;
  ctgr_id?: string;
  sntn_auth_code?: string;
  product_cd?: string;
  category_id?: string;
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

export type BookShelf = {
  id: string;
  name: string;
  books: ShelfBook[];
  createdAt: string;
  updatedAt: string;
  isDefault?: boolean;
};
