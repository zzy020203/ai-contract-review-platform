# 后端镜像（FastAPI + Celery 共用；多阶段：依赖层与代码层分离，提升构建缓存命中率）
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HF_ENDPOINT=https://hf-mirror.com

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 预下载 BGE 向量模型，保证私有化环境离线可运行
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-zh-v1.5')"

COPY app ./app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD curl -fsS http://localhost:8000/api/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
