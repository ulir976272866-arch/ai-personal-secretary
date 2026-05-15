document.addEventListener('DOMContentLoaded', () => {
    window.editingWishId = null;
    window.editingTodoId = null;
    window.editingMemoId = null;
    window.editingEventId = null;

    const chatHistory = document.getElementById('chat-history');
    const userInput = document.getElementById('userInput');
    const sendBtn = document.getElementById('sendBtn');

    // --- 核心功能：每次打開自動載入今日行程卡片 ---
    async function loadTodaySchedule() {
        // 如果已經有內容（例如從背景回來），就不再重複載入或清空
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

    // 從背景恢復時不再自動重新載入，保留使用者原本的查詢畫面
    /*
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            loadTodaySchedule();
        }
    });
    */

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
            document.getElementById('manual_date').valueAsDate = new Date();
            document.getElementById('manual_all_day').checked = false;
            document.getElementById('time_input_wrapper').style.display = 'flex';
            const submitBtn = document.getElementById('submitSchedule');
            if (submitBtn) {
                submitBtn.innerText = '確認加入日曆';
                submitBtn.style.background = '';
            }
        }
        document.getElementById(id).classList.add('show');
        if (id === 'wishlistModal') window.loadWishes();
        if (id === 'todoModal') window.loadTodos();
        if (id === 'memoModal') window.loadMemos();
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
    function initAutocomplete() {
        const input = document.getElementById('manual_location');
        if (!input || typeof google === 'undefined') return;

        const autocomplete = new google.maps.places.Autocomplete(input, {
            types: ['geocode', 'establishment'],
            componentRestrictions: { country: 'tw' } // 限制在台灣
        });

        autocomplete.addListener('place_changed', () => {
            const place = autocomplete.getPlace();
            if (place.formatted_address) {
                input.value = place.formatted_address;
            }
        });
    }

    // 確保 Google Maps 載入後執行
    if (typeof google !== 'undefined') {
        initAutocomplete();
    } else {
        window.initMap = initAutocomplete; // 供 API Callback 使用
    }

    // --- 載入資料並顯示 ---
    // --- 待辦功能 (Keep 風格) ---
    window.addTodoTag = (tag) => {
        const input = document.getElementById('todo_title');
        input.value = tag + ' ' + input.value;
        input.focus();
    };

    window.loadTodos = async () => {
        const list = document.getElementById('todo_list');
        if (!list) return;

        // 顯示載入中
        list.innerHTML = `
            <div style="text-align: center; padding: 30px; color: #94a3b8;">
                <div class="loading-spinner" style="margin-bottom: 10px;">⌛</div>
                正在讀取待辦清單...
            </div>
        `;

        try {
            const res = await fetch('/api/todo');
            const data = await res.json();
            
            if (!Array.isArray(data)) {
                throw new Error(data.message || '資料格式錯誤');
            }

            // 僅顯示未完成的
            const activeTodos = data.filter(i => i.狀態 === '未完成');
            
            if (activeTodos.length === 0) {
                list.innerHTML = '<div style="color: #94a3b8; text-align: center; padding: 40px 20px;">任務全數達成！✨<br><small style="opacity: 0.7;">今天又是充實的一天呢</small></div>';
                return;
            }

            // 排序邏輯：1. 重要且緊急優先 2. 建立時間早優先 (原始順序)
            const priorityMap = {
                '重要且緊急': 0,
                '重要但不緊急': 1,
                '不重要但緊急': 2,
                '不重要且不緊急': 3
            };

            const sortedTodos = activeTodos.sort((a, b) => {
                const pA = priorityMap[a['優先級']] !== undefined ? priorityMap[a['優先級']] : 4;
                const pB = priorityMap[b['優先級']] !== undefined ? priorityMap[b['優先級']] : 4;
                if (pA !== pB) return pA - pB;
                return 0; // 維持原始順序 (最早在上方)
            });

            list.innerHTML = sortedTodos.map((item, idx) => {
                const safeID = item['唯一 ID'] || `legacy_${idx}`;
                const priority = item['優先級'] || '不重要且不緊急';
                
                // 優先級顏色映射
                let accentClass = 'accent-green';
                if (priority.includes('重要且緊急')) accentClass = 'accent-red';
                else if (priority.includes('重要但不緊急')) accentClass = 'accent-yellow';
                else if (priority.includes('不重要但緊急')) accentClass = 'accent-orange';

                return `
                    <div id="todo_item_${safeID}" style="display: flex; align-items: center; gap: 12px; padding: 15px 15px 15px 22px; border-bottom: 1px solid #f8fafc; transition: all 0.3s; background: white; margin-bottom: 10px; border-radius: 16px; box-shadow: 0 4px 6px rgba(0,0,0,0.02); position: relative; overflow: hidden;">
                        <div class="todo-accent ${accentClass}"></div>
                        
                        <div style="position: relative; width: 24px; height: 24px; flex-shrink: 0;">
                            <input type="checkbox" 
                                   style="width: 24px; height: 24px; cursor: pointer; opacity: 0; position: absolute; z-index: 2;"
                                   onchange="window.prepareTodo('${safeID}', this.checked)">
                            <div class="custom-checkbox" style="width: 24px; height: 24px; border: 2.5px solid #cbd5e1; border-radius: 8px; position: absolute; top: 0; left: 0; transition: all 0.2s;"></div>
                        </div>
                        
                        <div style="flex: 1;">
                            <div id="todo_text_${safeID}" style="color: #1e293b; font-weight: 700; font-size: 1.05rem; line-height: 1.4; margin-bottom: 4px;">
                                ${item['事項/內容']}
                            </div>
                            <div style="display: flex; gap: 8px; align-items: center;">
                                <span style="font-size: 0.65rem; color: #94a3b8; background: #f8fafc; padding: 2px 6px; border-radius: 4px; font-weight: 600;">
                                    ${item.分類}
                                </span>
                                <span style="font-size: 0.65rem; font-weight: 800; color: #64748b;">
                                    • ${priority}
                                </span>
                            </div>
                        </div>
                        <div id="todo_action_${safeID}" style="display: flex; gap: 10px; align-items: center;">
                            <button onclick="window.deleteTodo('${safeID}', '${item['事項/內容'].replace(/'/g, "\\'")}')" 
                                    style="background: none; border: none; color: #cbd5e1; cursor: pointer; font-size: 1.1rem; padding: 4px; transition: all 0.2s;">
                                ✕
                            </button>
                            <button onclick="window.editTodo('${safeID}', '${item['事項/內容'].replace(/'/g, "\\'")}', '${item.分類}')" 
                                    style="background: none; color: #3b82f6; border: none; padding: 4px; font-size: 0.85rem; cursor: pointer; font-weight: 600; transition: all 0.2s;">
                                編輯
                            </button>
                        </div>
                    </div>
                `;
            }).join('');
        } catch (e) {
            console.error('載入待辦清單失敗:', e);
            list.innerHTML = `<div style="color: #ef4444; text-align: center; padding: 20px;">載入失敗：${e.message} 🔌</div>`;
        }
    };

    window.deleteTodo = async (id, title) => {
        if (!confirm(`確定要刪除「${title}」嗎？`)) return;
        
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
                            <div style="display: flex; gap: 12px; align-items: center;">
                                <button onclick="window.deleteWish('${itemID}', '${item.商品名稱.replace(/'/g, "\\'")}')" 
                                        style="background: none; border: none; color: inherit; cursor: pointer; font-size: 1.1rem; padding: 4px; transition: all 0.2s; opacity: 0.4;">
                                    ✕
                                </button>
                                <button onclick="window.editWish('${itemID}', '${item.商品名稱.replace(/'/g, "\\'")}', '${item.預估價格}', '', '${item.分類}')" 
                                        style="background: none; color: inherit; border: none; padding: 0; font-size: 0.85rem; cursor: pointer; font-weight: 600; opacity: 0.8;">
                                    編輯
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
        if (!content || !mood || !weather) return;
 
        const res = await fetch('/api/memo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content, mood, weather })
        });
        const data = await res.json();
        if (data.status === 'success') {
            document.getElementById('memo_content').value = '';
            document.getElementById('memo_mood').value = '';
            document.getElementById('memo_weather').value = '';
            window.checkMemoFields(); // 重置按鈕狀態
            window.loadMemos(); // 儲存後立即刷新列表
            // window.closeModal('memoModal'); // 不關閉彈窗，讓使用者看到記錄成功
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
        const priority = document.getElementById('todo_priority').value || '不重要且不緊急';
        if (!title) return;

        // 簡單判斷分類
        let category = '任務';
        if (title.includes('🎬')) category = '影視';
        if (title.includes('🍕')) category = '美食';
        if (title.includes('📖')) category = '學習';
        if (title.includes('🏠')) category = '生活';
        if (title.includes('✨')) category = '還願';
        if (title.includes('📍')) category = '旅遊';

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
            
            // 恢復按鈕 UI
            const submitBtn = document.querySelector('#todoModal .modal-content button[onclick="saveTodo()"]');
            if (submitBtn) {
                submitBtn.innerHTML = '＋';
                submitBtn.style.background = '#3b82f6';
                submitBtn.style.width = '40px';
            }
            
            window.loadTodos();
            
            // 重置優先級選擇到預設
            const defaultOpt = document.querySelector('.priority-opt.green');
            if (defaultOpt) window.selectPriority(defaultOpt, '不重要且不緊急');
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
            
            // 恢復按鈕 UI
            const submitBtn = document.querySelector('#wishlistModal .modal-content button[onclick="saveWish()"]');
            if (submitBtn) {
                submitBtn.innerHTML = '＋';
                submitBtn.style.background = '#f97316';
                submitBtn.style.width = '45px';
            }
            
            window.loadWishes();
        }
    };

    window.editTodo = (id, title, category) => {
        const input = document.getElementById('todo_title');
        input.value = title;
        window.editingTodoId = id;
        input.focus();
        
        // 修改按鈕 UI
        const submitBtn = document.querySelector('#todoModal .modal-content button[onclick="saveTodo()"]');
        if (submitBtn) {
            submitBtn.innerHTML = '💾 儲存';
            submitBtn.style.background = '#10b981';
            submitBtn.style.width = '80px'; // 稍微加寬以容納文字
        }

        // 視覺提醒正在編輯
        input.style.borderBottom = '2px solid #3b82f6';
        setTimeout(() => input.style.borderBottom = 'none', 1500);
    };

    document.querySelectorAll('.close-modal').forEach(btn => btn.onclick = () => window.closeModal());

    // --- 輔助函式 ---
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

    function renderScheduleCard(events, dateStr) {
        const card = document.createElement('div');
        card.className = 'schedule-card';
        
        let headerHtml = `
            <div class="schedule-header">
                <h3>🗓️ ${dateStr} 行程</h3>
            </div>
        `;
        
        if (events.length === 0) {
            card.innerHTML = headerHtml + '<p style="padding: 10px; color: #64748b;">今天沒有安排行程喔！</p>';
            chatHistory.appendChild(card);
            scrollToBottom();
            return;
        }

        let listHtml = '<ul class="schedule-list">';
        events.forEach(event => {
            let locationHtml = '';
            if (event.location) {
                const isUrl = event.location.startsWith('http');
                let mapUrl = event.location;
                
                if (!isUrl) {
                    const encodedLoc = encodeURIComponent(event.location);
                    const ua = navigator.userAgent;
                    
                    if (/iPhone|iPad|iPod/i.test(ua)) {
                        // iOS 直接喚起 App
                        mapUrl = `comgooglemaps://?q=${encodedLoc}`;
                    } else if (/Android/i.test(ua)) {
                        // Android 直接喚起 App
                        mapUrl = `geo:0,0?q=${encodedLoc}`;
                    } else {
                        // 電腦端維持網頁版
                        mapUrl = `https://www.google.com/maps/search/?api=1&query=${encodedLoc}`;
                    }
                }
                locationHtml = `<a href="${mapUrl}" class="location-link">📍 ${event.location}</a>`;
            }

            listHtml += `
                <li id="event_li_${event.id}" class="schedule-item ${event.completed ? 'completed' : ''}" data-id="${event.id}">
                        <span class="event-title">${event.display_title}</span>
                        <div class="event-meta">
                            <span class="event-time">${event.time}</span>
                            ${locationHtml}
                            <span class="edit-event-link" onclick="window.editEvent('${event.id}', '${event.title.replace(/'/g, "\\'")}', '${event.location.replace(/'/g, "\\'")}', '${event.start_time}', ${event.is_all_day})" style="margin-left: 10px; text-decoration: underline; cursor: pointer; color: #3b82f6; font-size: 0.75rem;">編輯</span>
                            <span class="delete-event-link" onclick="window.deleteEvent('${event.id}', '${event.title.replace(/'/g, "\\'")}')" style="margin-left: 10px; text-decoration: underline; cursor: pointer; color: #94a3b8; font-size: 0.75rem;">刪除</span>
                        </div>
                    </div>
                     <div class="done-toggle ${event.completed ? 'completed' : ''}">
                         ${event.completed ? '✓' : ''}
                     </div>
                 </li>
             `;
         });
 
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
        if (!confirm(`確定要從 Google 日曆刪除「${title}」嗎？`)) return;

        const res = await fetch('/api/delete_event', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ event_id: eventId })
        });
        
        const data = await res.json();
        if (data.status === 'success') {
            const allItems = document.querySelectorAll(`[data-id="${eventId}"]`);
            allItems.forEach(li => {
                li.style.opacity = '0';
                li.style.transform = 'translateX(20px)';
                setTimeout(() => li.remove(), 300);
            });
            appendMessage(`已刪除行程：${title}`);
        } else {
            alert("刪除失敗：" + data.message);
        }
    };
        listHtml += '</ul>';
        
        card.innerHTML = headerHtml + listHtml;
        chatHistory.appendChild(card);
        
        // 綁定完成切換事件
        card.querySelectorAll('.schedule-item').forEach(item => {
            const toggle = item.querySelector('.done-toggle');
            toggle.onclick = async (e) => {
                e.stopPropagation();
                const eventId = item.getAttribute('data-id');
                const response = await fetch('/api/toggle_completion', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ event_id: eventId })
                });
                const result = await response.json();
                if (result.status === 'success') {
                    item.classList.toggle('completed');
                    toggle.classList.toggle('completed');
                    toggle.innerText = result.is_completed ? '✓' : '';
                }
            };
        });
        
        scrollToBottom();
    }

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

    // --- 語音辨識 ---
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.lang = 'zh-TW';
        recognition.continuous = false;
        recognition.interimResults = false;

        recognition.onstart = () => {
            voiceBtn.classList.add('listening');
            userInput.placeholder = "聆聽中...";
        };

        recognition.onend = () => {
            voiceBtn.classList.remove('listening');
            userInput.placeholder = "輸入行程或指令...";
        };

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            userInput.value = transcript;
            window.handleSend();
        };

        voiceBtn.onclick = () => {
            recognition.start();
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

    scheduleModal.onclick = (e) => { if (e.target === scheduleModal) window.closeModal('scheduleModal'); };
    expenseModal.onclick = (e) => { if (e.target === expenseModal) window.closeModal('expenseModal'); };
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
});
