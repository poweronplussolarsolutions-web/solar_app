const CACHE_NAME = 'poweronplus-v2';
const OFFLINE_URL = '/dashboard';


// =====================================================
// INSTALL
// =====================================================

self.addEventListener('install', (event) => {
  console.log('[SW] Installing service worker:', CACHE_NAME);

  self.skipWaiting();
});


// =====================================================
// ACTIVATE
// =====================================================

self.addEventListener('activate', (event) => {
  console.log('[SW] Activating service worker:', CACHE_NAME);

  event.waitUntil(
    caches.keys()
      .then((names) => {
        return Promise.all(
          names
            .filter((name) => name !== CACHE_NAME)
            .map((name) => {
              console.log('[SW] Deleting old cache:', name);
              return caches.delete(name);
            })
        );
      })
      .then(() => {
        console.log('[SW] Claiming clients');
        return clients.claim();
      })
  );
});


// =====================================================
// FETCH
// Only handle GET navigation requests.
// Do NOT cache POST requests.
// =====================================================

self.addEventListener('fetch', (event) => {

  // Only process page navigation GET requests
  if (
    event.request.mode === 'navigate' &&
    event.request.method === 'GET'
  ) {

    event.respondWith(
      fetch(event.request)
        .then((response) => {

          // Clone response before using it
          const copy = response.clone();

          caches.open(CACHE_NAME)
            .then((cache) => {
              return cache.put(event.request, copy);
            })
            .then(() => {
              console.log(
                '[SW] Cached:',
                event.request.url
              );
            })
            .catch((error) => {
              console.error(
                '[SW] Cache put failed:',
                error
              );
            });

          return response;
        })

        .catch(() => {

          console.log(
            '[SW] Network failed, checking cache:',
            event.request.url
          );

          return caches.match(event.request)
            .then((cached) => {

              if (cached) {
                return cached;
              }

              return caches.match(OFFLINE_URL);
            });
        })
    );
  }

  // IMPORTANT:
  // POST requests and other requests are NOT intercepted.
});


// =====================================================
// PUSH NOTIFICATION
// =====================================================

self.addEventListener('push', (event) => {

  console.log('====================================');
  console.log('[SW] REAL PUSH RECEIVED');
  console.log('====================================');

  let data = {
    title: 'Power On Plus',
    body: 'You have a new update.',
    url: '/dashboard'
  };


  // ---------------------------------------------------
  // Read push payload
  // ---------------------------------------------------

  try {

    if (event.data) {

      const rawData = event.data.text();

      console.log('[SW] Raw push data:', rawData);

      try {
        data = JSON.parse(rawData);

        console.log(
          '[SW] Parsed push data:',
          data
        );

      } catch (jsonError) {

        console.warn(
          '[SW] Payload is not JSON'
        );

        data.body = rawData;
      }
    }

  } catch (error) {

    console.error(
      '[SW] Error reading push data:',
      error
    );
  }


  // ---------------------------------------------------
  // Show notification
  // ---------------------------------------------------

  console.log(
    '[SW] SHOWING NOTIFICATION:',
    data
  );


  event.waitUntil(

    self.registration.showNotification(

      data.title || 'Power On Plus',

      {
        body: data.body || 'You have a new update.',

        icon: '/static/icons/icon-192.png',

        badge: '/static/icons/icon-192.png',

        data: {
          url: data.url || '/dashboard'
        },

        tag: data.tag || undefined,

        renotify: !!data.tag
      }

    )

    .then(() => {

      console.log(
        '[SW] NOTIFICATION DISPLAYED SUCCESSFULLY'
      );

    })

    .catch((error) => {

      console.error(
        '[SW] showNotification FAILED:',
        error
      );

    })

  );

});


// =====================================================
// NOTIFICATION CLICK
// =====================================================

self.addEventListener('notificationclick', (event) => {

  console.log(
    '[SW] Notification clicked'
  );

  event.notification.close();


  const url =
    (
      event.notification.data &&
      event.notification.data.url
    ) || '/dashboard';


  console.log(
    '[SW] Opening URL:',
    url
  );


  event.waitUntil(

    clients.matchAll({
      type: 'window',
      includeUncontrolled: true
    })

    .then((clientList) => {

      // Try to focus an existing window
      for (const client of clientList) {

        if (
          client.url.includes(url) &&
          'focus' in client
        ) {

          return client.focus();
        }
      }


      // Otherwise open a new window
      if (clients.openWindow) {

        return clients.openWindow(url);
      }

    })

  );

});