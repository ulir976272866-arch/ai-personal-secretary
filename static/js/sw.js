const CACHE_NAME = 'ai-secretary-v1.1';
const ASSETS_TO_CACHE = [
    '/',
    '/static/manifest.json',
    '/static/css/style.css?v=5.0',
    '/static/js/app.js?v=6.9',
    '/static/icons/icon.png',
    'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap'
];

// Installation Event: Pre-cache core shell assets
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('[Service Worker] Pre-caching core shell assets...');
            return cache.addAll(ASSETS_TO_CACHE);
        }).then(() => self.skipWaiting())
    );
});

// Activation Event: Clean up old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('[Service Worker] Removing old cache:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch Event with Stale-While-Revalidate and Network-First combo
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Only handle GET requests
    if (event.request.method !== 'GET') return;

    // 1. For HTML/Document requests (root or page routes): Network-First
    // If the network takes too long (e.g. Cloud Run is cold starting), fall back to cached shell instantly!
    if (event.request.mode === 'navigate' || url.pathname === '/') {
        event.respondWith(
            new Promise((resolve) => {
                const timeoutId = setTimeout(() => {
                    // Timeout triggered (e.g. cold start lag > 1.8 seconds) -> serve cached root page instantly!
                    caches.match('/').then((cachedResponse) => {
                        if (cachedResponse) {
                            console.log('[Service Worker] Network slow (Cold Start). Serving cached shell.');
                            resolve(cachedResponse);
                        }
                    });
                }, 1800); // 1.8 seconds threshold

                fetch(event.request)
                    .then((networkResponse) => {
                        clearTimeout(timeoutId);
                        // Save a copy of the fresh page to the cache
                        const cacheCopy = networkResponse.clone();
                        caches.open(CACHE_NAME).then((cache) => {
                            cache.put('/', cacheCopy);
                        });
                        resolve(networkResponse);
                    })
                    .catch(() => {
                        clearTimeout(timeoutId);
                        // Network error / offline -> serve cached root page
                        caches.match('/').then((cachedResponse) => {
                            resolve(cachedResponse || fetch(event.request));
                        });
                    });
            })
        );
        return;
    }

    // 2. For Static Assets (CSS, JS, Fonts, Images): Cache-First / Stale-While-Revalidate
    if (ASSETS_TO_CACHE.some(asset => url.pathname.includes(asset.split('?')[0])) || url.host === 'fonts.gstatic.com' || url.host === 'fonts.googleapis.com') {
        event.respondWith(
            caches.match(event.request).then((cachedResponse) => {
                if (cachedResponse) {
                    // Fetch and update cache in background (Stale-While-Revalidate)
                    fetch(event.request).then((networkResponse) => {
                        if (networkResponse.status === 200) {
                            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, networkResponse));
                        }
                    }).catch(() => {});
                    return cachedResponse;
                }
                return fetch(event.request);
            })
        );
    }
});
