# open Dockerfile and add this line anywhere
# rebuild trigger

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y git curl && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements first — Docker layer caching
# If requirements.txt hasn't changed, this layer is reused
# and pip install is skipped on rebuild. Saves 5+ minutes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# HuggingFace Spaces requires port 7860
EXPOSE 7860

# Start FastAPI
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "7860"]
