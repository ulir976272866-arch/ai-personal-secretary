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

    window.defaultExpenseCategories = ["食", "衣", "住", "行", "育", "樂", "醫", "投資", "公益"];
    window.incomeCategories = ["薪資", "獎金", "投資獲利", "投資", "退款", "其他進帳"];

    // --- 分類選單核心邏輯 (V23.0 完美修復版) ---
    window.updateExpenseCategoryDropdown = (mode = 'expense') => {
        const select = document.getElementById('manual_expense_category');
        if (!select) return;

        select.innerHTML = '';

        const deletedCats = JSON.parse(localStorage.getItem('deletedExpenseCats') || '[]');
        const customCats = window.loadExpenseCategories().filter(c => !deletedCats.includes(c.name));
        
        const incomeMap = { "薪資": "💰", "獎金": "🧧", "投資獲利": "💹", "投資": "📈", "退款": "🔙", "其他進帳": "🪙" };
        const expenseMap = { "食": "🍔", "衣": "👔", "住": "🏠", "行": "🚗", "育": "📚", "樂": "🎬", "醫": "🏥", "投資": "📈", "公益": "💖" };

        let finalCategories = [];
        if (mode === 'income') {
            finalCategories = window.incomeCategories.map(cat => ({ name: cat, icon: incomeMap[cat] || "💰" }));
        } else {
            // 支出模式：預設 + 自訂
            const baseCats = window.defaultExpenseCategories.map(cat => ({ name: cat, icon: expenseMap[cat] || "💸" }));
            const extraCats = customCats.map(cat => ({ name: cat, icon: cat.icon || "📝" }));
            finalCategories = [...baseCats, ...extraCats];
        }

        select.innerHTML = finalCategories.map(item => 
            `<option value="${item.name}">${item.icon} ${item.name}</option>`
        ).join('');
        
        if (mode === 'income') select.value = '薪資';
    };

    // 強制自癒並讀取資料
    window.loadExpenseCategories = () => {
        try {
            const raw = localStorage.getItem('customExpenseCategories');
            let stored = raw ? JSON.parse(raw) : [];
            if (!Array.isArray(stored)) return [];
            
            return stored.map(c => {
                if (typeof c === 'string') return { name: c, icon: '💸' };
                if (c && typeof c === 'object' && c.name) {
                    return { name: String(c.name).trim(), icon: c.icon || '💸' };
                }
                return null;
            }).filter(c => c !== null);
        } catch (e) {
            return [];
        }
    };

    window.saveExpenseCategories = (cats) => {
        localStorage.setItem('customExpenseCategories', JSON.stringify(cats));
    };

    window.updateExpenseDropdown = () => {
        // 直接使用統一的分類下拉選單更新
        const type = document.getElementById('expense_type')?.value || 'expense';
        window.updateExpenseCategoryDropdown(type);
    };

    window.suggestExpenseEmoji = (text) => {
        const suggestions = {
            '寵物': ['🐶', '🐱', '🐹', '🐰'],
            '保養': ['🧴', '✨', '💅', '💄'],
            '化妝': ['💄', '🎨', '✨'],
            '美容': ['💇', '💅', '🧴', '💄', '✨'],
            '美髮': ['💇', '✂️', '💈'],
            '禮物': ['🎁', '💝', '🎂'],
            '保險': ['🛡️', '📄', '💰'],
            '孝親': ['👵', '👴', '🧧', '❤️'],
            '捐款': ['💖', '🤲', '🕊️'],
            '學費': ['🎓', '🎒', '🖋️'],
            '裝修': ['🛠️', '🏠', '🎨'],
            '運動': ['🏃', '🏋️', '🏀', '🎾'],
            '零用': ['💵', '🪙', '🧧'],
            '旅遊': ['✈️', '🏨', '🌍', '📸'],
            '進修': ['📚', '✍️', '💡']
        };
        
        const container = document.getElementById('expense_emoji_suggestions');
        container.innerHTML = '';
        
        // --- 修改核心：如果沒打字，直接收起來 (V16.1) ---
        if (!text || !text.trim()) return;

        // 智慧匹配關鍵字
        const matchedKey = Object.keys(suggestions).find(k => k.includes(text) || text.includes(k));
        
        // 如果沒有匹配到，也不顯示預設的那一排 (比照待辦清單)
        if (!matchedKey) return;
        
        const icons = suggestions[matchedKey];
        icons.forEach(icon => {
            const span = document.createElement('span');
            span.innerText = icon;
            span.style.cssText = "font-size: 1.5rem; cursor: pointer; padding: 6px 10px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; transition: all 0.2s; box-shadow: 0 2px 5px rgba(0,0,0,0.05); flex-shrink: 0;";
            span.onclick = () => {
                document.getElementById('new_expense_cat_preview').innerText = icon;
                document.getElementById('new_expense_cat_icon_hidden').value = icon;
            };
            container.appendChild(span);
        });
    };

    window.confirmAddExpenseCategory = () => {
        const input = document.getElementById('new_expense_cat_name');
        const name = input.value.trim();
        const icon = document.getElementById('new_expense_cat_icon_hidden').value || '💸';
        
        if (name) {
            let current = window.loadExpenseCategories();
            if (!current.some(c => c.name === name)) {
                current.push({ name, icon });
                window.saveExpenseCategories(current);
                window.updateExpenseDropdown();
                
                const select = document.getElementById('manual_expense_category');
                const targetVal = `${icon} ${name}`;
                select.value = targetVal;
                showToast(`已新增並選取：${targetVal}`, 'success');
            } else {
                showToast("此分類已存在喔！");
            }
            closeModal('expenseCatModal');
        } else {
            showToast("請輸入分類名稱！");
        }
    };

    window.openExpenseCatManage = () => {
        const container = document.getElementById('expense_manage_list');
        if (!container) return;
        
        const customCats = window.loadExpenseCategories();
        container.innerHTML = customCats.map(cat => `
            <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px; background: #f8fafc; border-radius: 12px; border: 1px solid #e2e8f0; margin-bottom: 8px;">
                <div style="font-size: 1rem; font-weight: 600; color: #1e293b;">${cat.icon} ${cat.name}</div>
                <button onclick="deleteExpenseCategory('${cat.name}')" style="background: #fee2e2; color: #ef4444; border: none; padding: 6px 12px; border-radius: 8px; font-size: 0.8rem; font-weight: 700; cursor: pointer;">刪除</button>
            </div>
        `).join('');
        
        if (customCats.length === 0) {
            container.innerHTML = '<div style="text-align: center; color: #94a3b8; padding: 20px;">目前沒有自定義分類。</div>';
        }
        openModal('expenseCatManageModal');
    };

    window.deleteExpenseCategory = (name) => {
        const targetText = document.getElementById('delete_expense_cat_target_text');
        if (targetText) targetText.innerHTML = `確定要刪除「${name}」分類嗎？<br><span style="font-size:0.75rem; color:#94a3b8;">(這不會影響已記錄的帳目)</span>`;
        
        const confirmBtn = document.getElementById('confirm_delete_expense_btn');
        if (confirmBtn) confirmBtn.onclick = () => {
            let current = window.loadExpenseCategories().filter(c => c.name !== name);
            window.saveExpenseCategories(current);
            window.updateExpenseDropdown();
            window.openExpenseCatManage(); 
            closeModal('expenseDeleteConfirmModal');
            showToast(`已刪除分類：${name}`, 'success');
        };
        openModal('expenseDeleteConfirmModal');
    };

    window.addNewExpenseCategory = () => {
        document.getElementById('new_expense_cat_name').value = '';
        document.getElementById('new_expense_cat_preview').innerText = '💸';
        document.getElementById('new_expense_cat_icon_hidden').value = '💸';
        document.getElementById('expense_emoji_suggestions').innerHTML = '';
        // 核心修正：不預填建議
        openModal('expenseCatModal');
    };

    window.suggestExpenseExpenseEmoji = (text) => window.suggestExpenseEmoji(text);

    // 初始化選單
    window.updateExpenseDropdown();

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

    // --- 自定義確認彈窗與警告彈窗邏輯 ---
    let confirmResolver = null;
    window.customConfirm = (title, msg, icon = '🗑️', yesText = '確定刪除') => {
        return new Promise((resolve) => {
            confirmResolver = resolve;
            document.getElementById('confirm_title').innerText = title;
            document.getElementById('confirm_msg').innerText = msg;

            // 確保取消按鈕顯示
            const cancelBtn = document.getElementById('confirm_cancel_btn');
            if (cancelBtn) cancelBtn.style.display = 'block';

            const yesBtn = document.getElementById('confirm_yes_btn');
            if (yesBtn) {
                yesBtn.innerText = yesText;
                if (yesText === '移入常用地址') {
                    // 琥珀黃色 (Amber Yellow) - 高顏值漸層
                    yesBtn.style.background = 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)';
                    yesBtn.style.boxShadow = '0 4px 15px rgba(217, 119, 6, 0.35)';
                } else if (yesText === '移回口袋景點') {
                    // 綠色系 (Emerald Green) - 高顏值漸層
                    yesBtn.style.background = 'linear-gradient(135deg, #10b981 0%, #059669 100%)';
                    yesBtn.style.boxShadow = '0 4px 15px rgba(5, 150, 105, 0.35)';
                } else {
                    // 確定刪除 (珊瑚紅/經典紅)
                    yesBtn.style.background = 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)';
                    yesBtn.style.boxShadow = '0 4px 15px rgba(220, 38, 38, 0.35)';
                }
            }

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

    window.customAlert = (title, msg, icon = '⚠️', okText = '好的') => {
        return new Promise((resolve) => {
            confirmResolver = resolve;
            document.getElementById('confirm_title').innerText = title;
            document.getElementById('confirm_msg').innerText = msg;

            // 隱藏取消按鈕
            const cancelBtn = document.getElementById('confirm_cancel_btn');
            if (cancelBtn) cancelBtn.style.display = 'none';

            const yesBtn = document.getElementById('confirm_yes_btn');
            if (yesBtn) {
                yesBtn.innerText = okText;
                // 使用優雅的灰色/暗色漸層作為 Alert 確認按鈕
                yesBtn.style.background = 'linear-gradient(135deg, #475569 0%, #334155 100%)';
                yesBtn.style.boxShadow = '0 4px 15px rgba(51, 65, 85, 0.35)';
            }

            const svgIcon = document.getElementById('confirm_svg');
            const iconContainer = document.getElementById('confirm_icon_container');
            svgIcon.style.display = 'none';

            let emojiEl = iconContainer.querySelector('.emoji-icon');
            if (!emojiEl) {
                emojiEl = document.createElement('div');
                emojiEl.className = 'emoji-icon';
                emojiEl.style.fontSize = '2.5rem';
                iconContainer.appendChild(emojiEl);
            }
            emojiEl.innerText = icon;

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
            document.getElementById('duration_input_wrapper').style.display = 'block';

            // 重置所有時間與預估時間選單為未填寫狀態（防呆必選）
            document.getElementById('manual_ampm').value = '';
            if (window.updateHourOptions) window.updateHourOptions('');
            document.getElementById('manual_hour').value = '';
            document.getElementById('manual_minute').value = '';
            document.getElementById('manual_duration').value = '';

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
        if (id === 'healthModal') {
            // 重置為加載狀態，避免閃爍舊的或預設數據 (V14.8)
            const daysEl = document.querySelector('.health-status-days');
            const descEl = document.querySelector('.health-status-desc');
            if (daysEl) daysEl.innerHTML = `-- <span style="font-size: 1.2rem;">天</span>`;
            if (descEl) descEl.innerText = `正在計算預測日期...`;
            
            const stats = document.querySelectorAll('.health-stat-box .val');
            if (stats.length >= 2) {
                stats[0].innerHTML = `-- <span>天</span>`;
                stats[1].innerHTML = `-- <span>天</span>`;
            }
            
            const historyList = document.getElementById('health_history_list');
            if (historyList) {
                historyList.innerHTML = `<div style="text-align: center; padding: 20px; color: #94a3b8;">⏳ 正在載入歷史紀錄...</div>`;
            }

            if (window.loadHealthInfo) window.loadHealthInfo();
        }
        if (id === 'trainingModal') {
            if (window.loadTrainingRules) window.loadTrainingRules();
        }
        if (id === 'symptomModal') {
            if (window.loadSymptoms) window.loadSymptoms();
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
                                    ${(window.todoCategories.find(c => c.name === category) || { icon: '📝' }).icon} ${category}
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

            // 💡 雙重條件排序：1. 必買 > 可買 > 可不買 2. 同分類依建立時間從小到大（早到晚）排序
            const getCategoryWeight = (cat) => {
                if (!cat) return 4;
                const c = cat.trim();
                if (c.includes('必買')) return 1;
                if (c.includes('可買') || c.includes('家用') || c.includes('送禮')) return 2;
                if (c.includes('可不買') || c.includes('靈感')) return 3;
                return 4;
            };

            activeWishes.sort((a, b) => {
                const weightA = getCategoryWeight(a.分類);
                const weightB = getCategoryWeight(b.分類);
                if (weightA !== weightB) {
                    return weightA - weightB;
                }
                const idA = parseInt(a['唯一 ID'] || a.id) || 0;
                const idB = parseInt(b['唯一 ID'] || b.id) || 0;
                return idA - idB;
            });

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

                let linkHtml = '';
                const noteVal = (item['備註/連結'] || '').trim();
                if (noteVal) {
                    if (noteVal.startsWith('http://') || noteVal.startsWith('https://')) {
                        // 偵測是否為手機端
                        const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
                        
                        // 辨識平台
                        if (noteVal.includes('shopee') || noteVal.includes('蝦皮')) {
                            // 手機端編譯為強制開啟蝦皮 App 的 Deep Link！
                            const targetUrl = isMobile ? `shopeetw://urls?url=${encodeURIComponent(noteVal)}` : noteVal;
                            linkHtml = `<a href="${targetUrl}" target="_blank" style="text-decoration: none; margin-top: 10px; display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 10px; background: linear-gradient(135deg, #ff5722 0%, #ff7043 100%); color: white; font-size: 0.75rem; font-weight: 800; box-shadow: 0 2px 6px rgba(255, 87, 34, 0.2);"><span style="font-size:0.9rem;">🧡</span> 蝦皮商城 ${isMobile ? '📲' : ''}</a>`;
                        } else if (noteVal.includes('momo')) {
                            linkHtml = `<a href="${noteVal}" target="_blank" style="text-decoration: none; margin-top: 10px; display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 10px; background: linear-gradient(135deg, #d81b60 0%, #ec407a 100%); color: white; font-size: 0.75rem; font-weight: 800; box-shadow: 0 2px 6px rgba(216, 27, 96, 0.2);"><span style="font-size:0.9rem;">💖</span> momo 購物</a>`;
                        } else {
                            linkHtml = `<a href="${noteVal}" target="_blank" style="text-decoration: none; margin-top: 10px; display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 10px; background: linear-gradient(135deg, #475569 0%, #64748b 100%); color: white; font-size: 0.75rem; font-weight: 800; box-shadow: 0 2px 6px rgba(71, 85, 105, 0.15);"><span style="font-size:0.9rem;">🔗</span> 前往購買</a>`;
                        }
                    } else {
                        // 純文字備註
                        linkHtml = `<div style="font-size: 0.8rem; opacity: 0.8; margin-top: 8px; font-weight: 500; display: flex; align-items: center; gap: 4px;">📝 ${noteVal}</div>`;
                    }
                }

                return `
                    <div style="${cardStyle} padding: 18px; border-radius: 18px; margin-bottom: 15px; box-shadow: 0 4px 12px rgba(0,0,0,0.03); transition: transform 0.2s;" onactive="this.style.transform='scale(0.98)'">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                            <div style="font-weight: 800; font-size: 1.1rem; flex: 1;">
                                ${item.商品名稱}
                                ${linkHtml ? `<div style="margin-top: 5px;">${linkHtml}</div>` : ''}
                            </div>
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
                                <button onclick="window.editWish('${itemID}', '${item.商品名稱.replace(/'/g, "\\'")}', '${item.預估價格}', '${noteVal.replace(/'/g, "\\'")}', '${item.分類}')" 
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
        if (!(await window.customConfirm('確定要斷捨離？', `確定要從清單移除「${title}」嗎？`))) return;

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

            const submitBtn = document.getElementById('saveWishBtn');
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
        document.getElementById('wish_note').value = note; // 👈 載入網址或備註！
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

        // 修改按鈕 UI 為統一的勾勾圖標，並保持正方形
        const submitBtn = document.getElementById('saveWishBtn');
        if (submitBtn) {
            submitBtn.innerHTML = '✓';
            submitBtn.style.background = '#10b981';
            submitBtn.style.width = '45px';
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

    window.pendingCompletionTimers = window.pendingCompletionTimers || {};

    window.toggleEventDone = async (id) => {
        const lis = document.querySelectorAll(`[id="event_li_${id}"]`);
        if (lis.length === 0) return;

        const firstLi = lis[0];
        const btn = firstLi.querySelector('.done-btn');
        const isCompleted = btn.classList.contains('completed');

        // 2秒內再次點擊 ➔ 「撤銷/取消打勾完成」
        if (window.pendingCompletionTimers[id]) {
            clearTimeout(window.pendingCompletionTimers[id]);
            delete window.pendingCompletionTimers[id];

            lis.forEach(li => {
                const b = li.querySelector('.done-btn');
                if (b) {
                    b.classList.remove('completed');
                    b.innerText = '✓';
                }
            });
            return;
        }

        if (!isCompleted) {
            // ==========================================
            // 情況一：標記完成 (給予 2 秒的「撤銷完成」緩衝時間，防誤觸)
            // ==========================================
            lis.forEach(li => {
                const b = li.querySelector('.done-btn');
                if (b) {
                    b.classList.add('completed');
                    b.innerText = '完成';
                }
            });

            // 設定 2 秒後自動執行隱藏與背景 Google Calendar 同步
            window.pendingCompletionTimers[id] = setTimeout(() => {
                delete window.pendingCompletionTimers[id];

                // A. 隱藏動畫
                lis.forEach(li => li.classList.add('fade-out'));

                // B. 立即更新本地快取 (隱藏名單)
                let hidden = JSON.parse(localStorage.getItem('hiddenPocketEvents') || '[]');
                if (!hidden.includes(id)) hidden.push(id);
                localStorage.setItem('hiddenPocketEvents', JSON.stringify(hidden));

                // C. 更新 DOM 中的顯示狀態並觸發查詢
                setTimeout(() => {
                    lis.forEach(li => {
                        li.style.display = 'none';
                        const card = li.closest('.schedule-card');
                        if (card) {
                            const restoreBtn = card.querySelector('.restore-btn-ui');
                            if (restoreBtn) {
                                restoreBtn.innerText = `🔄 恢復隱藏(${hidden.length})`;
                            }
                        }
                    });
                    // 重新載入以維持最新狀態
                    window.querySchedule(window.lastQueryDays || 7);
                }, 400);

                // D. 背景非同步向後端同步，標記為完成 (打勾)
                fetch('/api/toggle_completion', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ event_id: id })
                }).catch(e => console.error("Sync Error in background:", e));

            }, 2000);

        } else {
            // ==========================================
            // 情況二：原本已完成且恢復隱藏，點選則「取消完成」
            // ==========================================
            lis.forEach(li => {
                const b = li.querySelector('.done-btn');
                if (b) {
                    b.classList.remove('completed');
                    b.innerText = '✓';
                }
            });

            // A. 立即從隱藏名單中移除
            let hidden = JSON.parse(localStorage.getItem('hiddenPocketEvents') || '[]');
            hidden = hidden.filter(item => item !== id);
            localStorage.setItem('hiddenPocketEvents', JSON.stringify(hidden));

            // B. 重整畫面以立即恢復顯示
            setTimeout(() => {
                window.querySchedule(window.lastQueryDays || 7);
            }, 100);

            // C. 背景非同步向後端同步，取消完成標記 (去打勾)
            fetch('/api/toggle_completion', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ event_id: id })
            }).catch(e => console.error("Sync Error in background:", e));
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

        const activeEvents = events.filter(e => !e.completed && !hiddenEvents.includes(e.id));

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
                    <div class="event-address-row" style="display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 4px;">
                        <div style="display: flex; align-items: center; gap: 4px; flex: 1; min-width: 0;">
                            <div class="event-address-icon" style="flex-shrink: 0;">📍</div>
                            <a href="${mapUrl}" class="location-link" style="color: #94a3b8; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${event.location}</a>
                        </div>
                        <button id="add_fav_btn_${event.id}" onclick="window.addLocationToFavorites('${event.location.replace(/'/g, "\\'")}', '${event.title.replace(/'/g, "\\'")}', 'add_fav_btn_${event.id}')" 
                                style="cursor: pointer; background: #fffbeb; color: #d97706; border: 1.5px solid #fde68a; font-size: 0.65rem; font-weight: 800; padding: 2px 6px; border-radius: 6px; display: inline-flex; align-items: center; gap: 2px; transition: all 0.2s; white-space: nowrap;" 
                                class="add-fav-loc-btn">
                            📌 常用
                        </button>
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
                            <span class="action-link edit" onclick="window.editEvent('${event.id}', '${event.title.replace(/'/g, "\\'")}', '${(event.location || "").replace(/'/g, "\\'")}', '${event.start_time}', '${event.end_time || ""}', ${event.is_all_day})">
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

    function renderCompletedScheduleCard(events, keyword, days) {
        const card = document.createElement('div');
        card.className = 'schedule-card';

        const kLabel = keyword ? `關鍵字「${keyword}」` : '所有';
        let headerHtml = `
            <div class="schedule-header" style="display: flex; justify-content: space-between; align-items: center; padding: 12px 15px; border-bottom: 1px solid #f1f5f9;">
                <h3 style="margin:0; font-size: 1rem; color: #0f172a;">🔍 歷史行程 (${kLabel})</h3>
                <span style="font-size: 0.7rem; color: #475569; background: #f1f5f9; padding: 4px 10px; border-radius: 8px; font-weight: 800; border: 1.5px solid #cbd5e1;">
                    過去 ${days} 天
                </span>
            </div>
        `;

        if (events.length === 0) {
            card.innerHTML = headerHtml + `
                <div style="padding: 30px 15px; text-align: center;">
                    <p style="color: #64748b; margin:0;">沒有找到任何符合的行程喔！</p>
                </div>
            `;
            chatHistory.appendChild(card);
            scrollToBottom();
            return;
        }

        let listHtml = '<div class="schedule-list">';
        events.forEach(event => {
            let locationHtml = '';
            if (event.location) {
                const mapUrl = getMapUrl(event.location);
                locationHtml = `
                    <div class="event-address-row" style="display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 4px;">
                        <div style="display: flex; align-items: center; gap: 4px; flex: 1; min-width: 0;">
                            <div class="event-address-icon" style="flex-shrink: 0;">📍</div>
                            <a href="${mapUrl}" class="location-link" style="color: #94a3b8; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${event.location}</a>
                        </div>
                        <button id="add_fav_btn_${event.id}" onclick="window.addLocationToFavorites('${event.location.replace(/'/g, "\\'")}', '${event.title.replace(/'/g, "\\'")}', 'add_fav_btn_${event.id}')" 
                                style="cursor: pointer; background: #fffbeb; color: #d97706; border: 1.5px solid #fde68a; font-size: 0.65rem; font-weight: 800; padding: 2px 6px; border-radius: 6px; display: inline-flex; align-items: center; gap: 2px; transition: all 0.2s; white-space: nowrap;" 
                                class="add-fav-loc-btn">
                            📌 常用
                        </button>
                    </div>`;
            }

            let itemBorder = event.completed ? '4px solid #10b981' : '4px solid #f59e0b';
            let timeColor = event.completed ? '#10b981' : '#f59e0b';
            let titleHtml = event.completed 
                ? `<div class="event-title-row" style="text-decoration: line-through; color: #94a3b8;">✅ ${event.title}</div>`
                : `<div class="event-title-row" style="color: #0f172a; font-weight: 700;">${event.title}</div>`;
            
            let actionBtnHtml = event.completed
                ? `<button onclick="window.restoreCompletedEvent('${event.id}', '${event.title.replace(/'/g, "\\'")}')" 
                                style="cursor: pointer; background: #ecfdf5; border: 1.5px solid #a7f3d0; color: #047857; padding: 4px 10px; border-radius: 8px; font-size: 0.7rem; font-weight: 800; display: inline-flex; align-items: center; gap: 2px; transition: all 0.2s; border-radius: 8px;">
                            ↩️ 恢復
                        </button>`
                : `<button onclick="window.completeEventFromSearch('${event.id}', '${event.title.replace(/'/g, "\\'")}')" 
                                style="cursor: pointer; background: #fffbeb; border: 1.5px solid #fde68a; color: #d97706; padding: 4px 10px; border-radius: 8px; font-size: 0.7rem; font-weight: 800; display: inline-flex; align-items: center; gap: 2px; transition: all 0.2s; border-radius: 8px;">
                            ✔️ 完成
                        </button>`;

            listHtml += `
                <div id="completed_event_li_${event.id}" class="schedule-item" style="border-left: ${itemBorder};">
                    <div class="event-info" style="flex: 1;">
                        <div class="event-time-row" style="color: ${timeColor}; font-weight: 800;">[${event.date}] ${event.time}</div>
                        ${titleHtml}
                        ${locationHtml}
                    </div>
                    <div class="event-actions" style="display: flex; flex-direction: column; gap: 6px; align-items: flex-end;">
                        ${actionBtnHtml}
                    </div>
                </div>
            `;
        });
        listHtml += '</div>';
        card.innerHTML = headerHtml + listHtml;
        chatHistory.appendChild(card);
        scrollToBottom();
    }

    window.restoreCompletedEvent = async (id, name) => {
        showToast(`🔄 正在將「${name}」恢復為未完成...`, 'info');
        
        try {
            // A. 從隱藏名單中移除
            let hidden = JSON.parse(localStorage.getItem('hiddenPocketEvents') || '[]');
            hidden = hidden.filter(item => item !== id);
            localStorage.setItem('hiddenPocketEvents', JSON.stringify(hidden));

            // B. 發送 API 請求取消完成標記
            const res = await fetch('/api/toggle_completion', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ event_id: id })
            });
            const data = await res.json();
            
            if (data.status === 'success') {
                showToast(`✅ 已成功將「${name}」恢復至未完成日程！`, 'success');
                // C. 將該行卡片項目更新為「已恢復」視覺
                const li = document.getElementById(`completed_event_li_${id}`);
                if (li) {
                    li.style.borderLeft = '4px solid #f59e0b';
                    const timeRow = li.querySelector('.event-time-row');
                    if (timeRow) timeRow.style.color = '#f59e0b';
                    
                    const titleRow = li.querySelector('.event-title-row');
                    if (titleRow) {
                        titleRow.style.textDecoration = 'none';
                        titleRow.style.color = '#0f172a';
                        titleRow.innerText = name;
                    }
                    const btn = li.querySelector('.event-actions button');
                    if (btn) {
                        btn.onclick = () => window.completeEventFromSearch(id, name);
                        btn.style.background = '#fffbeb';
                        btn.style.border = '1.5px solid #fde68a';
                        btn.style.color = '#d97706';
                        btn.innerHTML = '✔️ 完成';
                    }
                }
            } else {
                showToast(`❌ 恢復失敗：${data.message}`, 'error');
            }
        } catch (e) {
            showToast('❌ 伺服器連線失敗', 'error');
        }
    };

    window.completeEventFromSearch = async (id, name) => {
        showToast(`🔄 正在將「${name}」標記為已完成...`, 'info');
        
        try {
            // A. 發送 API 請求標記為已完成 (加勾)
            const res = await fetch('/api/toggle_completion', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ event_id: id })
            });
            const data = await res.json();
            
            if (data.status === 'success') {
                showToast(`✅ 已成功完成「${name}」！`, 'success');
                
                // B. 將該行卡片項目更新為「已完成」視覺 (變綠、劃線、變按鈕)
                const li = document.getElementById(`completed_event_li_${id}`);
                if (li) {
                    li.style.borderLeft = '4px solid #10b981';
                    const timeRow = li.querySelector('.event-time-row');
                    if (timeRow) timeRow.style.color = '#10b981';
                    
                    const titleRow = li.querySelector('.event-title-row');
                    if (titleRow) {
                        titleRow.style.textDecoration = 'line-through';
                        titleRow.style.color = '#94a3b8';
                        titleRow.innerHTML = `✅ ${name}`;
                    }
                    const btn = li.querySelector('.event-actions button');
                    if (btn) {
                        // 重新綁定為 restoreCompletedEvent
                        btn.onclick = () => window.restoreCompletedEvent(id, name);
                        btn.style.background = '#ecfdf5';
                        btn.style.border = '1.5px solid #a7f3d0';
                        btn.style.color = '#047857';
                        btn.innerHTML = '↩️ 恢復';
                    }
                }
            } else {
                showToast(`❌ 操作失敗：${data.message}`, 'error');
            }
        } catch (e) {
            showToast('❌ 伺服器連線失敗', 'error');
        }
    };

    let addFavAddressResolver = null;
    window.openAddFavAddressModal = (location, defaultName) => {
        return new Promise((resolve) => {
            addFavAddressResolver = resolve;
            document.getElementById('fav_address_preview').innerText = `📍 地址：${location}`;
            document.getElementById('fav_address_name_input').value = defaultName;
            document.getElementById('addFavAddressModal').classList.add('show');
            setTimeout(() => {
                const input = document.getElementById('fav_address_name_input');
                input.focus();
                input.select(); // 自動全選預設標題，方便直接修改
            }, 300);
        });
    };

    window.closeAddFavAddressModal = (confirmed) => {
        const name = document.getElementById('fav_address_name_input').value.trim();
        document.getElementById('addFavAddressModal').classList.remove('show');
        if (addFavAddressResolver) addFavAddressResolver(confirmed ? name : null);
    };

    window.addLocationToFavorites = async (location, eventTitle, buttonId) => {
        // 去除標記完成的 ✅ 符號（如果是已完成的行程）
        const cleanTitle = eventTitle.replace(/^✅\s*/, '');
        const name = await window.openAddFavAddressModal(location, cleanTitle);
        if (!name) return; // 使用者按取消

        showToast(`📍 正在將「${name}」存入常用地址...`, 'info');

        try {
            const res = await fetch('/api/pocket/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    category: '常用',
                    name: name,
                    location: location,
                    note: '來自日程匯入'
                })
            });
            const data = await res.json();

            if (data.status === 'success') {
                showToast(`📌 已成功將「${name}」加入常用地址！`, 'success');

                // A. 尋找畫面中所有同名/同 event 的 設為常用 按鈕並更新視覺
                const btns = document.querySelectorAll(`[id="${buttonId}"]`);
                btns.forEach(btn => {
                    btn.disabled = true;
                    btn.style.background = '#f1f5f9';
                    btn.style.border = '1px solid #cbd5e1';
                    btn.style.color = '#94a3b8';
                    btn.style.cursor = 'default';
                    btn.innerHTML = '✓ 已設常用';
                });

                // B. 主動重整口袋面板
                if (typeof window.loadPocket === 'function') {
                    window.loadPocket();
                }
            } else {
                showToast(`❌ 存入失敗：${data.message}`, 'error');
            }
        } catch (e) {
            showToast('❌ 伺服器連線失敗', 'error');
        }
    };

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
    clearBtn.onclick = async () => {
        if (await window.customConfirm('確定清空對話？', '清空後將無法復原目前的對話內容喔！', '🧹')) {
            chatHistory.innerHTML = '';
            appendMessage('對話已清空。');
        }
    };

    window.editEvent = (id, title, location, startTime, endTime, isAllDay) => {
        window.editingEventId = id;
        document.getElementById('manual_summary').value = title;
        document.getElementById('manual_location').value = location;

        const dateInput = document.getElementById('manual_date');
        const allDayCheckbox = document.getElementById('manual_all_day');
        const timeWrapper = document.getElementById('time_input_wrapper');
        const durationWrapper = document.getElementById('duration_input_wrapper');

        if (isAllDay) {
            dateInput.value = startTime;
            allDayCheckbox.checked = true;
            timeWrapper.style.display = 'none';
            if (durationWrapper) durationWrapper.style.display = 'none';
        } else {
            // startTime format: YYYY-MM-DDTHH:MM:SS+08:00 or YYYY-MM-DDTHH:MM:SSZ
            const dt = new Date(startTime);
            const yyyy = dt.getFullYear();
            const mm = String(dt.getMonth() + 1).padStart(2, '0');
            const dd = String(dt.getDate()).padStart(2, '0');
            dateInput.value = `${yyyy}-${mm}-${dd}`;

            allDayCheckbox.checked = false;
            timeWrapper.style.display = 'flex';
            if (durationWrapper) durationWrapper.style.display = 'block';

            let hours = dt.getHours();
            const minutes = dt.getMinutes();
            const ampm = hours >= 12 ? 'PM' : 'AM';

            if (hours > 12) hours -= 12;
            if (hours === 0) hours = 12;
            const hoursStr = String(hours).padStart(2, '0');

            document.getElementById('manual_ampm').value = ampm;
            if (window.updateHourOptions) {
                window.updateHourOptions(ampm, hoursStr);
            } else {
                document.getElementById('manual_hour').value = hoursStr;
            }
            document.getElementById('manual_minute').value = String(minutes).padStart(2, '0');

            if (startTime && endTime) {
                const durationMin = Math.round((new Date(endTime) - new Date(startTime)) / 60000);
                document.getElementById('manual_duration').value = String(durationMin);
            } else {
                document.getElementById('manual_duration').value = '';
            }
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
    window.appendCalc = function (val) {
        const amountInput = document.getElementById('expense_amount');
        if (amountInput.value === '0' && val !== '.') {
            amountInput.value = val;
        } else {
            amountInput.value += val;
        }
    };

    window.clearEntry = function () {
        document.getElementById('expense_amount').value = '0';
    };

    window.clearCalc = function () {
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
        voiceBtn.onclick = () => {
            showToast('您的瀏覽器不支援語音功能，請更換瀏覽器後再試', 'warning');
        };
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
        const rangeLabel = days === 1 ? '今日' : (days === 7 ? '本週' : '近30日');
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

    window.handleChatImage = async (input) => {
        if (!input.files || !input.files[0]) return;
        const file = input.files[0];
        
        toggleScanner(true, file);
        const compressedBlob = await compressImage(file);
        await window.handleSend(null, compressedBlob);
        toggleScanner(false);
        input.value = '';
    };

    window.handleSend = async function (text = null, file = null) {
        const message = text || userInput.value.trim();
        if (!message && !file) return;

        if (!text) {
            if (file) {
                appendMessage(`[傳送圖片] ${message || ''}`, true);
            } else {
                appendMessage(message, true);
            }
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
                            const dStr = i.distance < 1 ? `${Math.round(i.distance * 1000)}m` : `${i.distance.toFixed(1)}km`;
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
            let response;
            if (file) {
                const formData = new FormData();
                formData.append('text', message || '');
                formData.append('image', file);
                response = await fetch('/api/chat', {
                    method: 'POST',
                    body: formData
                });
            } else {
                response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: message })
                });
            }
            const data = await response.json();

            if (data.status === 'success') {
                if (data.type === 'query_schedule') {
                    renderScheduleCard(data.data, data.date_str);
                } else if (data.type === 'query_completed_schedule') {
                    renderCompletedScheduleCard(data.data, data.keyword, data.days);
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

    // --- 方案 A：AM/PM 上下午智慧重排排序與補零 ---
    window.updateHourOptions = (selectedAmpm, selectedHourValue = '') => {
        const hourSelect = document.getElementById('manual_hour');
        if (!hourSelect) return;

        hourSelect.innerHTML = '<option value="" selected>時</option>';

        let hours = [];
        if (selectedAmpm === 'AM') {
            // 上午: 06, 07, 08, 09, 10, 11, 12, 01, 02, 03, 04, 05
            hours = ['06', '07', '08', '09', '10', '11', '12', '01', '02', '03', '04', '05'];
        } else if (selectedAmpm === 'PM') {
            // 下午: 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12
            hours = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12'];
        } else {
            // 未選: 01 ~ 12 順序
            hours = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12'];
        }

        hours.forEach(h => {
            const opt = document.createElement('option');
            opt.value = h;
            opt.innerText = h;
            if (h === selectedHourValue) {
                opt.selected = true;
            }
            hourSelect.appendChild(opt);
        });

        if (selectedHourValue) {
            hourSelect.value = selectedHourValue;
        } else {
            hourSelect.value = '';
        }
    };

    // 綁定上下午變更事件以智慧排序小時
    const ampmEl = document.getElementById('manual_ampm');
    if (ampmEl) {
        ampmEl.addEventListener('change', (e) => {
            window.updateHourOptions(e.target.value);
        });
    }

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
        const duration = document.getElementById('manual_duration').value;
        const location = document.getElementById('manual_location') ? document.getElementById('manual_location').value : '';
        const isAllDayCheckbox = document.getElementById('manual_all_day');
        const isAllDay = isAllDayCheckbox ? isAllDayCheckbox.checked : false;

        if (!title || !date) {
            window.customAlert('欄位未滿 ⚠️', '請填寫行程名稱與日期！', '📝');
            return;
        }

        // 防呆驗證：若非全天，強制要求選擇時間與預估時間
        if (!isAllDay) {
            if (!ampm || !h || !m) {
                window.customAlert('時間未選 ⚠️', '請選擇行程的具體時間（上下午、時、分）！', '🕒');
                return;
            }
            if (!duration) {
                window.customAlert('預估時間未選 ⚠️', '請選擇預估行程需要多久時間！', '⏳');
                return;
            }
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

        // 恢復按鈕 UI 用的 Helper
        const resetBtnUI = () => {
            const submitBtn = document.getElementById('submitSchedule');
            if (submitBtn) {
                submitBtn.innerText = window.editingEventId ? '💾 儲存修改' : '確認加入日曆';
                submitBtn.style.background = window.editingEventId ? '#10b981' : '';
            }
        };

        if (window.editingEventId) {
            appendMessage(`正在更新行程：${title}...`, true);
            const res = await fetch('/api/update_event', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    event_id: window.editingEventId,
                    title,
                    start_time: startTime,
                    duration: isAllDay ? 0 : parseInt(duration), // 傳送預估時間
                    location,
                    is_all_day: finalIsAllDay
                })
            });
            const result = await res.json();
            
            if (result.status === 'error') {
                // 原地高質感警示彈窗提示衝突！
                window.customAlert('行程衝突 ⚠️', result.message, '🚫');
                resetBtnUI();
            } else {
                appendMessage(result.message);
                window.closeModal('scheduleModal');
            }
        } else {
            appendMessage(`新增行程：${title}`, true);
            const res = await fetch('/api/manual_action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    type: 'calendar', 
                    title, 
                    start_time: startTime, 
                    duration: isAllDay ? 0 : parseInt(duration), // 傳送預估時間
                    location, 
                    is_all_day: finalIsAllDay
                })
            });
            const result = await res.json();
            
            if (result.status === 'error') {
                // 原地高質感警示彈窗提示衝突！
                window.customAlert('行程衝突 ⚠️', result.message, '🚫');
                resetBtnUI();
            } else {
                appendMessage(result.message);
                window.closeModal('scheduleModal');
            }
        }
    };

    // --- 質感提示系統 (V15.0) ---
    window.showToast = (msg, type = 'warning') => {
        let container = document.querySelector('.toast-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container';
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        const icon = type === 'success' ? '✅' : '⚠️';
        toast.innerHTML = `<span>${icon}</span> <span>${msg}</span>`;

        container.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    };
    // 移除重複的舊函數邏輯


    // --- 掃描儀 UI 控制 (V23.1) ---
    const toggleScanner = (show, file = null) => {
        const overlay = document.getElementById('scanOverlay');
        const preview = document.getElementById('scanPreview');
        if (!overlay) return;
        if (show) {
            if (file) {
                preview.src = URL.createObjectURL(file);
            }
            overlay.style.display = 'flex';
        } else {
            overlay.style.display = 'none';
        }
    };

    // --- 圖片壓縮小助手 (V23.0) ---
    const compressImage = (file, maxWidth = 1024) => {
        return new Promise((resolve) => {
            const reader = new FileReader();
            reader.readAsDataURL(file);
            reader.onload = (event) => {
                const img = new Image();
                img.src = event.target.result;
                img.onload = () => {
                    const canvas = document.createElement('canvas');
                    let width = img.width;
                    let height = img.height;
                    if (width > maxWidth) {
                        height = (maxWidth / width) * height;
                        width = maxWidth;
                    }
                    canvas.width = width;
                    canvas.height = height;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0, width, height);
                    canvas.toBlob((blob) => resolve(blob), 'image/jpeg', 0.8);
                };
            };
        });
    };



    document.getElementById('submitExpense').onclick = async () => {
        window.calculateResult();

        const item = document.getElementById('expense_item').value;
        const amount = document.getElementById('expense_amount').value;
        const category = document.getElementById('manual_expense_category').value;

        // 強制檢查分類 (V14.6)
        if (!category) {
            showToast('請選擇分類！');
            return;
        }

        if (!item || amount === '0' || !amount) {
            showToast('請輸入項目與金額！');
            return;
        }

        const expenseType = document.getElementById('expense_type').value;
        const emoji = expenseType === 'income' ? '💰' : '💸';

        closeModal();
        appendMessage(`${emoji} 記帳：${item} $${amount} [${category}]`, true);
        const res = await fetch('/api/manual_action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'expense', expense_type: expenseType, item, amount: parseInt(amount), category })
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

    window.setExpenseType = (type) => {
        const btnExpense = document.getElementById('type_expense');
        const btnIncome = document.getElementById('type_income');
        const typeInput = document.getElementById('expense_type');
        const itemLabel = document.getElementById('item_label');
        const itemInput = document.getElementById('expense_item');
        const submitBtn = document.getElementById('submitExpense');

        typeInput.value = type;

        if (type === 'income') {
            btnIncome.classList.add('active');
            btnIncome.style.background = 'white';
            btnIncome.style.color = '#3b82f6'; // 藍色
            btnIncome.style.boxShadow = '0 2px 8px rgba(0,0,0,0.05)';

            btnExpense.classList.remove('active');
            btnExpense.style.background = 'transparent';
            btnExpense.style.color = '#64748b';
            btnExpense.style.boxShadow = 'none';

            if (itemLabel) itemLabel.innerText = '收入項目';
            if (itemInput) itemInput.placeholder = '這筆收入是哪來的？';
            if (submitBtn) {
                submitBtn.innerText = '確認收入入帳 💰';
                submitBtn.style.background = '#3b82f6';
            }
            // 自動切換分類選單為收入類別 (V20.0)
            updateExpenseCategoryDropdown('income');
        } else {
            btnExpense.classList.add('active');
            btnExpense.style.background = 'white';
            btnExpense.style.color = '#ef4444'; // 紅色
            btnExpense.style.boxShadow = '0 2px 8px rgba(0,0,0,0.05)';

            btnIncome.classList.remove('active');
            btnIncome.style.background = 'transparent';
            btnIncome.style.color = '#64748b';
            btnIncome.style.boxShadow = 'none';

            if (itemLabel) itemLabel.innerText = '支出項目';
            if (itemInput) itemInput.placeholder = '消費了什麼？';
            if (submitBtn) {
                submitBtn.innerText = '確認支出記帳 💸';
                submitBtn.style.background = 'var(--secondary-color)';
            }
        }
        // 自動切換分類選單
        window.updateExpenseCategoryDropdown(type);
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

    window.currentPocketTab = 'all';
    window.currentPocketFilter = '全部';
    window.currentAreaFilter = '全部';

    window.switchPocketTab = (tab) => {
        window.currentPocketTab = tab;
        const tabAll = document.getElementById('pocket_tab_all');
        const tabFav = document.getElementById('pocket_tab_fav');
        const formCard = document.getElementById('pocket_form_card_container');
        const filterBar = document.getElementById('pocket_filter_bar_container');

        if (tab === 'fav') {
            if (tabFav) {
                tabFav.style.background = 'white';
                tabFav.style.color = '#e11d48';
                tabFav.style.boxShadow = '0 2px 8px rgba(0,0,0,0.05)';
            }
            if (tabAll) {
                tabAll.style.background = 'transparent';
                tabAll.style.color = '#64748b';
                tabAll.style.boxShadow = 'none';
            }
            if (formCard) formCard.style.display = 'none';
            if (filterBar) filterBar.style.display = 'none';
        } else {
            if (tabAll) {
                tabAll.style.background = 'white';
                tabAll.style.color = '#14b8a6';
                tabAll.style.boxShadow = '0 2px 8px rgba(0,0,0,0.05)';
            }
            if (tabFav) {
                tabFav.style.background = 'transparent';
                tabFav.style.color = '#64748b';
                tabFav.style.boxShadow = 'none';
            }
            if (formCard) formCard.style.display = 'block';
            if (filterBar) filterBar.style.display = 'flex';
        }

        window.loadPocket();
    };

    window.copyAddressText = (location, name) => {
        navigator.clipboard.writeText(location).then(() => {
            showToast(`📋 已複製 [${name}] 的地址！`, 'success');
        }).catch(() => {
            showToast('複製失敗，請手動複製', 'error');
        });
    };

    window.moveToFavorites = async (id, name, targetCategory) => {
        const isMovingToFav = targetCategory === '常用';
        const yesText = isMovingToFav ? '移入常用地址' : '移回口袋景點';
        const confirmed = await window.customConfirm(
            isMovingToFav ? '移入常用地址？' : '移回口袋景點？',
            isMovingToFav 
                ? `您確定要將「${name}」移入常用地址，並從口袋景點中隱藏嗎？` 
                : `您確定要將「${name}」移回口袋景點嗎？`,
            '📌',
            yesText
        );
        if (!confirmed) return;

        try {
            const res = await fetch('/api/pocket/update_category', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id, category: targetCategory })
            });
            const data = await res.json();
            if (data.status === 'success') {
                showToast(isMovingToFav ? `📌 已將「${name}」移入常用地址！` : `↩️ 已將「${name}」移回口袋景點！`, 'success');
                window.loadPocket();
            } else {
                showToast('更新失敗，請重試', 'error');
            }
        } catch (e) {
            showToast('連線失敗，請重試', 'error');
        }
    };

    window.editPocketCustomName = (id, currentNote) => {
        const modal = document.getElementById('pocketCustomNameModal');
        const input = document.getElementById('custom_pocket_name_input');
        if (modal && input) {
            input.value = currentNote;
            modal.classList.add('show');
            setTimeout(() => input.focus(), 100);

            window.closePocketCustomNameModal = async (confirmed) => {
                modal.classList.remove('show');
                if (!confirmed) return;

                const newName = input.value.trim();
                try {
                    const res = await fetch('/api/pocket/update_note', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ id, note: newName })
                    });
                    const data = await res.json();
                    if (data.status === 'success') {
                        showToast('✏️ 自訂稱呼已更新！', 'success');
                        window.loadPocket();
                    } else {
                        showToast('更新失敗，請重試', 'error');
                    }
                } catch (e) {
                    showToast('連線失敗，請重試', 'error');
                }
            };
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

                // 2. 分頁與篩選過濾
                let items = rawItems;
                const isFavTab = window.currentPocketTab === 'fav';

                if (isFavTab) {
                    items = items.filter(i => i.category === '常用');
                } else {
                    items = items.filter(i => i.category !== '常用');
                    if (window.currentPocketFilter !== '全部') {
                        items = items.filter(i => i.category === window.currentPocketFilter);
                    }
                    if (window.currentAreaFilter !== '全部') {
                        items = items.filter(i => i.area === window.currentAreaFilter);
                    }
                }

                // 3. 排序
                const priorityMap = { '美食': 1, '常用': 2, '旅遊': 3, '住宿': 4, '咖啡': 5, '購物': 6, '其他': 7 };
                items.sort((a, b) => (priorityMap[a.category] || 99) - (priorityMap[b.category] || 99));

                list.innerHTML = items.map(item => {
                    const mapUrl = getMapUrl(item.location || item.name);
                    const icon = getPocketIcon(item.category);
                    const isFavCategory = item.category === '常用';

                    // 距離顯示邏輯
                    let distHtml = '';
                    if (window.userCoords && item.lat && item.lng) {
                        const d = calculateDistance(window.userCoords.lat, window.userCoords.lng, item.lat, item.lng);
                        const distStr = d < 1 ? `${Math.round(d * 1000)}m` : `${d.toFixed(1)}km`;
                        distHtml = `<span style="font-size: 0.7rem; color: #10b981; font-weight: 800; background: #ecfdf5; padding: 2px 8px; border-radius: 6px;">距離約 ${distStr}</span>`;
                    }

                    // 移入/移出與複製按鈕組合
                    let actionButtonsHtml = '';
                    if (isFavCategory) {
                        actionButtonsHtml = `
                            <span onclick="window.copyAddressText('${(item.location || '').replace(/'/g, "\\'")}', '${item.name.replace(/'/g, "\\'")}')" 
                                  style="cursor: pointer; background: #f1f5f9; color: #475569; padding: 2px 8px; border-radius: 8px; font-size: 0.7rem; font-weight: 800; display: inline-flex; align-items: center; gap: 2px; border: 1.5px solid #cbd5e1; transition: all 0.2s;">
                                📋 複製
                            </span>
                            <span onclick="window.moveToFavorites('${item.id}', '${item.name.replace(/'/g, "\\'")}', '其他')" 
                                  style="cursor: pointer; background: #f0fdf4; color: #16a34a; padding: 2px 8px; border-radius: 8px; font-size: 0.7rem; font-weight: 800; display: inline-flex; align-items: center; gap: 2px; border: 1.5px solid #bbf7d0; transition: all 0.2s;">
                                ↩️ 移回口袋
                            </span>
                        `;
                    } else {
                        actionButtonsHtml = `
                            <span onclick="window.copyAddressText('${(item.location || '').replace(/'/g, "\\'")}', '${item.name.replace(/'/g, "\\'")}')" 
                                  style="cursor: pointer; background: #f1f5f9; color: #475569; padding: 2px 8px; border-radius: 8px; font-size: 0.7rem; font-weight: 800; display: inline-flex; align-items: center; gap: 2px; border: 1.5px solid #cbd5e1; transition: all 0.2s;">
                                📋 複製
                            </span>
                            <span onclick="window.moveToFavorites('${item.id}', '${item.name.replace(/'/g, "\\'")}', '常用')" 
                                  style="cursor: pointer; background: #fffbeb; color: #d97706; padding: 2px 8px; border-radius: 8px; font-size: 0.7rem; font-weight: 800; display: inline-flex; align-items: center; gap: 2px; border: 1.5px solid #fde68a; transition: all 0.2s;" 
                                  class="fav-action-btn">
                                📌 移入常用
                            </span>
                        `;
                    }

                    // 編輯稱呼按鈕 (僅常用地址有)
                    const editBtnHtml = isFavCategory ? `
                        <button onclick="window.editPocketCustomName('${item.id}', '${(item.note || '').replace(/'/g, "\\'")}')" 
                                style="background: none; border: none; color: #10b981; cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 5px; transition: all 0.2s;" 
                                title="編輯稱呼">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                                <path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4z"></path>
                            </svg>
                        </button>
                    ` : '';

                    return `
                        <div style="background: white; border: 1px solid #f1f5f9; padding: 15px; border-radius: 20px; margin-bottom: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.03); animation: fadeIn 0.3s ease;">
                            ${(isFavCategory && item.note) ? `
                                <div style="font-size: 0.85rem; font-weight: 800; color: #e11d48; margin-bottom: 8px; display: flex; align-items: center; gap: 4px;">
                                    <span>📌 自訂稱呼：${item.note}</span>
                                </div>
                            ` : ''}
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
                                ${editBtnHtml}
                            </div>
                            <div style="padding-left: 2px;">
                                ${item.location ? `
                                    <div style="font-size: 0.75rem; color: #64748b; display: flex; align-items: center; gap: 4px; margin-bottom: 6px; justify-content: space-between; width: 100%;">
                                        <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; margin-right: 8px;">📍 ${item.location}</span>
                                        <div style="display: flex; gap: 4px; flex-shrink: 0;">
                                            ${actionButtonsHtml}
                                        </div>
                                    </div>
                                ` : ''}
                                ${(!isFavCategory && item.note) ? `<div style="font-size: 0.8rem; color: #64748b; font-style: italic; background: #f8fafc; padding: 6px 10px; border-radius: 8px; display: inline-block; width: 100%;">"${item.note}"</div>` : ''}
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

    // --- 🌸 生理期健康面板邏輯 ---
    window.loadHealthInfo = async () => {
        try {
            const res = await fetch('/api/health/info');
            const data = await res.json();
            if (data.status === 'success') {
                // 更新狀態大圖卡
                const statusTitleEl = document.getElementById('health_status_title');
                const statusDaysEl = document.getElementById('health_status_days');
                const statusDescEl = document.getElementById('health_status_desc');
                const cardGradientEl = document.getElementById('health_card_gradient');
                const phaseWrapperEl = document.getElementById('health_phase_wrapper');
                const phaseBadgeEl = document.getElementById('health_phase_badge');
                const pregnancyBadgeEl = document.getElementById('health_pregnancy_badge');
                const tipsCardEl = document.getElementById('health_tips_card');

                if (statusTitleEl) statusTitleEl.innerText = data.status_title || '距離下次預測';
                
                if (statusDaysEl) {
                    if (data.is_ongoing) {
                        statusDaysEl.innerHTML = `${data.days_until_next} <span style="font-size: 1.2rem;">天</span>`;
                    } else {
                        statusDaysEl.innerHTML = `${data.days_until_next} <span style="font-size: 1.2rem;">天</span>`;
                    }
                }
                
                if (statusDescEl) {
                    if (data.is_ongoing) {
                        statusDescEl.innerText = `生理週期進行中...`;
                    } else {
                        statusDescEl.innerText = `預計 ${data.next_date} 開始`;
                    }
                }

                // 根據當前生理階段進行動態漸層渲染
                if (data.current_phase && cardGradientEl) {
                    let gradient = '';
                    let shadow = '';
                    let textColor = '';
                    let badgeBg = '';
                    let badgeBorder = '';
                    let tipsBg = '';
                    let tipsBorder = '';
                    let tipsTextColor = '';

                    if (data.current_phase === '生理期') {
                        gradient = 'linear-gradient(135deg, #ffe4e6 0%, #fecdd3 100%)';
                        shadow = '0 8px 25px rgba(251, 113, 133, 0.4)';
                        textColor = '#9f1239';
                        badgeBg = 'rgba(255, 255, 255, 0.7)';
                        badgeBorder = 'rgba(251, 113, 133, 0.4)';
                        tipsBg = 'rgba(255, 241, 242, 0.8)';
                        tipsBorder = '#fecdd3';
                        tipsTextColor = '#be123c';
                    } else if (data.current_phase === '安全期 (濾泡期)' || data.current_phase === '濾泡期 (安全期)') {
                        gradient = 'linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%)';
                        shadow = '0 8px 25px rgba(74, 222, 128, 0.3)';
                        textColor = '#14532d';
                        badgeBg = 'rgba(255, 255, 255, 0.7)';
                        badgeBorder = 'rgba(74, 222, 128, 0.4)';
                        tipsBg = 'rgba(240, 253, 244, 0.8)';
                        tipsBorder = '#bbf7d0';
                        tipsTextColor = '#15803d';
                    } else if (data.current_phase.includes('排卵期')) {
                        gradient = 'linear-gradient(135deg, #ffedd5 0%, #fed7aa 100%)';
                        shadow = '0 8px 25px rgba(251, 146, 60, 0.3)';
                        textColor = '#7c2d12';
                        badgeBg = 'rgba(255, 255, 255, 0.7)';
                        badgeBorder = 'rgba(251, 146, 60, 0.4)';
                        tipsBg = 'rgba(255, 247, 237, 0.8)';
                        tipsBorder = '#fed7aa';
                        tipsTextColor = '#c2410c';
                    } else if (data.current_phase.includes('黃體期')) {
                        gradient = 'linear-gradient(135deg, #f3e8ff 0%, #e9d5ff 100%)';
                        shadow = '0 8px 25px rgba(192, 132, 252, 0.3)';
                        textColor = '#581c87';
                        badgeBg = 'rgba(255, 255, 255, 0.7)';
                        badgeBorder = 'rgba(192, 132, 252, 0.4)';
                        tipsBg = 'rgba(250, 245, 255, 0.8)';
                        tipsBorder = '#e9d5ff';
                        tipsTextColor = '#6b21a8';
                    }

                    cardGradientEl.style.background = gradient;
                    cardGradientEl.style.boxShadow = shadow;
                    if (statusTitleEl) statusTitleEl.style.color = textColor;
                    if (statusDaysEl) statusDaysEl.style.color = textColor;
                    if (statusDescEl) statusDescEl.style.color = textColor;

                    if (phaseWrapperEl && phaseBadgeEl) {
                        phaseBadgeEl.innerHTML = `${data.phase_icon || '🌸'} ${data.current_phase}`;
                        phaseBadgeEl.style.color = textColor;
                        phaseBadgeEl.style.background = badgeBg;
                        phaseBadgeEl.style.borderColor = badgeBorder;
                        
                        if (pregnancyBadgeEl) {
                            pregnancyBadgeEl.innerHTML = data.pregnancy_probability || '🍀 不易懷孕 (安全期)';
                            pregnancyBadgeEl.style.color = textColor;
                            pregnancyBadgeEl.style.borderColor = badgeBorder;
                        }
                        
                        phaseWrapperEl.style.display = 'flex';
                    }

                    if (tipsCardEl) {
                        tipsCardEl.innerHTML = `💡 <b>當前階段特徵：</b><br>${data.phase_desc}`;
                        tipsCardEl.style.background = tipsBg;
                        tipsCardEl.style.borderColor = tipsBorder;
                        tipsCardEl.style.color = tipsTextColor;
                        tipsCardEl.style.display = 'block';
                    }
                }
                
                // 更新統計看板
                const stats = document.querySelectorAll('.health-stat-box .val');
                if (stats.length >= 2) {
                    stats[0].innerHTML = `${data.avg_cycle} <span>天</span>`;
                    stats[1].innerHTML = `${data.avg_length} <span>天</span>`;
                }

                // 更新歷史紀錄
                const historyList = document.getElementById('health_history_list');
                if (historyList) {
                    historyList.innerHTML = data.history.map(item => `
                        <div class="health-history-item">
                            <div class="date-range">${item.start} - ${item.end}</div>
                            <div class="symptoms">${item.symptoms || '無特殊症狀'}</div>
                        </div>
                    `).join('');
                }
            } else {
                showToast(data.message, 'error');
            }
        } catch (e) {
            console.error('載入健康資料失敗:', e);
            showToast('載入失敗，請檢查網路連接', 'error');
        }
    };

    // 綁定快速操作按鈕事件
    document.querySelectorAll('.health-action-btn').forEach(btn => {
        btn.onclick = async function() {
            const isStart = this.classList.contains('start');
            const isEnd = this.classList.contains('end');
            const isSymptom = this.classList.contains('symptom');
            
            const originalHtml = this.innerHTML;
            this.innerHTML = '<div class="icon">⏳</div>處理中...';
            this.style.opacity = '0.7';
            
            try {
                if (isStart) {
                    const res = await fetch('/api/health/record_start', { method: 'POST' });
                    const data = await res.json();
                    if (data.status === 'success') {
                        showToast(data.message, 'success');
                        window.loadHealthInfo();
                    } else {
                        showToast(data.message, 'error');
                    }
                } else if (isEnd) {
                    const res = await fetch('/api/health/record_end', { method: 'POST' });
                    const data = await res.json();
                    if (data.status === 'success') {
                        showToast(data.message, 'success');
                        window.loadHealthInfo();
                    } else {
                        showToast(data.message, 'error');
                    }
                } else if (isSymptom) {
                    window.openModal('symptomModal');
                }
            } catch (e) {
                console.error(e);
                showToast('伺服器連線失敗', 'error');
            } finally {
                this.innerHTML = originalHtml;
                this.style.opacity = '1';
            }
        };
    });

    // --- 🩺 症狀紀錄邏輯 ---
    window.loadSymptoms = async () => {
        try {
            const res = await fetch('/api/health/symptoms/options');
            const data = await res.json();
            if (data.status === 'success') {
                const list = document.getElementById('symptoms_list');
                list.innerHTML = data.data.map(opt => `
                    <div style="background: white; border: 1px solid #cbd5e1; padding: 8px 12px; border-radius: 20px; display: flex; align-items: center; gap: 8px;">
                        <input type="checkbox" id="sym_${opt}" value="${opt}" style="width: 16px; height: 16px; accent-color: #ec4899;">
                        <label for="sym_${opt}" style="font-size: 0.9rem; color: #334155; user-select: none;">${opt}</label>
                        <span onclick="window.deleteSymptom('${opt}')" style="color: #94a3b8; font-size: 0.8rem; margin-left: 5px; cursor: pointer;">&times;</span>
                    </div>
                `).join('');
            }
        } catch (e) {
            console.error('載入症狀選項失敗:', e);
        }
    };

    window.addSymptomOption = async () => {
        const input = document.getElementById('new_symptom_input');
        const val = input.value.trim();
        if (!val) return;
        
        try {
            const res = await fetch('/api/health/symptoms/options', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({option: val})
            });
            const data = await res.json();
            if (data.status === 'success') {
                input.value = '';
                showToast('已新增症狀選項！', 'success');
                window.loadSymptoms();
            }
        } catch (e) {
            showToast('新增失敗', 'error');
        }
    };

    window.deleteSymptom = async (opt) => {
        if(!confirm(`確定要刪除「${opt}」這個選項嗎？`)) return;
        try {
            const res = await fetch('/api/health/symptoms/options', {
                method: 'DELETE',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({option: opt})
            });
            const data = await res.json();
            if (data.status === 'success') {
                showToast('已刪除選項', 'success');
                window.loadSymptoms();
            }
        } catch (e) {
            showToast('刪除失敗', 'error');
        }
    };

    window.saveSymptoms = async () => {
        const checkboxes = document.querySelectorAll('#symptoms_list input[type="checkbox"]:checked');
        const selected = Array.from(checkboxes).map(cb => cb.value);
        
        if (selected.length === 0) {
            showToast('請至少勾選一項症狀哦', 'error');
            return;
        }
        
        try {
            const res = await fetch('/api/health/symptoms/record', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({symptoms: selected})
            });
            const data = await res.json();
            if (data.status === 'success') {
                showToast(data.message, 'success');
                closeModal('symptomModal');
                window.loadHealthInfo();
            } else {
                showToast(data.message, 'error');
            }
        } catch (e) {
            showToast('儲存失敗', 'error');
        }
    };

    // --- ⚙️ AI 訓練室邏輯 ---
    window.loadTrainingRules = async () => {
        try {
            const res = await fetch('/api/training/rules');
            const data = await res.json();
            const list = document.getElementById('ai_rules_list');
            if (data.status === 'success' && list) {
                if (data.data.length === 0) {
                    list.innerHTML = `<div style="text-align:center; padding: 20px; color: #94a3b8;">尚未建立任何規則。快來教 AI 吧！</div>`;
                    return;
                }
                list.innerHTML = data.data.map(rule => `
                    <div style="background: white; padding: 15px; border-radius: 12px; border: 1px solid #e2e8f0; margin-bottom: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
                        <div style="font-weight: 700; color: #1e293b; margin-bottom: 5px;">「${rule.trigger}」</div>
                        <div style="font-size: 0.85rem; color: #64748b;">➔ ${rule.action}</div>
                    </div>
                `).reverse().join(''); // 最新在上
            }
        } catch (e) {
            console.error('載入訓練規則失敗:', e);
        }
    };

    // 綁定訓練按鈕事件
    const trainSubmitBtn = document.querySelector('#trainingModal .submit-btn');
    if (trainSubmitBtn) {
        trainSubmitBtn.onclick = async () => {
            const trigger = document.getElementById('train_trigger').value.trim();
            const action = document.getElementById('train_action').value.trim();
            if (!trigger || !action) {
                showToast('請完整輸入情境與行為喔！');
                return;
            }
            
            const btn = trainSubmitBtn;
            const originalText = btn.innerHTML;
            btn.innerHTML = '建立中...';
            btn.style.opacity = '0.7';

            try {
                const res = await fetch('/api/training/add_rule', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ trigger, action })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast(data.message, 'success');
                    document.getElementById('train_trigger').value = '';
                    document.getElementById('train_action').value = '';
                    window.loadTrainingRules();
                } else {
                    showToast(data.message, 'error');
                }
            } catch (e) {
                showToast('寫入失敗，請稍後再試', 'error');
            } finally {
                btn.innerHTML = originalText;
                btn.style.opacity = '1';
            }
        };
    }
});
