// Google Maps API 回呼 (需在全域作用域)
window.initMap = () => {
    if (window.initAutocomplete) window.initAutocomplete();
};

// =================================================================
// Google OAuth 2.0 登入頁面與安全機制互動邏輯
// =================================================================
window.toggleLoginButton = (checked) => {
    const btn = document.getElementById('google-login-btn');
    if (!btn) return;
    if (checked) {
        btn.classList.remove('disabled');
    } else {
        btn.classList.add('disabled');
    }
};

window.handleLoginClick = (e) => {
    const btn = document.getElementById('google-login-btn');
    if (btn && btn.classList.contains('disabled')) {
        e.preventDefault();
    }
};

window.openNdaModal = (e) => {
    if (e) e.preventDefault();
    const modal = document.getElementById('loginNdaModal');
    if (modal) modal.style.display = 'flex';
};

window.closeLoginNdaModal = () => {
    const modal = document.getElementById('loginNdaModal');
    if (modal) modal.style.display = 'none';
};

// 已移除動態浮水印系統以恢復畫面純淨簡潔與高端美感

document.addEventListener('DOMContentLoaded', () => {
    window.editingEventId = null;

    // --- 🌸 生理健康免責聲明跨裝置自動解鎖同步 ---
    if (!localStorage.getItem('menstrual_disclaimer_agreed')) {
        fetch('/api/health/check_disclaimer')
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success' && data.agreed) {
                    localStorage.setItem('menstrual_disclaimer_agreed', 'true');
                    console.log('[Consent Roaming] 偵測到雲端已有免責聲明同意紀錄，本機已自動同步解鎖生理期助理！');
                }
            })
            .catch(err => {
                console.error('[Consent Roaming] 同步免責聲明狀態失敗:', err);
            });
    }

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
            const baseCats = window.defaultExpenseCategories.map(cat => ({ name: cat, icon: expenseMap[cat] || "💸" }));
            const extraCats = customCats.map(cat => ({ name: cat.name, icon: cat.icon || "📝" }));
            finalCategories = [...baseCats, ...extraCats];
        }

        select.innerHTML = finalCategories.map(item => 
            `<option value="${item.name}">${item.icon} ${item.name}</option>`
        ).join('');
        
        if (mode === 'income') select.value = '薪資';

        // ✅ 同步渲染自訂下拉選單並自動選取第一個分類
        window.renderExpenseCategoryDropdown(mode);
        const defaultCat = mode === 'income'
            ? { name: '薪資', icon: '💰' }
            : { name: '食', icon: '🍔' };
        window.selectExpenseCategoryDisplay(defaultCat.name, defaultCat.icon);
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

    // =====================================================
    // 🎛️ 記帳自訂分類下拉選單 (V14.0 — 與待辦清單同款)
    // =====================================================
    window.toggleExpenseCategoryDropdown = () => {
        const dropdown = document.getElementById('expense_cat_dropdown');
        if (dropdown) dropdown.classList.toggle('show');
    };

    // 純 UI 更新（不觸發特殊邏輯），供 updateExpenseCategoryDropdown 初始化使用
    window.selectExpenseCategoryDisplay = (name, icon) => {
        const displaySpan = document.getElementById('current_expense_cat_display');
        const hiddenInput = document.getElementById('expense_category_hidden');
        const hiddenSelect = document.getElementById('manual_expense_category');
        if (displaySpan) displaySpan.innerHTML = name ? `${icon} ${name}` : '請選擇';
        if (hiddenInput) hiddenInput.value = name || '';
        if (hiddenSelect) hiddenSelect.value = name || '';
    };

    // 選取分類（含投資/公益特殊處理）
    window.selectExpenseCategory = async (name, icon) => {
        const dropdown = document.getElementById('expense_cat_dropdown');
        if (dropdown) dropdown.classList.remove('show');

        // 特殊分類：投資 → paywall
        if (name === '投資' || name === '投資獲利') {
            if (!window.checkFeatureAccess('stock')) {
                const confirmed = await window.customConfirm(
                    '解鎖存股記帳雙向回填特權 💎',
                    '偵測到您記錄了一筆投資性質的交易！升級至 旗艦尊榮會員，即可一鍵解鎖「存股標的自動回填記帳」與「存股自動看盤助手」，省去重複手動記帳的時間！',
                    '🔒', '💎 升級尊榮方案'
                );
                if (confirmed) window.openModal('upgradePaywallModal');
                return; // 不選取，直接返回
            }
        }

        // 特殊分類：公益 → paywall + 顯示上傳區
        if (name === '公益') {
            if (!window.checkFeatureAccess('tax')) {
                const confirmed = await window.customConfirm(
                    '解鎖報稅收據雲端備份特權 💎',
                    '偵測到您記錄了一筆公益性質的交易！升級至 旗艦尊榮會員，即可解鎖「發票收據自動命名歸檔」與「雲端公益資料夾」特權，五月報稅更輕鬆！',
                    '🔒', '💎 升級尊榮方案'
                );
                if (confirmed) window.openModal('upgradePaywallModal');
                return;
            }
            const uploadWrapper = document.getElementById('charity_receipt_upload_wrapper');
            if (uploadWrapper) uploadWrapper.style.display = 'block';
        } else {
            const uploadWrapper = document.getElementById('charity_receipt_upload_wrapper');
            if (uploadWrapper) uploadWrapper.style.display = 'none';
            if (window.clearReceiptFile) window.clearReceiptFile();
        }

        // 更新 UI 顯示 + 同步 hidden inputs
        window.selectExpenseCategoryDisplay(name, icon);
    };

    window.renderExpenseCategoryDropdown = (mode = 'expense') => {
        const dropdown = document.getElementById('expense_cat_dropdown');
        if (!dropdown) return;

        const deletedCats = JSON.parse(localStorage.getItem('deletedExpenseCats') || '[]');
        const customCats = window.loadExpenseCategories().filter(c => !deletedCats.includes(c.name));

        const incomeMap = { "薪資": "💰", "獎金": "🧧", "投資獲利": "💹", "投資": "📈", "退款": "🔙", "其他進帳": "🪙" };
        const expenseMap = { "食": "🍔", "衣": "👔", "住": "🏠", "行": "🚗", "育": "📚", "樂": "🎬", "醫": "🏥", "投資": "📈", "公益": "💖" };

        let finalCategories = [];
        if (mode === 'income') {
            finalCategories = window.incomeCategories.map(cat => ({ name: cat, icon: incomeMap[cat] || "💰" }));
        } else {
            const baseCats = window.defaultExpenseCategories.map(cat => ({ name: cat, icon: expenseMap[cat] || "💸" }));
            const extraCats = customCats.map(cat => ({ name: cat.name, icon: cat.icon || "📝" }));
            finalCategories = [...baseCats, ...extraCats];
        }

        dropdown.innerHTML = finalCategories.map(cat => `
            <div class="todo-dropdown-item" onclick="window.selectExpenseCategory('${cat.name}', '${cat.icon}')">
                <span>${cat.icon}</span>
                <div style="flex: 1;">${cat.name}</div>
                ${mode !== 'income' ? `<div class="cat-delete-btn" onclick="event.stopPropagation(); window.removeExpenseCategory('${cat.name}')">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                </div>` : ''}
            </div>
        `).join('') + `
            <div class="todo-dropdown-item add-new" onclick="window.addNewExpenseCategoryFromDropdown()">
                <span>＋</span> 新增分類...
            </div>
        `;
    };

    window.removeExpenseCategory = async (name) => {
        const confirmed = await window.customConfirm(
            '確定刪除分類？',
            `您即將刪除「${name}」分類。<br><span style="font-size:0.75rem; color:#94a3b8;">(這不會影響已記錄的帳目)</span>`,
            '🗑️'
        );
        if (!confirmed) return;

        // 移除自訂分類
        let current = window.loadExpenseCategories().filter(c => c.name !== name);
        window.saveExpenseCategories(current);

        // 標記為刪除（備援）
        let deleted = JSON.parse(localStorage.getItem('deletedExpenseCats') || '[]');
        if (!deleted.includes(name)) deleted.push(name);
        localStorage.setItem('deletedExpenseCats', JSON.stringify(deleted));

        // 如果目前選的就是被刪除的，重設為食
        const currentVal = document.getElementById('expense_category_hidden')?.value;
        const currentMode = document.getElementById('expense_type')?.value || 'expense';
        if (currentVal === name) {
            const fallback = currentMode === 'income' ? { name: '薪資', icon: '💰' } : { name: '食', icon: '🍔' };
            window.selectExpenseCategoryDisplay(fallback.name, fallback.icon);
        }

        window.updateExpenseCategoryDropdown(currentMode);
        showToast(`已刪除分類：${name}`, 'success');
    };

    window.addNewExpenseCategoryFromDropdown = async () => {
        const dropdown = document.getElementById('expense_cat_dropdown');
        if (dropdown) dropdown.classList.remove('show');

        // 共用待辦清單的 customCatInput 彈窗 ✅
        const result = await window.customCatInput();
        if (result && result.name) {
            let current = window.loadExpenseCategories();
            if (!current.some(c => c.name === result.name)) {
                current.push({ name: result.name, icon: result.icon || '💸' });
                window.saveExpenseCategories(current);
            }

            // 若曾被標記為刪除，移除該標記
            let deleted = JSON.parse(localStorage.getItem('deletedExpenseCats') || '[]');
            deleted = deleted.filter(c => c !== result.name);
            localStorage.setItem('deletedExpenseCats', JSON.stringify(deleted));

            const currentMode = document.getElementById('expense_type')?.value || 'expense';
            window.updateExpenseCategoryDropdown(currentMode);
            // ✅ 新增後自動選取該分類
            window.selectExpenseCategory(result.name, result.icon || '💸');
            showToast(`已新增並選取：${result.icon || '💸'} ${result.name}`, 'success');
        }
    };

    // 點擊外部關閉分類下拉選單
    document.addEventListener('click', (e) => {
        const selector = document.getElementById('expense_cat_selector');
        if (selector && !selector.contains(e.target)) {
            const dropdown = document.getElementById('expense_cat_dropdown');
            if (dropdown) dropdown.classList.remove('show');
        }

        // ✅ 點擊外部關閉口袋名單分類下拉選單 (V6.2 Fix)
        const pocketSelector = document.getElementById('custom_cat_dropdown');
        if (pocketSelector && !pocketSelector.contains(e.target)) {
            const pocketDropdown = document.getElementById('cat_options');
            if (pocketDropdown) pocketDropdown.classList.remove('show');
        }

        // ✅ 點擊外部關閉待辦清單分類下拉選單 (V6.5 Fix)
        const todoSelector = document.getElementById('todo_category_selector');
        const todoDropdown = document.getElementById('todo_cat_dropdown');
        if (todoSelector && todoDropdown && !todoSelector.contains(e.target) && !todoDropdown.contains(e.target)) {
            todoDropdown.classList.remove('show');
        }
    });

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
                
                // ✅ 修正：option value 是乾淨的 name（無 emoji 前綴），直接設定 name 即可選中！
                const select = document.getElementById('manual_expense_category');
                if (select) select.value = name;
                window.selectExpenseCategoryDisplay(name, icon);
                showToast(`已新增並選取：${icon} ${name}`, 'success');
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
    window.customConfirm = (title, msg, icon = '🗑️', yesText = '確定刪除', showCancel = true) => {
        return new Promise((resolve) => {
            confirmResolver = resolve;
            document.getElementById('confirm_title').innerText = title;
            document.getElementById('confirm_msg').innerHTML = msg;

            const modalContent = document.querySelector('#confirmModal .modal-content');
            const cancelBtn = document.getElementById('confirm_cancel_btn');
            const yesBtn = document.getElementById('confirm_yes_btn');

            if (showCancel) {
                if (cancelBtn) cancelBtn.style.display = 'block';
                if (modalContent) modalContent.style.maxWidth = '320px';
                if (yesBtn) {
                    yesBtn.style.width = 'auto';
                    yesBtn.style.flex = '1.2';
                    yesBtn.style.padding = '12px';
                    yesBtn.style.fontSize = '0.9rem';
                }
            } else {
                if (cancelBtn) cancelBtn.style.display = 'none';
                if (modalContent) modalContent.style.maxWidth = '380px'; // 讓寬度加寬以保證字體在單行呈現
                if (yesBtn) {
                    yesBtn.style.width = '100%';
                    yesBtn.style.flex = 'none';
                    yesBtn.style.padding = '14px 20px'; // 放大按鈕高度與字體
                    yesBtn.style.fontSize = '0.95rem';
                }
            }

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
                } else if (yesText.includes('返回') || yesText.includes('前往') || yesText.includes('確認')) {
                    // 科技藍色系 (Blue Gradient) - 極致科技美感
                    yesBtn.style.background = 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)';
                    yesBtn.style.boxShadow = '0 4px 15px rgba(37, 99, 235, 0.35)';
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
            document.getElementById('confirm_msg').innerHTML = msg;

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
        '醫療': ['🏥', '💊', '🩺', '🚑'],
        // ⛩️ 新增：寺廟、廟宇、拜拜、祈福專屬圖示 (V14.1)
        '寺廟': ['⛩️', '🛕', '🙏', '📿', '✨', '🧧'],
        '廟宇': ['⛩️', '🛕', '🙏', '📿', '✨', '🧧'],
        '拜拜': ['🙏', '⛩️', '🛕', '📿', '🕯️', '🧧'],
        '祈福': ['🙏', '✨', '⛩️', '🕯️', '🧧', '🌸'],
        // 🏪 新增：商店、超商、超市、便利商店專屬圖示 (V14.2)
        '商店': ['🏪', '🏬', '🛒', '🛍️', '🏠', '🥤'],
        '超商': ['🏪', '🥤', '🍞', '🍱', '🛒', '🛍️'],
        '超市': ['🛒', '🏪', '🥦', '🍎', '🥩', '🛍️'],
        '便利商店': ['🏪', '🥤', '🥪', '🍱', '🛍️', '☕'],
        // 🏋️ 新增：健身房、醫院、餐廳、酒店、小吃、飲料專屬圖示 (V14.3)
        '健身房': ['🏋️', '💪', '🏃', '🧘', '🚴', '🥊', '👟'],
        '醫院': ['🏥', '💊', '🩺', '🚑', '💉', '🤒'],
        '餐廳': ['🍽️', '🍴', '🍷', '🥩', '🥗', '🍝', '🍛'],
        '飯店': ['🏨', '🛌', '🛎️', '🍽️', '🍷', '🥂'],
        '酒店': ['🏨', '🍻', '🍷', '🥂', '🍹', '🎤', '🛌'],
        '小吃': ['🍢', '🍟', '🥟', '🍘', '🍗', '🍜', '🍱'],
        '涼水': ['🧋', '🥤', '🍹', '🍧', '🍨', '🍵', '🧊'],
        '飲料': ['🧋', '🥤', '🍹', '🧉', '🍵', '🍋', '🧊'],
        '精舍': ['🪷', '🛕', '🙏', '📿', '✨', '🧧'],
        '停車場': ['🅿️', '🚗', '🚙', '🚘', '🛵'],
        '停車': ['🅿️', '🚗', '🚙', '🚘', '🛵'],
        '家': ['🏠', '🏡', '🏢', '🔑', '🛋️'],
        '公司': ['🏢', '💼', '💻', '📈', '🏬']
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

    // --- 商業特權與解鎖防線檢測 (V1.0) ---
    window.checkFeatureAccess = (featureOrModalId) => {
        // 核心開發者管理員白名單，免檢放行，絕不受任何鎖頭阻擋！
        if (window.USER_EMAIL === 'ulir976272866@gmail.com') {
            return true;
        }

        const subType = window.USER_SUBSCRIPTION_TYPE || 'NONE';
        
        // 免費版 (NONE) 鎖定：行程、備忘、健康、股票、報稅收據
        const freeLockedTabs = ['schedule', 'memo', 'health', 'stock', 'tax'];
        const freeLockedModals = [
            'scheduleModal', 'memoModal', 'todoModal', 'pocketModal', 
            'wishlistModal', 'healthModal', 'trackingModal', 'trainingModal', 'stockModal', 'stockAnalysisModal'
        ];
        
        // 基礎版 (MONTHLY_AI) 鎖定：股票
        const basicLockedTabs = ['stock'];
        const basicLockedModals = ['stockModal', 'stockAnalysisModal'];
        
        if (subType === 'NONE') {
            if (freeLockedTabs.includes(featureOrModalId) || freeLockedModals.includes(featureOrModalId)) {
                return false;
            }
        } else if (subType === 'MONTHLY_AI') {
            if (basicLockedTabs.includes(featureOrModalId) || basicLockedModals.includes(featureOrModalId)) {
                return false;
            }
        }
        return true;
    };

    // 商業版模擬訂閱與加購 (導向金流收銀台)
    window.mockSubscribe = async (tier) => {
        const currentType = window.USER_SUBSCRIPTION_TYPE || 'NONE';
        const isSubscribed = window.USER_IS_SUBSCRIBED;
        const isTrialActive = window.USER_IS_TRIAL_ACTIVE;

        // 🛡️ 最強後盾防線：防呆阻斷，若用戶訂閱等級大於或等於要購買的等級，直接 return 不做動作
        if (isSubscribed && !isTrialActive) {
            if (currentType === 'YEARLY_AI') {
                console.log("[mockSubscribe Blocked] 用戶已是最高階尊榮版，不允許再訂閱任何方案");
                return;
            }
            if (currentType === 'PREMIUM_MONTHLY' && (tier === 'BASIC' || tier === 'PREMIUM_MONTHLY')) {
                console.log("[mockSubscribe Blocked] 用戶已是旗艦版，不允許訂閱低階方案");
                return;
            }
            if (currentType === 'MONTHLY_AI' && tier === 'BASIC') {
                console.log("[mockSubscribe Blocked] 用戶已是基礎版，不允許重複訂閱同方案");
                return;
            }
        }

        const email = window.USER_EMAIL || '';
        let targetTier = tier;
        if (tier === 'PREMIUM' && window.USER_SUBSCRIPTION_TYPE === 'MONTHLY_AI') {
            targetTier = 'PREMIUM_UPGRADE';
        }
        // 另開新分頁前往結帳，主畫面保持不動
        window.open(`/mock/checkout?tier=${targetTier}&email=${encodeURIComponent(email)}`, '_blank');
    };

    window.mockBuyPoints = async (points, price) => {
        const email = window.USER_EMAIL || '';
        const tier = points === 300 ? 'POINTS_300' : 'POINTS_600';
        // 另開新分頁前往結帳，主畫面保持不動
        window.open(`/mock/checkout?tier=${tier}&email=${encodeURIComponent(email)}`, '_blank');
    };

    // --- 訂閱到期倒數與試用到期計時器 (V25.0 Premium UI) ---
    window.initSubscriptionCountdown = () => {
        const wrapper = document.getElementById('sub_countdown_wrapper');
        const countdownEl = document.getElementById('sub_countdown');
        if (!wrapper || !countdownEl) return;
        
        const expiresStr = window.USER_SUBSCRIPTION_EXPIRES_AT;
        const subType = window.USER_SUBSCRIPTION_TYPE;
        if (!expiresStr || subType === 'NONE' || !window.USER_IS_SUBSCRIBED) {
            wrapper.style.display = 'none';
            return;
        }
        
        // 注入警告呼吸動畫樣式 (只在需要時注入)
        if (!document.getElementById('sub-warning-pulse-style')) {
            const style = document.createElement('style');
            style.id = 'sub-warning-pulse-style';
            style.innerHTML = `
                @keyframes sub-warning-pulse-red {
                    0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); transform: scale(1); }
                    50% { box-shadow: 0 0 0 6px rgba(239, 68, 68, 0); transform: scale(1.02); }
                    100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); transform: scale(1); }
                }
            `;
            document.head.appendChild(style);
        }
        
        function updateSub() {
            const expireTime = new Date(expiresStr.replace(' ', 'T')).getTime();
            const now = new Date().getTime();
            const diff = expireTime - now;
            
            if (diff <= 0) {
                countdownEl.innerText = "⚠️ 訂閱已過期，即將降級...";
                wrapper.style.background = "rgba(239, 68, 68, 0.12)";
                wrapper.style.color = "#dc2626";
                wrapper.style.borderColor = "rgba(239, 68, 68, 0.3)";
                if (window.subIntervalId) clearInterval(window.subIntervalId);
                setTimeout(() => window.location.reload(), 3000);
                return;
            }
            
            const diffDays = Math.ceil(diff / (1000 * 60 * 60 * 24));
            
            if (diffDays > 7) {
                wrapper.style.fontWeight = "800";
                if (subType === 'MONTHLY_AI') {
                    wrapper.style.background = "linear-gradient(135deg, rgba(20, 184, 166, 0.1) 0%, rgba(13, 148, 136, 0.1) 100%)";
                    wrapper.style.border = "1.5px solid rgba(20, 184, 166, 0.4)";
                    wrapper.style.color = "#0f766e";
                    wrapper.style.animation = "none";
                    countdownEl.innerText = `⚡ 基礎續期剩餘: ${diffDays}天`;
                } else if (subType === 'PREMIUM_MONTHLY') {
                    wrapper.style.background = "linear-gradient(135deg, rgba(251, 191, 36, 0.1) 0%, rgba(217, 119, 6, 0.1) 100%)";
                    wrapper.style.border = "1.5px solid rgba(251, 191, 36, 0.4)";
                    wrapper.style.color = "#b45309";
                    wrapper.style.animation = "none";
                    countdownEl.innerText = `✨ 旗艦續期剩餘: ${diffDays}天`;
                } else if (subType === 'YEARLY_AI') {
                    wrapper.style.background = "linear-gradient(135deg, rgba(139, 92, 246, 0.08) 0%, rgba(251, 191, 36, 0.08) 100%)";
                    wrapper.style.border = "1.5px solid rgba(139, 92, 246, 0.35)";
                    wrapper.style.color = "#6d28d9";
                    wrapper.style.animation = "none";
                    countdownEl.innerText = `👑 尊榮續期剩餘: ${diffDays}天`;

                    // 🟢 尊榮版：設為尊榮續期字樣，並正常呈現樣式
                    countdownEl.innerText = `👑 尊榮續期剩餘: ${diffDays}天`;
                }
            } else {
                wrapper.style.fontWeight = "900";
                wrapper.style.background = "linear-gradient(135deg, rgba(239, 68, 68, 0.12) 0%, rgba(220, 38, 38, 0.12) 100%)";
                wrapper.style.border = "1.5px solid rgba(239, 68, 68, 0.45)";
                wrapper.style.color = "#dc2626";
                wrapper.style.boxShadow = "0 2px 8px rgba(239, 68, 68, 0.15)";
                wrapper.style.animation = "sub-warning-pulse-red 1.5s infinite ease-in-out";
                countdownEl.innerText = `⚠️ 訂閱即將到期 • 僅剩 ${diffDays}天`;
            }
            
            // 🔒 資料庫控制：全網支付狀態動態判定
            if (window.ALLOW_PAYMENT === false) {
                wrapper.removeAttribute('onclick');
                wrapper.removeAttribute('onmouseover');
                wrapper.removeAttribute('onmouseout');
                wrapper.style.cursor = 'default';
                wrapper.style.pointerEvents = 'none';
                wrapper.title = '系統當前已暫時關閉儲值與訂閱功能';

                const pointsPill = document.querySelector('.ai-points-mini-pill');
                if (pointsPill) {
                    pointsPill.removeAttribute('onclick');
                    pointsPill.style.cursor = 'default';
                    pointsPill.style.pointerEvents = 'none';
                    pointsPill.title = '系統當前已暫時關閉儲值與訂閱功能';
                }
                
                const trialPill = document.getElementById('trial_countdown_wrapper');
                if (trialPill) {
                    trialPill.removeAttribute('onclick');
                    trialPill.style.cursor = 'default';
                    trialPill.style.pointerEvents = 'none';
                    trialPill.title = '系統當前已暫時關閉儲值與訂閱功能';
                }
                
                const freeUpgradePill = document.querySelector('.free-upgrade-wrapper');
                if (freeUpgradePill) {
                    freeUpgradePill.removeAttribute('onclick');
                    freeUpgradePill.style.cursor = 'default';
                    freeUpgradePill.style.pointerEvents = 'none';
                    freeUpgradePill.title = '系統當前已暫時關閉儲值與訂閱功能';
                }
            } else {
                // 🟢 支付開放時，將正常連結事件與樣式還原，便於用戶儲值/點擊
                if (!wrapper.hasAttribute('onclick')) {
                    wrapper.setAttribute('onclick', "openModal('upgradePaywallModal')");
                    wrapper.style.cursor = 'pointer';
                    wrapper.style.pointerEvents = 'auto';
                }
                wrapper.title = `下次自動續期/扣款日: ${expiresStr}`;

                const pointsPill = document.querySelector('.ai-points-mini-pill');
                if (pointsPill && !pointsPill.hasAttribute('onclick')) {
                    pointsPill.setAttribute('onclick', "openModal('upgradePaywallModal')");
                    pointsPill.style.cursor = 'pointer';
                    pointsPill.style.pointerEvents = 'auto';
                    pointsPill.title = '點擊加購智慧點數';
                }
            }
        }
        
        updateSub();
        if (window.subIntervalId) clearInterval(window.subIntervalId);
        window.subIntervalId = setInterval(updateSub, 60000);
    };

    window.initTrialCountdown = () => {
        const wrapper = document.getElementById('trial_countdown_wrapper');
        const countdownEl = document.getElementById('trial_countdown');
        if (!wrapper || !countdownEl) return;
        
        const trialExpiresStr = window.TRIAL_EXPIRES_AT;
        if (!trialExpiresStr) {
            wrapper.style.display = 'none';
            return;
        }
        
        function updateTrial() {
            const expireTime = new Date(trialExpiresStr.replace(' ', 'T')).getTime();
            const now = new Date().getTime();
            const diff = expireTime - now;
            
            if (diff <= 0) {
                countdownEl.innerText = "⏳ 試用期已結束";
                wrapper.style.background = "rgba(239, 68, 68, 0.12)";
                wrapper.style.color = "#dc2626";
                wrapper.style.borderColor = "rgba(239, 68, 68, 0.3)";
                if (window.trialIntervalId) clearInterval(window.trialIntervalId);
                setTimeout(() => window.location.reload(), 3000);
                return;
            }
            
            const days = Math.floor(diff / (1000 * 60 * 60 * 24));
            const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
            const mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
            
            if (days > 0) {
                countdownEl.innerText = `⏳ 試用剩餘: ${days}天${hours}小時`;
            } else if (hours > 0) {
                countdownEl.innerText = `⏳ 試用剩餘: ${hours}小時${mins}分`;
            } else {
                countdownEl.innerText = `⏳ 試用剩餘: ${mins}分鐘`;
            }
            
            wrapper.title = `您的免費試用將於 ${trialExpiresStr} 到期，點擊升級！`;
        }
        
        updateTrial();
        if (window.trialIntervalId) clearInterval(window.trialIntervalId);
        window.trialIntervalId = setInterval(updateTrial, 60000);
    };

    // --- 補差額計費牆動態預覽處理 (V25.0 Pro-rata Upgrade Modal UI) ---
    window.initUpgradePaywallPreview = async () => {
        const basicCard = document.getElementById('paywall_basic_card');
        const basicBtn = document.getElementById('paywall_basic_btn');
        const premiumMonthlyCard = document.getElementById('paywall_premium_monthly_card');
        const premiumMonthlyBtn = document.getElementById('paywall_premium_monthly_btn');
        const premiumCard = document.getElementById('paywall_premium_card');
        const premiumBtn = document.getElementById('paywall_premium_btn');
        
        // 恢復預設樣式，避免狀態殘留
        [
            { card: basicCard, btn: basicBtn, tier: 'BASIC', text: "立即訂閱 🚀", bg: "linear-gradient(135deg, #14b8a6 0%, #0d9488 100%)", box: "0 4px 12px rgba(20, 184, 166, 0.25)" },
            { card: premiumMonthlyCard, btn: premiumMonthlyBtn, tier: 'PREMIUM_MONTHLY', text: "立即訂閱 🚀", bg: "linear-gradient(135deg, #38bdf8 0%, #0284c7 100%)", box: "0 4px 12px rgba(56, 189, 248, 0.25)" },
            { card: premiumCard, btn: premiumBtn, tier: 'PREMIUM', text: "尊榮解鎖 ✨", bg: "linear-gradient(135deg, #d97706 0%, #b45309 100%)", box: "0 4px 12px rgba(217, 119, 6, 0.3)" }
        ].forEach(item => {
            if (item.card) {
                item.card.style.opacity = '1';
                item.card.style.filter = 'none';
                item.card.style.pointerEvents = 'auto'; // 恢復卡片事件
                const badge = item.card.querySelector('.paywall-active-badge');
                if (badge) badge.remove();
            }
            if (item.btn) {
                item.btn.disabled = false;
                item.btn.innerText = item.text;
                item.btn.style.background = item.bg;
                item.btn.style.boxShadow = item.box;
                item.btn.style.cursor = "pointer";
                item.btn.style.pointerEvents = "auto";
                item.btn.setAttribute('onclick', `mockSubscribe('${item.tier}')`); // 恢復按鈕預設點擊綁定
            }
        });

        // 移除舊折抵膠囊
        const oldPill = document.getElementById('paywall_premium_discount_pill');
        if (oldPill) oldPill.remove();

        const currentType = window.USER_SUBSCRIPTION_TYPE || 'NONE';
        const isSubscribed = window.USER_IS_SUBSCRIBED;
        const isTrialActive = window.USER_IS_TRIAL_ACTIVE;

        // 1. 若為最高階 👑 尊榮版 (YEARLY_AI)
        if (currentType === 'YEARLY_AI' && isSubscribed && !isTrialActive) {
            // A. 基礎版與旗艦版呈現灰色屏蔽並物理上鎖卡片
            [
                { card: basicCard, btn: basicBtn },
                { card: premiumMonthlyCard, btn: premiumMonthlyBtn }
            ].forEach(item => {
                if (item.card) {
                    item.card.style.opacity = '0.45';
                    item.card.style.filter = 'grayscale(100%)';
                    item.card.style.pointerEvents = 'none'; // 鎖死整張卡片，防止 Hover / Click 反應！
                }
                if (item.btn) {
                    item.btn.disabled = true;
                    item.btn.innerText = "已擁有高階方案";
                    item.btn.style.background = "#94a3b8";
                    item.btn.style.boxShadow = "none";
                    item.btn.style.cursor = "not-allowed";
                    item.btn.style.pointerEvents = "none";
                    item.btn.removeAttribute('onclick'); // 移除點擊綁定，徹底防呆
                }
            });

            // B. 尊榮版卡片顯示最高權限使用中
            if (premiumCard) {
                let badge = premiumCard.querySelector('.paywall-active-badge');
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'paywall-active-badge';
                    badge.style.cssText = "position: absolute; bottom: 65px; left: 50%; transform: translateX(-50%); font-size: 0.72rem; font-weight: 800; background: rgba(245, 158, 11, 0.18); color: #b45309; border: 1px solid rgba(245, 158, 11, 0.3); padding: 4px 12px; border-radius: 20px; backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); white-space: nowrap;";
                    badge.innerText = "✓ 您當前已解鎖最高榮譽";
                    premiumCard.appendChild(badge);
                }
            }
            if (premiumBtn) {
                premiumBtn.disabled = true;
                premiumBtn.innerText = "使用中";
                premiumBtn.style.background = "#94a3b8";
                premiumBtn.style.boxShadow = "none";
                premiumBtn.style.cursor = "not-allowed";
                premiumBtn.style.pointerEvents = "none";
                premiumBtn.removeAttribute('onclick');
            }
        }
        // 2. 若為中階 🥇 旗艦版 (PREMIUM_MONTHLY)
        else if (currentType === 'PREMIUM_MONTHLY' && isSubscribed && !isTrialActive) {
            // A. 基礎版屏蔽並鎖死卡片
            if (basicCard) {
                basicCard.style.opacity = '0.45';
                basicCard.style.filter = 'grayscale(100%)';
                basicCard.style.pointerEvents = 'none';
            }
            if (basicBtn) {
                basicBtn.disabled = true;
                basicBtn.innerText = "已擁有高階方案";
                basicBtn.style.background = "#94a3b8";
                basicBtn.style.boxShadow = "none";
                basicBtn.style.cursor = "not-allowed";
                basicBtn.style.pointerEvents = "none";
                basicBtn.removeAttribute('onclick');
            }

            // B. 旗艦版顯示使用中
            if (premiumMonthlyCard) {
                let badge = premiumMonthlyCard.querySelector('.paywall-active-badge');
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'paywall-active-badge';
                    badge.style.cssText = "position: absolute; bottom: 65px; left: 50%; transform: translateX(-50%); font-size: 0.72rem; font-weight: 800; background: rgba(14, 165, 233, 0.18); color: #0369a1; border: 1px solid rgba(14, 165, 233, 0.3); padding: 4px 12px; border-radius: 20px; backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); white-space: nowrap;";
                    badge.innerText = "✓ 您當前正在使用此方案";
                    premiumMonthlyCard.appendChild(badge);
                }
            }
            if (premiumMonthlyBtn) {
                premiumMonthlyBtn.disabled = true;
                premiumMonthlyBtn.innerText = "使用中";
                premiumMonthlyBtn.style.background = "#94a3b8";
                premiumMonthlyBtn.style.boxShadow = "none";
                premiumMonthlyBtn.style.cursor = "not-allowed";
                premiumMonthlyBtn.style.pointerEvents = "none";
                premiumMonthlyBtn.removeAttribute('onclick');
            }

            // C. 尊榮版顯示升級更划算
            if (premiumBtn) {
                premiumBtn.innerText = "升級尊榮方案 🚀";
                premiumBtn.setAttribute('onclick', "mockSubscribe('PREMIUM')");
            }
        }
        // 3. 若為初階 🥈 基礎版 (MONTHLY_AI)
        else if (currentType === 'MONTHLY_AI' && isSubscribed && !isTrialActive) {
            // A. 基礎版顯示使用中並屏蔽卡片事件
            if (basicCard) {
                basicCard.style.opacity = '0.7';
                basicCard.style.filter = 'grayscale(15%)';
                basicCard.style.pointerEvents = 'none';
                let badge = basicCard.querySelector('.paywall-active-badge');
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'paywall-active-badge';
                    badge.style.cssText = "position: absolute; bottom: 65px; left: 50%; transform: translateX(-50%); font-size: 0.72rem; font-weight: 800; background: rgba(16, 185, 129, 0.18); color: #047857; border: 1px solid rgba(16, 185, 129, 0.3); padding: 4px 12px; border-radius: 20px; backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); white-space: nowrap;";
                    badge.innerText = "✓ 您當前正在使用此方案";
                    basicCard.appendChild(badge);
                }
            }
            if (basicBtn) {
                basicBtn.disabled = true;
                basicBtn.innerText = "使用中";
                basicBtn.style.background = "#94a3b8";
                basicBtn.style.boxShadow = "none";
                basicBtn.style.cursor = "not-allowed";
                basicBtn.style.pointerEvents = "none";
                basicBtn.removeAttribute('onclick');
            }

            // B. 旗艦版與尊榮版提供折抵補差額直升預覽
            try {
                const res = await fetch('/api/subscription/upgrade_preview');
                const data = await res.json();
                
                if (data.status === 'success') {
                    let discountPill = document.createElement('div');
                    discountPill.id = 'paywall_premium_discount_pill';
                    discountPill.style.cssText = "font-size: 0.7rem; font-weight: 800; background: #fffbeb; color: #d97706; border: 1.5px solid #fde68a; padding: 6px 12px; border-radius: 12px; margin-bottom: 12px; width: calc(100% - 4px); text-align: left; animation: paywall-discount-pulse 1.5s infinite ease-in-out; display: flex; align-items: center; gap: 4px; box-sizing: border-box;";
                    
                    if (!document.getElementById('paywall-discount-pulse-style')) {
                        const style = document.createElement('style');
                        style.id = 'paywall-discount-pulse-style';
                        style.innerHTML = `
                            @keyframes paywall-discount-pulse {
                                0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(251, 191, 36, 0.3); }
                                50% { transform: scale(1.01); box-shadow: 0 0 0 4px rgba(251, 191, 36, 0); }
                                100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(251, 191, 36, 0); }
                            }
                        `;
                        document.head.appendChild(style);
                    }
                    
                    // 動態插入折抵說明到尊榮年費版
                    if (premiumCard) {
                        const clonePill = discountPill.cloneNode(true);
                        clonePill.innerHTML = `💡 基礎版折抵 NT$ ${data.discount}，今日僅需 NT$ ${data.upgrade_price}`;
                        const priceBlock = premiumCard.querySelector('div[style*="display: flex; align-items: baseline"]');
                        if (priceBlock) {
                            premiumCard.insertBefore(clonePill, priceBlock);
                        } else {
                            premiumCard.appendChild(clonePill);
                        }
                    }

                    if (premiumBtn) {
                        premiumBtn.innerText = "直升尊榮方案 🚀";
                        premiumBtn.setAttribute('onclick', "mockSubscribe('PREMIUM')");
                    }

                    // 旗艦版按鈕也可以直接補差額
                    if (premiumMonthlyBtn) {
                        premiumMonthlyBtn.innerText = "補差額升級 🚀";
                        premiumMonthlyBtn.setAttribute('onclick', "mockSubscribe('PREMIUM_MONTHLY')");
                    }
                }
            } catch (err) {
                console.error("[Upgrade Paywall Preview] 取得差額預覽失敗:", err);
            }
        }
    };

    // --- 樹狀導航切換 ---
    window.switchTab = (tab, e) => {
        // 特權防線攔截
        if (!window.checkFeatureAccess(tab)) {
            if (e) e.preventDefault();
            window.openModal('upgradePaywallModal');
            return;
        }

        // 更新母頁籤樣式
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        if (e) {
            e.currentTarget.classList.add('active');
        } else if (window.event) {
            window.event.currentTarget.classList.add('active');
        }

        // 更新子選單顯示
        document.querySelectorAll('.sub-menu').forEach(menu => menu.classList.remove('active'));
        const targetMenu = document.getElementById(`sub_${tab}`);
        if (targetMenu) {
            targetMenu.classList.add('active');
        }
    };

    // --- 彈窗控制 ---
    window.openModal = (id) => {
        // 生理健康避孕暨臨床醫學免責聲明攔截
        if ((id === 'healthModal' || id === 'trackingModal') && !localStorage.getItem('menstrual_disclaimer_agreed')) {
            window.pendingMenstrualModal = id;
            window.openModal('menstrualDisclaimerModal');
            return;
        }

        // 特權防線攔截
        if (id !== 'upgradePaywallModal' && !window.checkFeatureAccess(id)) {
            window.openModal('upgradePaywallModal');
            return;
        }

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
        if (id === 'upgradePaywallModal') {
            if (typeof window.initUpgradePaywallPreview === 'function') {
                window.initUpgradePaywallPreview();
            }
        }
        const modalEl = document.getElementById(id);
        if (!modalEl) {
            console.warn(`[openModal] 彈窗 ID "${id}" 在 DOM 中不存在！`);
            return;
        }
        modalEl.classList.add('show');

        // 分支邏輯優化 (V11.1)
        if (id === 'wishlistModal') window.loadWishes();
        if (id === 'todoModal') {
            window.selectTodoCategory('', '');
            window.loadTodos();
            window.renderTodoCatDropdown();
        }
        if (id === 'pocketModal') {
            window.selectCategory(''); // 口袋名單開啟時預設空白
            setTimeout(window.initPocketAutocomplete, 300);
            window.loadPocket(true);
        }
        if (id === 'healthModal' || id === 'trackingModal') {
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
            } else {
                // For trackingModal (the calendar)
                // 1. 立即顯現超高階毛玻璃微光加載遮罩
                const overlay = document.getElementById('calendar_loader_overlay');
                if (overlay) {
                    overlay.style.opacity = '1';
                    overlay.style.pointerEvents = 'auto';
                }
                
                // 2. 立即初始化年份與月份（防止首次載入未定義）
                const today = new Date();
                if (!window.currentCalendarYear) window.currentCalendarYear = today.getFullYear();
                if (!window.currentCalendarMonth) window.currentCalendarMonth = today.getMonth() + 1;
                if (!window.selectedCalendarDate) window.selectedCalendarDate = today;
                
                // 3. 立即呼叫骨架月曆生成器，於第 1 毫秒渲染整齊呼吸漸變的骨架網格
                if (typeof window.renderMenstrualCalendar === 'function') {
                    window.renderMenstrualCalendar(window.currentCalendarYear, window.currentCalendarMonth, true);
                }
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

        // 🔒 安全保護機制：如果目前待辦清單中還有未完成任務歸類在此類別下，則禁止刪除！
        if (window.cachedTodos && window.cachedTodos.length > 0) {
            const hasActiveTodos = window.cachedTodos.some(todo => todo.分類 === catName && todo.狀態 === '未完成');
            if (hasActiveTodos) {
                await window.customAlert(
                    '無法刪除類別 ⚠️',
                    `類別「${catObj.icon} ${catName}」中目前還有未完成的任務正在使用它，因此無法刪除！<br><br><span style="font-size: 0.8rem; color: #64748b;">💡 溫馨提示：請先將這些任務完成、刪除或重新分類後，再來刪除此類別喔。</span>`,
                    '⚠️',
                    '我知道了'
                );
                return;
            }
        }

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

            // 3. 🚀 零延遲本地渲染更新 (不再需要呼叫 loadTodos() 的雲端網路載入)
            window.renderTodoCatDropdown();
            window.syncTodoFilterBar();
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

            // 🚀 零延遲本地渲染更新 (不用等候 loadTodos() 網路請求)
            window.renderTodoCatDropdown();
            window.selectTodoCategory(result.name, result.icon || '📌');
            window.syncTodoFilterBar();
        }
    };

    const todoTitleInput = document.getElementById('todo_title');
    if (todoTitleInput) {
        todoTitleInput.oninput = updateTodoSubmitButtonState;

        // 🛡️ 解決待辦輸入框點擊不關閉下拉選單的 Bug (V6.5)
        todoTitleInput.addEventListener('focus', () => {
            const todoDropdown = document.getElementById('todo_cat_dropdown');
            if (todoDropdown) todoDropdown.classList.remove('show');
        });
        todoTitleInput.addEventListener('click', () => {
            const todoDropdown = document.getElementById('todo_cat_dropdown');
            if (todoDropdown) todoDropdown.classList.remove('show');
        });
    }

    window.syncTodoFilterBar = (filterCategory = '全部') => {
        const filterSelect = document.getElementById('todo_filter_cat');
        if (!filterSelect) return;

        const deletedCats = JSON.parse(localStorage.getItem('deletedTodoCats') || '[]');
        const activeTodos = (window.cachedTodos || []).filter(i => i.狀態 === '未完成');
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
    };

    window.loadTodos = async (filterCategory = '全部') => {
        const list = document.getElementById('todo_list');
        if (!list) return;

        // 展示高級炫光旋轉載入動畫，打破卡頓感
        list.innerHTML = `
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px; color: #14b8a6;">
                <svg style="animation: spin 1s linear infinite;" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <circle cx="12" cy="12" r="10" stroke="#f1f5f9" stroke-width="2.5"></circle>
                    <path d="M12 2C6.477 2 2 6.477 2 12c0 1.89.52 3.66 1.43 5.17" stroke="#14b8a6" stroke-width="2.5" stroke-linecap="round"></path>
                </svg>
                <span style="font-size: 0.85rem; font-weight: 700; margin-top: 12px; color: #64748b;">📡 正在連線雲端硬碟更新中...</span>
            </div>
        `;

        try {
            const res = await fetch('/api/todo');
            const data = await res.json();
            if (!Array.isArray(data)) throw new Error('資料錯誤');

            window.cachedTodos = data; // ✅ 快取至全域 (用於刪除類別的安全阻擋 check)
            const activeTodos = data.filter(i => i.狀態 === '未完成');

            // --- 動態生成篩選列 ---
            window.syncTodoFilterBar(filterCategory);

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

        // 展示高級炫光旋轉載入動畫，打破卡頓感 (配對願望清單的質感玫瑰紅配色)
        list.innerHTML = `
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px; color: #e11d48;">
                <svg style="animation: spin 1s linear infinite;" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <circle cx="12" cy="12" r="10" stroke="#f1f5f9" stroke-width="2.5"></circle>
                    <path d="M12 2C6.477 2 2 6.477 2 12c0 1.89.52 3.66 1.43 5.17" stroke="#e11d48" stroke-width="2.5" stroke-linecap="round"></path>
                </svg>
                <span style="font-size: 0.85rem; font-weight: 700; margin-top: 12px; color: #64748b;">📡 正在連線雲端硬碟更新中...</span>
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

                // 4. 重置
                window.checkMemoFields();

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

        // 停用按鈕並顯示 Loading Spinner
        const submitBtn = document.getElementById('submitTodoBtn');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.style.pointerEvents = 'none';
            submitBtn.innerHTML = '<span class="loading-spinner" style="width: 14px; height: 14px; margin: 0; border-width: 2px;"></span>';
            submitBtn.style.opacity = '1';
        }

        const resetTodoBtnUI = () => {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.style.pointerEvents = window.editingTodoId ? 'auto' : 'none';
                submitBtn.innerHTML = '✓';
                submitBtn.style.opacity = window.editingTodoId ? '1' : '0.3';
            }
        };

        try {
            const endpoint = window.editingTodoId ? '/api/todo/update' : '/api/todo';
            const payload = { title, category, priority };
            if (window.editingTodoId) payload.id = window.editingTodoId;

            const res = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            if (data.status === 'success') {
                input.value = '';
                window.editingTodoId = null;

                resetTodoBtnUI();
                window.loadTodos();

                // 重置選擇
                const defaultOpt = document.querySelector('.priority-opt.green');
                if (defaultOpt) window.selectPriority(defaultOpt, '一般');

                // 重置類別
                window.selectTodoCategory('任務', '📝');
            } else {
                alert('儲存失敗：' + (data.message || '未知錯誤'));
                resetTodoBtnUI();
            }
        } catch (e) {
            console.error("Save Todo Error:", e);
            alert('連線失敗，請重試。');
            resetTodoBtnUI();
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

        // 停用按鈕並顯示 Loading Spinner
        const submitBtn = document.getElementById('saveWishBtn');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.style.pointerEvents = 'none';
            submitBtn.innerHTML = '<span class="loading-spinner" style="width: 14px; height: 14px; margin: 0; border-width: 2px;"></span>';
        }

        const resetWishBtnUI = () => {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.style.pointerEvents = '';
                if (window.editingWishId) {
                    submitBtn.innerHTML = '✓';
                    submitBtn.style.background = '#10b981';
                } else {
                    submitBtn.innerHTML = '＋';
                    submitBtn.style.background = '#f97316';
                }
                submitBtn.style.width = '45px';
            }
        };

        try {
            const endpoint = window.editingWishId ? '/api/wishlist/update' : '/api/wishlist';
            const payload = { name, price, note, category };
            if (window.editingWishId) payload.id = window.editingWishId;

            const res = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            if (data.status === 'success') {
                nameInput.value = '';
                priceInput.value = '';
                noteInput.value = '';
                window.editingWishId = null;

                resetWishBtnUI();
                window.loadWishes();
            } else {
                alert('儲存失敗：' + (data.message || '未知錯誤'));
                resetWishBtnUI();
            }
        } catch (e) {
            console.error("Save Wish Error:", e);
            alert('連線失敗，請重試。');
            resetWishBtnUI();
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
        // 清除本地隱藏快取，不需要跟伺服器同步解除 (讓已完成的項目在重新載入時保持已打勾、槓線狀態！)
        localStorage.removeItem('hiddenPocketEvents');
        if (typeof window.showToast === 'function') {
            window.showToast('✨ 已成功還原所有已完成與隱藏的行程！已完成之項目仍保持勾選狀態。', 'success');
        }
        window.querySchedule(window.lastQueryDays || 7);
    };

    window.toggleEventDone = async (id) => {
        const lis = document.querySelectorAll(`[id="event_li_${id}"]`);
        if (lis.length === 0) return;

        const firstLi = lis[lis.length - 1]; // 獲取最新渲染的 DOM，完美避免舊卡片殘留造成的 Selector 碰撞！
        const btn = firstLi.querySelector('.done-btn');
        const isCompleted = btn.classList.contains('completed');

        if (!isCompleted) {
            // ==========================================
            // 勾選狀態 ➔ 圓圈填綠色、文字槓掉、彈出「完成」隱藏按鈕
            // ==========================================
            lis.forEach(li => {
                li.classList.add('checked-off');
                const b = li.querySelector('.done-btn');
                if (b) {
                    b.classList.add('completed');
                    b.innerText = '✓';
                }
            });
            if (typeof window.showToast === 'function') {
                window.showToast('✅ 已勾選行程！請點擊右側彈出的「完成」按鈕將它隱藏。', 'info');
            }
        } else {
            // ==========================================
            // 取消勾選 ➔ 圓圈還原、文字恢復正常、隱藏「完成」按鈕
            // ==========================================
            lis.forEach(li => {
                li.classList.remove('checked-off');
                const b = li.querySelector('.done-btn');
                if (b) {
                    b.classList.remove('completed');
                    b.innerText = '✓';
                }
            });

            // 如果原本在伺服器上是已完成狀態（data-server-completed="true"），則需要向後端同步撤銷完成狀態 (拿掉 ✅)
            const isServerCompleted = btn.getAttribute('data-server-completed') === 'true';
            if (isServerCompleted) {
                try {
                    fetch('/api/toggle_completion', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ event_id: id })
                    }).then(res => res.json()).then(data => {
                        if (data.status === 'success') {
                            lis.forEach(li => {
                                const b = li.querySelector('.done-btn');
                                if (b) b.setAttribute('data-server-completed', 'false');
                            });
                        }
                    }).catch(e => console.error("Uncomplete Sync Error:", e));
                } catch (err) {
                    console.error("Uncomplete Sync Error:", err);
                }
            }

            if (typeof window.showToast === 'function') {
                window.showToast('↩️ 已取消勾選！', 'info');
            }
        }
    };

    window.hideCompletedEvent = async (id) => {
        const lis = document.querySelectorAll(`[id="event_li_${id}"]`);
        if (lis.length === 0) return;

        const firstLi = lis[lis.length - 1]; // 獲取最新渲染的 DOM，完美避免舊卡片殘留造成的 Selector 碰撞！
        const titleEl = firstLi.querySelector('.event-title-row');
        let title = titleEl ? titleEl.innerText : '日程';
        if (title.includes('] ')) {
            title = title.split('] ')[1];
        }

        // 1. 立即啟動淡出隱藏動畫
        lis.forEach(li => li.classList.add('fade-out'));

        // 2. 立即將 ID 寫入本地隱藏名單，防止重新整理後再度出現
        let hidden = JSON.parse(localStorage.getItem('hiddenPocketEvents') || '[]');
        if (!hidden.includes(id)) hidden.push(id);
        localStorage.setItem('hiddenPocketEvents', JSON.stringify(hidden));

        // 3. 300ms 後優雅地將 DOM 隱藏，並重新查詢日程清單以重整界面
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
            window.querySchedule(window.lastQueryDays || 7);
        }, 300);

        // 4. 背景非同步同步至 Google Calendar 伺服器，將行程標記為已完成 (加 ✅)
        try {
            const res = await fetch('/api/toggle_completion', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ event_id: id })
            });
            const data = await res.json();
            if (data.status === 'success') {
                if (typeof window.showToast === 'function') {
                    window.showToast(`✅ 已完成並隱藏「${title}」！`, 'success');
                }
            } else {
                console.error("Failed to sync completion:", data.message);
            }
        } catch (err) {
            console.error("Sync Error in background:", err);
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
                const isAlreadyFav = window.cachedPocketItems && window.cachedPocketItems.some(
                    i => i.is_fav === '1' && i.location.trim().toLowerCase() === event.location.trim().toLowerCase()
                );
                locationHtml = `
                    <div class="event-address-row" style="display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 4px;">
                        <div style="display: flex; align-items: center; gap: 4px; flex: 1; min-width: 0;">
                            <div class="event-address-icon" style="flex-shrink: 0;">📍</div>
                            <a href="${mapUrl}" class="location-link" style="color: #94a3b8; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${event.location}</a>
                        </div>
                        ${isAlreadyFav ? `
                            <button id="add_fav_btn_${event.id}" disabled
                                     style="cursor: default; background: #f1f5f9; color: #94a3b8; border: 1.5px solid #cbd5e1; font-size: 0.65rem; font-weight: 800; padding: 2px 6px; border-radius: 6px; display: inline-flex; align-items: center; gap: 2px; transition: all 0.2s; white-space: nowrap; pointer-events: none;" 
                                     class="add-fav-loc-btn">
                                ✓ 已設常用
                            </button>
                        ` : `
                            <button id="add_fav_btn_${event.id}" onclick="window.addLocationToFavorites('${event.location.replace(/'/g, "\\'")}', '${event.title.replace(/'/g, "\\'")}', 'add_fav_btn_${event.id}')" 
                                     style="cursor: pointer; background: #fffbeb; color: #d97706; border: 1.5px solid #fde68a; font-size: 0.65rem; font-weight: 800; padding: 2px 6px; border-radius: 6px; display: inline-flex; align-items: center; gap: 2px; transition: all 0.2s; white-space: nowrap;" 
                                     class="add-fav-loc-btn">
                                📌 常用
                            </button>
                        `}
                    </div>`;
            }

            const itemClass = event.completed ? 'schedule-item checked-off' : 'schedule-item';
            const btnClass = event.completed ? 'done-btn completed' : 'done-btn';

            listHtml += `
                <div id="event_li_${event.id}" class="${itemClass}">
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
                        <div class="event-buttons-group">
                            <button class="${btnClass}" data-server-completed="${event.completed ? 'true' : 'false'}" onclick="window.toggleEventDone('${event.id}')">✓</button>
                            <button class="confirm-hide-btn" onclick="window.hideCompletedEvent('${event.id}')">完成</button>
                        </div>
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
                const isAlreadyFav = window.cachedPocketItems && window.cachedPocketItems.some(
                    i => i.is_fav === '1' && i.location.trim().toLowerCase() === event.location.trim().toLowerCase()
                );
                locationHtml = `
                    <div class="event-address-row" style="display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 4px;">
                        <div style="display: flex; align-items: center; gap: 4px; flex: 1; min-width: 0;">
                            <div class="event-address-icon" style="flex-shrink: 0;">📍</div>
                            <a href="${mapUrl}" class="location-link" style="color: #94a3b8; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${event.location}</a>
                        </div>
                        ${isAlreadyFav ? `
                            <button id="add_fav_btn_${event.id}" disabled
                                    style="cursor: default; background: #f1f5f9; color: #94a3b8; border: 1.5px solid #cbd5e1; font-size: 0.65rem; font-weight: 800; padding: 2px 6px; border-radius: 6px; display: inline-flex; align-items: center; gap: 2px; transition: all 0.2s; white-space: nowrap; pointer-events: none;" 
                                    class="add-fav-loc-btn">
                                ✓ 已設常用
                            </button>
                        ` : `
                            <button id="add_fav_btn_${event.id}" onclick="window.addLocationToFavorites('${event.location.replace(/'/g, "\\'")}', '${event.title.replace(/'/g, "\\'")}', 'add_fav_btn_${event.id}')" 
                                    style="cursor: pointer; background: #fffbeb; color: #d97706; border: 1.5px solid #fde68a; font-size: 0.65rem; font-weight: 800; padding: 2px 6px; border-radius: 6px; display: inline-flex; align-items: center; gap: 2px; transition: all 0.2s; white-space: nowrap;" 
                                    class="add-fav-loc-btn">
                                📌 常用
                            </button>
                        `}
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
        // 點數防線攔截：非無限版且剩餘點數 <= 0，攔截對話請求並開啟計費牆
        if (window.USER_SUBSCRIPTION_TYPE !== 'YEARLY_AI' && window.USER_SUBSCRIPTION_TYPE !== 'PREMIUM_MONTHLY' && window.USER_AI_POINTS <= 0) {
            const confirmed = await window.customConfirm(
                '🚨 AI 智慧點數已歸 0',
                '您的智慧對話點數額度已用完 (剩餘 0 點)！請立即加購點數或升級為無限對話的尊榮付費方案以繼續使用！',
                '🚨',
                '💎 立即儲值/升級'
            );
            if (confirmed) {
                window.openModal('upgradePaywallModal');
            }
            return;
        }

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
                } else if (data.type === 'stock_prefill') {
                    appendMessage(data.message);
                    window.switchTab('stock');
                    if (window.openAddStockTxModalWithValues) {
                        window.openAddStockTxModalWithValues(data.stock_data);
                    }
                } else if (data.type === 'stock_locked') {
                    appendMessage(data.message);
                } else {
                    appendMessage(data.message || data.reply);
                }
            } else {
                appendMessage("❌ 錯誤：" + (data.message || "發生未知錯誤"));
                if (data.points_depleted) {
                    const confirmed = await window.customConfirm(
                        '🚨 AI 智慧點數已歸 0',
                        '您的智慧對話點數額度已用完 (剩餘 0 點)！請立即加購點數或升級為無限對話的尊榮付費方案以繼續使用！',
                        '🚨',
                        '💎 立即儲值/升級'
                    );
                    if (confirmed) {
                        window.openModal('upgradePaywallModal');
                    }
                }
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
                submitBtn.disabled = false;
                submitBtn.style.opacity = '';
                submitBtn.style.pointerEvents = '';
                submitBtn.innerText = window.editingEventId ? '💾 儲存修改' : '確認加入日曆';
                submitBtn.style.background = window.editingEventId ? '#10b981' : '';
            }
        };

        // 開始寫入，停用按鈕並顯示 Loading Spinner
        const submitBtn = document.getElementById('submitSchedule');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.style.pointerEvents = 'none';
            submitBtn.style.opacity = '0.7';
            submitBtn.innerHTML = `<span class="loading-spinner"></span>${window.editingEventId ? '正在儲存修改...' : '正在加入日曆...'}`;
        }

        try {
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
                    resetBtnUI();
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
                    resetBtnUI();
                }
            }
        } catch (e) {
            console.error("Save Schedule Error:", e);
            window.showToast('網路連線或系統發生錯誤，請重試。', 'warning');
            resetBtnUI();
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
    window.compressImage = compressImage;



    // --- 報稅公益收據上傳與預覽小助手 (V9.0 Premium) ---
    window.handleReceiptFileChange = (input) => {
        const file = input.files[0];
        if (!file) return;
        
        const previewImg = document.getElementById('receipt_preview_img');
        const previewContainer = document.getElementById('receipt_preview_container');
        const statusSpan = document.getElementById('receipt_upload_status');
        
        if (previewImg && previewContainer && statusSpan) {
            previewImg.src = URL.createObjectURL(file);
            previewContainer.style.display = 'block';
            statusSpan.innerText = '已選取照片 📸';
            statusSpan.style.color = '#e11d48';
            statusSpan.style.fontWeight = '800';
        }
    };
    
    window.clearReceiptFile = () => {
        const input = document.getElementById('charity_receipt_input');
        const previewImg = document.getElementById('receipt_preview_img');
        const previewContainer = document.getElementById('receipt_preview_container');
        const statusSpan = document.getElementById('receipt_upload_status');
        
        if (input) input.value = '';
        if (previewImg) previewImg.src = '';
        if (previewContainer) previewContainer.style.display = 'none';
        if (statusSpan) {
            statusSpan.innerText = '未選取照片';
            statusSpan.style.color = '#64748b';
            statusSpan.style.fontWeight = 'normal';
        }
    };

    window.triggerChatReceiptUpload = () => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = 'image/*';
        input.capture = 'environment';
        input.onchange = async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            
            showToast('📸 正在處理並上傳收據...', 'info');
            
            const compressedBlob = await window.compressImage(file);
            
            const formData = new FormData();
            formData.append('file', compressedBlob, 'receipt.jpg');
            
            try {
                const res = await fetch('/api/tax/upload_receipt', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast('✅ 收據成功上傳並歸檔在個人雲端硬碟！', 'success');
                    appendMessage(`📸 系統已成功為您將該筆收據/發票照片以新檔名 <b>${data.filename}</b> 年度歸檔至雲端空間的「報稅公益收據管理/${data.year}」目錄！`);
                } else {
                    showToast(`❌ 上傳失敗: ${data.message}`, 'error');
                }
            } catch (err) {
                console.error(err);
                showToast('❌ 雲端上傳連線失敗', 'error');
            }
        };
        input.click();
    };

    // ✅ 舊的 categorySelect change 監聽器已移至 selectExpenseCategory()（V14.0 自訂下拉選單統一化）

    document.getElementById('submitExpense').onclick = async () => {
        window.calculateResult();

        const item = document.getElementById('expense_item').value;
        const amount = document.getElementById('expense_amount').value;
        // ✅ V14.0：優先讀取自訂下拉選單的 hidden input；降級備援讀取原生 select
        const category = document.getElementById('expense_category_hidden')?.value || document.getElementById('manual_expense_category')?.value;

        // 強制檢查分類 (V14.6)
        if (!category) {
            showToast('請選擇分類！');
            return;
        }

        if (!item || amount === '0' || !amount) {
            showToast('請輸入項目與金額！');
            return;
        }

        const receiptInput = document.getElementById('charity_receipt_input');
        
        // 1. 防呆提醒：公益類別若未選取照片，詢問是否上傳
        if (category === '公益' && window.checkFeatureAccess('tax')) {
            const hasFile = receiptInput && receiptInput.files && receiptInput.files[0];
            if (!hasFile) {
                const confirmed = await window.customConfirm(
                    '💖 公益收據雲端歸檔',
                    '系統已將此筆交易標記為【年度報稅憑證】！是否要立即將發票/收據拍照存檔到個人的雲端硬碟「報稅公益收據管理」中？',
                    '📸',
                    '立即拍照上傳'
                );
                if (confirmed) {
                    receiptInput.click();
                    return;
                }
            }
        }

        const expenseType = document.getElementById('expense_type').value;
        const emoji = expenseType === 'income' ? '💰' : '💸';

        // 鎖定確認按鈕防止重複提交
        const submitBtn = document.getElementById('submitExpense');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerText = '正在記帳中... ⏳';
        }

        let uploadedFileName = '';
        let uploadedYear = '';

        // 2. 執行收據雲端上傳
        if (receiptInput && receiptInput.files && receiptInput.files[0]) {
            showToast('📸 正在將收據上傳至雲端硬碟...', 'info');
            const file = receiptInput.files[0];
            const compressedBlob = await window.compressImage(file);
            const formData = new FormData();
            formData.append('file', compressedBlob, 'receipt.jpg');
            
            try {
                const taxRes = await fetch('/api/tax/upload_receipt', {
                    method: 'POST',
                    body: formData
                });
                const taxData = await taxRes.json();
                if (taxData.status === 'success') {
                    uploadedFileName = taxData.filename;
                    uploadedYear = taxData.year;
                    showToast('✅ 公益收據雲端歸檔成功！', 'success');
                } else {
                    showToast(`❌ 收據備份失敗: ${taxData.message}`, 'error');
                }
            } catch (err) {
                console.error(err);
                showToast('❌ 收據備份連線失敗', 'error');
            }
        }

        closeModal('expenseModal');
        appendMessage(`${emoji} 記帳：${item} $${amount} [${category}]`, true);
        
        const res = await fetch('/api/manual_action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'expense', expense_type: expenseType, item, amount: parseInt(amount), category })
        });
        const data = await res.json();
        appendMessage(data.message);

        if (uploadedFileName) {
            appendMessage(`📸 系統已成功為您將該筆收據/發票照片以新檔名 <b>${uploadedFileName}</b> 年度歸檔至雲端空間的「報稅公益收據管理/${uploadedYear}」目錄！`);
        }

        // 解鎖按鈕
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerText = expenseType === 'income' ? '確認收入記帳 💰' : '確認支出記帳 💸';
        }

        // 3. 投資/投資獲利正向同步引導 (一鍵直接跳轉分頁並預填 Modal)
        if ((category === '投資' || category === '投資獲利') && window.checkFeatureAccess('stock')) {
            const txType = category === '投資' ? '買進' : '賣出';
            const isConfirmed = await window.customConfirm(
                '📈 引導至存股紀錄',
                `偵測到這筆支出屬於投資性質。是否一鍵跳轉至【📈 存股】模組，直接自動為您開啟【${txType}】持股交易登記表單並預填內容？`,
                '📈',
                '前往存股登記 🚀'
            );
            if (isConfirmed) {
                window.switchTab('stock');
                if (window.openAddStockTxModalWithValues) {
                    window.openAddStockTxModalWithValues({
                        name: item,
                        total_budget: parseFloat(amount),
                        tx_type: txType,
                        date: new Date().toISOString().split('T')[0]
                    });
                }
            }
        }

        // 清空輸入
        document.getElementById('expense_item').value = '';
        clearCalc();
        window.clearReceiptFile();
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
    const defaultPocketCategories = [
        { name: '美食', icon: '🍜' },
        { name: '咖啡', icon: '☕' },
        { name: '景點', icon: '🎡' },
        { name: '住宿', icon: '🏨' },
        { name: '購物', icon: '🛍️' },
        { name: '宮廟', icon: '⛩️' },
        { name: '寺廟', icon: '🛕' },
        { name: '精舍', icon: '🪷' },
        { name: '停車場', icon: '🅿️' },
        { name: '家', icon: '🏠' }
    ];
    let loadedPocketCats = localStorage.getItem('pocketCategories');
    if (loadedPocketCats) {
        try {
            let parsed = JSON.parse(loadedPocketCats);
            let changed = false;
            let deletedCats = JSON.parse(localStorage.getItem('deletedPocketCats') || '[]');

            // 智慧遷移：僅在分類「既不存在於目前清單，且也從未被使用者刪除」時才進行補入，防止刪除後重載復活！
            const checkAndPush = (name, icon) => {
                if (!parsed.some(c => c.name === name) && !deletedCats.includes(name)) {
                    parsed.push({ name, icon });
                    changed = true;
                }
            };

            checkAndPush('宮廟', '⛩️');
            checkAndPush('寺廟', '🛕');
            checkAndPush('精舍', '🪷');
            checkAndPush('停車場', '🅿️');
            checkAndPush('家', '🏠');

            if (changed) {
                localStorage.setItem('pocketCategories', JSON.stringify(parsed));
            }
            window.pocketCategories = parsed;
        } catch (e) {
            window.pocketCategories = defaultPocketCategories;
        }
    } else {
        window.pocketCategories = defaultPocketCategories;
        localStorage.setItem('pocketCategories', JSON.stringify(defaultPocketCategories));
    }

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
        window.lastDbPocketCategories = categories || [];
        const optionsDiv = document.getElementById('cat_options');
        if (!optionsDiv) return;

        const deletedCats = JSON.parse(localStorage.getItem('deletedPocketCats') || '[]');
        // 確保排除 '常用' 與 空字串 分類
        const allCats = [...window.pocketCategories].filter(c => !deletedCats.includes(c.name) && c.name !== '常用' && c.name !== '');

        // 合併資料庫中已有的分類，並同樣過濾掉 '常用' 與 空字串
        const dbCats = [...new Set(categories)].filter(c => c !== '常用' && c !== '' && !allCats.find(ac => ac.name === c));
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
        // 額外防禦：禁止手動刪除 '常用' 分類
        if (catName === '常用') return;

        const catObj = window.pocketCategories.find(c => c.name === catName) || { name: catName, icon: '📍' };

        // 🔒 安全保護機制：如果目前口袋名單中還有景點歸類在此類別下，則禁止刪除！
        if (window.cachedPocketItems && window.cachedPocketItems.length > 0) {
            const hasItems = window.cachedPocketItems.some(item => item.category === catName && item.is_fav !== '1');
            if (hasItems) {
                await window.customAlert(
                    '無法刪除類別 ⚠️',
                    `類別「${catObj.icon} ${catName}」中目前還有景點正在使用它，因此無法刪除！<br><br><span style="font-size: 0.8rem; color: #64748b;">💡 溫馨提示：請先將這些景點刪除或重新歸類至其他分類後，再來刪除此類別喔。</span>`,
                    '⚠️',
                    '我知道了'
                );
                return;
            }
        }

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

        // 4. 🚀 零延遲立即在本地重新渲染下拉選單 (免去 Google Sheets API 數秒的網路等待！)
        renderCatOptions(window.lastDbPocketCategories || []);

        // 5. 🚀 同步重新渲染口袋清單與篩選列
        if (window.cachedPocketItems) {
            window.renderPocketListDirectly(window.cachedPocketItems);
        }
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

        // 🛡️ 解決 Google Autocomplete 阻止冒泡導致下拉選單不關閉的 Bug (V6.3)
        const inputs = ['pocket_name', 'pocket_location', 'pocket_note'];
        inputs.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('focus', () => {
                    const pocketDropdown = document.getElementById('cat_options');
                    if (pocketDropdown) pocketDropdown.classList.remove('show');
                });
                el.addEventListener('click', () => {
                    const pocketDropdown = document.getElementById('cat_options');
                    if (pocketDropdown) pocketDropdown.classList.remove('show');
                });
            }
        });
    };

    window.currentPocketFilter = '全部';
    window.currentAreaFilter = '全部';


    function renderFilterBar(categories) {
        const select = document.getElementById('pocket_filter_cat');
        if (!select) return;
        const currentVal = window.currentPocketFilter;
        // 過濾掉 '常用' 與 空字串 分類
        const allCats = ['全部', ...new Set(categories.filter(c => c !== '常用' && c !== ''))];
        select.innerHTML = allCats.map(cat => `
            <option value="${cat}" ${currentVal === cat ? 'selected' : ''}>
                ${cat === '全部' ? '類別' : cat}
            </option>
        `).join('');
    }

    window.setPocketFilter = (cat) => {
        window.currentPocketFilter = cat;
        window.loadPocket(false);
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
        window.loadPocket(false);
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
            window.loadPocket(true);
        }
    };

    window.currentPocketTab = 'all';
    window.currentPocketFilter = '全部';
    window.currentAreaFilter = '全部';
    window.currentPocketSearchKeyword = '';

    window.handlePocketSearch = (value) => {
        window.currentPocketSearchKeyword = value.trim();
        window.loadPocket(false);
    };

    window.switchPocketTab = (tab) => {
        window.currentPocketTab = tab;
        const tabAll = document.getElementById('pocket_tab_all');
        const tabFav = document.getElementById('pocket_tab_fav');
        const formCard = document.getElementById('pocket_form_card_container');
        const filterBar = document.getElementById('pocket_filter_bar_container');
        const searchBar = document.getElementById('pocket_search_container');
        const searchInput = document.getElementById('pocket_search_input');

        if (searchInput) {
            searchInput.value = '';
        }
        window.currentPocketSearchKeyword = '';

        const keywordSearchInput = document.getElementById('pocket_keyword_search');
        if (keywordSearchInput) {
            keywordSearchInput.value = '';
        }
        window.currentPocketKeyword = '';

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
            if (searchBar) searchBar.style.display = 'block';
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
            if (searchBar) searchBar.style.display = 'none';
        }

        window.loadPocket(false);
    };

    window.handlePocketKeywordSearch = (value) => {
        window.currentPocketKeyword = value;
        window.loadPocket(false);
    };

    window.copyAddressText = (location, name) => {
        navigator.clipboard.writeText(location).then(() => {
            showToast(`📋 已複製 [${name}] 的地址！`, 'success');
        }).catch(() => {
            showToast('複製失敗，請手動複製', 'error');
        });
    };

    window.openPocketMoveBackModal = (itemName) => {
        return new Promise((resolve) => {
            const modal = document.getElementById('pocketMoveBackModal');
            const nameSpan = document.getElementById('move_back_item_name');
            const select = document.getElementById('move_back_category_select');
            const customInput = document.getElementById('move_back_custom_category');
            
            if (modal && nameSpan && select && customInput) {
                nameSpan.innerText = itemName;
                customInput.value = '';
                
                // 動態渲染可選的類別下拉選單 (排除 '常用')
                const deletedCats = JSON.parse(localStorage.getItem('deletedPocketCats') || '[]');
                const availableCats = window.pocketCategories.filter(c => !deletedCats.includes(c.name) && c.name !== '常用' && c.name !== '');
                
                select.innerHTML = availableCats.map(c => `
                    <option value="${c.name}">${c.icon} ${c.name}</option>
                `).join('') + `<option value="其他">📍 其他</option>`;
                
                // 預設選擇第一項或景點
                const defaultSel = availableCats.find(c => c.name === '景點') ? '景點' : (availableCats.length > 0 ? availableCats[0].name : '其他');
                select.value = defaultSel;
                
                modal.classList.add('show');
                
                window.closePocketMoveBackModal = (confirmed) => {
                    modal.classList.remove('show');
                    if (!confirmed) {
                        resolve(null);
                    } else {
                        const customVal = customInput.value.trim();
                        if (customVal) {
                            resolve(customVal);
                        } else {
                            resolve(select.value);
                        }
                    }
                };
            } else {
                resolve(null);
            }
        });
    };

    window.moveToFavorites = async (id, name, targetCategory) => {
        const isMovingToFav = targetCategory === '常用';
        
        let finalCategory = targetCategory;
        if (!isMovingToFav) {
            // 使用全新的優雅自訂彈窗取代原生的 ugly prompt
            const chosen = await window.openPocketMoveBackModal(name);
            if (chosen === null) return; // 使用者點選取消
            finalCategory = chosen.trim() || '其他';
        }

        const yesText = isMovingToFav ? '移入常用地址' : '移回口袋景點';
        const confirmed = await window.customConfirm(
            isMovingToFav ? '移入常用地址？' : '移回口袋景點？',
            isMovingToFav 
                ? `您確定要將「${name}」移入常用地址，並從口袋景點中隱藏嗎？` 
                : `您確定要將「${name}」移回口袋景點，並歸類為「${finalCategory}」嗎？`,
            '📌',
            yesText
        );
        if (!confirmed) return;

        try {
            const payload = isMovingToFav 
                ? { id, is_fav: '1' } 
                : { id, category: finalCategory, is_fav: '' };

            const res = await fetch('/api/pocket/update_category', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (data.status === 'success') {
                showToast(isMovingToFav ? `📌 已將「${name}」移入常用地址！` : `↩️ 已將「${name}」移回口袋景點！`, 'success');
                window.loadPocket(true);
            } else {
                showToast('更新失敗，請重試', 'error');
            }
        } catch (e) {
            showToast('連線失敗，請重試', 'error');
        }
    };

    window.editPocketCustomName = (id, currentNote, currentName) => {
        const modal = document.getElementById('pocketCustomNameModal');
        const inputNote = document.getElementById('custom_pocket_name_input');
        const inputName = document.getElementById('custom_pocket_address_title_input');
        if (modal && inputNote && inputName) {
            inputNote.value = currentNote;
            inputName.value = currentName || '';
            modal.classList.add('show');
            setTimeout(() => inputNote.focus(), 100);

            window.closePocketCustomNameModal = async (confirmed) => {
                modal.classList.remove('show');
                if (!confirmed) return;

                const newNote = inputNote.value.trim();
                const newName = inputName.value.trim();
                try {
                    const res = await fetch('/api/pocket/update_note', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ id, note: newNote, name: newName })
                    });
                    const data = await res.json();
                    if (data.status === 'success') {
                        showToast('✏️ 地標資料已成功更新！', 'success');
                        window.loadPocket(true);
                    } else {
                        showToast('更新失敗，請重試', 'error');
                    }
                } catch (e) {
                    showToast('連線失敗，請重試', 'error');
                }
            };
        }
    };

    // --- 📅 行事曆地點「彈窗式下拉選單」帶入功能與全域同步 (V5.0 Premium) ---
    window.openImportFavAddressModal = async () => {
        const modal = document.getElementById('importFavAddressModal');
        const select = document.getElementById('import_fav_address_select');
        if (!modal || !select) return;

        // 如果全域快取尚未載入，則異步加載
        let favs = (window.cachedPocketItems || []).filter(i => i.is_fav === '1');
        if (favs.length === 0) {
            try {
                const res = await fetch('/api/pocket/list');
                const data = await res.json();
                if (data.status === 'success') {
                    window.cachedPocketItems = data.data || [];
                    favs = window.cachedPocketItems.filter(i => i.is_fav === '1');
                }
            } catch (e) {
                console.error("加載常用地址失敗", e);
            }
        }

        if (favs.length === 0) {
            showToast('⚠️ 您目前還沒有設定任何常用地址喔！', 'error');
            return;
        }

        // 注入常用地址選項 (自訂備註優先，相容地標名稱)
        select.innerHTML = favs.map(item => {
            const displayName = item.note ? `📌 ${item.note}` : `📍 ${item.name}`;
            return `<option value="${item.location.replace(/"/g, '&quot;')}">${displayName} (${item.location})</option>`;
        }).join('');

        modal.classList.add('show');

        window.closeImportFavAddressModal = (confirmed) => {
            modal.classList.remove('show');
            if (confirmed && select.value) {
                const input = document.getElementById('manual_location');
                if (input) {
                    input.value = select.value;
                    showToast('📋 已填入常用地址！', 'success');
                }
            }
        };
    };

    // 掃描日程卡片並即時將重複地址按鈕設為已設常用
    window.syncEventFavButtons = () => {
        if (!window.cachedPocketItems) return;
        const favLocations = new Set(
            window.cachedPocketItems
                .filter(i => i.is_fav === '1')
                .map(i => i.location.trim().toLowerCase())
        );

        document.querySelectorAll('.add-fav-loc-btn').forEach(btn => {
            const onclickAttr = btn.getAttribute('onclick') || '';
            const match = onclickAttr.match(/window\.addLocationToFavorites\('(.*?)',/);
            if (match && match[1]) {
                const loc = match[1].replace(/\\'/g, "'").trim().toLowerCase();
                if (favLocations.has(loc)) {
                    btn.disabled = true;
                    btn.style.background = '#f1f5f9';
                    btn.style.border = '1.5px solid #cbd5e1';
                    btn.style.color = '#94a3b8';
                    btn.style.cursor = 'default';
                    btn.style.pointerEvents = 'none';
                    btn.innerHTML = '✓ 已設常用';
                }
            }
        });
    };

    window.renderPocketListDirectly = (rawItems) => {
        const list = document.getElementById('pocket_list');
        if (!list) return;

        const isFavTab = window.currentPocketTab === 'fav';
        const pocketItems = rawItems.filter(i => i.is_fav !== '1');
        const favItems = rawItems.filter(i => i.is_fav === '1');

        // 1. 生成篩選列
        renderFilterBar([...new Set(pocketItems.map(i => i.category))]);
        renderAreaFilterBar([...new Set(pocketItems.map(i => i.area).filter(a => a))]);
        renderCatOptions([...new Set(pocketItems.map(i => i.category))]);

        // 2. 分頁與篩選過濾
        let items = [];

        if (isFavTab) {
            items = favItems;
            
            // 常用地址模糊查詢：以自訂名稱 (item.note) 為主要搜尋原則，並相容主要地標名稱 (item.name)
            if (window.currentPocketSearchKeyword) {
                const kw = window.currentPocketSearchKeyword.toLowerCase();
                items = items.filter(item => {
                    const matchNote = (item.note || '').toLowerCase().includes(kw);
                    const matchName = (item.name || '').toLowerCase().includes(kw);
                    return matchNote || matchName;
                });
            }
        } else {
            items = pocketItems;
            if (window.currentPocketFilter !== '全部') {
                items = items.filter(i => i.category === window.currentPocketFilter);
            }
            if (window.currentAreaFilter !== '全部') {
                items = items.filter(i => i.area === window.currentAreaFilter);
            }
            if (window.currentPocketKeyword) {
                const kw = window.currentPocketKeyword.toLowerCase();
                items = items.filter(item => {
                    return (item.name || '').toLowerCase().includes(kw) || 
                           (item.location || '').toLowerCase().includes(kw) ||
                           (item.note || '').toLowerCase().includes(kw);
                });
            }
        }

        // 3. 排序：統一採用建立時間降序排列
        const itemsWithIndex = items.map((item, idx) => ({ item, idx }));
        itemsWithIndex.sort((a, b) => {
            const timeA = a.item.time || '';
            const timeB = b.item.time || '';
            const cmp = timeB.localeCompare(timeA);
            if (cmp !== 0) return cmp;
            return b.idx - a.idx;
        });
        items = itemsWithIndex.map(x => x.item);

        list.innerHTML = items.map(item => {
            const mapUrl = getMapUrl(item.location || item.name);
            const icon = getPocketIcon(item.category);
            const isFavCategory = item.is_fav === '1';

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

            const editBtnHtml = isFavCategory ? `
                <button onclick="window.editPocketCustomName('${item.id}', '${(item.note || '').replace(/'/g, "\\'")}', '${item.name.replace(/'/g, "\\'")}')" 
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
                            <span>📌 ${item.note}</span>
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
    };

    window.loadPocket = async (forceFetch = false) => {
        const list = document.getElementById('pocket_list');
        if (!list) return;

        // 若非強制更新且快取中已有資料，立即本機秒速渲染
        if (!forceFetch && window.cachedPocketItems && window.cachedPocketItems.length > 0) {
            window.renderPocketListDirectly(window.cachedPocketItems);
            return;
        }

        // 展示高級炫光旋轉載入動畫，打破卡頓感
        list.innerHTML = `
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px; color: #14b8a6;">
                <svg style="animation: spin 1s linear infinite;" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <circle cx="12" cy="12" r="10" stroke="#f1f5f9" stroke-width="2.5"></circle>
                    <path d="M12 2C6.477 2 2 6.477 2 12c0 1.89.52 3.66 1.43 5.17" stroke="#14b8a6" stroke-width="2.5" stroke-linecap="round"></path>
                </svg>
                <span style="font-size: 0.85rem; font-weight: 700; margin-top: 12px; color: #64748b;">📡 正在連線雲端硬碟更新中...</span>
            </div>
        `;

        try {
            const res = await fetch('/api/pocket/list');
            const data = await res.json();
            if (data.status === 'success') {
                const rawItems = data.data || [];
                window.cachedPocketItems = rawItems; // 全域常用地址快取
                window.syncEventFavButtons();       // 同步重複地址日程按鈕狀態
                window.renderPocketListDirectly(rawItems);
            } else {
                list.innerHTML = `<div style="color: #ef4444; text-align: center; padding: 40px;">載入失敗，請重試</div>`;
            }
        } catch (e) {
            console.error("載入口袋失敗", e);
            list.innerHTML = `<div style="color: #ef4444; text-align: center; padding: 40px;">連線失敗，請重試</div>`;
        }
    };

    document.getElementById('submitPocket').onclick = async () => {
        const name = document.getElementById('pocket_name').value.trim();
        const location = document.getElementById('pocket_location').value.trim();
        const area = document.getElementById('pocket_area').value;
        const note = document.getElementById('pocket_note').value.trim();
        const category = window.selectedPocketCategory;

        if (!name) return;

        // 🛑 核心防呆：判斷手動新增時地址是否已存在於常用地址中 (V7.0 Premium)
        if (location) {
            const isDuplicated = (window.cachedPocketItems || []).some(
                i => i.is_fav === '1' && i.location.trim().toLowerCase() === location.toLowerCase()
            );
            if (isDuplicated) {
                // 1. 彈出客製化毛玻璃警告對話框
                await window.customAlert('地址已重複 ⚠️', '新增失敗：此地址已存在於常用地址中囉！', '📍', '我知道了');
                
                // 2. 點選「我知道了」後，立刻清空搜尋、地址與備註欄位
                document.getElementById('pocket_name').value = '';
                document.getElementById('pocket_location').value = '';
                document.getElementById('pocket_note').value = '';
                
                const areaDisplay = document.getElementById('detected_area_display');
                if (areaDisplay) {
                    areaDisplay.style.display = 'none';
                    document.getElementById('detected_area_val').innerText = '';
                    document.getElementById('pocket_area').value = '';
                }
                
                // 3. 還原新增按鈕為灰色禁用狀態
                const btn = document.getElementById('submitPocket');
                if (btn) {
                    btn.style.opacity = '0.3';
                    btn.style.pointerEvents = 'none';
                }
                
                document.getElementById('pocket_name').focus();
                return; // 直接攔截，完美阻斷新增！
            }
        }

        const res = await fetch('/api/pocket/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, location, area, note, category })
        });
        if ((await res.json()).status === 'success') {
            window.resetPocketForm();
            window.loadPocket(true);
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

                // 渲染冷啟動溫馨提示橫幅
                const coldStartBannerEl = document.getElementById('health_cold_start_banner');
                if (coldStartBannerEl) {
                    if (data.is_cold_start) {
                        coldStartBannerEl.style.display = 'block';
                    } else {
                        coldStartBannerEl.style.display = 'none';
                    }
                }

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

                // --- 繪製月曆與詳情 ---
                window.menstrualData = data;
                const today = new Date();
                if (!window.currentCalendarYear) window.currentCalendarYear = today.getFullYear();
                if (!window.currentCalendarMonth) window.currentCalendarMonth = today.getMonth() + 1;
                if (!window.selectedCalendarDate) window.selectedCalendarDate = today;
                
                // 4. 漸變淡出毛玻璃加載遮罩
                const overlay = document.getElementById('calendar_loader_overlay');
                if (overlay) {
                    overlay.style.opacity = '0';
                    overlay.style.pointerEvents = 'none';
                }

                if (typeof window.renderMenstrualCalendar === 'function') {
                    window.renderMenstrualCalendar(window.currentCalendarYear, window.currentCalendarMonth, false);
                }
            } else {
                showToast(data.message, 'error');
            }
        } catch (e) {
            console.error('載入健康資料失敗:', e);
            showToast('載入失敗，請檢查網路連接', 'error');
        }
    };

    // --- 🌸 生理健康免責條款與補錄邏輯 (V5.1) ---
    window.agreeMenstrualDisclaimer = () => {
        localStorage.setItem('menstrual_disclaimer_agreed', 'true');
        window.closeModal('menstrualDisclaimerModal');
        const targetModal = window.pendingMenstrualModal || 'healthModal';
        window.openModal(targetModal);

        // 非同步向後端發送免責聲明同意存證
        fetch('/api/health/agree_disclaimer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        })
        .then(res => res.json())
        .then(data => {
            console.log('[Consent DB Logging] 免責聲明雙重雲端存證完成！', data);
        })
        .catch(err => {
            console.error('[Consent DB Logging] 雲端存證失敗，但本地已解鎖:', err);
        });
    };

    window.calculateBackfillLength = () => {
        const startVal = document.getElementById('backfill_start_date').value;
        const endVal = document.getElementById('backfill_end_date').value;
        const lengthEl = document.getElementById('backfill_period_length');
        
        if (startVal && endVal) {
            const startDt = new Date(startVal);
            const endDt = new Date(endVal);
            
            if (startDt > endDt) {
                lengthEl.value = '❌ 開始日期不能大於結束日期';
                lengthEl.style.color = '#be123c';
                return;
            }
            
            const diffDays = Math.round((endDt - startDt) / (1000 * 60 * 60 * 24)) + 1;
            lengthEl.value = `${diffDays} 天`;
            lengthEl.style.color = '#1e293b';
        } else {
            lengthEl.value = '';
        }
    };

    window.submitMenstrualBackfill = async () => {
        const start_date = document.getElementById('backfill_start_date').value;
        const end_date = document.getElementById('backfill_end_date').value;
        const symptoms = document.getElementById('backfill_symptoms').value;
        const submitBtn = document.getElementById('submitBackfillBtn');
        
        if (!start_date || !end_date) {
            showToast('請完整填寫開始與結束日期！', 'warning');
            return;
        }
        
        const startDt = new Date(start_date);
        const endDt = new Date(end_date);
        if (startDt > endDt) {
            showToast('開始日期不能大於結束日期！', 'warning');
            return;
        }
        
        const originalText = submitBtn.innerText;
        submitBtn.disabled = true;
        submitBtn.innerText = '⏳ 正在寫入雲端...';
        submitBtn.style.opacity = '0.7';
        
        try {
            const res = await fetch('/api/health/backfill', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ start_date, end_date, symptoms })
            });
            const data = await res.json();
            if (data.status === 'success') {
                showToast(data.message, 'success');
                window.closeModal('menstrualBackfillModal');
                
                // 清空欄位
                document.getElementById('backfill_start_date').value = '';
                document.getElementById('backfill_end_date').value = '';
                document.getElementById('backfill_symptoms').value = '';
                document.getElementById('backfill_period_length').value = '';
                
                // 重新載入生理健康資訊與統計
                window.loadHealthInfo();
            } else {
                showToast(data.message, 'error');
            }
        } catch (err) {
            console.error('Backfill request error:', err);
            showToast('雲端連線失敗，請稍後再試！', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerText = originalText;
            submitBtn.style.opacity = '1';
        }
    };

    // 綁定快速操作按鈕事件
    document.querySelectorAll('.health-action-btn').forEach(btn => {
        if (btn.classList.contains('backfill')) return;
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

    // --- 📈 股票與證券資產核心邏輯 (V15.0 - Premium) ---
    window.currentStockTxType = '買進';

    window.openAddStockTxModal = () => {
        document.getElementById('stock_tx_ticker').value = '';
        document.getElementById('stock_tx_name').value = '';
        document.getElementById('stock_tx_price').value = '';
        document.getElementById('stock_tx_shares').value = '';
        document.getElementById('stock_tx_fee').value = '';
        
        // 清除記帳匯入的預算狀態，避免正常新增持股時殘留或洩漏
        window.importedStockBudget = null;
        const helperCard = document.getElementById('stock_budget_helper_card');
        if (helperCard) helperCard.style.display = 'none';
        
        // 預設日期為今天 (台灣時間 YYYY-MM-DD)
        const tzoffset = (new Date()).getTimezoneOffset() * 60000;
        const localISOTime = (new Date(Date.now() - tzoffset)).toISOString().slice(0, 10);
        document.getElementById('stock_tx_date').value = localISOTime;
        
        window.setStockTxType('買進');
        window.openModal('stockModal');
    };

    window.setStockTxType = (type) => {
        window.currentStockTxType = type;
        const buyBtn = document.getElementById('tx_type_buy');
        const sellBtn = document.getElementById('tx_type_sell');
        const saveBtn = document.getElementById('saveStockTxBtn');
        const previewCard = document.getElementById('stock_tx_preview_card');
        
        if (type === '買進') {
            // 買進按鈕：高級翠綠色
            buyBtn.style.cssText = "flex: 1; padding: 8px; border: none; border-radius: 8px; font-weight: bold; font-size: 0.85rem; cursor: pointer; transition: all 0.2s; background: #16a34a; color: white;";
            sellBtn.style.cssText = "flex: 1; padding: 8px; border: none; border-radius: 8px; font-weight: bold; font-size: 0.85rem; cursor: pointer; transition: all 0.2s; background: transparent; color: #64748b;";
            
            // 確認按鈕：高級翠綠色
            if (saveBtn) {
                saveBtn.style.background = "#16a34a";
                saveBtn.style.boxShadow = "0 4px 10px rgba(22,163,74,0.15)";
            }
            
            // 試算卡片：綠色系
            if (previewCard) {
                previewCard.style.background = "#f0fdf4";
                previewCard.style.borderColor = "#bbf7d0";
                previewCard.style.color = "#166534";
                previewCard.innerHTML = `
                    <span style="font-weight: 900; color: #14532d; display: block; margin-bottom: 5px;">💡 本次交易預算試算：</span>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                        <span>購買股數：</span>
                        <span id="preview_shares" style="font-weight: 800;">0 股</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                        <span>每股單價：</span>
                        <span id="preview_price" style="font-weight: 800;">$ 0.00</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                        <span>預估成交金額 (股數*單價)：</span>
                        <span id="preview_subtotal" style="font-weight: 800;">$ 0.00</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                        <span>手續費：</span>
                        <span id="preview_fee" style="font-weight: 800;">$ 0.00</span>
                    </div>
                    <div style="border-top: 1px dashed #bbf7d0; margin-top: 6px; padding-top: 6px; display: flex; justify-content: space-between; font-size: 0.88rem; font-weight: 900; color: #14532d;">
                        <span>💰 本次交易您共需支付：</span>
                        <span id="preview_total">$ 0.00</span>
                    </div>
                `;
            }
        } else {
            // 賣出按鈕：珊瑚紅色
            buyBtn.style.cssText = "flex: 1; padding: 8px; border: none; border-radius: 8px; font-weight: bold; font-size: 0.85rem; cursor: pointer; transition: all 0.2s; background: transparent; color: #64748b;";
            sellBtn.style.cssText = "flex: 1; padding: 8px; border: none; border-radius: 8px; font-weight: bold; font-size: 0.85rem; cursor: pointer; transition: all 0.2s; background: #ef4444; color: white;";
            
            // 確認按鈕：珊瑚紅色
            if (saveBtn) {
                saveBtn.style.background = "#ef4444";
                saveBtn.style.boxShadow = "0 4px 10px rgba(239,68,68,0.15)";
            }
            
            // 試算卡片：紅色系
            if (previewCard) {
                previewCard.style.background = "#fef2f2";
                previewCard.style.borderColor = "#fecaca";
                previewCard.style.color = "#991b1b";
                previewCard.innerHTML = `
                    <span style="font-weight: 900; color: #7f1d1d; display: block; margin-bottom: 5px;">💡 本次交易預算試算：</span>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                        <span>賣出股數：</span>
                        <span id="preview_shares" style="font-weight: 800;">0 股</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                        <span>每股單價：</span>
                        <span id="preview_price" style="font-weight: 800;">$ 0.00</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                        <span>預估成交金額 (股數*單價)：</span>
                        <span id="preview_subtotal" style="font-weight: 800;">$ 0.00</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                        <span>手續費：</span>
                        <span id="preview_fee" style="font-weight: 800;">$ 0.00</span>
                    </div>
                    <div style="border-top: 1px dashed #fecaca; margin-top: 6px; padding-top: 6px; display: flex; justify-content: space-between; font-size: 0.88rem; font-weight: 900; color: #7f1d1d;">
                        <span>💰 本次交易您共可回收：</span>
                        <span id="preview_total">$ 0.00</span>
                    </div>
                `;
            }
        }
        window.updateStockTxPreview();
    };

    const hotTickers = [
        { ticker: "TPE:0050", name: "元大台灣50", short: "0050" },
        { ticker: "TPE:0056", name: "元大高股息", short: "0056" },
        { ticker: "TPE:00878", name: "國泰永續高股息", short: "00878" },
        { ticker: "TPE:00919", name: "群益台灣精選高息", short: "00919" },
        { ticker: "TPE:00929", name: "復華台灣科技優息", short: "00929" },
        { ticker: "TPE:2330", name: "台積電", short: "2330" },
        { ticker: "TPE:2317", name: "鴻海", short: "2317" },
        { ticker: "TPE:2454", name: "聯發科", short: "2454" },
        { ticker: "TPE:2303", name: "聯電", short: "2303" },
        { ticker: "TPE:2603", name: "長榮", short: "2603" },
        { ticker: "TPE:2618", name: "長榮航", short: "2618" },
        { ticker: "TPE:2002", name: "中鋼", short: "2002" },
        { ticker: "TPE:2308", name: "台達電", short: "2308" },
        { ticker: "TPE:2881", name: "富邦金", short: "2881" },
        { ticker: "TPE:2882", name: "國泰金", short: "2882" },
        { ticker: "TPE:2884", name: "玉山金", short: "2884" },
        { ticker: "TPE:2886", name: "兆豐金", short: "2886" },
        { ticker: "TPE:2891", name: "中信金", short: "2891" },
        { ticker: "NASDAQ:AAPL", name: "Apple", short: "AAPL" },
        { ticker: "NASDAQ:NVDA", name: "Nvidia", short: "NVDA" },
        { ticker: "NASDAQ:MSFT", name: "Microsoft", short: "MSFT" },
        { ticker: "NASDAQ:TSLA", name: "Tesla", short: "TSLA" }
    ];

    window.onStockTickerInput = async () => {
        const input = document.getElementById('stock_tx_ticker');
        const val = input.value.trim().toLowerCase();
        const container = document.getElementById('stock_ticker_autocomplete');
        
        if (!val) {
            container.style.display = 'none';
            return;
        }
        
        let matches = [];
        try {
            // 優先從 TiDB 資料庫動態模糊查詢
            const res = await fetch(`/api/stock/suggestions?q=${encodeURIComponent(val)}`);
            matches = await res.json();
        } catch (e) {
            console.warn("[Stock Autocomplete] 資料庫連線異常，切換至本機備份選單:", e);
        }
        
        // 🛡️ 降級守衛：若 TiDB 查無匹配或連線失敗，無縫 fallback 至本機靜態字典
        if (!matches || matches.length === 0) {
            matches = hotTickers.filter(t => 
                t.short.toLowerCase().includes(val) || 
                t.ticker.toLowerCase().includes(val) || 
                t.name.toLowerCase().includes(val)
            );
        }
        
        if (matches.length === 0) {
            container.style.display = 'none';
            return;
        }
        
        container.innerHTML = matches.map(m => `
            <div onclick="window.selectStockSuggestion('${m.ticker}', '${m.name}')" style="padding: 10px; cursor: pointer; border-radius: 6px; font-size: 0.85rem; font-weight: bold; color: #1e293b; transition: background 0.2s;" onmouseover="this.style.background='#f1f5f9'" onmouseout="this.style.background='transparent'">
                <span style="color:#0f172a;">${m.ticker}</span> - <span style="color:#64748b;">${m.name}</span>
            </div>
        `).join('');
        container.style.display = 'block';
    };

    window.onStockNameInput = async () => {
        const input = document.getElementById('stock_tx_name');
        const val = input.value.trim().toLowerCase();
        const container = document.getElementById('stock_name_autocomplete');
        
        if (!val) {
            container.style.display = 'none';
            return;
        }
        
        let matches = [];
        try {
            const res = await fetch(`/api/stock/suggestions?q=${encodeURIComponent(val)}`);
            matches = await res.json();
        } catch (e) {
            console.warn("[Stock Autocomplete] 資料庫連線異常，切換至本機選單:", e);
        }
        
        if (!matches || matches.length === 0) {
            matches = hotTickers.filter(t => 
                t.short.toLowerCase().includes(val) || 
                t.ticker.toLowerCase().includes(val) || 
                t.name.toLowerCase().includes(val)
            );
        }
        
        if (matches.length === 0) {
            container.style.display = 'none';
            return;
        }
        
        container.innerHTML = matches.map(m => `
            <div onclick="window.selectStockSuggestion('${m.ticker}', '${m.name}')" style="padding: 10px; cursor: pointer; border-radius: 6px; font-size: 0.85rem; font-weight: bold; color: #1e293b; transition: background 0.2s;" onmouseover="this.style.background='#f1f5f9'" onmouseout="this.style.background='transparent'">
                <span style="color:#0f172a;">${m.ticker}</span> - <span style="color:#64748b;">${m.name}</span>
            </div>
        `).join('');
        container.style.display = 'block';
    };

    window.selectStockSuggestion = (ticker, name) => {
        document.getElementById('stock_tx_ticker').value = ticker;
        document.getElementById('stock_tx_name').value = name;
        document.getElementById('stock_ticker_autocomplete').style.display = 'none';
        document.getElementById('stock_name_autocomplete').style.display = 'none';
        window.updateStockTxPreview();
    };

    // 點擊/觸控外部關閉自動聯想
    const hideStockAutocompletes = (e) => {
        const tickerContainer = document.getElementById('stock_ticker_autocomplete');
        if (tickerContainer && e.target.id !== 'stock_tx_ticker') {
            tickerContainer.style.display = 'none';
        }
        const nameContainer = document.getElementById('stock_name_autocomplete');
        if (nameContainer && e.target.id !== 'stock_tx_name') {
            nameContainer.style.display = 'none';
        }
    };
    document.addEventListener('click', hideStockAutocompletes);
    document.addEventListener('touchstart', hideStockAutocompletes, { passive: true });

    // 焦點離開 (Focusout 委派) 時延時關閉 (延遲 200ms 確保 select 點擊事件能被正確接收，且完美解決 DOM 載入順序問題)
    document.addEventListener('focusout', (e) => {
        if (e.target && e.target.id === 'stock_tx_ticker') {
            setTimeout(() => {
                const container = document.getElementById('stock_ticker_autocomplete');
                if (container) container.style.display = 'none';
            }, 200);
        }
        if (e.target && e.target.id === 'stock_tx_name') {
            setTimeout(() => {
                const container = document.getElementById('stock_name_autocomplete');
                if (container) container.style.display = 'none';
            }, 200);
        }
    });

    window.saveStockTransaction = async () => {
        const ticker = document.getElementById('stock_tx_ticker').value.trim();
        const name = document.getElementById('stock_tx_name').value.trim();
        const price = document.getElementById('stock_tx_price').value.trim();
        const sharesInput = document.getElementById('stock_tx_shares');
        sharesInput.value = sharesInput.value.replace(/[^0-9]/g, ''); // 強制防呆取整
        const shares = sharesInput.value.trim();
        const fee = document.getElementById('stock_tx_fee').value.trim() || "0";
        const date = document.getElementById('stock_tx_date').value.trim();
        
        if (!ticker || !name || !price || !shares || !date) {
            showToast('請完整填寫股票代號、名稱、單價與股數喔！');
            return;
        }
        
        const saveBtn = document.getElementById('saveStockTxBtn');
        const originalText = saveBtn.innerHTML;
        saveBtn.innerHTML = '<span class="loading-spinner" style="width: 16px; height: 16px; border-width: 2px;"></span> 寫入中...';
        saveBtn.style.opacity = '0.7';
        saveBtn.disabled = true;
        
        try {
            const res = await fetch('/api/stock/add_transaction', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ticker,
                    name,
                    type: window.currentStockTxType,
                    price: parseFloat(price),
                    shares: parseInt(shares), // 強制以整數傳入後端
                    fee: parseFloat(fee),
                    date
                })
            });
            const data = await res.json();
            if (data.status === 'success') {
                closeModal('stockModal');
                
                document.getElementById('stock_tx_ticker').value = '';
                document.getElementById('stock_tx_name').value = '';
                document.getElementById('stock_tx_price').value = '';
                document.getElementById('stock_tx_shares').value = '';
                document.getElementById('stock_tx_fee').value = '';
                
                const previewCard = document.getElementById('stock_tx_preview_card');
                if (previewCard) previewCard.style.display = 'none';

                // 2. 顯示炫麗的「Mission Accomplished」成功記帳彈窗 (V12.2 Master UX)
                const sharesVal = parseInt(shares) || 1;
                const priceVal = parseFloat(price) || 0;
                const feeVal = parseFloat(fee) || 0;
                const subtotal = priceVal * sharesVal;
                const totalCost = subtotal + feeVal;

                const confirmMsg = `
                    <div style="text-align: left; line-height: 1.6; font-size: 0.85rem; color: #334155;">
                        <p style="margin-top: 0; font-weight: 800; color: #16a34a; font-size: 0.95rem; display: flex; align-items: center; gap: 6px;">
                            <span>🎉 投資交易與記帳已同步完成！</span>
                        </p>
                        <div style="background: #f8fafc; border: 1.5px dashed #cbd5e1; border-radius: 12px; padding: 12px; margin-bottom: 12px;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                                <span style="color:#64748b;">📈 證券代碼：</span><span style="font-weight: bold; color: #0f172a;">${ticker}</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                                <span style="color:#64748b;">🏷️ 股票名稱：</span><span style="font-weight: bold; color: #0f172a;">${name}</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                                <span style="color:#64748b;">💵 成交單價：</span><span style="font-weight: bold; color: #0f172a;">$ ${priceVal.toLocaleString()}</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                                <span style="color:#64748b;">📊 交易股數：</span><span style="font-weight: bold; color: #0f172a;">${sharesVal} 股</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                                <span style="color:#64748b;">💸 交易手續費：</span><span style="font-weight: bold; color: #0f172a;">$ ${feeVal.toLocaleString()}</span>
                            </div>
                            <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 8px 0;">
                            <div style="display: flex; justify-content: space-between; font-weight: bold; color: #1e3a8a;">
                                <span>💰 同步記帳金額：</span><span>$ ${totalCost.toLocaleString()}</span>
                            </div>
                        </div>
                        <p style="margin: 0; font-size: 0.78rem; color: #475569; font-weight: 500;">
                            ℹ️ 該筆投資支出已<b>同步寫入「記帳」試算表</b>，您可隨時前往 Google Drive / Sheets 雲端硬碟目錄查看完整會計明細。
                        </p>
                    </div>
                `;

                await window.customConfirm(
                    '🎉 同步完成！',
                    confirmMsg,
                    '💼',
                    '確認並返回主頁對話框 🚀',
                    false // ❌ 不需要取消按鈕！直接寬版大按鈕一行搞定！
                );

                // 3. 跳轉至主頁對話框 (自動選取並點擊記帳 Tab 以確保 active 樣式正常)
                const financeBtn = Array.from(document.querySelectorAll('.tab-btn')).find(btn => btn.innerText.includes('記帳'));
                if (financeBtn) {
                    financeBtn.click();
                } else {
                    window.switchTab('finance');
                }

                // 4. 在對話框中以精美格式列出支出與買入股票資訊
                const reportMsg = `📈 <b>證券持股與記帳同步成功報告</b> 💼\n` +
                                  `─────────────────\n` +
                                  `• <b>標的資訊：</b> ${name} (${ticker})\n` +
                                  `• <b>交易日期：</b> ${date}\n` +
                                  `• <b>交易類型：</b> 買進\n` +
                                  `• <b>每股單價：</b> $${priceVal.toLocaleString()}\n` +
                                  `• <b>成交股數：</b> ${sharesVal} 股\n` +
                                  `• <b>交易手續費：</b> $${feeVal.toLocaleString()}\n` +
                                  `• <b>證券成交總價：</b> $${subtotal.toLocaleString()}\n` +
                                  `─────────────────\n` +
                                  `💰 <b>自動記帳備案：</b>\n` +
                                  `• 記帳項目已新增一筆金額為 <b>$${totalCost.toLocaleString()}</b> 的「投資」分類支出明細。\n` +
                                  `• <b>雲端狀態：</b> 已直連寫入 Google Sheets，請前往雲端硬碟查核！`;

                appendMessage(reportMsg);

                window.loadStockPortfolio().catch(() => {});
            } else {
                showToast(data.message, 'error');
            }
        } catch (e) {
            showToast('寫入失敗，請稍後再試', 'error');
        } finally {
            saveBtn.innerHTML = originalText;
            saveBtn.style.opacity = '1';
            saveBtn.disabled = false;
        }
    };

    window.loadStockPortfolio = async () => {
        const listContainer = document.getElementById('stock_portfolio_list');
        const historyContainer = document.getElementById('stock_tx_history');
        if (!listContainer || !historyContainer) return;
        
        listContainer.innerHTML = '<div style="text-align: center; color: #94a3b8; font-size: 0.85rem; padding: 20px;"><span class="loading-spinner" style="width: 20px; height: 20px; border-color: #0f172a; border-top-color: transparent;"></span> 讀取證券資料中...</div>';
        
        try {
            const res = await fetch('/api/stock/portfolio');
            const data = await res.json();
            
            if (data.status === 'locked') {
                closeModal('stockModal');
                openModal('upgradePaywallModal');
                return;
            }
            
            if (data.status === 'error') {
                listContainer.innerHTML = `<div style="text-align: center; color: #ef4444; font-size: 0.85rem; padding: 20px;">❌ 載入失敗: ${data.message}</div>`;
                return;
            }
            
            // 1. 渲染頂部總體資產
            document.getElementById('stock_total_value').innerText = `$ ${data.summary.total_value.toLocaleString()}`;
            document.getElementById('stock_total_cost').innerText = `$ ${data.summary.total_cost.toLocaleString()}`;
            
            const roiVal = data.summary.total_roi;
            const roiRate = data.summary.total_roi_rate;
            const roiEl = document.getElementById('stock_total_roi');
            if (roiVal >= 0) {
                roiEl.innerText = `+$ ${roiVal.toLocaleString()} (+${roiRate}%)`;
                roiEl.style.color = '#34d399';
            } else {
                roiEl.innerText = `-$ ${Math.abs(roiVal).toLocaleString()} (${roiRate}%)`;
                roiEl.style.color = '#f87171';
            }
            
            // 2. 渲染持股卡片
            const portfolio = data.portfolio;
            const tickers = Object.keys(portfolio);
            
            if (tickers.length === 0) {
                listContainer.innerHTML = `
                    <div style="text-align: center; padding: 25px; background: #f8fafc; border-radius: 16px; border: 1.5px dashed #cbd5e1;">
                        <span style="font-size: 1.8rem; display: block; margin-bottom: 8px;">📈</span>
                        <div style="font-weight: bold; color: #475569; font-size: 0.9rem; margin-bottom: 10px;">目前試算表尚無任何持股部位</div>
                        <div style="text-align: left; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px; font-size: 0.78rem; color: #64748b; margin-bottom: 12px; line-height: 1.6;">
                            <div style="font-weight: 800; color: #334155; margin-bottom: 6px; display: flex; align-items: center; gap: 4px;">🎯 系統將在此為您條列與統計：</div>
                            <div style="display: flex; gap: 4px; margin-bottom: 2px;"><span>1.</span><span><strong>條列持有股票</strong>：股票名稱與代號</span></div>
                            <div style="display: flex; gap: 4px; margin-bottom: 2px;"><span>2.</span><span><strong>共持有多少股數</strong>：累計持股總股數</span></div>
                            <div style="display: flex; gap: 4px; margin-bottom: 2px;"><span>3.</span><span><strong>每股平均成本</strong>：每整股的平均取得成本</span></div>
                            <div style="display: flex; gap: 4px; margin-bottom: 2px;"><span>4.</span><span><strong>即時最新市價</strong>：對接 Google 金融報價</span></div>
                            <div style="display: flex; gap: 4px;"><span>5.</span><span><strong>累計即時損益</strong>：最新市值減成本與 ROI (%)</span></div>
                        </div>
                        <div style="color: #94a3b8; font-size: 0.75rem;">點擊上方「➕ 新增持股」分頁即可開始存股！</div>
                    </div>
                `;
            } else {
                listContainer.innerHTML = tickers.map(t => {
                    const p = portfolio[t];
                    const roi = p.total_roi;
                    const roiRate = p.total_cost > 0 ? ((roi / p.total_cost) * 100).toFixed(2) : "0.00";
                    const isProfit = roi >= 0;
                    const badgeColor = isProfit ? "#d1fae5" : "#fee2e2";
                    const textColor = isProfit ? "#065f46" : "#991b1b";
                    const sign = isProfit ? "+" : "";
                    
                    return `
                        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 16px; padding: 15px; display: flex; flex-direction: column; gap: 8px; transition: transform 0.2s;" onmouseover="this.style.transform='scale(1.01)'" onmouseout="this.style.transform='scale(1.0)'">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <span style="font-size: 0.95rem; font-weight: 800; color: #1e293b; text-align: left; display: inline-block;">${p.name}</span>
                                    <span style="font-size: 0.72rem; color: #64748b; margin-left: 4px; background: #e2e8f0; padding: 2px 6px; border-radius: 6px;">${p.ticker}</span>
                                </div>
                                <div style="background: ${badgeColor}; color: ${textColor}; font-size: 0.75rem; font-weight: 800; padding: 4px 8px; border-radius: 20px;">
                                    ${sign}${roi.toLocaleString()} (${sign}${roiRate}%)
                                </div>
                            </div>
                            
                            <div style="display: flex; justify-content: space-between; font-size: 0.78rem; color: #64748b; margin-top: 4px; text-align: left;">
                                <div>
                                    <div>持股股數: <span style="font-weight: bold; color: #1e293b;">${p.net_shares.toLocaleString()} 股</span></div>
                                    <div>每股平均成本: <span style="font-weight: bold; color: #1e293b;">$ ${p.avg_cost}</span></div>
                                </div>
                                <div style="text-align: right;">
                                    <div>即時市價: <span style="font-weight: bold; color: #1e293b;">$ ${p.live_price}</span></div>
                                    <div>部位累計成本: <span style="font-weight: bold; color: #1e293b;">$ ${p.total_cost.toLocaleString()}</span></div>
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');
            }
            
            // 3. 渲染交易歷史
            const transactions = data.transactions;
            if (transactions.length === 0) {
                historyContainer.innerHTML = '<div style="text-align: center; color: #94a3b8; font-size: 0.75rem; padding: 10px;">目前尚無交易明細。</div>';
            } else {
                historyContainer.innerHTML = transactions.map(tx => {
                    const isBuy = tx.type === '買進';
                    const pillColor = isBuy ? '#e0f2fe' : '#fee2e2';
                    const textColor = isBuy ? '#0369a1' : '#b91c1c';
                    
                    return `
                        <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px; background: #f8fafc; border: 1px solid #f1f5f9; border-radius: 10px; font-size: 0.78rem;">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span style="background: ${pillColor}; color: ${textColor}; font-weight: 800; padding: 2px 6px; border-radius: 6px; font-size: 0.7rem;">${tx.type}</span>
                                <span style="font-weight: bold; color: #1e293b;">${tx.name}</span>
                                <span style="color: #94a3b8;">${tx.date}</span>
                            </div>
                            <div style="text-align: right; font-weight: bold; color: #475569;">
                                ${tx.shares.toLocaleString()} 股 @ $ ${tx.price}
                            </div>
                        </div>
                    `;
                }).join('');
            }
            
        } catch (e) {
            listContainer.innerHTML = '<div style="text-align: center; color: #ef4444; font-size: 0.85rem; padding: 20px;">❌ 載入失敗，連線異常</div>';
        }
    };

    window.runStockAIFit = async () => {
        const runBtn = document.getElementById('runStockAIBtn');
        const container = document.getElementById('stock_ai_report_container');
        if (!container || !runBtn) return;
        
        container.innerHTML = `
            <div style="text-align: center; color: #94a3b8; padding-top: 50px;">
                <span class="loading-spinner" style="width: 32px; height: 32px; border-color: #38bdf8; border-top-color: transparent; margin-bottom: 12px; display: block; margin-left: auto; margin-right: auto;"></span>
                🤖 AI 正在全方位解讀您的存股配置並進行診斷，大數據複雜計算預估需要 8-15 秒，請稍候...
            </div>
        `;
        runBtn.disabled = true;
        runBtn.style.opacity = '0.6';
        runBtn.innerHTML = '⚡ AI 正在精算大數據中...';
        
        try {
            const res = await fetch('/api/stock/ai_analysis', { method: 'POST' });
            const data = await res.json();
            
            if (data.status === 'locked') {
                closeModal('stockAnalysisModal');
                openModal('upgradePaywallModal');
                return;
            }
            
            if (data.status === 'error') {
                container.innerHTML = `<div style="text-align: center; color: #ef4444; padding: 20px;">❌ 診斷失敗: ${data.message}</div>`;
                return;
            }
            
            // 格式化 markdown 並印出
            container.innerHTML = `
                <div style="display: flex; align-items: center; gap: 8px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px; margin-bottom: 15px; color:#38bdf8; font-weight: bold; font-size: 0.95rem; text-align: left;">
                    <span>🤖</span> 旗艦版 AI 全能證券健檢報告 (已成功精算)
                </div>
                <div style="text-align: left;">
                    ${formatStockMarkdown(data.analysis)}
                </div>
            `;
            
            // 同步更新首頁右上角的點數顯示
            const pointEl = document.getElementById('user_ai_points');
            if (pointEl && data.remaining_points !== undefined) {
                pointEl.innerText = data.remaining_points;
                window.USER_AI_POINTS = data.remaining_points;
            }
            showToast('AI 全能持股健檢大數據計算完畢！', 'success');
            
        } catch (e) {
            container.innerHTML = '<div style="text-align: center; color: #ef4444; padding: 20px;">❌ 連線失敗，無法取得 AI 報告</div>';
        } finally {
            runBtn.disabled = false;
            runBtn.style.opacity = '1';
            runBtn.innerHTML = '⚡ 立即啟動 AI 全能診斷 (扣除 30 點)';
        }
    };

    function formatStockMarkdown(text) {
        if (!text) return "";
        // 若內容已經是後端格式化好的精美 HTML 樣式，則直接返回，避免二次逸出破壞樣式
        if (text.includes('<div') || text.includes('<span')) {
            return text;
        }
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\*\*([^*]+)\*\*/g, '<strong style="color: #38bdf8; font-weight: 800;">$1</strong>')
            .replace(/\*([^*]+)\*/g, '<em style="color: #93c5fd;">$1</em>')
            .replace(/`([^`]+)`/g, '<code style="background: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 4px; color:#f472b6;">$1</code>')
            .replace(/\n/g, '<br>');
    }

    // --- 投資持股直出對話框核心 ---
    window.queryStockPortfolioSummary = async () => {
        appendMessage(`查詢當前證券持股...`, true);
        try {
            const res = await fetch('/api/query_stock_portfolio', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await res.json();
            if (data.status === 'success') {
                appendMessage(formatStockMarkdown(data.message));
            } else {
                appendMessage("❌ 查詢失敗：" + data.message);
            }
        } catch (error) {
            appendMessage("❌ 伺服器連線失敗");
        }
    };

    window.openAddStockTxModalWithValues = async (tx) => {
        window.openAddStockTxModal();
        
        window.importedStockBudget = null;
        const helperCard = document.getElementById('stock_budget_helper_card');
        if (helperCard) helperCard.style.display = 'none';

        // 1. 智慧分流股票代碼與名稱 + 實時 TiDB/本機熱門選單補齊 (V12.0 Master UX)
        if (tx.name) {
            const val = tx.name.trim();
            const isPureDigits = /^\d+$/.test(val);
            const isUsTicker = /^[A-Za-z]{1,5}$/.test(val) && val === val.toUpperCase();
            const isPrefixedTicker = /^[A-Za-z]+:\d+$/.test(val);
            
            let matched = null;
            
            // A. 優先嘗試從 TiDB 實時模糊搜尋 (0點成本)
            try {
                const res = await fetch(`/api/stock/suggestions?q=${encodeURIComponent(val)}`);
                const data = await res.json();
                if (data && data.length > 0) {
                    matched = data.find(t => 
                        t.short === val || 
                        t.ticker === val || 
                        t.name === val
                    ) || data[0];
                }
            } catch (e) {
                console.warn("[Stock Redirect AutoComplete] 實時聯想查詢失敗，採用本機字典備份:", e);
            }
            
            // B. 降級備份匹配 (hotTickers fallback)
            if (!matched) {
                matched = hotTickers.find(t => 
                    t.short.toLowerCase() === val.toLowerCase() || 
                    t.ticker.toLowerCase() === val.toLowerCase() ||
                    t.name.toLowerCase() === val.toLowerCase() ||
                    t.name.toLowerCase().includes(val.toLowerCase())
                );
            }

            if (matched) {
                document.getElementById('stock_tx_ticker').value = matched.ticker;
                document.getElementById('stock_tx_name').value = matched.name;
            } else {
                if (isPureDigits || isUsTicker || isPrefixedTicker) {
                    document.getElementById('stock_tx_ticker').value = val;
                    document.getElementById('stock_tx_name').value = '';
                } else {
                    document.getElementById('stock_tx_ticker').value = '';
                    document.getElementById('stock_tx_name').value = val;
                }
            }
        } else {
            if (tx.ticker) document.getElementById('stock_tx_ticker').value = tx.ticker;
            if (tx.name) document.getElementById('stock_tx_name').value = tx.name;
        }

        // 2. 成交單價與預算分流 (AI 對話帶入成交單價；記帳同步帶入總預算助手)
        if (tx.total_budget) {
            window.importedStockBudget = tx.total_budget;
            document.getElementById('stock_tx_price').value = '';
            document.getElementById('stock_tx_shares').value = '';
            
            const budgetAmount = document.getElementById('budget_helper_amount');
            if (budgetAmount) budgetAmount.innerText = `$ ${tx.total_budget.toLocaleString()}`;
            if (helperCard) helperCard.style.display = 'block';
        } else {
            if (tx.price) document.getElementById('stock_tx_price').value = tx.price;
            if (tx.shares) document.getElementById('stock_tx_shares').value = tx.shares;
        }

        if (tx.fee !== undefined) document.getElementById('stock_tx_fee').value = tx.fee;
        if (tx.date) document.getElementById('stock_tx_date').value = tx.date;
        if (tx.tx_type) window.setStockTxType(tx.tx_type);
        window.updateStockTxPreview();
    };

    window.applyBudgetSplit = () => {
        const budget = window.importedStockBudget;
        if (!budget) return;

        const priceInput = document.getElementById('stock_tx_price');
        const priceVal = parseFloat(priceInput.value) || 0;
        
        if (priceVal <= 0) {
            showToast('💡 請先手動輸入「成交單價」，系統將以總預算進行一鍵拆分！', 'info');
            priceInput.focus();
            return;
        }

        const feeInput = document.getElementById('stock_tx_fee');
        const feeVal = parseFloat(feeInput.value) || 0;
        
        const isSell = window.currentStockTxType === '賣出';
        const netBudget = isSell ? (budget + feeVal) : (budget - feeVal);
        
        if (netBudget <= 0) {
            showToast('❌ 預算金額不足扣抵手續費！', 'error');
            return;
        }

        const shares = Math.floor(netBudget / priceVal);
        if (shares <= 0) {
            showToast('❌ 計算股數為 0，請確認單價與手續費是否合理！', 'error');
            return;
        }

        document.getElementById('stock_tx_shares').value = shares;
        window.updateStockTxPreview();
        showToast(`✅ 已為您成功反推整數股數為 ${shares} 股！`, 'success');
    };

    // 💡 零股與交易金額即時雙向試算防呆 (V3 - 限制整數)
    window.updateStockTxPreview = () => {
        const sharesInput = document.getElementById('stock_tx_shares');
        if (sharesInput) {
            // 自動防呆過濾非數字
            sharesInput.value = sharesInput.value.replace(/[^0-9]/g, '');
        }
        
        const sharesVal = parseInt(sharesInput.value) || 0;
        const priceVal = parseFloat(document.getElementById('stock_tx_price').value) || 0;
        const feeVal = parseFloat(document.getElementById('stock_tx_fee').value) || 0;
        const previewCard = document.getElementById('stock_tx_preview_card');
        
        if (!previewCard) return;
        
        if (sharesVal > 0 && priceVal > 0) {
            previewCard.style.display = 'block';
            
            const subtotal = sharesVal * priceVal;
            // 💰 金融邏輯防呆對齊：買進為成交金額加手續費；賣出為成交金額扣除手續費
            const isSell = window.currentStockTxType === '賣出';
            const total = isSell ? (subtotal - feeVal) : (subtotal + feeVal);
            
            const sharesLabel = isSell ? `${sharesVal} 股 (賣出整數)` : `${sharesVal} 股 (買進整數)`;
            
            document.getElementById('preview_shares').innerText = sharesLabel;
            document.getElementById('preview_price').innerText = `$ ${priceVal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('preview_subtotal').innerText = `$ ${subtotal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('preview_fee').innerText = `$ ${feeVal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('preview_total').innerText = `$ ${total.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        } else {
            previewCard.style.display = 'none';
        }
    };

    // --- 📊 存股看板核心載入渲染器 (V3.2 - Premium Glassmorphism) ---
    window.openStockDashboard = async () => {
        window.openModal('stockDashboardModal');
        
        // 取得渲染容器與指標 DOM
        const totalValueEl = document.getElementById('dash_total_value');
        const totalRoiEl = document.getElementById('dash_total_roi');
        const totalCostEl = document.getElementById('dash_total_cost');
        const totalDividendsEl = document.getElementById('dash_total_dividends');
        const portfolioListEl = document.getElementById('dash_portfolio_list');
        
        if (!portfolioListEl) return;
        
        // 初始化 Loading 狀態
        portfolioListEl.innerHTML = `
            <div style="text-align: center; padding: 40px 10px; color: #64748b; font-weight: bold; font-size: 0.85rem; width: 100%;">
                <div class="loading-spinner" style="border-top-color: #38bdf8; margin: 0 auto 10px auto;"></div>
                正在安全連結 Google 試算表計算最新損益...
            </div>
        `;
        
        try {
            const res = await fetch('/api/stock/portfolio');
            const data = await res.json();
            
            if (data.status === 'locked') {
                // 如果是免費版被鎖定，直接交由 HTML 訂閱遮罩阻擋即可，此處清空列表
                portfolioListEl.innerHTML = `
                    <div style="text-align: center; padding: 40px 10px; color: #64748b; font-weight: bold; font-size: 0.85rem;">
                        🔒 升級旗艦版會員解鎖實時存股看板
                    </div>
                `;
                return;
            }
            
            if (data.status !== 'success') {
                portfolioListEl.innerHTML = `
                    <div style="text-align: center; padding: 40px 10px; color: #f87171; font-weight: bold; font-size: 0.85rem;">
                        ❌ 載入失敗：${data.message || '無法連線到試算表'}
                    </div>
                `;
                return;
            }
            
            const summary = data.summary || { total_cost: 0, total_value: 0, total_roi: 0, total_roi_rate: 0, total_dividends: 0, total_realized_pnl: 0, global_total_roi: 0 };
            const portfolio = data.portfolio || {};
            
            // 1. 渲染頂部總計資產卡片 (一鍵資產看板)
            totalValueEl.innerHTML = `$${Math.round(summary.total_value).toLocaleString()} <span style="font-size: 1rem; color: #94a3b8; font-weight: 700;">NTD</span>`;
            totalCostEl.innerText = `$${Math.round(summary.total_cost).toLocaleString()}`;
            totalDividendsEl.innerText = `$${Math.round(summary.total_dividends || 0).toLocaleString()} NTD`;
            
            // 渲染新增的「累計已實現損益」指標
            const totalRealizedEl = document.getElementById('dash_total_realized');
            if (totalRealizedEl) {
                const realizedVal = Math.round(summary.total_realized_pnl || 0);
                const realizedSign = realizedVal >= 0 ? '+' : '';
                const realizedColor = realizedVal >= 0 ? '#38bdf8' : '#f87171';
                totalRealizedEl.innerHTML = `$${realizedVal.toLocaleString()} NTD`;
                totalRealizedEl.style.color = realizedColor;
            }
            
            // 渲染全域報酬率為：未實現 + 已實現 + 股息 的全局利潤
            const globalRoi = Math.round(summary.global_total_roi || 0);
            const globalRoiRate = (summary.total_roi_rate || 0).toFixed(2);
            if (globalRoi >= 0) {
                totalRoiEl.innerText = `+${globalRoi.toLocaleString()} (+${globalRoiRate}%)`;
                totalRoiEl.style.color = '#4ade80'; // Soft Mint Green
            } else {
                totalRoiEl.innerText = `${globalRoi.toLocaleString()} (${globalRoiRate}%)`;
                totalRoiEl.style.color = '#f87171'; // Warning Coral Red
            }
            
            // 2. 渲染持股明細清單 (微軟式極簡深色毛玻璃卡片)
            const tickers = Object.keys(portfolio);
            if (tickers.length === 0) {
                portfolioListEl.innerHTML = `
                    <div style="text-align: center; padding: 40px 10px; color: #94a3b8; font-size: 0.82rem; font-weight: 700; line-height: 1.5;">
                        🌱 您的證券投資組合目前沒有持股紀錄喔！<br>
                        點擊下方「➕ 新增持股」快速補登您的第一筆部位吧！
                    </div>
                `;
            } else {
                let htmlContent = '';
                tickers.forEach(t => {
                    const p = portfolio[t];
                    
                    const netShares = Math.round(p.net_shares);
                    let sharesText = '';
                    if (netShares >= 1000) {
                        const sheets = Math.floor(netShares / 1000);
                        const rem = netShares % 1000;
                        sharesText = rem > 0 ? `🎟️ ${sheets}張 ${rem}股` : `🎟️ ${sheets}張`;
                    } else {
                        sharesText = `🌱 ${netShares}股`;
                    }
                    
                    const stockRoiRate = p.total_cost > 0 ? ((p.unrealized_roi / p.total_cost) * 100).toFixed(2) : '0.00';
                    
                    const isProfit = p.unrealized_roi >= 0;
                    const roiColor = isProfit ? '#4ade80' : '#f87171';
                    const roiSign = isProfit ? '+' : '';
                    const bgBorderStyling = isProfit 
                        ? 'border: 1px solid rgba(74, 222, 128, 0.16); background: rgba(255, 255, 255, 0.02);' 
                        : 'border: 1px solid rgba(248, 113, 113, 0.16); background: rgba(255, 255, 255, 0.02);';
                        
                    htmlContent += `
                        <div style="border-radius: 16px; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; ${bgBorderStyling} transition: all 0.2s ease;">
                            <div style="display: flex; align-items: center; justify-content: space-between;">
                                <span style="font-weight: 800; font-size: 0.95rem; color: #f8fafc; letter-spacing: -0.2px;">
                                    ${p.name}
                                    <span style="font-size: 0.72rem; color: #64748b; font-weight: normal; margin-left: 5px;">${p.ticker}</span>
                                </span>
                                <span style="font-weight: 800; font-size: 0.92rem; color: #f8fafc; font-family: monospace;">
                                    $${p.live_price.toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 2})}
                                </span>
                            </div>
                            
                            <div style="display: flex; align-items: flex-end; justify-content: space-between; font-size: 0.78rem;">
                                <div style="display: flex; flex-direction: column; gap: 2px; color: #94a3b8;">
                                    <span>數量: <span style="font-weight: 700; color: #cbd5e1;">${sharesText}</span></span>
                                    <span>均價: <span style="font-weight: 700; color: #cbd5e1;">$${p.avg_cost.toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 2})}</span></span>
                                </div>
                                <div style="text-align: right; display: flex; flex-direction: column; gap: 2px;">
                                    <span style="font-size: 0.7rem; color: #64748b; font-weight: 700;">帳面損益</span>
                                    <span style="font-weight: 800; color: ${roiColor}; font-size: 0.88rem; font-family: monospace;">
                                        ${roiSign}$${Math.round(p.unrealized_roi).toLocaleString()} (${roiSign}${stockRoiRate}%)
                                    </span>
                                </div>
                            </div>
                        </div>
                    `;
                });
                portfolioListEl.innerHTML = htmlContent;
            }

            // 3. 渲染已結清歷史戰績 (Closed Positions Dashboard)
            const closedListEl = document.getElementById('dash_closed_list');
            if (closedListEl) {
                const closedPortfolio = data.closed_portfolio || {};
                const closedTickers = Object.keys(closedPortfolio);
                
                if (closedTickers.length === 0) {
                    closedListEl.innerHTML = `
                        <div style="text-align: center; padding: 20px 10px; color: #64748b; font-size: 0.8rem; font-weight: bold;">
                            目前尚無已結清的歷史交易紀錄喔！
                        </div>
                    `;
                } else {
                    let closedHtmlContent = '';
                    closedTickers.forEach(t => {
                        const p = closedPortfolio[t];
                        const realizedVal = Math.round(p.realized_pnl);
                        const isProfit = realizedVal >= 0;
                        const roiColor = isProfit ? '#4ade80' : '#f87171';
                        const roiSign = isProfit ? '+' : '';
                        const bgBorderStyling = isProfit 
                            ? 'border: 1px solid rgba(74, 222, 128, 0.1); background: rgba(255, 255, 255, 0.01);' 
                            : 'border: 1px solid rgba(248, 113, 113, 0.1); background: rgba(255, 255, 255, 0.01);';
                            
                        closedHtmlContent += `
                            <div style="border-radius: 16px; padding: 10px 12px; display: flex; flex-direction: column; gap: 4px; ${bgBorderStyling} font-size: 0.78rem;">
                                <div style="display: flex; align-items: center; justify-content: space-between;">
                                    <span style="font-weight: 800; color: #e2e8f0; letter-spacing: -0.2px;">
                                        ${p.name} <span style="font-size: 0.68rem; color: #64748b; font-weight: normal; margin-left: 3px;">${p.ticker}</span>
                                    </span>
                                    <span style="color: #64748b; font-size: 0.68rem;">結清日期: ${p.close_date || '未知'}</span>
                                </div>
                                <div style="display: flex; align-items: center; justify-content: space-between;">
                                    <span style="color: #94a3b8; font-size: 0.72rem;">歷史配息: <span style="color: #fcd34d; font-weight: 700;">$${Math.round(p.dividends).toLocaleString()}</span></span>
                                    <span style="font-weight: 800; color: ${roiColor}; font-family: monospace;">
                                        實際賺賠: ${roiSign}$${realizedVal.toLocaleString()}
                                    </span>
                                </div>
                            </div>
                        `;
                    });
                    closedListEl.innerHTML = closedHtmlContent;
                }
            }
            
        } catch (error) {
            console.error('[Dashboard Error]', error);
            portfolioListEl.innerHTML = `
                <div style="text-align: center; padding: 40px 10px; color: #f87171; font-weight: bold; font-size: 0.85rem;">
                    ❌ 連線異常，請確認您的網路環境後再重試！
                </div>
            `;
        }
    };

    // ☁️ 雲端存股表自癒觸發包裝器
    window.openCloudStockSheet = (url) => {
        // 先在背景發送一個輕量級的 API 請求，悄悄觸發自癒守衛
        fetch('/api/stock/portfolio').catch(() => {});
        // 同時順暢地在分頁開啟雲端存股表
        window.open(url, '_blank');
    };

    // ☁️ 雲端生理紀錄表自癒觸發包裝器
    window.openCloudHealthSheet = (url) => {
        // 先在背景發送一個輕量級的 API 請求，悄悄觸發自癒守衛（修復生理紀錄表頭與警告鎖）
        fetch('/api/health/info').catch(() => {});
        // 同時順暢地在分頁開啟健康紀錄表
        window.open(url, '_blank');
    };

    // =====================================================
    // 🌸 互動式生理追蹤月曆引擎 (Menstrual Calendar Engine)
    // =====================================================
    window.changeCalendarMonth = (offset) => {
        window.currentCalendarMonth += offset;
        if (window.currentCalendarMonth > 12) {
            window.currentCalendarMonth = 1;
            window.currentCalendarYear += 1;
        } else if (window.currentCalendarMonth < 1) {
            window.currentCalendarMonth = 12;
            window.currentCalendarYear -= 1;
        }
        window.renderMenstrualCalendar(window.currentCalendarYear, window.currentCalendarMonth);
    };

    window.renderMenstrualCalendar = (year, month, isSkeleton = false) => {
        const grid = document.getElementById('calendar_days_grid');
        const monthYearSpan = document.getElementById('calendar_month_year');
        if (!grid || !monthYearSpan) return;
        
        monthYearSpan.innerText = `${year}年 ${month}月`;
        grid.innerHTML = '';
        
        const today = new Date();
        
        // Ensure selectedCalendarDate exists
        if (!window.selectedCalendarDate) {
            window.selectedCalendarDate = today;
        }
        
        // Calculate calendar dates array (42 days)
        const firstDay = new Date(year, month - 1, 1);
        let startDayOfWeek = firstDay.getDay(); // 0 is Sunday, 1 is Monday, ..., 6 is Saturday
        let startOffset = startDayOfWeek === 0 ? 6 : startDayOfWeek - 1;
        
        const totalDays = new Date(year, month, 0).getDate();
        const prevTotalDays = new Date(year, month - 1, 0).getDate();
        
        const dayObjects = [];
        // Prev month trailing days
        for (let i = startOffset - 1; i >= 0; i--) {
            dayObjects.push({
                date: new Date(year, month - 2, prevTotalDays - i),
                isCurrentMonth: false
            });
        }
        // Current month days
        for (let i = 1; i <= totalDays; i++) {
            dayObjects.push({
                date: new Date(year, month - 1, i),
                isCurrentMonth: true
            });
        }
        // Next month leading days
        const remaining = 42 - dayObjects.length;
        for (let i = 1; i <= remaining; i++) {
            dayObjects.push({
                date: new Date(year, month, i),
                isCurrentMonth: false
            });
        }
        
        // Helper to parse "YYYY/MM/DD" cleanly
        function parseLocalDate(str) {
            if (!str) return null;
            const parts = str.split('/');
            if (parts.length < 3) return null;
            return new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        }
        
        // Build predictions
        const predictions = [];
        const latestStartStr = window.menstrualData?.history?.[0]?.start;
        if (latestStartStr && !isSkeleton) {
            const latestStart = parseLocalDate(latestStartStr);
            const avgCycle = window.menstrualData.avg_cycle || 31;
            const avgLength = window.menstrualData.avg_length || 7;
            
            for (let n = 1; n <= 12; n++) {
                const predStart = new Date(latestStart.getTime());
                predStart.setDate(predStart.getDate() + n * avgCycle);
                
                const predEnd = new Date(predStart.getTime());
                predEnd.setDate(predEnd.getDate() + avgLength - 1);
                
                const ovulationDay = new Date(predStart.getTime());
                ovulationDay.setDate(ovulationDay.getDate() - 14);
                
                const fertileStart = new Date(ovulationDay.getTime());
                fertileStart.setDate(fertileStart.getDate() - 5);
                
                const fertileEnd = new Date(ovulationDay.getTime());
                fertileEnd.setDate(fertileEnd.getDate() + 1);
                
                predictions.push({
                    start: predStart.getTime(),
                    end: predEnd.getTime(),
                    ovulation: ovulationDay.getTime(),
                    fertileStart: fertileStart.getTime(),
                    fertileEnd: fertileEnd.getTime()
                });
            }
        }
        
        dayObjects.forEach(day => {
            const d = day.date;
            const dayTime = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
            
            let isRecorded = false;
            let recordedItem = null;
            if (window.menstrualData?.history && !isSkeleton) {
                for (const item of window.menstrualData.history) {
                    const startDt = parseLocalDate(item.start);
                    if (!startDt) continue;
                    let endDt = parseLocalDate(item.end);
                    if (!endDt || item.end === "進行中") {
                        endDt = new Date();
                    }
                    if (dayTime >= startDt.getTime() && dayTime <= endDt.getTime()) {
                        isRecorded = true;
                        recordedItem = item;
                        break;
                    }
                }
            }
            
            let isPredictedPeriod = false;
            let isOvulation = false;
            let isFertile = false;
            let predictionMatch = null;
            
            if (!isRecorded && !isSkeleton) {
                for (const p of predictions) {
                    if (dayTime >= p.start && dayTime <= p.end) {
                        isPredictedPeriod = true;
                        predictionMatch = p;
                        break;
                    }
                    if (dayTime === p.ovulation) {
                        isOvulation = true;
                        predictionMatch = p;
                        break;
                    }
                    if (dayTime >= p.fertileStart && dayTime <= p.fertileEnd) {
                        isFertile = true;
                        predictionMatch = p;
                        break;
                    }
                }
            }
            
            const cell = document.createElement('div');
            cell.className = 'cal-day-cell';
            if (isSkeleton) {
                cell.classList.add('skeleton');
            }
            if (!day.isCurrentMonth) {
                cell.classList.add('other-month');
            }
            
            // Apply indicator classes or child dots
            if (isRecorded) {
                cell.classList.add('recorded-period');
            } else if (isPredictedPeriod) {
                const dot = document.createElement('span');
                dot.className = 'cal-dot predicted-period';
                cell.appendChild(dot);
            } else if (isOvulation) {
                const dot = document.createElement('span');
                dot.className = 'cal-dot ovulation';
                cell.appendChild(dot);
            } else if (isFertile) {
                const dot = document.createElement('span');
                dot.className = 'cal-dot fertile';
                cell.appendChild(dot);
            }
            
            // Check if today
            if (d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth() && d.getDate() === today.getDate()) {
                cell.classList.add('today');
            }
            
            // Check if selected
            if (!isSkeleton && window.selectedCalendarDate && d.getFullYear() === window.selectedCalendarDate.getFullYear() && d.getMonth() === window.selectedCalendarDate.getMonth() && d.getDate() === window.selectedCalendarDate.getDate()) {
                cell.classList.add('selected');
            }
            
            // Date text
            const textNode = document.createElement('span');
            textNode.innerText = d.getDate();
            cell.appendChild(textNode);
            
            if (!isSkeleton) {
                cell.onclick = () => {
                    const prevSel = grid.querySelector('.cal-day-cell.selected');
                    if (prevSel) prevSel.classList.remove('selected');
                    cell.classList.add('selected');
                    window.selectedCalendarDate = d;
                    window.showCalendarDetail(d);
                };
            }
            
            grid.appendChild(cell);
        });
        
        // Update detail card for the currently selected date
        if (!isSkeleton) {
            window.showCalendarDetail(window.selectedCalendarDate);
        }
    };

    window.showCalendarDetail = (d) => {
        const detailCard = document.getElementById('calendar_detail_card');
        const detailDate = document.getElementById('cal_detail_date');
        const detailCycle = document.getElementById('cal_detail_cycle');
        const detailPregnancy = document.getElementById('cal_detail_pregnancy');
        const detailSymptoms = document.getElementById('cal_detail_symptoms');
        
        if (!d || !detailCard || !detailDate || !detailCycle || !detailPregnancy || !detailSymptoms) return;
        
        // Format Date
        const yearStr = d.getFullYear();
        const monthStr = String(d.getMonth() + 1).padStart(2, '0');
        const dayStr = String(d.getDate()).padStart(2, '0');
        const weekdayChar = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()];
        detailDate.innerText = `${monthStr}/${dayStr} (${weekdayChar})`;
        
        const dayTime = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
        
        // Clean Date parser helper
        function parseLocalDate(str) {
            if (!str) return null;
            const parts = str.split('/');
            if (parts.length < 3) return null;
            return new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        }
        
        // Determine status of target date
        let isRecorded = false;
        let recordedItem = null;
        if (window.menstrualData?.history) {
            for (const item of window.menstrualData.history) {
                const startDt = parseLocalDate(item.start);
                if (!startDt) continue;
                let endDt = parseLocalDate(item.end);
                if (!endDt || item.end === "進行中") {
                    endDt = new Date();
                }
                if (dayTime >= startDt.getTime() && dayTime <= endDt.getTime()) {
                    isRecorded = true;
                    recordedItem = item;
                    break;
                }
            }
        }
        
        // Build predictions array dynamically to evaluate
        const predictions = [];
        const latestStartStr = window.menstrualData?.history?.[0]?.start;
        if (latestStartStr) {
            const latestStart = parseLocalDate(latestStartStr);
            const avgCycle = window.menstrualData.avg_cycle || 31;
            const avgLength = window.menstrualData.avg_length || 7;
            
            for (let n = 1; n <= 12; n++) {
                const predStart = new Date(latestStart.getTime());
                predStart.setDate(predStart.getDate() + n * avgCycle);
                
                const predEnd = new Date(predStart.getTime());
                predEnd.setDate(predEnd.getDate() + avgLength - 1);
                
                const ovulationDay = new Date(predStart.getTime());
                ovulationDay.setDate(ovulationDay.getDate() - 14);
                
                const fertileStart = new Date(ovulationDay.getTime());
                fertileStart.setDate(fertileStart.getDate() - 5);
                
                const fertileEnd = new Date(ovulationDay.getTime());
                fertileEnd.setDate(fertileEnd.getDate() + 1);
                
                predictions.push({
                    start: predStart.getTime(),
                    end: predEnd.getTime(),
                    ovulation: ovulationDay.getTime(),
                    fertileStart: fertileStart.getTime(),
                    fertileEnd: fertileEnd.getTime()
                });
            }
        }
        
        let isPredictedPeriod = false;
        let isOvulation = false;
        let isFertile = false;
        let predictionMatch = null;
        
        if (!isRecorded) {
            for (const p of predictions) {
                if (dayTime >= p.start && dayTime <= p.end) {
                    isPredictedPeriod = true;
                    predictionMatch = p;
                    break;
                }
                if (dayTime === p.ovulation) {
                    isOvulation = true;
                    predictionMatch = p;
                    break;
                }
                if (dayTime >= p.fertileStart && dayTime <= p.fertileEnd) {
                    isFertile = true;
                    predictionMatch = p;
                    break;
                }
            }
        }
        
        // 1. Calculate Cycle Day
        const allStarts = [];
        if (window.menstrualData?.history) {
            window.menstrualData.history.forEach(h => {
                const dt = parseLocalDate(h.start);
                if (dt) allStarts.push(dt.getTime());
            });
        }
        predictions.forEach(p => {
            allStarts.push(p.start);
        });
        allStarts.sort((a, b) => a - b);
        
        let lastStart = null;
        for (let i = allStarts.length - 1; i >= 0; i--) {
            if (allStarts[i] <= dayTime) {
                lastStart = allStarts[i];
                break;
            }
        }
        
        if (lastStart) {
            const cycleDay = Math.round((dayTime - lastStart) / (1000 * 60 * 60 * 24)) + 1;
            detailCycle.innerText = `第 ${cycleDay} 天`;
            detailCycle.style.display = 'inline-block';
        } else {
            detailCycle.innerText = `第 -- 天`;
            detailCycle.style.display = 'none';
        }
        
        // 2. Set phase and pregnancy details
        if (isRecorded) {
            detailPregnancy.innerHTML = `<span style="background: #f43f5e; color: white; padding: 2px 8px; border-radius: 20px; font-weight: 800; font-size: 0.72rem; display: inline-flex; align-items: center; gap: 4px;">🩸 生理期</span> <span style="color: #9f1239; font-weight: 800; font-size: 0.76rem;">❄️ 懷孕機率極低</span>`;
            detailSymptoms.innerHTML = `<b>當日記錄症狀與備忘：</b><br>${(recordedItem && recordedItem.symptoms) ? recordedItem.symptoms : '無特殊症狀與記錄'}`;
            detailCard.style.background = 'rgba(255, 241, 242, 0.8)';
            detailCard.style.borderColor = '#fecdd3';
        } else if (isPredictedPeriod) {
            detailPregnancy.innerHTML = `<span style="background: #fda4af; color: white; padding: 2px 8px; border-radius: 20px; font-weight: 800; font-size: 0.72rem; display: inline-flex; align-items: center; gap: 4px;">🌸 預測生理期</span> <span style="color: #be123c; font-weight: 800; font-size: 0.76rem;">❄️ 懷孕機率極低</span>`;
            detailSymptoms.innerHTML = `<b>預估生理期：</b><br>預測當天將進入生理期，請提早準備個人用品與溫熱飲品舒緩。`;
            detailCard.style.background = 'rgba(255, 241, 242, 0.5)';
            detailCard.style.borderColor = '#ffe4e6';
        } else if (isOvulation) {
            detailPregnancy.innerHTML = `<span style="background: #a855f7; color: white; padding: 2px 8px; border-radius: 20px; font-weight: 800; font-size: 0.72rem; display: inline-flex; align-items: center; gap: 4px;">✨ 預測排卵日</span> <span style="color: #6b21a8; font-weight: 800; font-size: 0.76rem;">🔥 懷孕機率極高</span>`;
            detailSymptoms.innerHTML = `<b>預估排卵當天：</b><br>此為預估排卵黃金期最高峰，如果有備孕計畫，今日是受孕率最高的一天！`;
            detailCard.style.background = 'rgba(250, 245, 255, 0.8)';
            detailCard.style.borderColor = '#e9d5ff';
        } else if (isFertile) {
            detailPregnancy.innerHTML = `<span style="background: #fbbf24; color: white; padding: 2px 8px; border-radius: 20px; font-weight: 800; font-size: 0.72rem; display: inline-flex; align-items: center; gap: 4px;">🍑 易孕期</span> <span style="color: #b45309; font-weight: 800; font-size: 0.76rem;">🔥 懷孕機率高</span>`;
            detailSymptoms.innerHTML = `<b>黃金受孕期：</b><br>處於易受孕區間，如有避孕考量，請務必做好防護措施。`;
            detailCard.style.background = 'rgba(255, 247, 237, 0.8)';
            detailCard.style.borderColor = '#fed7aa';
        } else {
            // Safely check if luteal or follicular phase
            let isLuteal = false;
            if (predictionMatch) {
                if (dayTime > predictionMatch.ovulation + (1 * 24 * 60 * 60 * 1000) && dayTime < predictionMatch.start) {
                    isLuteal = true;
                }
            }
            if (isLuteal) {
                detailPregnancy.innerHTML = `<span style="background: #c084fc; color: white; padding: 2px 8px; border-radius: 20px; font-weight: 800; font-size: 0.72rem; display: inline-flex; align-items: center; gap: 4px;">💜 黃體期 (經前期)</span> <span style="color: #6b21a8; font-weight: 800; font-size: 0.76rem;">🍀 懷孕機率低</span>`;
                detailSymptoms.innerHTML = `<b>經前調養期：</b><br>此階段可能伴隨水腫、疲憊 or 情緒敏感，建議清淡飲食，並做些放鬆的伸展運動。`;
                detailCard.style.background = 'rgba(250, 245, 255, 0.5)';
                detailCard.style.borderColor = '#f3e8ff';
            } else {
                detailPregnancy.innerHTML = `<span style="background: #10b981; color: white; padding: 2px 8px; border-radius: 20px; font-weight: 800; font-size: 0.72rem; display: inline-flex; align-items: center; gap: 4px;">🟢 安全期 (濾泡期)</span> <span style="color: #047857; font-weight: 800; font-size: 0.76rem;">🍀 懷孕機率低</span>`;
                detailSymptoms.innerHTML = `<b>濾泡代謝期：</b><br>荷爾蒙狀態極佳，思緒敏捷、體能充沛，適合高強度工作、學習與運動衝刺！`;
                detailCard.style.background = 'rgba(240, 253, 244, 0.8)';
                detailCard.style.borderColor = '#bbf7d0';
            }
        }
    };

    // 初始化訂閱與試用倒數計時器（在所有函式宣告完成後呼叫，以防未定義錯誤）
    if (typeof window.initSubscriptionCountdown === 'function') window.initSubscriptionCountdown();
    if (typeof window.initTrialCountdown === 'function') window.initTrialCountdown();
});
