import pypdf
import re
import csv

def parse_pdf(file_path):
    reader = pypdf.PdfReader(file_path)
    text = '\n'.join([page.extract_text() for page in reader.pages])
    
    # Regex for lines like:
    # 04/30 - 今天 7天
    # 03/27 - 04/29 14天 34天
    # 12/09,2025年 - 01/10 8天 33天
    # 11/11,2025年 - 12/08,2025年 9天 28天
    
    pattern = re.compile(r'(\d{2}/\d{2}(?:,20\d{2}年)?)\s*-\s*(\d{2}/\d{2}(?:,20\d{2}年)?|今天)\s+(\d+)天(?:\s+(\d+)天)?')
    matches = pattern.findall(text)
    
    print(f"Found {len(matches)} records.")
    
    results = []
    # Assume the current year of export is 2026.
    # Records are listed from newest to oldest in the '週期歷程記錄' section.
    # But wait, there are also other sections. Let's just collect all unique matches by start date.
    
    unique_records = {}
    current_year = 2026
    
    for match in matches:
        start_str = match[0]
        end_str = match[1]
        length = match[2]
        cycle = match[3] if match[3] else ""
        
        # parse start
        if ",20" in start_str:
            start_date = start_str.replace("年", "").replace(",", "/")
            # start_date is now mm/dd/yyyy. Let's make it yyyy/mm/dd
            parts = start_date.split("/")
            year = parts[2]
            month = parts[0]
            day = parts[1]
            start_date_fmt = f"{year}/{month}/{day}"
        else:
            year = str(current_year)
            parts = start_str.split("/")
            month = parts[0]
            day = parts[1]
            start_date_fmt = f"{year}/{month}/{day}"
            
        # parse end
        if end_str == "今天":
            end_date_fmt = ""
        elif ",20" in end_str:
            end_date_p = end_str.replace("年", "").replace(",", "/")
            parts = end_date_p.split("/")
            eyear = parts[2]
            emonth = parts[0]
            eday = parts[1]
            end_date_fmt = f"{eyear}/{emonth}/{eday}"
        else:
            # End year is usually same as start year, unless month crossed over. 
            # But the PDF usually omits year for the current year (2026).
            # If start is 2025 and end omits year, it means it crossed into 2026? 
            # E.g. "12/09,2025年 - 01/10" -> 01/10 is in 2026!
            # If start has no year, it's 2026. So end is also 2026.
            parts = end_str.split("/")
            emonth = parts[0]
            eday = parts[1]
            if ",20" in start_str and emonth < month: 
                eyear = str(int(year) + 1) # Crossed year
            else:
                eyear = year
            end_date_fmt = f"{eyear}/{emonth}/{eday}"
            
        # Deduplicate
        if start_date_fmt not in unique_records:
            unique_records[start_date_fmt] = {
                "year": year,
                "month": month,
                "start": start_date_fmt,
                "end": end_date_fmt,
                "length": length,
                "cycle": cycle,
                "note": "匯入自 PDF" if end_date_fmt else "目前進行中"
            }
            
    # Sort from newest to oldest
    sorted_records = sorted(unique_records.values(), key=lambda x: x['start'], reverse=True)
    
    with open('parsed_records.csv', 'w') as f:
        writer = csv.writer(f)
        writer.writerow(["年度", "月份", "開始日期", "結束日期", "經期天數", "週期天數", "備註"])
        for r in sorted_records:
            writer.writerow([r["year"], r["month"], r["start"], r["end"], r["length"], r["cycle"], r["note"]])
            
    print(f"Parsed {len(sorted_records)} unique records.")
    
if __name__ == '__main__':
    parse_pdf('PC_Report.pdf')
