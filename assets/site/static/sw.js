// Service worker for the REFLEC BEAT plus chart browser. It makes the site installable as a
// standalone app and able to work offline. An install prompt needs a service worker with a fetch
// handler, and the cache lets a tune already looked at open again with no network.
const CACHE = 'rbp-charts-v1';

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  );
});

const store = (request, response) => {
  if (response.ok) {
    void caches.open(CACHE).then((cache) => cache.put(request, response));
  }
};

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET' || new URL(request.url).origin !== self.location.origin) {
    return;
  }
  // A navigation is served network-first, and a new build is therefore picked up. It falls back to
  // the cached shell, and a deep link therefore still opens with no network. Everything else is
  // served cache-first. The script and stylesheet include a content hash in their file name, and a
  // chart never changes.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          store(request, response.clone());
          return response;
        })
        .catch(() => caches.match(request).then((hit) => hit || caches.match('index.html'))),
    );
    return;
  }
  event.respondWith(
    caches.match(request).then(
      (hit) =>
        hit ||
        fetch(request).then((response) => {
          store(request, response.clone());
          return response;
        }),
    ),
  );
});
