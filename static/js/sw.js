const CACHE_NAME = 'ai-secretary-v2.0';
const ASSETS_TO_CACHE = [
    '/',
    '/static/manifest.json',
    '/static/css/style.css?v=6.3',
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

    // 🛡️ 繞過 OAuth 認證、登入、登出與 API 請求，避免 Service Worker 攔截造成無限導向循環
    if (
        url.pathname.startsWith('/login') || 
        url.pathname.startsWith('/callback') || 
        url.pathname.startsWith('/logout') || 
        url.pathname.startsWith('/api')
    ) {
        return;
    }

    // 1. For HTML/Document requests (only for root page): Network-First
    // If the network takes too long (e.g. database cold start lag > 1.8 seconds), serve cached root page instantly!
    if (event.request.mode === 'navigate' && url.pathname === '/') {
        event.respondWith(
            new Promise((resolve) => {
                const timeoutId = setTimeout(() => {
                    // Timeout triggered -> serve cached root page instantly!
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
