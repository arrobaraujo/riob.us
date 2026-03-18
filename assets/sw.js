const CACHE_NAME = 'bus-rio-v3';
const OFFLINE_URL = '/assets/offline.html';
const APP_SHELL_ASSETS = [
  '/',
  OFFLINE_URL,
  '/assets/manifest.json',
  '/assets/styles.css',
  '/assets/icon-192.png',
  '/assets/icon-512.png',
  '/assets/screenshot-wide.png',
  '/assets/screenshot-mobile.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache =>
      Promise.all(
        APP_SHELL_ASSETS.map(url =>
          cache.add(url).catch(() => null)
        )
      )
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.map(key => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
          return null;
        })
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') {
    return;
  }

  const url = new URL(event.request.url);
  const isDashDataRoute = url.pathname.startsWith('/_dash-');
  if (isDashDataRoute) {
    return;
  }

  const isSameOrigin = url.origin === self.location.origin;
  const isAsset = url.pathname.startsWith('/assets/');

  if (event.request.mode === 'navigate') {
    event.respondWith(networkFirstPage(event.request));
    return;
  }

  if (isSameOrigin && isAsset) {
    event.respondWith(staleWhileRevalidate(event.request));
    return;
  }

  if (isSameOrigin) {
    event.respondWith(networkFirstWithCacheFallback(event.request));
  }
});

async function networkFirstPage(request) {
  try {
    const networkResponse = await fetch(request);
    const cache = await caches.open(CACHE_NAME);
    cache.put(request, networkResponse.clone());
    return networkResponse;
  } catch (err) {
    const cachedPage = await caches.match(request);
    if (cachedPage) {
      return cachedPage;
    }

    const offlinePage = await caches.match(OFFLINE_URL);
    if (offlinePage) {
      return offlinePage;
    }

    return new Response('Sem conexao no momento.', {
      status: 503,
      headers: {'Content-Type': 'text/plain; charset=UTF-8'}
    });
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  const fetchPromise = fetch(request)
    .then(response => {
      if (response && response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  if (cached) {
    return cached;
  }

  const network = await fetchPromise;
  if (network) {
    return network;
  }

  return new Response('', {status: 504});
}

async function networkFirstWithCacheFallback(request) {
  try {
    const networkResponse = await fetch(request);
    const cache = await caches.open(CACHE_NAME);
    cache.put(request, networkResponse.clone());
    return networkResponse;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) {
      return cached;
    }
    return new Response('', {status: 504});
  }
}
