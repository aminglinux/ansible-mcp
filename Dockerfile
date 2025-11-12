FROM python:3.11-slim

WORKDIR /app
COPY . .

# 安装 ansible & python 依赖
RUN apt-get update && apt-get install -y sshpass && \
    pip install --no-cache-dir -r requirements.txt && \
    rm -rf /var/lib/apt/lists/*

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

