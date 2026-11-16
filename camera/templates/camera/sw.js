{% autoescape off %}// 서비스 워커: 신호가 없어도 촬영 화면이 열리도록 화면 파일을 보관합니다.
const CACHE = 'momentcam-v1';
const ASSETS = ['/', {% for a in assets %}'{{ a }}'{% if not forloop.last %}, {% endif %}{% endfor %}];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ASSETS).catch(() => {})).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/media/') || url.pathname.startsWith('/admin/')) return;

  // 화면과 파일: 신호가 있으면 새것을 받고 보관, 없으면 보관해 둔 것을 씁니다.
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok && !res.redirected && (url.pathname === '/' || url.pathname.startsWith('/static/'))) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req).then((hit) => hit || (req.mode === 'navigate' ? caches.match('/') : Response.error())))
  );
});
{% endautoescape %}