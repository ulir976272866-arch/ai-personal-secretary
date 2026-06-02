import re

path = "static/js/app.js"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# We know window.renderChatBillSplits = (dataList) => { ... } ends when window.loadChatHistory or similar starts.
# But we can also just split by "window.renderChatBillSplits = (dataList) => {"

new_func = """    window.renderChatBillSplits = (dataList) => {
        const cardDiv = document.createElement('div');
        cardDiv.className = 'chat-split-card message ai-message';
        cardDiv.style.background = 'linear-gradient(135deg, rgba(26, 188, 156, 0.08) 0%, rgba(26, 188, 156, 0.03) 100%)';
        cardDiv.style.border = '1px solid rgba(26, 188, 156, 0.2)';
        cardDiv.style.borderRadius = '16px';
        cardDiv.style.padding = '12px';
        cardDiv.style.margin = '8px 0';
        cardDiv.style.boxShadow = '0 8px 32px 0 rgba(31, 38, 135, 0.07)';
        cardDiv.style.backdropFilter = 'blur(10px)';
        cardDiv.style.webkitBackdropFilter = 'blur(10px)';
        
        let activeHtml = '';
        let settledHtml = '';
        
        dataList.forEach(item => {
            const isSettled = item.status === '已結清' || item.status === '已收回';
            
            let detailsList = [];
            if (item.breakdown) {
                let owesCount = 0;
                for (const [name, info] of Object.entries(item.breakdown)) {
                    if (name.startsWith('_')) continue;
                    const owed = info.owed || 0;
                    const received = info.received || 0;
                    const balance = owed - received;
                    
                    if (balance > 0) {
                        owesCount++;
                        detailsList.push(`
                            <div class="debt-row" style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px; font-size: 0.8rem; color: var(--text-color);">
                                <span>👥 ${name}：$${balance} [ ⏳ 待收 ]</span>
                                <button class="repay-pill-btn" data-id="${item.id}" data-friend="${name}" style="background: rgba(244, 63, 94, 0.1); border: 1.5px solid rgba(244, 63, 94, 0.3); color: #f43f5e; padding: 4px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 700; cursor: pointer; transition: all 0.2s ease;">✅ 一鍵收回</button>
                            </div>
                        `);
                    } else {
                        detailsList.push(`
                            <div class="debt-row settled" style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px; font-size: 0.8rem; color: #94a3b8; text-decoration: line-through; opacity: 0.6;">
                                <span>👥 ${name}：$${owed} [ 已收回 ]</span>
                            </div>
                        `);
                    }
                }
                
                if (owesCount > 1) {
                    detailsList.push(`
                        <div class="debt-row" style="display: flex; justify-content: flex-end; align-items: center; margin-top: 6px; padding-top: 6px; border-top: 1px dashed rgba(244, 63, 94, 0.15);">
                            <button class="repay-pill-btn" data-id="${item.id}" data-friend="all" style="background: rgba(16, 185, 129, 0.1); border: 1.5px solid rgba(16, 185, 129, 0.3); color: #10b981; padding: 4px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 700; cursor: pointer; transition: all 0.2s ease;">✅ 全部收回</button>
                        </div>
                    `);
                }
            }
            
            const itemHtml = `
                <div class="split-item-row" data-settled="${isSettled ? 'true' : 'false'}" style="margin-bottom: 12px; padding: 10px; border-radius: 14px; ${isSettled ? 'background: rgba(255, 255, 255, 0.25); backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); border: 1px solid rgba(244, 63, 94, 0.15); opacity: 0.65; text-decoration: line-through; display: none;' : 'background: rgba(255, 255, 255, 0.5); border: 1px solid rgba(226, 232, 240, 0.8);'}">
                    <div style="font-weight: 700; font-size: 0.9rem; display: flex; justify-content: space-between; color: var(--text-color);">
                        <span>📌 ${item.description}</span>
                        <span style="color: ${isSettled ? '#f43f5e' : '#1abc9c'};">$${item.total_amount}</span>
                    </div>
                    <div style="font-size: 0.75rem; color: #64748b; margin-top: 2px;">📅 建立時間：${item.time || item.date}</div>
                    <div style="margin-top: 6px; border-top: 1px dashed rgba(0,0,0,0.05); padding-top: 4px;">
                        ${detailsList.join('')}
                    </div>
                </div>
            `;
            
            if (isSettled) {
                settledHtml += itemHtml;
            } else {
                activeHtml += itemHtml;
            }
        });
        
        cardDiv.innerHTML = `
            <div style="font-weight: 800; font-size: 1.05rem; margin-bottom: 12px; color: #f43f5e; display: flex; align-items: center; gap: 6px;">
                💸 代墊款收支明細管理
            </div>
            
            <div class="active-splits-container">
                ${activeHtml || '<div style="text-align: center; padding: 20px 0; color: #64748b; font-size: 0.85rem;">🎉 太棒了！目前沒有未收回的代墊款！</div>'}
            </div>
            
            <div class="settled-splits-container" style="display: none; border-top: 1px dashed rgba(244, 63, 94, 0.2); margin-top: 10px; padding-top: 10px;">
                ${settledHtml || '<div style="text-align: center; padding: 20px 0; color: #94a3b8; font-size: 0.85rem;">目前無已結清項目</div>'}
            </div>
            
            <div style="margin-top: 12px; display: flex; justify-content: center;">
                <button class="history-toggle-btn" style="background: rgba(244, 63, 94, 0.05); border: 1.5px solid rgba(244, 63, 94, 0.3); color: #f43f5e; padding: 8px 16px; border-radius: 14px; font-size: 0.8rem; font-weight: 700; cursor: pointer; transition: all 0.2s ease; display: flex; align-items: center; gap: 4px; outline: none;">
                    🔄 查看已回收代墊款
                </button>
            </div>
        `;
        
        return cardDiv;
    };"""

pattern = r"    window\.renderChatBillSplits = \(dataList\) => \{.*?\n        return cardDiv;\n    \};"
new_content = re.sub(pattern, new_func, content, flags=re.DOTALL)

if new_content != content:
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Successfully replaced renderChatBillSplits using regex.")
else:
    print("Regex replacement failed.")
