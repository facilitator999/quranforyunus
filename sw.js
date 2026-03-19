/* Service Worker for Quran for Yunus - PWA install + offline Quran text */
const CACHE = 'quranforyunus-v7';
const PAGE_COUNT = 604;

function assetUrls(scope) {
  const u = (path) => new URL(path.replace(/^\//, ''), scope).href;
  return {
    static: [
      u('index.html'),
      u('manifest.json'),
      u('data/full_quran.json'),
      u('fonts/UthmanicHafs1Ver18.woff2'),
      u('fonts/UthmanicHafs1Ver18.ttf'),
      u('fonts/QCF_SurahHeader_COLOR-Regular.ttf'),
      u('logo.png'),
      u('logo-white.png')
    ],
    pages: Array.from({ length: PAGE_COUNT }, (_, i) => u('data/pages/' + (i + 1) + '.json'))
  };
}

const CDN_FONTS = [
  'https://static-cdn.tarteel.ai/qul/fonts/nastaleeq/Hanafi/normal-v4.2.2/with-waqf-lazmi/font.woff2',
  'https://static-cdn.tarteel.ai/qul/fonts/nastaleeq/Hanafi/normal-v4.2.2/with-waqf-lazmi/font.ttf'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    self.registration.ready.then(() => {
      const { static: STATIC_ASSETS, pages } = assetUrls(self.registration.scope);
      return caches.open(CACHE).then((c) => {
        return Promise.allSettled([
          c.addAll(STATIC_ASSETS),
          c.addAll(pages),
          ...CDN_FONTS.map((url) =>
            fetch(url, { mode: 'cors' }).then((r) => r.ok && c.put(new Request(url, { method: 'GET' }), r)).catch(() => {})
          )
        ]);
      });
    }).then(() => self.skipWaiting()).catch(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  const url = event.request.url;
  const parsed = new URL(url);
  const isSameOrigin = parsed.origin === self.location.origin;
  const path = parsed.pathname;
  const isOurs =
    isSameOrigin &&
    (path.includes('/data/') ||
      path.includes('/fonts/') ||
      /index\.html$/i.test(path) ||
      path === '/' ||
      /\/$/.test(path));
  const isCdnFont = CDN_FONTS.some((f) => url === f || url.startsWith(f.split('?')[0]));

  if (isOurs || isCdnFont) {
    const isFont = path.includes('.woff') || path.includes('.woff2') || path.includes('.ttf') || isCdnFont;
    const fontKey = new Request(parsed.origin + parsed.pathname, { method: 'GET' });
    event.respondWith(
      isFont
        ? caches.match(fontKey, { ignoreSearch: true }).then((cached) => {
            if (cached) return cached;
            return fetch(event.request, isCdnFont ? { mode: 'cors' } : {}).then((res) => {
              if (res.ok) caches.open(CACHE).then((c) => c.put(fontKey, res.clone()));
              return res;
            }).catch(() => caches.match(fontKey, { ignoreSearch: true }));
          })
        : fetch(event.request)
            .then((res) => {
              if (res.ok) {
                const clone = res.clone();
                caches.open(CACHE).then((c) => c.put(event.request, clone));
              }
              return res;
            })
            .catch(() => caches.match(event.request, { ignoreSearch: true }))
    );
  }
});
