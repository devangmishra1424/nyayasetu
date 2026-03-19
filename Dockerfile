FROM python:3.11-slim

WORKDIR /app

# Permanent fix for Groq SSL/connection error
RUN apt-get update && \
    apt-get install -y git curl ca-certificates && \
    update-ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "7860"]