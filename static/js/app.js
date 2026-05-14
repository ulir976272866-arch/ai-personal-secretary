document.addEventListener('DOMContentLoaded', () => {
    window.editingWishId = null;
    window.editingTodoId = null;
    window.editingMemoId = null;

    const chatHistory = document.getElementById('chat-history');
    const userInput = document.getElementById('userInput');
    const sendBtn = document.getElementById('sendBtn');

    // --- 核心功能：每次打開自動載入今日行程卡片 ---
    async function loadTodaySchedule() {
        // 清空所有舊紀錄
        chatHistory.innerHTML = '';

        try {
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: '今日行程' })
            });
            const data = await res.json();
            if (data.status === 'success' && data.type === 'query_schedule') {
                renderScheduleCard(data.data, data.date_str);
            } else {
                appendMessage(data.message || '您好！今天沒有行程安排。');
            }
        } catch (e) {
            console.error('載入今日行程失敗:', e);
        }
    }

    // 啟動時載入
    loadTodaySchedule();

    // 從背景恢復時重新載入
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            loadTodaySchedule();
        }
    });

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
        document.getElementById(id).classList.add('show');
        if (id === 'wishlistModal') window.loadWishes();
        if (id === 'todoModal') window.loadTodos();
        if (id === 'memoModal') window.loadMemos();
    };

    window.closeModal = (id) => {
        if (id) {
            document.getElementById(id).classList.remove('show');
        } else {
            document.querySelectorAll('.modal-backdrop').forEach(m => m.classList.remove('show'));
        }
    };

    // --- 載入資料並顯示 ---
    // --- 待辦功能 (Keep 風格) ---
    window.addTodoTag = (tag) => {
        const input = document.getElementById('todo_title');
        input.value = tag + ' ' + input.value;
        input.focus();
    };

    window.loadTodos = async () => {
        const res = await fetch('/api/todo');
        const data = await res.json();
        const list = document.getElementById('todo_list');
        if (!list) return;

        // 僅顯示未完成的
        list.innerHTML = data.filter(i => i.狀態 === '未完成').reverse().map((item, idx) => {
            const safeID = item.唯一ID || `legacy_${idx}`;
            return `
                <div id="todo_item_${safeID}" style="display: flex; align-items: center; gap: 10px; padding: 12px; border-bottom: 1px solid #f8fafc; transition: all 0.3s;">
                    <input type="checkbox" 
                           style="width: 18px; height: 18px; cursor: pointer;"
                           onchange="window.prepareTodo('${safeID}', this.checked)">
                    
                    <span id="todo_text_${safeID}" style="flex: 1; color: #1e293b; font-weight: 500;">
                        ${item['事項/內容']}
                    </span>
                    
                    <div id="todo_action_${safeID}" style="display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 0.7rem; color: #64748b; background: #f1f5f9; padding: 4px 8px; border-radius: 6px;">
                            ${item.分類}
                        </span>
                        <button onclick="window.editTodo('${safeID}', '${item['事項/內容'].replace(/'/g, "\\'")}', '${item.分類}')" 
                                style="background: none; border: none; color: #cbd5e1; cursor: pointer; font-size: 0.8rem; padding: 0 4px; transition: all 0.2s;"
                                onmouseover="this.style.color='#3b82f6'"
                                onmouseout="this.style.color='#cbd5e1'">
                            編輯
                        </button>
                        <button onclick="window.deleteTodo('${safeID}', '${item['事項/內容'].replace(/'/g, "\\'")}')" 
                                style="background: none; border: none; color: #cbd5e1; cursor: pointer; font-size: 0.9rem; padding: 0 4px; transition: all 0.2s;"
                                onmouseover="this.style.color='#ef4444'"
                                onmouseout="this.style.color='#cbd5e1'">
                            ✕
                        </button>
                    </div>
                </div>
            `;
        }).join('') || '<div style="color: #94a3b8; text-align: center; padding: 20px;">任務全數達成！✨</div>';
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
    window.addWishTag = (tag) => {
        const input = document.getElementById('wish_name');
        input.value = tag + ' ' + input.value;
        input.focus();
    };

    window.loadWishes = async () => {
        const res = await fetch('/api/wishlist');
        const data = await res.json();
        const list = document.getElementById('wish_list');
        const summary = document.getElementById('wish_summary');
        if (!list) return;

        let totalBudget = 0;
        const activeWishes = data.filter(i => i.狀態 === '想買');

        list.innerHTML = activeWishes.reverse().map(item => {
            const price = parseInt(item.預估價格) || 0;
            totalBudget += price;
            return `
                <div style="background: #fff; border: 1px solid #f1f5f9; padding: 15px; border-radius: 12px; margin-bottom: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 8px;">
                        <div style="font-weight: 700; color: #1e293b; font-size: 1rem;">${item.商品名稱}</div>
                        <div style="color: #f97316; font-weight: 800; font-size: 1.1rem;">$${item.預估價格}</div>
                    </div>
                    <div style="font-size: 0.85rem; color: #64748b; line-height: 1.4; margin-bottom: 10px;">${item['備註/連結'] || ''}</div>
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 0.7rem; color: #cbd5e1;">${item.建立日期} (${item.分類})</span>
                        <div style="display: flex; gap: 12px; align-items: center;">
                            <button onclick="window.editWish('${item['唯一 ID']}', '${item.商品名稱.replace(/'/g, "\\'")}', '${item.預估價格}', '${(item['備註/連結'] || '').replace(/'/g, "\\'")}', '${item.分類}')" 
                                    style="background: none; color: #94a3b8; border: none; padding: 0; font-size: 0.8rem; cursor: pointer; text-decoration: underline; transition: all 0.2s;"
                                    onmouseover="this.style.color='#3b82f6'"
                                    onmouseout="this.style.color='#94a3b8'">
                                編輯
                            </button>
                            <button onclick="window.deleteWish('${item['唯一 ID']}', '${item.商品名稱.replace(/'/g, "\\'")}')" 
                                    style="background: none; color: #94a3b8; border: none; padding: 0; font-size: 0.8rem; cursor: pointer; text-decoration: underline; transition: all 0.2s;"
                                    onmouseover="this.style.color='#ef4444'"
                                    onmouseout="this.style.color='#94a3b8'">
                                刪除
                            </button>
                            <button onclick="window.fulfillWish('${item['唯一 ID']}', '${item.商品名稱}', '${item.預估價格}')" 
                                    style="background: #f97316; color: white; border: none; padding: 5px 12px; border-radius: 20px; font-size: 0.8rem; cursor: pointer; font-weight: bold; transition: all 0.2s;">
                                圓夢 ✨
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }).join('') || '<div style="color: #94a3b8; text-align: center; padding: 20px;">目前沒有正在進行的願望 ✨</div>';
        
        if (summary) {
            summary.innerHTML = activeWishes.length > 0 ? `預算總計：$${totalBudget.toLocaleString()}` : '';
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

    window.saveTodo = async () => {
        const input = document.getElementById('todo_title');
        const title = input.value.trim();
        if (!title) return;

        // 簡單判斷分類
        let category = '任務';
        if (title.includes('🎬')) category = '影視';
        if (title.includes('🍕')) category = '美食';
        if (title.includes('📖')) category = '學習';
        if (title.includes('🏠')) category = '生活';
        if (title.includes('✨')) category = '還願';

        const res = await fetch('/api/todo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, category })
        });
        if ((await res.json()).status === 'success') {
            input.value = '';
            window.loadTodos();
        }
    };

    window.editWish = (id, name, price, note, category) => {
        document.getElementById('wish_name').value = name;
        document.getElementById('wish_price').value = price;
        document.getElementById('wish_note').value = note;
        window.editingWishId = id;
        
        // 修改按鈕 UI
        const submitBtn = document.querySelector('.modal-content button[onclick="saveWish()"]');
        if (submitBtn) {
            submitBtn.innerHTML = '💾 儲存修改';
            submitBtn.style.background = '#10b981';
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

        let category = '靈感';
        if (name.includes('💎')) category = '必買';
        if (name.includes('🎁')) category = '送禮';
        if (name.includes('🏠')) category = '家用';
        if (name.includes('💡')) category = '靈感';

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
            const submitBtn = document.querySelector('.modal-content button[onclick="saveWish()"]');
            if (submitBtn) {
                submitBtn.innerHTML = '＋';
                submitBtn.style.background = '#f97316';
            }
            
            window.loadWishes();
        }
    };

    window.editTodo = (id, title, category) => {
        const input = document.getElementById('todo_title');
        input.value = title;
        window.editingTodoId = id;
        input.focus();
        
        // 視覺提醒正在編輯
        input.style.borderBottom = '2px solid #3b82f6';
        setTimeout(() => input.style.borderBottom = 'none', 1500);
    };

    window.saveTodo = async () => {
        const input = document.getElementById('todo_title');
        const title = input.value.trim();
        if (!title) return;

        let category = '任務';
        if (title.includes('🎬')) category = '影視';
        if (title.includes('🍕')) category = '美食';
        if (title.includes('📖')) category = '學習';
        if (title.includes('🏠')) category = '生活';
        if (title.includes('✨')) category = '還願';

        const endpoint = window.editingTodoId ? '/api/todo/update' : '/api/todo';
        const payload = { title, category };
        if (window.editingTodoId) payload.id = window.editingTodoId;

        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if ((await res.json()).status === 'success') {
            input.value = '';
            window.editingTodoId = null;
            window.loadTodos();
        }
    };

    const scheduleModal = document.getElementById('scheduleModal');
    const expenseModal = document.getElementById('expenseModal');






    
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
                const mapUrl = isUrl ? event.location : `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(event.location)}`;
                locationHtml = `<a href="${mapUrl}" target="_blank" class="location-link">📍 ${event.location}</a>`;
            }

            listHtml += `
                <li id="event_li_${event.id}" class="schedule-item ${event.completed ? 'completed' : ''}" data-id="${event.id}">
                    <div class="event-info">
                        <span class="event-title">${event.title}</span>
                        <div class="event-meta">
                            <span class="event-time">${event.time}</span>
                            ${locationHtml}
                            <span class="delete-event-link" onclick="window.deleteEvent('${event.id}', '${event.title}')" style="margin-left: 10px; text-decoration: underline; cursor: pointer; color: #94a3b8; font-size: 0.75rem;">刪除</span>
                        </div>
                    </div>
                    <div class="done-toggle ${event.completed ? 'completed' : ''}">
                        ${event.completed ? '✓' : ''}
                    </div>
                </li>
            `;
        });

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

        // 如果不是全天行程，則根據 AM/PM 轉換時間
        if (!isAllDay) {
            let hour24 = parseInt(h);
            if (ampm === 'PM' && hour24 < 12) hour24 += 12;
            if (ampm === 'AM' && hour24 === 12) hour24 = 0;
            
            const hourStr = String(hour24).padStart(2, '0');
            const minuteStr = String(m).padStart(2, '0');
            
            startTime = `${date}T${hourStr}:${minuteStr}:00`;
            finalIsAllDay = false;
        }
        
        window.closeModal('scheduleModal');
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
