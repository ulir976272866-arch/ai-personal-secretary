document.addEventListener('DOMContentLoaded', () => {
    const chatHistory = document.getElementById('chat-history');
    const userInput = document.getElementById('userInput');
    const sendBtn = document.getElementById('sendBtn');

    // --- 核心功能：抓取晨間簡報 ---
    async function fetchMorningBriefing() {
        try {
            const res = await fetch('/api/morning_briefing', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'success') {
                appendMessage(data.message);
            }
        } catch (e) {
            console.error('Briefing fetch failed:', e);
        }
    }

    // 啟動晨間簡報
    fetchMorningBriefing();

    // 處理手機背景待機恢復：當使用者回到 App 時自動更新資料
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            console.log('App resumed, refreshing data...');
            fetchMorningBriefing();
        }
    });

    // 快捷按鈕
    const queryTodayBtn = document.getElementById('queryTodayBtn');
    const queryWeekBtn = document.getElementById('queryWeekBtn');
    const queryExpenseBtn = document.getElementById('queryExpenseBtn');
    const openSheetBtn = document.getElementById('openSheetBtn');
    const voiceBtn = document.getElementById('voiceBtn');
    const clearBtn = document.getElementById('clearBtn');

    // --- 輔助函式 ---
    function appendMessage(text, isUser = false) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${isUser ? 'user-message' : 'ai-message'}`;
        if (isUser) {
            msgDiv.innerText = text;
        } else {
            msgDiv.innerHTML = text.replace(/\n/g, '<br>');
        }
        chatHistory.appendChild(msgDiv);
        chatHistory.scrollTop = chatHistory.scrollHeight;
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
            chatHistory.scrollTop = chatHistory.scrollHeight;
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
                <li class="schedule-item ${event.completed ? 'completed' : ''}" data-id="${event.id}">
                    <div class="event-info">
                        <span class="event-title">${event.title}</span>
                        <div class="event-meta">
                            <span class="event-time">${event.time}</span>
                            ${locationHtml}
                        </div>
                    </div>
                    <div class="done-toggle ${event.completed ? 'completed' : ''}">
                        ${event.completed ? '✓' : ''}
                    </div>
                </li>
            `;
        });
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
        
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    // --- 計算機邏輯 ---
    const expenseAmountInput = document.getElementById('expense_amount');
    window.appendCalc = (val) => {
        if (expenseAmountInput.value === '0' && !isNaN(val)) {
            expenseAmountInput.value = val;
        } else {
            expenseAmountInput.value += val;
        }
    };
    window.clearCalc = () => {
        expenseAmountInput.value = '0';
    };
    window.calculateResult = () => {
        try {
            // 安全地評估數學運算式
            const result = eval(expenseAmountInput.value.replace('×', '*').replace('÷', '/'));
            expenseAmountInput.value = Math.round(result);
        } catch (e) {
            alert('計算錯誤');
            expenseAmountInput.value = '0';
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
            // 語音輸入後自動發送
            handleSend();
        };

        voiceBtn.onclick = () => {
            recognition.start();
        };
    } else {
        voiceBtn.style.display = 'none';
    }

    async function handleSend(text = null) {
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
                appendMessage("❌ 錯誤：" + data.message);
            }
        } catch (error) {
            appendMessage("❌ 伺服器連線失敗");
        }
    }

    // --- 事件監聽 ---
    sendBtn.onclick = () => handleSend();
    userInput.onkeypress = (e) => { if (e.key === 'Enter') handleSend(); };
    
    queryTodayBtn.onclick = () => handleSend("今日行程");
    queryWeekBtn.onclick = () => handleSend("這週行程");
    queryExpenseBtn.onclick = () => handleSend("本月合計");
    openSheetBtn.onclick = () => handleSend("開啟記帳表單");

    // --- Modal 邏輯 ---
    const scheduleModal = document.getElementById('scheduleModal');
    const expenseModal = document.getElementById('expenseModal');
    const manualScheduleBtn = document.getElementById('manualScheduleBtn');
    const manualExpenseBtn = document.getElementById('manualExpenseBtn');
    const closeButtons = document.querySelectorAll('.close-modal');
    const isAllDayCheckbox = document.getElementById('is_all_day');
    const timeInputGroup = document.getElementById('timeInputGroup');

    document.getElementById('manual_date').valueAsDate = new Date();
    isAllDayCheckbox.onchange = () => {
        timeInputGroup.style.display = isAllDayCheckbox.checked ? 'none' : 'block';
    };

    function showModal(modal) { modal.classList.add('show'); }
    function closeModal() { 
        scheduleModal.classList.remove('show'); 
        expenseModal.classList.remove('show'); 
    }

    manualScheduleBtn.onclick = () => {
        isAllDayCheckbox.checked = false;
        timeInputGroup.style.display = 'block';
        showModal(scheduleModal);
    };
    manualExpenseBtn.onclick = () => showModal(expenseModal);
    closeButtons.forEach(btn => btn.onclick = closeModal);

    scheduleModal.onclick = (e) => { if (e.target === scheduleModal) closeModal(); };
    expenseModal.onclick = (e) => { if (e.target === expenseModal) closeModal(); };
    document.querySelectorAll('.modal-content').forEach(c => c.onclick = (e) => e.stopPropagation());

    // 手動送出
    document.getElementById('submitSchedule').onclick = async () => {
        const title = document.getElementById('manual_title').value;
        const date = document.getElementById('manual_date').value;
        const time = document.getElementById('manual_time').value;
        const location = document.getElementById('manual_location').value;
        const isAllDay = isAllDayCheckbox.checked;

        if (!title || !date || (!isAllDay && !time)) {
            alert('請填寫完整資訊！');
            return;
        }

        closeModal();
        appendMessage(`新增行程：${title}`, true);
        const res = await fetch('/api/manual_action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                type: 'calendar', title, start_time: isAllDay ? date : `${date}T${time}:00`, location, is_all_day: isAllDay
            })
        });
        const data = await res.json();
        appendMessage(data.message);
    };

    document.getElementById('submitExpense').onclick = async () => {
        // 先自動計算結果，以防使用者沒按等號
        calculateResult();
        
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
});
