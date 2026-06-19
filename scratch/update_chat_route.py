import os

filepath = "/Users/yinmin/0_Ai coding/私人行事曆安排/ai-personal-secretary/app.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update batch processing loop
target_batch = """                if "data" in item and isinstance(item["data"], dict):
                    nested_data = item.pop("data")
                    for k in ["response", "reply", "message"]:
                        if k in nested_data and not ai_response_message:
                            ai_response_message = nested_data.pop(k)
                    item.update(nested_data)
                cleaned_intents.append(item)"""

replacement_batch = """                if "data" in item and isinstance(item["data"], dict):
                    nested_data = item.pop("data")
                    for k in ["response", "reply", "message"]:
                        if k in nested_data and not ai_response_message:
                            ai_response_message = nested_data.pop(k)
                    item.update(nested_data)
                if item.get('type') == 'expense':
                    item['sub_category'] = normalize_sub_category(
                        item.get('category'),
                        item.get('sub_category'),
                        is_income=(item.get('expense_type') == 'income')
                    )
                cleaned_intents.append(item)"""

# 2. Update single expense processing
target_single = """    elif intent_type == "expense":
        service = get_sheets_service()
        is_income = parsed_data.get('expense_type') == 'income'
        category = parsed_data.get('category')
        sub_category = parsed_data.get('sub_category', '')
        amount = int(parsed_data.get('amount') or 0)"""

replacement_single = """    elif intent_type == "expense":
        service = get_sheets_service()
        is_income = parsed_data.get('expense_type') == 'income'
        category = parsed_data.get('category')
        sub_category = normalize_sub_category(category, parsed_data.get('sub_category', ''), is_income)
        parsed_data['sub_category'] = sub_category
        amount = int(parsed_data.get('amount') or 0)"""

if target_batch not in content:
    print("Error: Target batch block not found!")
    exit(1)

if target_single not in content:
    print("Error: Target single block not found!")
    exit(1)

content = content.replace(target_batch, replacement_batch, 1)
content = content.replace(target_single, replacement_single, 1)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print("Successfully updated chat route in app.py with subcategory normalization!")
