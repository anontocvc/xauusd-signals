// XAUUSD Signal System — Service Worker v1.0
// Enables: offline shell, background fetch, push-ready foundation

const CACHE_NAME   = 'xau-signals-v1';
const SHELL_ASSETS = [
  '/mobile',
  '/static/icon192.png',
  '/static/icon512.png',
  '/static/manifest.json',
];

// ── Install: cache the app shell ─────────────────────────────────────────────
self.addEventListener('install', event => {
  console.log('[SW] Installing...');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: clean old caches ────────────────────────────────────────────────
self.addEventListener('activate', event => {
  console.log('[SW] Activating...');
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// ── Fetch: network-first for API, cache-first for shell ──────────────────────
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // API calls — always network, never cache
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() =>
        new Response(
          JSON.stringify({ status: 'offline', error: 'Server not reachable' }),
          { headers: { 'Content-Type': 'application/json' } }
        )
      )
    );
    return;
  }

  // Shell assets — cache-first with network fallback
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        // Cache successful responses for shell assets
        if (response.ok && event.request.method === 'GET') {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => caches.match('/mobile'));
    })
  );
});

// ── Background Sync (when connection returns) ─────────────────────────────────
self.addEventListener('sync', event => {
  if (event.tag === 'sync-signals') {
    console.log('[SW] Background sync triggered');
    event.waitUntil(
      fetch('/api/analysis')
        .then(r => r.json())
        .then(data => {
          // Notify all open clients
          return self.clients.matchAll().then(clients => {
            clients.forEach(client => client.postMessage({ type: 'BG_UPDATE', data }));
          });
        })
        .catch(err => console.log('[SW] Sync failed:', err))
    );
  }
});

// ── Push Notifications ────────────────────────────────────────────────────────
self.addEventListener('push', event => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch(e) {}

  const title   = payload.title   || '⚡ XAUUSD Signal';
  const options = {
    body:    payload.body    || 'New trade signal detected',
    icon:    '/static/icon192.png',
    badge:   '/static/icon72.png',
    tag:     'xau-signal',
    renotify: true,
    vibrate: [200, 100, 200],
    data:    payload.data    || { url: '/mobile' },
    actions: [
      { action: 'view',    title: 'View Signal' },
      { action: 'dismiss', title: 'Dismiss'     },
    ]
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// ── Notification Click ────────────────────────────────────────────────────────
self.addEventListener('notificationclick', event => {
  event.notification.close();
  if (event.action === 'dismiss') return;

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then(clientList => {
        if (clientList.length > 0) {
          clientList[0].focus();
          clientList[0].navigate('/mobile');
        } else {
          clients.openWindow('/mobile');
        }
      })
  );
});

console.log('[SW] Service worker loaded');
