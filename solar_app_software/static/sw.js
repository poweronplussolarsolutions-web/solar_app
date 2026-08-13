const CACHE_NAME = 'poweronplus-v1';
const OFFLINE_URL = '/dashboard';

self.addEventListener('install', (e) => {
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    ).then(() => clients.claim())
  );
});

// Network-first for navigations, so users always see live project data;
// falls back to the last cached dashboard shell if fully offline.
self.addEventListener('fetch', (e) => {
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request)
        .then((res) => {
          if (e.request.method === 'GET' && res.ok) {
            const copy = res.clone();
            caches.open(CACHE_NAME)
              .then((c) => c.put(e.request, copy))
              .catch(() => {}); // never let a cache-write failure break navigation
          }
          return res;
        })
        .catch(() => caches.match(e.request).then((c) => c || caches.match(OFFLINE_URL)))
    );
  }
});

self.addEventListener('push', (e) => {
  let data = { title: 'Power On Plus', body: 'You have a new update.' };
  try {
    if (e.data) data = e.data.json();
  } catch (err) {
    if (e.data) data.body = e.data.text();
  }

  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      const focusedClient = list.find((c) => c.focused);

      if (focusedClient) {
        // App is open and focused, like WhatsApp Web with the window in front —
        // skip the OS popup and let the page render its own quiet in-app toast.
        focusedClient.postMessage({ type: 'IN_APP_NOTIFICATION', payload: data });
        return;
      }

      return self.registration.showNotification(data.title || 'Power On Plus', {
        body: data.body || '',
        icon: '/static/icons/icon-192.png',
        badge: '/static/icons/icon-192.png',
        data: { url: data.url || '/dashboard' },
        tag: data.tag || undefined,
        renotify: !!data.tag,
      });
    })
  );
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/dashboard';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if (client.url.includes(url) && 'focus' in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});