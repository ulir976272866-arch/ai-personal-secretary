// Google Maps API 回呼 (需在全域作用域)
window.initMap = () => {
    if (window.initAutocomplete) window.initAutocomplete();
};

document.addEventListener('DOMContentLoaded', () => {
    window.editingEventId = null;

    // --- 更新動態日期圖示 (V13.0) ---
    function updateDynamicDateIcons() {
        const today = new Date();
        const day = today.getDate();
        document.querySelectorAll('.current-day-val').forEach(el => {
            el.innerText = day;
        });
    }
    updateDynamicDateIcons();

    // --- 定位與距離計算邏輯 (V11.2) ---
    window.getCurrentLocation = () => {
        return new Promise((resolve, reject) => {
            if (!navigator.geolocation) return reject("瀏覽器不支援定位");
            navigator.geolocation.getCurrentPosition(
                (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
                (err) => reject(err),
                { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
            );
        });
    };

    function calculateDistance(lat1, lon1, lat2, lon2) {
        if (!lat1 || !lon1 || !lat2 || !lon2) return Infinity;
        const R = 6371; // km
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                  Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                  Math.sin(dLon / 2) * Math.sin(dLon / 2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return R * c;
    }

    // --- 自定義確認彈窗邏輯 ---
    let confirmResolver = null;
    window.customConfirm = (title, msg, icon = '🗑️') => {
        return new Promise((resolve) => {
            confirmResolver = resolve;
            document.getElementById('confirm_title').innerText = title;
            document.getElementById('confirm_msg').innerText = msg;
            
            const svgIcon = document.getElementById('confirm_svg');
            const iconContainer = document.getElementById('confirm_icon_container');
            
            if (icon === '🗑️') {
                svgIcon.style.display = 'block';
                if (iconContainer.querySelector('.emoji-icon')) iconContainer.querySelector('.emoji-icon').remove();
            } else {
                svgIcon.style.display = 'none';
                let emojiEl = iconContainer.querySelector('.emoji-icon');
                if (!emojiEl) {
                    emojiEl = document.createElement('div');
                    emojiEl.className = 'emoji-icon';
                    emojiEl.style.fontSize = '2.5rem';
                    iconContainer.appendChild(emojiEl);
                }
                emojiEl.innerText = icon;
            }
            
            document.getElementById('confirmModal').classList.add('show');
        });
    };

    window.closeConfirm = (result) => {
        document.getElementById('confirmModal').classList.remove('show');
        if (confirmResolver) confirmResolver(result);
    };

    document.getElementById('confirm_yes_btn').onclick = () => window.closeConfirm(true);

    // --- 自定義類別輸入彈窗邏輯 ---
    let catInputResolver = null;
    window.customCatInput = () => {
        return new Promise((resolve) => {
            catInputResolver = resolve;
            document.getElementById('new_cat_name').value = '';
            document.getElementById('new_cat_icon_hidden').value = '📌';
            document.getElementById('new_cat_preview_icon').innerText = '📌';
            document.getElementById('catInputModal').classList.add('show');
            setTimeout(() => document.getElementById('new_cat_name').focus(), 300);
        });
    };

    window.closeCatInput = (confirmed) => {
        const name = document.getElementById('new_cat_name').value.trim();
        const icon = document.getElementById('new_cat_icon_hidden').value.trim() || '📌';
        document.getElementById('catInputModal').classList.remove('show');
        document.getElementById('cat_emoji_suggestions').innerHTML = ''; 
        if (catInputResolver) {
            catInputResolver(confirmed ? { name, icon } : null);
        }
    };

    // --- Emoji 智慧建議字典 ---
    const emojiDict = {
        '運動': ['🏃', '🏋️', '🏀', '⚽', '🎾', '🏊'],
        '學習': ['📚', '✍️', '🎓', '🧪', '🧠'],
        '美食': ['🍜', '🍕', '🍰', '🍣', '🍱', '🥘'],
        '旅遊': ['🚗', '✈️', '🏝️', '🎒', '🗺️'],
        '影視': ['🎬', '🍿', '🎥', '📺', '📽️'],
        '生活': ['🏠', '🧹', '🧺', '🛋️', '🔑'],
        '工作': ['💻', '💼', '📅', '👔', '📈'],
        '購物': ['🛍️', '💰', '💳', '🎁'],
        '健康': ['🍎', '💊', '🩺', '💤'],
        '娛樂': ['🎮', '🎸', '🎨', '🧩'],
        '還願': ['✨', '🙏', '🕯️', '🧧'],
        '重要': ['🔥', '❗️', '🚨'],
        '心情': ['😊', '🥰', '🌈', '☀️'],
        '交通': ['🚲', '🚇', '🚌', '🚕'],
        '理財': ['💎', '💵', '📊'],
        '咖啡': ['☕', '🍵', '🥐', '🧁'],
        '住宿': ['🏨', '🛌', '🏠', '⛺'],
        '景點': ['🎡', '🎢', '🗼', '⛲', '🏛️'],
        '醫療': ['🏥', '💊', '🩺', '🚑']
    };

    window.suggestEmoji = (text) => {
        const suggestionsDiv = document.getElementById('cat_emoji_suggestions');
        if (!suggestionsDiv) return;
        
        if (!text.trim()) {
            suggestionsDiv.innerHTML = '';
            window.updateCatPreviewIcon('📌');
            return;
        }
        
        let found = [];
        for (const [key, icons] of Object.entries(emojiDict)) {
            if (text.includes(key) || key.includes(text)) {
                found = [...found, ...icons];
            }
        }
        
        const uniqueIcons = [...new Set(found)].slice(0, 8);
        
        if (uniqueIcons.length > 0) {
            suggestionsDiv.innerHTML = uniqueIcons.map(icon => `
                <div onclick="window.updateCatPreviewIcon('${icon}')" 
                     style="width: 44px; height: 44px; border-radius: 12px; background: #fff; border: 1.5px solid #e2e8f0; display: flex; align-items: center; justify-content: center; font-size: 1.6rem; cursor: pointer; transition: all 0.2s; flex-shrink: 0; box-shadow: 0 2px 5px rgba(0,0,0,0.05);">
                    ${icon}
                </div>
            `).join('');
            
            // 自動更新預覽為第一個建議
            window.updateCatPreviewIcon(uniqueIcons[0]);
        } else {
            suggestionsDiv.innerHTML = '';
            // 如果沒匹配到，不強制變更，或是重置為預設
            // window.updateCatPreviewIcon('📌'); 
        }
    };

    window.updateCatPreviewIcon = (icon) => {
        const previewIcon = document.getElementById('new_cat_preview_icon');
        const hiddenIcon = document.getElementById('new_cat_icon_hidden');
        if (previewIcon) previewIcon.innerText = icon;
        if (hiddenIcon) hiddenIcon.value = icon;
    };

    const getMapUrl = (location) => {
        const encodedLoc = encodeURIComponent(location).replace(/%20/g, '+');
        return `https://www.google.com/maps/search/?api=1&query=${encodedLoc}`;
    };

    const chatHistory = document.getElementById('chat-history');
    const userInput = document.getElementById('userInput');
    const sendBtn = document.getElementById('sendBtn');

    // --- 核心功能：每次打開自動載入今日行程卡片 ---
    async function loadTodaySchedule() {
        if (chatHistory.innerHTML.trim() !== '') return;

        try {
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: '今日行程' })
            });
            const data = await res.json();
            if (data.status === 'success' && data.type === 'query_schedule') {
                renderScheduleCard(data.data, data.date_str);
            }
        } catch (e) {
            console.error('載入今日行程失敗:', e);
        }
    }

    // 啟動時載入
    loadTodaySchedule();

    // --- 介面控制與變數初始化 ---
    const voiceBtn = document.getElementById('voiceBtn');
    const clearBtn = document.getElementById('clearBtn');

    // --- 樹狀導航切換 ---
    window.switchTab = (tab, e) => {
        // 更新母頁籤樣式
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        if (e) {
            e.currentTarget.classList.add('active');
        } else if (window.event) {
            window.event.currentTarget.classList.add('active');
        }

        // 更新子選單顯示
        document.querySelectorAll('.sub-menu').forEach(menu => menu.classList.remove('active'));
        document.getElementById(`sub_${tab}`).classList.add('active');
    };

    // --- 彈窗控制 ---
    window.openModal = (id) => {
        if (id === 'scheduleModal' && !window.editingEventId) {
            document.getElementById('manual_summary').value = '';
            document.getElementById('manual_location').value = '';
            const now = new Date();
            const offset = now.getTimezoneOffset();
            const localDate = new Date(now.getTime() - (offset * 60 * 1000));
            document.getElementById('manual_date').value = localDate.toISOString().split('T')[0];
            document.getElementById('manual_all_day').checked = false;
            document.getElementById('time_input_wrapper').style.display = 'flex';
            const submitBtn = document.getElementById('submitSchedule');
            if (submitBtn) {
                submitBtn.innerText = '確認加入日曆';
                submitBtn.style.background = '';
            }
        }
        document.getElementById(id).classList.add('show');
        
        // 分支邏輯優化 (V11.1)
        if (id === 'wishlistModal') window.loadWishes();
        if (id === 'todoModal') {
            window.selectTodoCategory('', '');
            window.loadTodos();
            window.renderTodoCatDropdown();
        }
        if (id === 'memoModal') window.loadMemos();
        if (id === 'pocketModal') {
            window.selectCategory(''); // 口袋名單開啟時預設空白
            setTimeout(window.initPocketAutocomplete, 300);
            window.loadPocket();
        }
    };

    window.closeModal = (id) => {
        if (id) {
            document.getElementById(id).classList.remove('show');
            if (id === 'scheduleModal') window.editingEventId = null;
        } else {
            document.querySelectorAll('.modal-backdrop').forEach(m => m.classList.remove('show'));
            window.editingEventId = null;
        }
    };

    // --- 初始化 Google Places Autocomplete ---
    window.initAutocomplete = () => {
        const input = document.getElementById('manual_location');
        if (!input || typeof google === 'undefined') return;

        const autocomplete = new google.maps.places.Autocomplete(input, {
            types: ['geocode', 'establishment'],
            componentRestrictions: { country: 'tw' }
        });

        autocomplete.addListener('place_changed', () => {
            const place = autocomplete.getPlace();
            if (place.formatted_address) {
                input.value = place.formatted_address;
            }
        });

        const pocketInput = document.getElementById('pocket_location');
        if (pocketInput) {
            const pocketAutocomplete = new google.maps.places.Autocomplete(pocketInput, {
                types: ['geocode', 'establishment'],
                componentRestrictions: { country: 'tw' }
            });
            pocketAutocomplete.addListener('place_changed', () => {
                const place = pocketAutocomplete.getPlace();
                if (place.formatted_address) {
                    pocketInput.value = place.formatted_address;
                }
            });
        }
    };
    
    if (typeof google !== 'undefined') {
        window.initAutocomplete();
    }

    // --- 待辦功能 (V10.8 精簡版) ---
    window.todoCategories = JSON.parse(localStorage.getItem('todoCategories')) || [
        { name: '美食', icon: '🍕' },
        { name: '影視', icon: '🎬' },
        { name: '學習', icon: '📖' },
        { name: '生活', icon: '🏠' },
        { name: '還願', icon: '✨' },
        { name: '旅遊', icon: '📍' }
    ];

    window.toggleTodoCategoryDropdown = () => {
        const dropdown = document.getElementById('todo_cat_dropdown');
        if (dropdown) dropdown.classList.toggle('show');
    };

    window.selectTodoCategory = (name, icon) => {
        const catInput = document.getElementById('todo_category');
        const displaySpan = document.getElementById('current_todo_cat_display');
        const dropdown = document.getElementById('todo_cat_dropdown');
        
        if (catInput) catInput.value = name;
        if (displaySpan) {
            displaySpan.innerHTML = name ? `${icon} ${name}` : '請選擇';
        }
        if (dropdown) dropdown.classList.remove('show');
        updateTodoSubmitButtonState();
    };

    function updateTodoSubmitButtonState() {
        const btn = document.getElementById('submitTodoBtn');
        const titleInput = document.getElementById('todo_title');
        const catInput = document.getElementById('todo_category');
        if (!btn || !titleInput || !catInput) return;
        
        const hasTitle = titleInput.value.trim().length > 0;
        const hasCat = catInput.value !== '';
        
        btn.style.opacity = (hasTitle && hasCat) ? '1' : '0.3';
        btn.style.pointerEvents = (hasTitle && hasCat) ? 'auto' : 'none';
    }

    window.renderTodoCatDropdown = () => {
        const dropdown = document.getElementById('todo_cat_dropdown');
        if (!dropdown) return;
        
        const deletedCats = JSON.parse(localStorage.getItem('deletedTodoCats') || '[]');
        const allCats = [...window.todoCategories].filter(c => !deletedCats.includes(c.name));
        
        dropdown.innerHTML = allCats.map((cat, idx) => `
            <div class="todo-dropdown-item" onclick="window.selectTodoCategory('${cat.name}', '${cat.icon}')">
                <span>${cat.icon}</span> 
                <div style="flex: 1;">${cat.name}</div>
                <div class="cat-delete-btn" onclick="event.stopPropagation(); window.removeTodoCategory('${cat.name}')">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                </div>
            </div>
        `).join('') + `
            <div class="todo-dropdown-item add-new" onclick="window.addNewTodoCategory()">
                <span>＋</span> 新增類別...
            </div>
        `;
    };
    window.removeTodoCategory = async (catName) => {
        const catObj = window.todoCategories.find(c => c.name === catName) || { name: catName, icon: '📝' };
        
        
        const confirmed = await window.customConfirm(
            '確定刪除類別？',
            `您即將刪除「${catObj.icon} ${catName}」類別。`,
            '🗑️'
        );
        
        if (confirmed) {
            // 1. 記錄到隱藏清單
            let deleted = JSON.parse(localStorage.getItem('deletedTodoCats') || '[]');
            if (!deleted.includes(catName)) deleted.push(catName);
            localStorage.setItem('deletedTodoCats', JSON.stringify(deleted));
            
            // 2. 如果當前選中，則重設
            const currentCat = document.getElementById('todo_category').value;
            if (currentCat === catName) {
                window.selectTodoCategory('任務', '📝');
            }
            
            window.renderTodoCatDropdown();
            window.loadTodos(); 
        }
    };

    window.addNewTodoCategory = async () => {
        // 先關掉下拉選單
        const dropdown = document.getElementById('todo_cat_dropdown');
        if (dropdown) dropdown.classList.remove('show');
        
        const result = await window.customCatInput();
        if (result && result.name) {
            // 檢查是否已存在
            if (!window.todoCategories.find(c => c.name === result.name)) {
                window.todoCategories.push({ name: result.name, icon: result.icon || '📌' });
                localStorage.setItem('todoCategories', JSON.stringify(window.todoCategories));
            }
            
            // 重要：如果曾在刪除名單中，將其移除（復原）
            let deleted = JSON.parse(localStorage.getItem('deletedTodoCats') || '[]');
            if (deleted.includes(result.name)) {
                deleted = deleted.filter(c => c !== result.name);
                localStorage.setItem('deletedTodoCats', JSON.stringify(deleted));
            }
            
            window.renderTodoCatDropdown();
            window.selectTodoCategory(result.name, result.icon || '📌');
            window.loadTodos(); 
        }
    };

    const todoTitleInput = document.getElementById('todo_title');
    if (todoTitleInput) {
        todoTitleInput.oninput = updateTodoSubmitButtonState;
    }

    window.loadTodos = async (filterCategory = '全部') => {
        const list = document.getElementById('todo_list');
        if (!list) return;

        // 顯示載入中
        list.innerHTML = `<div style="text-align: center; padding: 30px; color: #94a3b8;"><div class="loading-spinner"></div> 正在讀取...</div>`;

        try {
            const res = await fetch('/api/todo');
            const data = await res.json();
            if (!Array.isArray(data)) throw new Error('資料錯誤');

            const activeTodos = data.filter(i => i.狀態 === '未完成');

            // --- 動態生成篩選列 (V10.9 統一下拉式) ---
            const filterSelect = document.getElementById('todo_filter_cat');
            if (filterSelect) {
                const deletedCats = JSON.parse(localStorage.getItem('deletedTodoCats') || '[]');
                // 找出目前有任務的類別 + 使用者自定義類別
                const activeCats = [...new Set(activeTodos.map(i => i.分類 || '任務'))];
                const customCats = window.todoCategories.map(c => c.name).filter(c => !deletedCats.includes(c));
                const allFilterCats = ['全部', ...new Set([...activeCats, ...customCats])].filter(c => !deletedCats.includes(c) || c === '全部');
                
                filterSelect.innerHTML = allFilterCats.map(cat => {
                    let icon = '🌟';
                    if (cat !== '全部') {
                        const found = window.todoCategories.find(c => c.name === cat);
                        icon = found ? found.icon : '📝';
                    }
                    return `<option value="${cat}" ${filterCategory === cat ? 'selected' : ''}>${icon} ${cat === '全部' ? '全部任務' : cat}</option>`;
                }).join('');
            }

            // 過濾與排序
            let filteredTodos = activeTodos;
            if (filterCategory !== '全部') {
                filteredTodos = activeTodos.filter(i => i.分類 === filterCategory);
            }

            const priorityMap = { '急要': 0, '重要': 1, '緊急': 2, '一般': 3 };
            const matrixMap = {
                '急要': '重要且緊急',
                '重要': '重要但不緊急',
                '緊急': '緊急但不重要',
                '一般': '不重要且不緊急'
            };
            // 處理反向映射 (如果資料庫裡存的是長字串)
            const reverseMatrixMap = {
                '重要且緊急': '急要',
                '重要但不緊急': '重要',
                '緊急但不重要': '緊急',
                '不重要且不緊急': '一般'
            };

            const sortedTodos = filteredTodos.sort((a, b) => {
                const getP = (p) => {
                    if (!p) return 4;
                    const trimmed = p.trim();
                    return priorityMap[reverseMatrixMap[trimmed] || trimmed] ?? 4;
                };
                return getP(a['優先級']) - getP(b['優先級']);
            });

            if (sortedTodos.length === 0) {
                list.innerHTML = `<div style="color: #94a3b8; text-align: center; padding: 40px 20px;">目前沒有「${filterCategory}」任務 ✨</div>`;
                return;
            }

            list.innerHTML = sortedTodos.map((item, idx) => {
                const safeID = item['唯一 ID'] || `legacy_${idx}`;
                let priorityVal = (item['優先級'] || '一般').trim();
                // 正規化優先級值
                if (reverseMatrixMap[priorityVal]) priorityVal = reverseMatrixMap[priorityVal];
                
                const priorityDisplay = matrixMap[priorityVal] || priorityVal;
                const category = (item['分類'] || '任務').trim();
                const accentClass = priorityVal === '急要' ? 'accent-red' : (priorityVal === '重要' ? 'accent-yellow' : (priorityVal === '緊急' ? 'accent-orange' : 'accent-green'));

                return `
                    <div id="todo_item_${safeID}" style="display: flex; align-items: center; gap: 12px; padding: 15px 15px 15px 22px; border-bottom: 1px solid #f8fafc; transition: all 0.3s; background: white; margin-bottom: 10px; border-radius: 16px; box-shadow: 0 4px 6px rgba(0,0,0,0.02); position: relative; overflow: hidden;">
                        <div class="todo-accent ${accentClass}"></div>
                        <div style="position: relative; width: 24px; height: 24px; flex-shrink: 0;">
                            <input type="checkbox" style="width: 24px; height: 24px; cursor: pointer; opacity: 0; position: absolute; z-index: 2;" onchange="window.prepareTodo('${safeID}', this.checked)">
                            <div class="custom-checkbox" style="width: 24px; height: 24px; border: 2.5px solid #cbd5e1; border-radius: 8px; position: absolute; top: 0; left: 0; transition: all 0.2s;"></div>
                        </div>
                        <div style="flex: 1;">
                            <div id="todo_text_${safeID}" style="color: #1e293b; font-weight: 700; font-size: 1.05rem; line-height: 1.4; margin-bottom: 4px;">${item['事項/內容']}</div>
                            <div style="display: flex; gap: 8px; align-items: center;">
                                <span style="font-size: 0.65rem; color: #3b82f6; background: #eff6ff; padding: 2px 8px; border-radius: 6px; font-weight: 800;">
                                    ${(window.todoCategories.find(c => c.name === category) || {icon: '📝'}).icon} ${category}
                                </span>
                                <span style="font-size: 0.7rem; font-weight: 600; color: #64748b;">• ${priorityDisplay}</span>
                            </div>
                        </div>
                        <div id="todo_action_${safeID}" style="display: flex; gap: 10px; align-items: center;">
                            <button onclick="window.deleteTodo('${safeID}', '${item['事項/內容'].replace(/'/g, "\\'")}')" 
                                    style="background: none; border: none; color: #ef4444; cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 4px; transition: all 0.2s;">
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                            </button>
                            <button onclick="window.editTodo('${safeID}', '${item['事項/內容'].replace(/'/g, "\\'")}', '${category}')" style="background: none; color: #3b82f6; border: none; padding: 4px; font-size: 0.85rem; cursor: pointer; display: flex; align-items: center; justify-content: center;">
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                            </button>
                        </div>
                    </div>
                `;
            }).join('');
        } catch (e) {
            console.error('載入待辦失敗:', e);
            list.innerHTML = `<div style="color: #ef4444; text-align: center; padding: 20px;">載入失敗 🔌</div>`;
        }
    };


    window.deleteTodo = async (id, title) => {
        const confirmed = await window.customConfirm('確定刪除事項？', `確定要刪除「${title}」嗎？`, '🗑️');
        if (!confirmed) return;
        
        const realID = id.startsWith('legacy_') ? '' : id;
        const res = await fetch('/api/todo/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: realID, title })
        });
        
        if ((await res.json()).status === 'success') {
            const item = document.getElementById(`todo_item_${id}`);
            if (item) {
                item.style.opacity = '0';
                setTimeout(() => {
                    item.remove();
                    if (document.getElementById('todo_list').children.length === 0) {
                        document.getElementById('todo_list').innerHTML = '<div style="color: #94a3b8; text-align: center; padding: 20px;">任務全數達成！✨</div>';
                    }
                }, 300);
            }
        }
    };

    window.prepareTodo = (id, isChecked) => {
        const text = document.getElementById(`todo_text_${id}`);
        const action = document.getElementById(`todo_action_${id}`);
        if (isChecked) {
            text.style.textDecoration = 'line-through';
            text.style.color = '#94a3b8';
            const title = text.innerText.trim();
            action.innerHTML = `<button onclick="window.finalizeTodo('${id}', '${title}')" style="background: #10b981; color: white; border: none; padding: 4px 10px; border-radius: 6px; font-size: 0.75rem; cursor: pointer; font-weight: bold; animation: popIn 0.3s ease;">完成！</button>`;
        } else {
            text.style.textDecoration = 'none';
            text.style.color = '#1e293b';
            window.loadTodos(); // 恢復原狀
        }
    };

    window.finalizeTodo = async (id, title) => {
        const item = document.getElementById(`todo_item_${id}`);
        item.style.opacity = '0.5';
        item.style.transform = 'translateX(20px)';
        
        const realID = id.startsWith('legacy_') ? '' : id;
        const res = await fetch('/api/todo/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: realID, title, completed: true })
        });
        
        if ((await res.json()).status === 'success') {
            item.style.height = '0';
            item.style.padding = '0';
            item.style.margin = '0';
            item.style.overflow = 'hidden';
            setTimeout(() => {
                item.remove();
                if (document.getElementById('todo_list').children.length === 0) {
                    document.getElementById('todo_list').innerHTML = '<div style="color: #94a3b8; text-align: center; padding: 20px;">任務全數達成！✨</div>';
                }
            }, 300);
        } else {
            alert("結算失敗，請重試");
            item.style.opacity = '1';
            item.style.transform = 'none';
        }
    };

    // --- 願望功能 ---
    window.selectWishTag = (el, val) => {
        document.querySelectorAll('.wish-tag').forEach(tag => tag.classList.remove('active'));
        el.classList.add('active');
        document.getElementById('wish_category').value = val;
    };

    window.loadWishes = async () => {
        const list = document.getElementById('wish_list');
        const summary = document.getElementById('wish_summary');
        if (!list) return;

        // 顯示載入中
        list.innerHTML = `
            <div style="text-align: center; padding: 30px; color: #94a3b8;">
                <div class="loading-spinner" style="margin-bottom: 10px;">⌛</div>
                正在讀取願望清單...
            </div>
        `;

        try {
            const res = await fetch('/api/wishlist');
            const data = await res.json();
            
            if (!Array.isArray(data)) {
                throw new Error(data.message || '資料格式錯誤');
            }

            let totalBudget = 0;
            const activeWishes = data.filter(i => i.狀態 === '想買');

            if (activeWishes.length === 0) {
                list.innerHTML = '<div style="color: #94a3b8; text-align: center; padding: 40px 20px;">目前沒有正在進行的願望 ✨<br><small style="opacity: 0.7;">點擊上方 + 按鈕開始許願吧！</small></div>';
                if (summary) summary.innerHTML = '';
                return;
            }

            list.innerHTML = activeWishes.map(item => {
                const price = parseInt(item.預估價格) || 0;
                totalBudget += price;
                const itemID = item['唯一 ID'] || item.id;
                
                // 根據分類決定顏色 (加強匹配與相容舊標籤)
                const cat = (item.分類 || '').trim();
                let cardStyle = 'background: white; border: 1px solid #f1f5f9; color: #1e293b;';
                
                if (cat.includes('必買')) {
                    cardStyle = 'background: #f3e8ff; border: 1px solid #d8b4fe; color: #7e22ce;';
                } else if (cat.includes('可買') || cat.includes('家用') || cat.includes('送禮')) {
                    cardStyle = 'background: #f0fdf4; border: 1px solid #bbf7d0; color: #15803d;';
                } else if (cat.includes('可不買') || cat.includes('靈感')) {
                    cardStyle = 'background: #fefce8; border: 1px solid #fef08a; color: #a16207;';
                } else {
                    // 預設為必買顏色 (若為空值)
                    cardStyle = 'background: #f3e8ff; border: 1px solid #d8b4fe; color: #7e22ce;';
                }

                return `
                    <div style="${cardStyle} padding: 18px; border-radius: 18px; margin-bottom: 15px; box-shadow: 0 4px 12px rgba(0,0,0,0.03); transition: transform 0.2s;" onactive="this.style.transform='scale(0.98)'">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                            <div style="font-weight: 800; font-size: 1.1rem; flex: 1;">${item.商品名稱}</div>
                            <div style="font-weight: 900; font-size: 1.2rem; margin-left: 10px;">$${price.toLocaleString()}</div>
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 15px;">
                            <span style="font-size: 0.75rem; opacity: 0.6; font-weight: 500;">
                                ${item.建立日期}
                            </span>
                             <div style="display: flex; gap: 15px; align-items: center;">
                                <button onclick="window.deleteWish('${itemID}', '${item.商品名稱.replace(/'/g, "\\'")}')" 
                                        style="background: none; border: none; color: #ef4444; cursor: pointer; padding: 4px; transition: all 0.2s; display: flex; align-items: center; justify-content: center;">
                                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                                </button>
                                <button onclick="window.editWish('${itemID}', '${item.商品名稱.replace(/'/g, "\\'")}', '${item.預估價格}', '', '${item.分類}')" 
                                        style="background: none; color: #3b82f6; border: none; padding: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center;">
                                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                                </button>
                                <button onclick="window.fulfillWish('${itemID}', '${item.商品名稱}', '${item.預估價格}')" 
                                        style="background: linear-gradient(135deg, #f97316, #ea580c); color: white; border: none; padding: 7px 16px; border-radius: 20px; font-size: 0.85rem; cursor: pointer; font-weight: 800; box-shadow: 0 4px 10px rgba(249, 115, 22, 0.25);">
                                    圓夢 ✨
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
            
            if (summary) {
                summary.innerHTML = `預算總計：<br>$${totalBudget.toLocaleString()}`;
            }
        } catch (e) {
            console.error('載入願望清單失敗:', e);
            list.innerHTML = `<div style="color: #ef4444; text-align: center; padding: 20px;">載入失敗：${e.message} 🔌</div>`;
        }
    };

    window.fulfillWish = async (id, title, estPrice) => {
        const actualPrice = prompt(`恭喜圓夢！✨\n請問「${title}」實際花了多少錢？`, estPrice);
        if (actualPrice === null) return;

        const res = await fetch('/api/wishlist/fulfill', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id, title, actual_price: actualPrice })
        });
        
        if ((await res.json()).status === 'success') {
            window.loadWishes();
            alert("已記錄您的圓夢時刻！🎊");
        }
    };

    window.deleteWish = async (id, title) => {
        if (!confirm(`確定要斷捨離「${title}」這個願望嗎？`)) return;

        const res = await fetch('/api/wishlist/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: String(id), title })
        });
        
        const result = await res.json();
        if (result.status === 'success') {
            window.loadWishes();
        } else {
            alert("❌ 刪除失敗：" + result.message);
        }
    };

    // --- 儲存邏輯 ---
    window.checkMemoFields = () => {
        const content = document.getElementById('memo_content').value.trim();
        const mood = document.getElementById('memo_mood').value;
        const weather = document.getElementById('memo_weather').value;
        const btn = document.getElementById('submitMemoBtn');

        if (content && mood && weather) {
            btn.disabled = false;
            btn.classList.remove('disabled');
        } else {
            btn.disabled = true;
            btn.classList.add('disabled');
        }
    };

    window.saveMemo = async () => {
        const content = document.getElementById('memo_content').value;
        const mood = document.getElementById('memo_mood').value;
        const weather = document.getElementById('memo_weather').value;
        const btn = document.getElementById('submitMemoBtn');
        
        if (!content || !mood || !weather) return;

        // 1. 顯示載入中狀態
        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<div class="loading-spinner"></div> 正在儲存...';
        btn.style.opacity = '0.8';

        try {
            // 增加一個微小的延遲，讓動畫能被看見
            await new Promise(resolve => setTimeout(resolve, 300));
            const res = await fetch('/api/memo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content, mood, weather })
            });
            const data = await res.json();
            if (data.status === 'success') {
                // 2. 清空輸入
                document.getElementById('memo_content').value = '';
                document.getElementById('memo_mood').value = '';
                document.getElementById('memo_weather').value = '';
                
                // 3. 成功後直接關閉彈窗 (使用者的要求)
                window.closeModal('memoModal');
                
                // 4. 重置與更新
                window.checkMemoFields();
                window.loadMemos();
                
                // 5. 給一點小提示
                appendMessage('✨ 日記已成功記錄！', false);
            } else {
                alert('儲存失敗：' + (data.message || '未知錯誤'));
            }
        } catch (e) {
            console.error('Save Memo Error:', e);
            alert('系統發生錯誤，請重試。');
        } finally {
            // 恢復按鈕狀態 (如果沒關閉的話)
            btn.disabled = false;
            btn.innerHTML = originalText;
            btn.style.opacity = '1';
        }
    };

    window.selectPriority = (el, val) => {
        document.querySelectorAll('.priority-opt').forEach(opt => opt.classList.remove('active'));
        el.classList.add('active');
        document.getElementById('todo_priority').value = val;
    };

    window.saveTodo = async () => {
        const input = document.getElementById('todo_title');
        const title = input.value.trim();
        const priority = document.getElementById('todo_priority').value || '一般';
        const category = document.getElementById('todo_category').value || '任務';
        
        if (!title) return;

        const endpoint = window.editingTodoId ? '/api/todo/update' : '/api/todo';
        const payload = { title, category, priority };
        if (window.editingTodoId) payload.id = window.editingTodoId;

        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if ((await res.json()).status === 'success') {
            input.value = '';
            window.editingTodoId = null;
            
            // 恢復按鈕 UI (V10.9)
            const submitBtn = document.getElementById('submitTodoBtn');
            if (submitBtn) {
                submitBtn.innerHTML = '✓';
                submitBtn.style.opacity = '0.3';
                submitBtn.style.pointerEvents = 'none';
            }
            
            window.loadTodos();
            
            // 重置選擇
            const defaultOpt = document.querySelector('.priority-opt.green');
            if (defaultOpt) window.selectPriority(defaultOpt, '一般');
            
            // 重置類別
            window.selectTodoCategory('任務', '📝');
        }
    };

    window.saveWish = async () => {
        const nameInput = document.getElementById('wish_name');
        const priceInput = document.getElementById('wish_price');
        const noteInput = document.getElementById('wish_note');
        const name = nameInput.value.trim();
        const price = priceInput.value || '0';
        const note = noteInput.value.trim();
        if (!name) return;

        const category = document.getElementById('wish_category').value || '必買';

        const endpoint = window.editingWishId ? '/api/wishlist/update' : '/api/wishlist';
        const payload = { name, price, note, category };
        if (window.editingWishId) payload.id = window.editingWishId;

        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if ((await res.json()).status === 'success') {
            nameInput.value = '';
            priceInput.value = '';
            noteInput.value = '';
            window.editingWishId = null;
            
            const submitBtn = document.querySelector('#wishlistModal .modal-content button[onclick="saveWish()"]');
            if (submitBtn) {
                submitBtn.innerHTML = '＋';
                submitBtn.style.background = '#f97316';
                submitBtn.style.width = '45px';
            }
            window.loadWishes();
        }
    };

    window.editWish = (id, name, price, note, category) => {
        document.getElementById('wish_name').value = name;
        document.getElementById('wish_price').value = price;
        window.editingWishId = id;
        
        // 映射舊標籤到新標籤
        let displayCategory = category;
        if (category === '送禮' || category === '家用') displayCategory = '可買';
        if (category === '靈感') displayCategory = '可不買';

        // 切換分類標籤
        document.querySelectorAll('.wish-tag').forEach(tag => {
            if (tag.innerText.includes(displayCategory)) {
                tag.classList.add('active');
                document.getElementById('wish_category').value = displayCategory;
            } else {
                tag.classList.remove('active');
            }
        });

        // 修改按鈕 UI
        const submitBtn = document.querySelector('#wishlistModal .modal-content button[onclick="saveWish()"]');
        if (submitBtn) {
            submitBtn.innerHTML = '💾 儲存';
            submitBtn.style.background = '#10b981';
            submitBtn.style.width = '80px';
        }
    };

    window.editTodo = (id, title, category) => {
        const input = document.getElementById('todo_title');
        input.value = title;
        window.editingTodoId = id;
        
        // 設定類別
        const catObj = window.todoCategories.find(c => c.name === category) || { name: '任務', icon: '📝' };
        window.selectTodoCategory(catObj.name, catObj.icon);
        
        input.focus();
        
        const submitBtn = document.getElementById('submitTodoBtn');
        if (submitBtn) {
            submitBtn.innerHTML = '✓';
            submitBtn.style.opacity = '1';
            submitBtn.style.pointerEvents = 'auto';
        }

        input.style.borderBottom = '2px solid #3b82f6';
        setTimeout(() => input.style.borderBottom = 'none', 1500);
    };

    window.lastQueryDays = 7; // 預設為本週

    window.restoreEvents = () => {
        localStorage.removeItem('hiddenPocketEvents');
        appendMessage('✨ 隱藏項目已全數復原，重新載入中...', false);
        window.querySchedule(window.lastQueryDays || 7);
    };

    window.toggleEventDone = (id) => {
        const li = document.getElementById(`event_li_${id}`);
        const btn = li.querySelector('.done-btn');
        
        if (!btn.classList.contains('completed')) {
            btn.classList.add('completed');
            btn.innerText = '完成';
        } else {
            li.classList.add('fade-out');
            let hidden = JSON.parse(localStorage.getItem('hiddenPocketEvents') || '[]');
            if (!hidden.includes(id)) hidden.push(id);
            localStorage.setItem('hiddenPocketEvents', JSON.stringify(hidden));
            // 延遲一下讓動畫跑完，然後重新渲染整個卡片以更新 Header 的計數
            setTimeout(() => {
                window.querySchedule(window.lastQueryDays || 7);
            }, 400);
        }
    };


    function renderScheduleCard(events, dateStr) {
        const card = document.createElement('div');
        card.className = 'schedule-card';
        
        const hiddenEvents = JSON.parse(localStorage.getItem('hiddenPocketEvents') || '[]');
        const hiddenCount = hiddenEvents.length;
        
        let headerHtml = `
            <div class="schedule-header" style="display: flex; justify-content: space-between; align-items: center; padding: 12px 15px;">
                <h3 style="margin:0; font-size: 1rem; color: var(--accent-amber);">🗓️ ${dateStr} 行程</h3>
                <span onclick="window.restoreEvents()" class="restore-btn-ui" style="font-size: 0.7rem; color: #94a3b8; cursor: pointer; background: #f8fafc; padding: 4px 10px; border-radius: 8px; border: 1px solid #e2e8f0; transition: all 0.2s;">
                    🔄 恢復隱藏${hiddenCount > 0 ? `(${hiddenCount})` : ''}
                </span>
            </div>
        `;
        
        const activeEvents = events.filter(e => !hiddenEvents.includes(e.id));

        if (activeEvents.length === 0) {
            const isTrulyEmpty = events.length === 0;
            const emptyMsg = isTrulyEmpty ? '今天沒有安排行程喔！' : '🎉 已完成所有行程！';
            
            card.innerHTML = headerHtml + `
                <div style="padding: 30px 15px; text-align: center;">
                    <p style="color: #64748b; margin:0;">${emptyMsg}</p>
                </div>
            `;
            chatHistory.appendChild(card);
            scrollToBottom();
            return;
        }

        let listHtml = '<div class="schedule-list">';
        activeEvents.forEach(event => {
            let locationHtml = '';
            if (event.location) {
                const mapUrl = getMapUrl(event.location);
                locationHtml = `
                    <div class="event-address-row">
                        <div class="event-address-icon">📍</div>
                        <a href="${mapUrl}" class="location-link" style="color: #94a3b8; text-decoration: none;">${event.location}</a>
                    </div>`;
            }

            listHtml += `
                <div id="event_li_${event.id}" class="schedule-item">
                    <div class="event-info">
                        <div class="event-time-row">${event.time}</div>
                        <div class="event-title-row">${event.display_title || event.title}</div>
                        ${locationHtml}
                    </div>
                    <div class="event-actions">
                        <div class="action-links">
                            <span class="action-link delete" onclick="window.deleteEvent('${event.id}', '${event.title.replace(/'/g, "\\'")}')">
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                            </span>
                            <span class="action-link edit" onclick="window.editEvent('${event.id}', '${event.title.replace(/'/g, "\\'")}', '${(event.location || "").replace(/'/g, "\\'")}', '${event.start_time}', ${event.is_all_day})">
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                            </span>
                        </div>
                        <button class="done-btn" onclick="window.toggleEventDone('${event.id}')">✓</button>
                    </div>
                </div>
            `;
        });
        listHtml += '</div>';
        card.innerHTML = headerHtml + listHtml;
        chatHistory.appendChild(card);
        scrollToBottom();
    }

    document.querySelectorAll('.close-modal').forEach(btn => btn.onclick = () => window.closeModal());

    function scrollToBottom() {
        requestAnimationFrame(() => {
            chatHistory.scrollTop = chatHistory.scrollHeight;
        });
    }

    function appendMessage(text, isUser = false) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${isUser ? 'user-message' : 'ai-message'}`;
        if (isUser) {
            msgDiv.innerText = text;
        } else {
            msgDiv.innerHTML = text.replace(/\n/g, '<br>');
        }
        chatHistory.appendChild(msgDiv);
        scrollToBottom();
        return msgDiv;
    }
    clearBtn.onclick = () => {
        if (confirm('確定要清空所有對話內容嗎？')) {
            chatHistory.innerHTML = '';
            appendMessage('對話已清空。');
        }
    };

    window.editEvent = (id, title, location, startTime, isAllDay) => {
         window.editingEventId = id;
         document.getElementById('manual_summary').value = title;
         document.getElementById('manual_location').value = location;
         
         const dateInput = document.getElementById('manual_date');
         const allDayCheckbox = document.getElementById('manual_all_day');
         const timeWrapper = document.getElementById('time_input_wrapper');
 
         if (isAllDay) {
             dateInput.value = startTime;
             allDayCheckbox.checked = true;
             timeWrapper.style.display = 'none';
         } else {
             // startTime format: YYYY-MM-DDTHH:MM:SS+08:00 or YYYY-MM-DDTHH:MM:SSZ
             const dt = new Date(startTime);
             const yyyy = dt.getFullYear();
             const mm = String(dt.getMonth() + 1).padStart(2, '0');
             const dd = String(dt.getDate()).padStart(2, '0');
             dateInput.value = `${yyyy}-${mm}-${dd}`;
             
             allDayCheckbox.checked = false;
             timeWrapper.style.display = 'flex';
             
             let hours = dt.getHours();
             const minutes = dt.getMinutes();
             const ampm = hours >= 12 ? 'PM' : 'AM';
             
             if (hours > 12) hours -= 12;
             if (hours === 0) hours = 12;
             
             document.getElementById('manual_ampm').value = ampm;
             document.getElementById('manual_hour').value = hours;
             document.getElementById('manual_minute').value = String(minutes).padStart(2, '0');
         }
 
         // 修改按鈕 UI
         const submitBtn = document.getElementById('submitSchedule');
         if (submitBtn) {
             submitBtn.innerText = '💾 儲存修改';
             submitBtn.style.background = '#10b981';
         }
         
         window.openModal('scheduleModal');
     };

    window.deleteEvent = async (eventId, title) => {
        const confirmed = await window.customConfirm("確定刪除？", `您確定要從日曆移除「${title}」嗎？`);
        if (!confirmed) return;

        const res = await fetch('/api/delete_event', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ event_id: eventId })
        });
        
        const data = await res.json();
        if (data.status === 'success') {
            const li = document.getElementById(`event_li_${eventId}`);
            if (li) {
                li.style.opacity = '0';
                li.style.transform = 'translateX(20px)';
                setTimeout(() => li.remove(), 300);
            }
        }
    };

    // --- 計算機邏輯 ---
    const expenseAmountInput = document.getElementById('expense_amount');
    window.appendCalc = function(val) {
        const amountInput = document.getElementById('expense_amount');
        if (amountInput.value === '0' && val !== '.') {
            amountInput.value = val;
        } else {
            amountInput.value += val;
        }
    };

    window.clearEntry = function() {
        document.getElementById('expense_amount').value = '0';
    };

    window.clearCalc = function() {
        document.getElementById('expense_amount').value = '0';
        document.getElementById('calc_history').innerText = '';
    };
    window.backspaceCalc = () => {
        if (expenseAmountInput.value.length > 1) {
            expenseAmountInput.value = expenseAmountInput.value.slice(0, -1);
        } else {
            expenseAmountInput.value = '0';
        }
    };
    window.calculateResult = () => {
        try {
            const amountInput = document.getElementById('expense_amount');
            const historyDiv = document.getElementById('calc_history');
            const expression = amountInput.value.replace(/×/g, '*').replace(/÷/g, '/');
            
            // 存入上方懸浮歷史區
            historyDiv.innerText = amountInput.value;
            
            // 安全計算
            const result = eval(expression);
            amountInput.value = Math.round(result).toString();
        } catch (e) {
            console.error("Calculation Error:", e);
            alert('計算格式錯誤');
            document.getElementById('expense_amount').value = '0';
        }
    };

    // --- 語音辨識 (V12.0 Toggle & Cancel Support) ---
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.lang = 'zh-TW';
        recognition.continuous = false;
        recognition.interimResults = false;

        let isListening = false;

        recognition.onstart = () => {
            isListening = true;
            voiceBtn.classList.add('listening');
            voiceBtn.innerHTML = '🛑'; // 變成停止圖示
            userInput.placeholder = "聆聽中... (點擊紅點取消)";
        };

        recognition.onend = () => {
            isListening = false;
            voiceBtn.classList.remove('listening');
            voiceBtn.innerHTML = '🎤'; // 恢復為麥克風
            userInput.placeholder = "輸入行程或指令...";
        };

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            userInput.value = transcript;
            window.handleSend();
        };

        voiceBtn.onclick = () => {
            if (isListening) {
                recognition.abort(); // 立即取消錄音
            } else {
                recognition.start();
            }
        };
    } else {
        voiceBtn.style.display = 'none';
    }

    // --- 核心查詢功能 ---
    window.queryFinanceSummary = async () => {
        appendMessage(`查詢本月記帳合計...`, true);
        try {
            const res = await fetch('/api/query_finance', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await res.json();
            if (data.status === 'success') {
                appendMessage(data.message);
            } else {
                appendMessage("❌ 查詢失敗：" + data.message);
            }
        } catch (error) {
            appendMessage("❌ 伺服器連線失敗");
        }
    };

    window.querySchedule = async (days) => {
        window.lastQueryDays = days;
        const rangeLabel = days === 1 ? '今日' : (days === 7 ? '本週' : '本月');
        appendMessage(`查詢${rangeLabel}行程...`, true);
        
        try {
            const res = await fetch('/api/query_schedule', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ days })
            });
            const data = await res.json();
            if (data.status === 'success') {
                renderScheduleCard(data.data, data.date_str);
            } else {
                appendMessage("❌ 查詢失敗：" + data.message);
            }
        } catch (error) {
            appendMessage("❌ 伺服器連線失敗");
        }
    };

    window.handleSend = async function(text = null) {
        const message = text || userInput.value.trim();
        if (!message) return;

        if (!text) {
            appendMessage(message, true);
            userInput.value = '';
        }

        // --- 定位搜尋口袋名單邏輯 (V12.5 Diagnostic Update) ---
        if (message.includes('附近') && (message.includes('想去') || message.includes('口袋名單') || message.includes('推薦'))) {
            appendMessage("正在為您掃描附近的口袋名單... 🛰️");
            try {
                const coords = await window.getCurrentLocation();
                window.userCoords = coords; 
                const res = await fetch('/api/pocket/list');
                const data = await res.json();
                
                if (data.status === 'success') {
                    const allItems = data.data;
                    const itemsWithCoords = allItems.filter(i => i.lat && i.lng);
                    
                    itemsWithCoords.forEach(i => {
                        i.distance = calculateDistance(coords.lat, coords.lng, parseFloat(i.lat), parseFloat(i.lng));
                    });
                    
                    // 將半徑擴大至 20km 以利測試
                    const searchRadius = 20; 
                    const nearby = itemsWithCoords.filter(i => i.distance < searchRadius).sort((a, b) => a.distance - b.distance);
                    
                    if (nearby.length > 0) {
                        let msg = `在您附近 ${searchRadius}km 內找到了 ${nearby.length} 個想去的地方：\n`;
                        nearby.slice(0, 3).forEach(i => {
                            const dStr = i.distance < 1 ? `${Math.round(i.distance*1000)}m` : `${i.distance.toFixed(1)}km`;
                            msg += `📍 ${getPocketIcon(i.category)} ${i.name} (約 ${dStr})\n`;
                        });
                        appendMessage(msg + "\n已為您在下方列出口袋名單！");
                        window.loadPocket(); 
                    } else {
                        // 診斷式回覆
                        let diagnosticMsg = `這附近 ${searchRadius}km 內似乎沒有您標記過的口袋名單喔！\n\n`;
                        diagnosticMsg += `💡 診斷資訊：\n`;
                        diagnosticMsg += `• 總清單數量：${allItems.length} 筆\n`;
                        diagnosticMsg += `• 有座標記錄：${itemsWithCoords.length} 筆\n`;
                        
                        if (itemsWithCoords.length === 0) {
                            diagnosticMsg += `\n⚠️ 偵測到所有資料都缺少座標！請檢查 Google Sheet 的 lat/lng 欄位是否為空。`;
                        } else {
                            diagnosticMsg += `\n您可以試著在口袋名單中手動搜尋特定店名。`;
                        }
                        
                        appendMessage(diagnosticMsg);
                    }
                }
            } catch (e) {
                console.error("Location Error:", e);
                appendMessage("暫時無法取得定位，請確保已開啟權限並使用 HTTPS 連線。");
            }
            return;
        }

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: message })
            });
            const data = await response.json();

            if (data.status === 'success') {
                if (data.type === 'query_schedule') {
                    renderScheduleCard(data.data, data.date_str);
                } else if (data.type === 'open_spreadsheet') {
                    appendMessage(data.message);
                    setTimeout(() => window.open(data.url, '_blank'), 1000);
                } else {
                    appendMessage(data.message || data.reply);
                }
            } else {
                appendMessage("❌ 錯誤：" + (data.message || "發生未知錯誤"));
            }
        } catch (error) {
            appendMessage("❌ 伺服器連線失敗");
        }
    };

    // --- 事件監聽 ---
    sendBtn.onclick = () => window.handleSend();
    userInput.onkeypress = (e) => { if (e.key === 'Enter') window.handleSend(); };
    
    document.getElementById('manual_date').valueAsDate = new Date();

    const sModal = document.getElementById('scheduleModal');
    if (sModal) sModal.onclick = (e) => { if (e.target === sModal) window.closeModal('scheduleModal'); };
    const eModal = document.getElementById('expenseModal');
    if (eModal) eModal.onclick = (e) => { if (e.target === eModal) window.closeModal('expenseModal'); };
    document.querySelectorAll('.modal-content').forEach(c => c.onclick = (e) => e.stopPropagation());

    // 手動送出行程
    document.getElementById('submitSchedule').onclick = async () => {
        const title = document.getElementById('manual_summary').value;
        const date = document.getElementById('manual_date').value;
        const h = document.getElementById('manual_hour').value;
        const m = document.getElementById('manual_minute').value;
        const ampm = document.getElementById('manual_ampm').value;
        const location = document.getElementById('manual_location') ? document.getElementById('manual_location').value : '';
        const isAllDayCheckbox = document.getElementById('manual_all_day');
        const isAllDay = isAllDayCheckbox ? isAllDayCheckbox.checked : false;

        if (!title || !date) {
            alert('請填寫完整資訊！');
            return;
        }

        let startTime = date;
        let finalIsAllDay = isAllDay;

        if (!isAllDay) {
            let hour24 = parseInt(h);
            if (ampm === 'PM' && hour24 < 12) hour24 += 12;
            if (ampm === 'AM' && hour24 === 12) hour24 = 0;
            const hourStr = String(hour24).padStart(2, '0');
            const minuteStr = String(m).padStart(2, '0');
            startTime = `${date}T${hourStr}:${minuteStr}:00`;
            finalIsAllDay = false;
        }
        
        if (window.editingEventId) {
            appendMessage(`正在更新行程：${title}...`, true);
            const res = await fetch('/api/update_event', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    event_id: window.editingEventId,
                    title,
                    start_time: startTime,
                    location,
                    is_all_day: finalIsAllDay
                })
            });
            const result = await res.json();
            appendMessage(result.message);
            window.closeModal('scheduleModal'); // 移動到這裡
            // 恢復按鈕 UI
            const submitBtn = document.getElementById('submitSchedule');
            if (submitBtn) {
                submitBtn.innerText = '確認加入日曆';
                submitBtn.style.background = '';
            }
        } else {
            appendMessage(`新增行程：${title}`, true);
            const res = await fetch('/api/manual_action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    type: 'calendar', title, start_time: startTime, location, is_all_day: finalIsAllDay
                })
            });
            const result = await res.json();
            appendMessage(result.message);
            if (result.status === 'success') {
                window.closeModal('scheduleModal');
            }
        }
    };

    document.getElementById('submitExpense').onclick = async () => {
        window.calculateResult();
        
        const item = document.getElementById('expense_item').value;
        const amount = document.getElementById('expense_amount').value;
        const category = document.getElementById('expense_category').value;

        if (!item || amount === '0' || !amount) {
            alert('請輸入項目與金額！');
            return;
        }

        closeModal();
        appendMessage(`記帳：${item} $${amount}`, true);
        const res = await fetch('/api/manual_action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'expense', item, amount: parseInt(amount), category })
        });
        const data = await res.json();
        appendMessage(data.message);
        
        // 清空
        document.getElementById('expense_item').value = '';
        clearCalc();
    };

    window.loadMemos = async () => {
        try {
            const res = await fetch('/api/memo/list');
            const data = await res.json();
            if (data.status === 'success') {
                window.renderMemoList(data.data);
            }
        } catch (e) {
            console.error("載入記事失敗", e);
        }
    };

    window.renderMemoList = (memos) => {
        const list = document.getElementById('memo_list');
        if (!list) return;
        list.innerHTML = (memos || []).reverse().map(item => `
            <div style="background: #fff; border: 1px solid #f1f5f9; padding: 12px; border-radius: 12px; margin-bottom: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.03);">
                <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: #94a3b8; margin-bottom: 5px;">
                    <span>${item.date}</span>
                    <span>${item.mood} | ${item.weather}</span>
                </div>
                <div style="font-size: 0.95rem; color: #334155; line-height: 1.5;">${item.content}</div>
            </div>
        `).join('') || '<div style="color: #94a3b8; text-align: center; padding: 20px;">尚無生活記錄 📝</div>';
    };

    // --- 口袋名單功能 (V10.9 完善版) ---
    window.currentPocketFilter = '全部';
    window.selectedPocketCategory = ''; // 預設空白
    window.pocketCategories = JSON.parse(localStorage.getItem('pocketCategories')) || [
        { name: '美食', icon: '🍜' },
        { name: '咖啡', icon: '☕' },
        { name: '景點', icon: '🎡' },
        { name: '住宿', icon: '🏨' },
        { name: '購物', icon: '🛍️' }
    ];

    function getPocketIcon(cat) {
        const found = window.pocketCategories.find(c => c.name === cat);
        return found ? found.icon : '📍';
    }

    window.resetPocketForm = () => {
        const nameInput = document.getElementById('pocket_name');
        const locInput = document.getElementById('pocket_location');
        const noteInput = document.getElementById('pocket_note');
        if (nameInput) nameInput.value = '';
        if (locInput) locInput.value = '';
        if (noteInput) noteInput.value = '';
        document.getElementById('pocket_area').value = '';
        document.getElementById('detected_area_display').style.display = 'none';
        window.selectCategory(''); // 重置類別
        updateSubmitButtonState();
    };

    window.toggleCatDropdown = () => {
        const options = document.getElementById('cat_options');
        if (options) options.classList.toggle('show');
    };

    window.selectCategory = (name, icon) => {
        window.selectedPocketCategory = name;
        const iconToUse = icon || '📍';
        const displayLabel = name ? `${iconToUse} ${name}` : '請選擇';
        
        const labelSpan = document.getElementById('selected_cat').querySelector('span');
        if (labelSpan) {
            labelSpan.innerHTML = displayLabel;
        }
        
        const options = document.getElementById('cat_options');
        if (options) options.classList.remove('show');
        updateSubmitButtonState();
    };

    function updateSubmitButtonState() {
        const btn = document.getElementById('submitPocket');
        if (!btn) return;
        const hasCat = window.selectedPocketCategory !== '';
        const hasName = document.getElementById('pocket_name').value.trim() !== '';
        btn.style.opacity = (hasCat && hasName) ? '1' : '0.3';
        btn.style.pointerEvents = (hasCat && hasName) ? 'auto' : 'none';
    }

    window.addCustomCategory = async () => {
        // 先關掉下拉選單
        const optionsDiv = document.getElementById('cat_options');
        if (optionsDiv) optionsDiv.classList.remove('show');
        
        const result = await window.customCatInput();
        if (result && result.name) {
            // 檢查是否已存在
            const existing = window.pocketCategories.find(c => c.name === result.name);
            if (!existing) {
                window.pocketCategories.push({ name: result.name, icon: result.icon || '📍' });
                localStorage.setItem('pocketCategories', JSON.stringify(window.pocketCategories));
            }
            
            // 重要：如果曾在刪除名單中，將其移除（復原）
            let deleted = JSON.parse(localStorage.getItem('deletedPocketCats') || '[]');
            if (deleted.includes(result.name)) {
                deleted = deleted.filter(c => c !== result.name);
                localStorage.setItem('deletedPocketCats', JSON.stringify(deleted));
            }
            
            // 重新渲染選單 (V10.9 修復正確路徑)
            const response = await fetch('/api/pocket/list');
            const data = await response.json();
            const dbCategories = [...new Set((data.data || []).map(item => item.category))];
            renderCatOptions(dbCategories);
            
            window.selectCategory(result.name, result.icon || '📍');
            const opts = document.getElementById('cat_options');
            if (opts) opts.classList.remove('show');
        }
    };

    function renderCatOptions(categories) {
        const optionsDiv = document.getElementById('cat_options');
        if (!optionsDiv) return;
        
        const deletedCats = JSON.parse(localStorage.getItem('deletedPocketCats') || '[]');
        const allCats = [...window.pocketCategories].filter(c => !deletedCats.includes(c.name));
        
        // 合併資料庫中已有的分類
        const dbCats = [...new Set(categories)].filter(c => !allCats.find(ac => ac.name === c));
        const finalCats = [...allCats, ...dbCats.map(c => ({ name: c, icon: '📍' }))];
        
        optionsDiv.innerHTML = finalCats.map(catObj => `
            <div class="todo-dropdown-item" onclick="window.selectCategory('${catObj.name}', '${catObj.icon}')">
                <span style="margin-right: 8px;">${catObj.icon}</span>
                <div style="flex: 1; font-weight: 600;">${catObj.name}</div>
                <div class="cat-delete-btn" onclick="event.stopPropagation(); window.deleteCategory('${catObj.name}')">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                </div>
            </div>
        `).join('') + `
            <div class="todo-dropdown-item add-new" onclick="window.addCustomCategory()">
                <span>＋</span> 新增類別...
            </div>
        `;
    }

    window.deleteCategory = async (catName) => {
        const catObj = window.pocketCategories.find(c => c.name === catName) || { name: catName, icon: '📍' };
        const confirmed = await window.customConfirm(
            '確定刪除類別？',
            `您即將刪除「${catObj.icon} ${catName}」類別。`,
            '🗑️'
        );
        if (!confirmed) return;
        
        // 1. 從口袋名單分類清單中移除
        window.pocketCategories = window.pocketCategories.filter(c => c.name !== catName);
        localStorage.setItem('pocketCategories', JSON.stringify(window.pocketCategories));
        
        // 2. 記錄到隱藏清單
        let deleted = JSON.parse(localStorage.getItem('deletedPocketCats') || '[]');
        if (!deleted.includes(catName)) deleted.push(catName);
        localStorage.setItem('deletedPocketCats', JSON.stringify(deleted));

        // 3. 重設選取狀態
        if (window.selectedPocketCategory === catName) {
            window.selectCategory('', '📍');
        }

        // 4. 重新渲染選單 (V10.9 修復正確路徑)
        const response = await fetch('/api/pocket/list');
        const data = await response.json();
        const dbCategories = [...new Set((data.data || []).map(item => item.category))];
        renderCatOptions(dbCategories);
    };

    function parseAddressToArea(place) {
        if (!place || !place.address_components) return '';
        let components = place.address_components;
        let country = '';
        let city = '';
        let district = '';

        for (let comp of components) {
            if (comp.types.includes('country')) country = comp.long_name;
            if (comp.types.includes('administrative_area_level_1')) city = comp.long_name;
            if (comp.types.includes('locality') || comp.types.includes('sublocality_level_1')) district = comp.long_name;
        }

        if (country !== 'Taiwan' && country !== '台灣') return country;
        return (city + district).replace('台灣', '');
    }

    window.initPocketAutocomplete = () => {
        const nameInput = document.getElementById('pocket_name');
        const locInput = document.getElementById('pocket_location');
        if (!nameInput || typeof google === 'undefined') return;

        const autocomplete = new google.maps.places.Autocomplete(nameInput, {
            types: ['establishment', 'geocode'],
            fields: ['name', 'formatted_address', 'address_components', 'geometry']
        });

        autocomplete.addListener('place_changed', () => {
            const place = autocomplete.getPlace();
            if (place.name) nameInput.value = place.name;
            if (place.formatted_address) locInput.value = place.formatted_address;
            
            const area = parseAddressToArea(place);
            if (area) {
                const areaInput = document.getElementById('pocket_area');
                const areaDisplay = document.getElementById('detected_area_display');
                const areaVal = document.getElementById('detected_area_val');
                if (areaInput) areaInput.value = area;
                if (areaVal) areaVal.innerText = area;
                if (areaDisplay) areaDisplay.style.display = 'block';
            }
            updateSubmitButtonState();
        });
        
        nameInput.oninput = updateSubmitButtonState;
    };

    window.currentPocketFilter = '全部';
    window.currentAreaFilter = '全部';


    function renderFilterBar(categories) {
        const select = document.getElementById('pocket_filter_cat');
        if (!select) return;
        const currentVal = window.currentPocketFilter;
        const allCats = ['全部', ...new Set(categories)];
        select.innerHTML = allCats.map(cat => `
            <option value="${cat}" ${currentVal === cat ? 'selected' : ''}>
                ${cat === '全部' ? '類別' : cat}
            </option>
        `).join('');
    }

    window.setPocketFilter = (cat) => {
        window.currentPocketFilter = cat;
        window.loadPocket();
    };

    function renderAreaFilterBar(areas) {
        const select = document.getElementById('pocket_filter_area');
        if (!select) return;
        const currentVal = window.currentAreaFilter;
        const allAreas = ['全部', ...new Set(areas)];
        select.innerHTML = allAreas.map(area => `
            <option value="${area}" ${currentVal === area ? 'selected' : ''}>
                ${area === '全部' ? '地區' : area}
            </option>
        `).join('');
    }

    window.setAreaFilter = (area) => {
        window.currentAreaFilter = area;
        window.loadPocket();
    };

    window.deletePocketItem = async (id, name) => {
        const confirmed = await window.customConfirm(
            '確定刪除項目？',
            `您確定要將「${name}」從口袋名單中移除嗎？`,
            '🗑️'
        );
        if (!confirmed) return;
        
        const res = await fetch('/api/pocket/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id })
        });
        if ((await res.json()).status === 'success') {
            window.loadPocket();
        }
    };

    window.loadPocket = async () => {
        const list = document.getElementById('pocket_list');
        if (!list) return;
        
        try {
            const res = await fetch('/api/pocket/list');
            const data = await res.json();
            if (data.status === 'success') {
                const rawItems = data.data || [];
                
                // 1. 生成篩選列
                renderFilterBar([...new Set(rawItems.map(i => i.category))]);
                renderAreaFilterBar([...new Set(rawItems.map(i => i.area).filter(a => a))]);
                renderCatOptions([...new Set(rawItems.map(i => i.category))]);

                // 2. 多重過濾
                let items = rawItems;
                if (window.currentPocketFilter !== '全部') {
                    items = items.filter(i => i.category === window.currentPocketFilter);
                }
                if (window.currentAreaFilter !== '全部') {
                    items = items.filter(i => i.area === window.currentAreaFilter);
                }
                
                // 3. 排序 (依照分類或距離)
                let userLoc = null;
                try { 
                    // 如果目前是需要排序距離，才去抓位置
                    if (rawItems.some(i => i.lat)) {
                        // 這裡不強制等待定位，若有定位才排
                    }
                } catch(e){}

                const priorityMap = { '美食': 1, '旅遊': 2, '住宿': 3, '咖啡': 4, '購物': 5, '其他': 6 };
                items.sort((a, b) => (priorityMap[a.category] || 99) - (priorityMap[b.category] || 99));

                list.innerHTML = items.map(item => {
                    const mapUrl = getMapUrl(item.location || item.name);
                    const icon = getPocketIcon(item.category);
                    
                    // 距離顯示邏輯 (若有座標且有權限)
                    let distHtml = '';
                    if (window.userCoords && item.lat && item.lng) {
                        const d = calculateDistance(window.userCoords.lat, window.userCoords.lng, item.lat, item.lng);
                        const distStr = d < 1 ? `${Math.round(d*1000)}m` : `${d.toFixed(1)}km`;
                        distHtml = `<span style="font-size: 0.7rem; color: #10b981; font-weight: 800; background: #ecfdf5; padding: 2px 8px; border-radius: 6px;">距離約 ${distStr}</span>`;
                    }

                    return `
                        <div style="background: white; border: 1px solid #f1f5f9; padding: 15px; border-radius: 20px; margin-bottom: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.03); animation: fadeIn 0.3s ease;">
                            <div style="display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-bottom: 8px;">
                                <span style="font-size: 0.65rem; color: #fff; background: #14b8a6; padding: 2px 8px; border-radius: 6px; font-weight: 800;">${icon} ${item.category}</span>
                                ${item.area ? `<span style="font-size: 0.65rem; color: #fff; background: #6366f1; padding: 2px 8px; border-radius: 6px; font-weight: 800;">${item.area}</span>` : ''}
                                ${distHtml}
                                <a href="${mapUrl}" target="_blank" style="flex: 1; min-width: 0; font-size: 0.9rem; font-weight: 800; color: #0f172a; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                                    ${item.name}
                                </a>
                                <button onclick="window.deletePocketItem('${item.id}', '${item.name.replace(/'/g, "\\'")}')" 
                                        style="background: none; border: none; color: #ef4444; cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 5px; transition: all 0.2s;">
                                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                                </button>
                            </div>
                            <div style="padding-left: 2px;">
                                ${item.location ? `<div style="font-size: 0.75rem; color: #64748b; display: flex; align-items: center; gap: 4px; margin-bottom: 6px;">
                                    <span>📍</span>
                                    <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${item.location}</span>
                                </div>` : ''}
                                ${item.note ? `<div style="font-size: 0.8rem; color: #64748b; font-style: italic; background: #f8fafc; padding: 6px 10px; border-radius: 8px; display: inline-block; width: 100%;">"${item.note}"</div>` : ''}
                            </div>
                        </div>
                    `;
                }).join('') || `<div style="color: #94a3b8; text-align: center; padding: 40px;">尚未有符合篩選的項目</div>`;
            }
        } catch (e) { console.error("載入口袋失敗", e); }
    };

    document.getElementById('submitPocket').onclick = async () => {
        const name = document.getElementById('pocket_name').value.trim();
        const location = document.getElementById('pocket_location').value.trim();
        const area = document.getElementById('pocket_area').value;
        const note = document.getElementById('pocket_note').value.trim();
        const category = window.selectedPocketCategory;

        if (!name) return;

        const res = await fetch('/api/pocket/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, location, area, note, category })
        });
        if ((await res.json()).status === 'success') {
            window.resetPocketForm();
            window.loadPocket();
        }
    };
});
