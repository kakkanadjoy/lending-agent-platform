FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python -m spacy download en_core_web_sm

COPY agents/ agents/
COPY api/ api/
COPY db/ db/
COPY ews/ ews/
COPY rag/ rag/
COPY rules/ rules/
COPY synth/ synth/
COPY ops/ ops/
COPY mlruns/ mlruns/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]