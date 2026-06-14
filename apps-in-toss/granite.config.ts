import { defineConfig } from '@apps-in-toss/web-framework/config';

export default defineConfig({
  appName: 'soulib',
  brand: {
    displayName: '전자도서관 통합검색',
    primaryColor: '#3182F6',
    icon: 'https://www.soulib.kr/static/img/app-icon-600.png',
  },
  web: {
    host: 'localhost',
    port: 5173,
    commands: {
      dev: 'vite dev',
      build: 'vite build',
    },
  },
  permissions: [],
  outdir: 'dist',
  webViewProps: {
    type: 'partner',
  },
});
