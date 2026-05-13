# 使用官方 Python 輕量版作為基礎影像
FROM python:3.10-slim

# 設定工作目錄
WORKDIR /app

# 複製需求檔案並安裝套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install gunicorn

# 複製所有專案檔案
COPY . .

# 設定環境變數（Cloud Run 會自動帶入 PORT）
ENV PORT 8080

# 啟動應用程式 (使用 gunicorn 以獲得更好的效能)
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
