import os

filepath = "/Users/yinmin/0_Ai coding/私人行事曆安排/ai-personal-secretary/app.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Let's locate rule_based_expense_parser
start_marker = "def rule_based_expense_parser(text, email=None):"
end_marker = "def rule_based_calendar_parser(text, now):"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx == -1 or end_idx == -1:
    print("Error: Could not locate markers in app.py!")
    print(f"start_marker found: {start_idx != -1}, end_marker found: {end_idx != -1}")
    exit(1)

# Verify if we have our custom definitions
custom_defs = """VALID_EXPENSE_SUB_CATEGORIES = {
    "食": ["早餐", "午餐", "晚餐", "飲料／咖啡", "外送", "超商／零食", "聚餐", "其他"],
    "衣": ["上衣／褲子", "鞋子", "包包／配件", "保養／化妝品", "其他"],
    "住": ["房租", "水費", "電費", "瓦斯費", "管理費", "手機費", "網路費", "修繕／家具", "清潔用品", "其他"],
    "行": ["油錢／加油", "停車費", "大眾交通", "Uber／計程車", "高鐵／火車", "機票", "其他"],
    "育": ["書籍", "課程／學費", "補習", "文具", "其他"],
    "樂": ["電影／演唱會", "KTV", "旅遊", "遊戲", "訂閱娛樂", "其他"],
    "醫": ["掛號／看診", "藥品", "健保", "保健品", "其他"],
    "保險費": ["壽險", "醫療險", "車險", "產險", "其他保費", "其他"],
    "貸款": ["信貸", "車貸", "房貸", "商品貸", "其他"],
    "儲蓄/投資": ["緊急備用金", "定存", "活儲", "投資型保單", "股票", "基金", "外匯", "其他衍生性商品", "其他"],
    "公益": ["其他"],
    "其他雜支": ["其他"]
}

VALID_INCOME_SUB_CATEGORIES = {
    "薪資": ["正職薪水", "兼職時薪", "小費進帳", "其他"],
    "獎金": ["年終獎金", "績效/三節", "專案分紅", "其他"],
    "投資獲利": ["股票股利/價差", "基金配息", "定存利息", "加密貨幣", "其他"],
    "副業收入": ["諮詢服務", "個人項目", "團購/分潤", "諮詢隨喜/小費", "其他"],
    "變更/退款": ["購物退款", "代墊款收回", "其他雜項", "其他"],
    "儲蓄/投資": ["緊急備用金", "定存", "活儲", "投資型保單", "股票", "基金", "外匯", "其他衍生性商品", "其他"],
    "貸款": ["信貸", "車貸", "房貸", "商品貸", "其他"]
}

def normalize_sub_category(category, sub_cat, is_income=False):
    sub_cat = (sub_cat or "").strip()
    if not sub_cat:
        return "其他"
        
    mapping = VALID_INCOME_SUB_CATEGORIES if is_income else VALID_EXPENSE_SUB_CATEGORIES
    
    if category not in mapping:
        return "其他"
        
    valid_list = mapping[category]
    
    def clean_str(s):
        return s.replace('／', '/').replace(' ', '').lower()
        
    cleaned_sub_cat = clean_str(sub_cat)
    
    # First pass: exact clean match
    for valid_item in valid_list:
        if clean_str(valid_item) == cleaned_sub_cat:
            return valid_item
            
    # Second pass: substring match (excluding "其他")
    for valid_item in valid_list:
        if valid_item == "其他":
            continue
        cv = clean_str(valid_item)
        if cleaned_sub_cat in cv or cv in cleaned_sub_cat:
            return valid_item
            
    return "其他"

"""

new_parser_func = """def rule_based_expense_parser(text, email=None):
    import re
    # Split by common conjunctions
    parts = re.split(r'然後|跟|和|，|、|\+|且|以及', text)
    expenses = []
    
    # Simple category keyword map
    cat_keywords = {
        '食': ['餐', '便當', '飯', '麵', '壽司', '火鍋', '餐廳', '點心', '麵包', '宵夜', '水果', '超商', '飲料', '咖啡', '茶', '奶茶', '冰', '麥當勞', '肯德基', '早餐', '午餐', '晚餐', '吃', '喝', '雞排', '茶'],
        '行': ['捷運', '公車', '計程車', '火車', '高鐵', '加油', '停車', '機車', '汽車', '悠遊卡', 'uber', '車票', '機票', '油錢', '客運', '輕軌', '租車'],
        '住': ['房租', '水費', '電費', '瓦斯', '網路', '管理費', '衛生紙', '洗面乳', '沐浴乳', '日用品', '生活百貨', '水電', '租金', '裝潢', '傢俱', '家電'],
        '衣': ['衣服', '褲子', '鞋子', '外套', '襪子', '襯衫', '帽子', '裙子', '西裝', '服飾', '買衣', '洗頭', '美甲', '美睫', '做臉', '美容', '理髮', '剪髮', '染髮'],
        '育': ['書', '課', '學費', '文具', '雜誌', '報紙', '演講', '補習', '教材', '原子筆'],
        '樂': ['電影', '遊戲', '唱歌', '玩具', '旅遊', '門票', '展覽', '密室', '打電動', '遊樂園', '住宿', '機票', '玩樂', '追劇', 'netflix', 'spotify', '按摩', 'spa', '油壓', '指壓'],
        '醫': ['看病', '門診', '藥', '醫院', '診所', '口罩', '感冒', '牙醫', '掛號', '醫療', '保健食品', '推拿', '整脊', '整骨', '復健'],
        '儲蓄/投資': ['股票', '基金', '定存', '理財', '投資', '買股', '證券', '美股', '台股'],
        '公益': ['捐款', '發票', '捐贈', '慈善', '公益', '愛心', '捐錢']
    }
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        # Match pattern: item name followed by numbers, optional "元" or "塊" or "元元" at the end
        match = re.search(r'^([^\d]+?)(?:花了|支出|買)?\s*(\d+)\s*(?:元|塊)?$', part)
        if match:
            item = match.group(1).strip()
            amount = int(match.group(2))
            
            category = None
            sub_category = None
            
            # Predefined sub-category mapping rules based on keywords
            if not category or not sub_category:
                category = '食' # default fallback
                sub_category = '其他'
                
                # Check category keywords
                for cat, keywords in cat_keywords.items():
                    if any(keyword in item for keyword in keywords):
                        category = cat
                        break
                
                sub_cat_rules = {
                    '食': [
                        ('早餐', '早餐'),
                        ('午餐', '午餐'),
                        ('中餐', '午餐'),
                        ('晚餐', '晚餐'),
                        ('便當', '午餐'),
                        ('宵夜', '晚餐'),
                        ('飲料', '飲料／咖啡'),
                        ('咖啡', '飲料／咖啡'),
                        ('茶', '飲料／咖啡'),
                        ('奶茶', '飲料／咖啡'),
                        ('外送', '外送'),
                        ('超商', '超商／零食'),
                        ('零食', '超商／零食'),
                        ('聚餐', '聚餐'),
                    ],
                    '行': [
                        ('計程車', 'Uber／計程車'),
                        ('小黃', 'Uber／計黃'), # wait, Uber／計程車
                        ('uber', 'Uber／計程車'),
                        ('捷運', '大眾交通'),
                        ('公車', '大眾交通'),
                        ('火車', '高鐵／火車'),
                        ('高鐵', '高鐵／火車'),
                        ('飛機', '機票'),
                        ('機票', '機票'),
                        ('悠遊卡', '大眾交通'),
                        ('加油', '油錢／加油'),
                        ('油錢', '油錢／加油'),
                        ('停車', '停車費'),
                    ],
                    '住': [
                        ('房租', '房租'),
                        ('租金', '房租'),
                        ('水費', '水費'),
                        ('電費', '電費'),
                        ('瓦斯', '瓦斯費'),
                        ('管理費', '管理費'),
                        ('手機', '手機費'),
                        ('電話費', '手機費'),
                        ('網路', '網路費'),
                        ('修繕', '修繕／家具'),
                        ('家具', '修繕／家具'),
                        ('清潔', '清潔用品'),
                    ],
                    '衣': [
                        ('衣服', '上衣／褲子'),
                        ('褲子', '上衣／褲子'),
                        ('外套', '上衣／褲子'),
                        ('襯衫', '上衣／褲子'),
                        ('裙子', '上衣／褲子'),
                        ('鞋', '鞋子'),
                        ('包包', '包包／配件'),
                        ('配件', '包包／配件'),
                        ('保養', '保養／化妝品'),
                        ('化妝', '保養／化妝品'),
                    ],
                    '育': [
                        ('書', '書籍'),
                        ('課程', '課程／學費'),
                        ('學費', '課程／學費'),
                        ('補習', '補習'),
                        ('文具', '文具'),
                    ],
                    '樂': [
                        ('電影', '電影／演唱會'),
                        ('演唱會', '電影／演唱會'),
                        ('ktv', 'KTV'),
                        ('唱歌', 'KTV'),
                        ('旅遊', '旅遊'),
                        ('住宿', '旅遊'),
                        ('遊戲', '遊戲'),
                        ('電動', '遊戲'),
                        ('訂閱', '訂閱娛樂'),
                    ],
                    '醫': [
                        ('看病', '掛號／看診'),
                        ('門診', '掛號／看診'),
                        ('掛號', '掛號／看診'),
                        ('診所', '掛號／看診'),
                        ('藥', '藥品'),
                        ('感冒', '藥品'),
                        ('健保', '健保'),
                        ('保健品', '保健品'),
                        ('維他命', '保健品'),
                    ],
                    '儲蓄/投資': [
                        ('緊急備用金', '緊急備用金'),
                        ('備用金', '緊急備用金'),
                        ('定存', '定存'),
                        ('活儲', '活儲'),
                        ('活期', '活儲'),
                        ('存款', '活儲'),
                        ('投資型保單', '投資型保單'),
                        ('保單', '投資型保單'),
                        ('股票', '股票'),
                        ('買股', '股票'),
                        ('基金', '基金'),
                        ('外匯', '外匯'),
                        ('衍生性商品', '其他衍生性商品'),
                    ],
                    '公益': [
                        ('捐款', '其他'),
                        ('公益', '其他'),
                    ]
                }
                
                # Apply sub-category rules for the detected category
                if category in sub_cat_rules:
                    for kw, sub_cat in sub_cat_rules[category]:
                        if kw in item:
                            sub_category = sub_cat
                            break
                            
            # Ensure normalization
            sub_category = normalize_sub_category(category, sub_category, is_income=False)
            
            # Strip verb prefix if any
            for prefix in ['買', '吃', '喝', '付', '繳']:
                if item.startswith(prefix) and len(item) > len(prefix):
                    item = item[len(prefix):]
            
            expenses.append({
                'type': 'expense',
                'item': item,
                'amount': amount,
                'category': category,
                'sub_category': sub_category
            })
            
    return expenses

"""

# Fix ('小黃', 'Uber／計黃') in rules to ('小黃', 'Uber／計程車')
new_parser_func = new_parser_func.replace("('小黃', 'Uber／計黃')", "('小黃', 'Uber／計程車')")

updated_content = content[:start_idx] + custom_defs + new_parser_func + content[end_idx:]

with open(filepath, "w", encoding="utf-8") as f:
    f.write(updated_content)

print("Successfully replaced rule_based_expense_parser in app.py!")
