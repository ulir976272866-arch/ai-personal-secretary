// ================================================================
// AI 小秘書 Service Worker  v2.2
// ================================================================
const CACHE_NAME = 'ai-secretary-v2.2';

// 核心 Shell 資源（必要）
const ASSETS_TO_CACHE = [
    '/',
    '/static/manifest.json',
    '/static/css/style.css?v=11.0',
    '/static/js/app.js?v=12.0',
    '/static/icons/icon.png',
    'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap'
];

// 🎴 會員卡條碼函式庫 CDN 白名單（目前尚未串接條碼功能，先留空陣列避免 fetch handler 噴 ReferenceError）
const MEMBER_CDN_ASSETS = [];

// ── Installation：預快取所有核心資源 ───────────────────────────────
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('[SW] Pre-caching core shell...');
            return cache.addAll(ASSETS_TO_CACHE);
        }).then(() => self.skipWaiting())
    );
});

// ── Activation：清除舊版快取 ──────────────────────────────────────
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('[SW] 清除舊版快取：', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        }).then(() => self.clients.claim())
    );
});

// ── Fetch：多層級快取策略 ─────────────────────────────────────────
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // 只處理 GET 請求
    if (event.request.method !== 'GET') return;

    // 🛡️ 繞過 OAuth / 登入 / 登出，避免 Service Worker 造成無限導向
    if (
        url.pathname.startsWith('/login') ||
        url.pathname.startsWith('/auth/google') ||
        url.pathname.startsWith('/callback') ||
        url.pathname.startsWith('/logout') ||
        url.pathname.startsWith('/api')
    ) {
        return;
    }

    // ① 首頁（HTML 文件）：Network-First，逾時 1.8s 降級為快取
    if (event.request.mode === 'navigate' && url.pathname === '/') {
        event.respondWith(
            new Promise((resolve) => {
                const timeoutId = setTimeout(() => {
                    caches.match('/').then((cachedResponse) => {
                        if (cachedResponse) {
                            console.log('[SW] 冷啟動逾時，回傳快取首頁');
                            resolve(cachedResponse);
                        }
                    });
                }, 1800);

                fetch(event.request)
                    .then((networkResponse) => {
                        clearTimeout(timeoutId);
                        const cacheCopy = networkResponse.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put('/', cacheCopy));
                        resolve(networkResponse);
                    })
                    .catch(() => {
                        clearTimeout(timeoutId);
                        caches.match('/').then((cachedResponse) => {
                            resolve(cachedResponse || fetch(event.request));
                        });
                    });
            })
        );
        return;
    }

    // ② 🎴 條碼函式庫 CDN：Cache-First（離線可用）
    if (MEMBER_CDN_ASSETS.includes(event.request.url)) {
        event.respondWith(
            caches.match(event.request).then((cachedResponse) => {
                if (cachedResponse) {
                    console.log('[SW] 🎴 條碼函式庫從快取回傳（離線可用）');
                    return cachedResponse;
                }
                // 沒快取才去網路抓，並存入快取
                return fetch(event.request).then((networkResponse) => {
                    if (networkResponse.ok) {
                        caches.open(CACHE_NAME).then((cache) => {
                            cache.put(event.request, networkResponse.clone());
                        });
                    }
                    return networkResponse;
                });
            })
        );
        return;
    }

    // ③ 靜態資源（CSS、JS、字型、圖示）：Stale-While-Revalidate
    const isStaticAsset = (
        ASSETS_TO_CACHE.some(asset => url.pathname.includes(asset.split('?')[0])) ||
        url.host === 'fonts.gstatic.com' ||
        url.host === 'fonts.googleapis.com' ||
        url.host === 'cdn.jsdelivr.net'
    );

    if (isStaticAsset) {
        event.respondWith(
            caches.match(event.request).then((cachedResponse) => {
                if (cachedResponse) {
                    // 背景更新快取，立即回傳舊版（Stale-While-Revalidate）
                    fetch(event.request).then((networkResponse) => {
                        if (networkResponse && networkResponse.status === 200) {
                            caches.open(CACHE_NAME).then((cache) => {
                                cache.put(event.request, networkResponse);
                            });
                        }
                    }).catch(() => {});
                    return cachedResponse;
                }
                return fetch(event.request);
            })
        );
    }
});

// ── Background Sync：🎴 離線寫入佇列重播 ───────────────────────────
// 當使用者在無網路環境（如超商地下室）新增/修改/刪除卡片時，
// 操作會存入 IndexedDB 佇列；網路恢復後此事件自動觸發重播。
self.addEventListener('sync', (event) => {
    if (event.tag === 'member-card-sync') {
        console.log('[SW] 🔄 Background Sync 觸發：會員卡佇列重播...');
        event.waitUntil(replayMemberQueue());
    }
});

async function replayMemberQueue() {
    try {
        // 開啟 IndexedDB member-queue 資料庫
        const db = await openMemberQueueDB();
        const queue = await getAllQueueItems(db);

        if (queue.length === 0) {
            console.log('[SW] 🎴 佇列為空，無需重播');
            return;
        }

        console.log(`[SW] 🎴 開始重播 ${queue.length} 筆離線佇列操作`);

        for (const item of queue) {
            try {
                const res = await fetch(item.url, {
                    method: item.method,
                    headers: { 'Content-Type': 'application/json' },
                    body: item.body || null
                });

                if (res.ok) {
                    // 成功後從佇列移除
                    await deleteQueueItem(db, item.id);
                    console.log(`[SW] 🎴 重播成功：${item.method} ${item.url}`);

                    // 通知前端重新整理卡片列表
                    const clients = await self.clients.matchAll({ type: 'window' });
                    clients.forEach(client => client.postMessage({
                        type: 'MEMBER_SYNC_DONE',
                        payload: { method: item.method, url: item.url }
                    }));
                } else {
                    console.warn(`[SW] 🎴 重播失敗（伺服器錯誤）：${res.status} ${item.url}`);
                }
            } catch (err) {
                console.warn(`[SW] 🎴 重播失敗（網路錯誤）：${item.url}`, err);
                // 保留在佇列，等下次 sync 再試
            }
        }
    } catch (err) {
        console.error('[SW] 🎴 replayMemberQueue 發生例外：', err);
    }
}

// ── IndexedDB 輔助函式（最小化實作）────────────────────────────────
function openMemberQueueDB() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open('member-queue-db', 1);
        req.onupgradeneeded = (e) => {
            const db = e.target.result;
            if (!db.objectStoreNames.contains('queue')) {
                db.createObjectStore('queue', { keyPath: 'id', autoIncrement: true });
            }
        };
        req.onsuccess = (e) => resolve(e.target.result);
        req.onerror = (e) => reject(e.target.error);
    });
}

function getAllQueueItems(db) {
    return new Promise((resolve, reject) => {
        const tx = db.transaction('queue', 'readonly');
        const req = tx.objectStore('queue').getAll();
        req.onsuccess = (e) => resolve(e.target.result);
        req.onerror = (e) => reject(e.target.error);
    });
}

function deleteQueueItem(db, id) {
    return new Promise((resolve, reject) => {
        const tx = db.transaction('queue', 'readwrite');
        const req = tx.objectStore('queue').delete(id);
        req.onsuccess = () => resolve();
        req.onerror = (e) => reject(e.target.error);
    });
}

