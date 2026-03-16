const CACHE_NAME = 'bus-rio-v1';
const ASSETS_TO_CACHE = [
  '/',
  '/assets/manifest.json',
  '/assets/icon-192.png',
  '/assets/icon-512.png'
];

// Install Event
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
});

// Activate Event
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.map(key => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    })
  );
});

// Fetch Event - Network First with Cache Fallback for API/HTML, Cache First for Static Assets
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  
  // Excluir rotas de API do Dash (_dash-*)
  if (url.pathname.includes('_dash-')) {
    return;
  }

  // Assets estáticos (Cache First)
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.match(event.request).then(response => {
        return response || fetch(event.request).then(fetchRes => {
          return caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, fetchRes.clone());
            return fetchRes;
          });
        });
      })
    );
    return;
  }

  // HTML Principal (Network First, fallback pro Cache offline)
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .catch(() => caches.match(event.request))
    );
  }
});
