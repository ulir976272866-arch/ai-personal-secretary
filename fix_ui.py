import os

path = "static/js/app.js"
with open(path, "r") as f:
    content = f.read()

target = """            if (item.breakdown) {
                for (const [name, info] of Object.entries(item.breakdown)) {
                    if (name.startsWith('_')) continue;
                    const owed = info.owed || 0;
                    const received = info.received || 0;
                    const balance = owed - received;
                    
                    if (balance > 0) {
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
            }"""

replacement = """            if (item.breakdown) {
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
            }"""

if target in content:
    content = content.replace(target, replacement)
    with open(path, "w") as f:
        f.write(content)
    print("Replacement success.")
else:
    print("Target block not found in file.")
