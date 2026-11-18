{% autoescape off %}// 서비스 워커: 서버가 잠들어 있거나 신호가 없어도 촬영 화면이 바로 열리게 합니다.
// - 촬영 화면('/')과 화면 파일은 보관해 둔 것을 먼저 보여 주고, 뒤에서 새것으로 바꿔 둡니다.
// - 사진 올리기(/api/)는 여기서 건드리지 않습니다. (휴대폰 안 대기열이 맡습니다)
const CACHE = 'momentcam-v3';
// '/'(촬영 화면)는 여기 넣지 않습니다. 로그인 전에는 로그인 화면으로 넘어가므로, 로그인한 뒤 열릴 때 보관합니다.
const ASSETS = [{% for a in assets %}'{{ a }}'{% if not forloop.last %}, {% endif %}{% endfor %}];

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

function refresh(req, cacheKey) {
  return fetch(req).then((res) => {
    // 로그인 화면으로 넘어간 응답(redirected)은 보관하지 않습니다.
    if (res.ok && !res.redirected) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(cacheKey || req, copy));
    }
    return res;
  });
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/media/') || url.pathname.startsWith('/admin/')) return;

  const isCamera = req.mode === 'navigate' && url.pathname === '/';
  const isStatic = url.pathname.startsWith('/static/');

  if (isCamera || isStatic) {
    // 보관본이 있으면 바로 보여 주고(잠든 서버를 기다리지 않음), 뒤에서 새것을 받아 둡니다.
    const key = isCamera ? '/' : req;
    event.respondWith(
      caches.match(key).then((hit) => {
        const fresh = refresh(req, key).catch(() => null);
        if (hit) {
          event.waitUntil(fresh);
          return hit;
        }
        return fresh.then((res) => res || Response.error());
      })
    );
    return;
  }

  // 그 밖의 화면(오늘, 설정): 서버 우선, 안 되면 보관본, 그것도 없으면 촬영 화면.
  event.respondWith(
    fetch(req).catch(() =>
      caches.match(req).then((hit) => hit || (req.mode === 'navigate' ? caches.match('/') : Response.error()))
    )
  );
});
{% endautoescape %}