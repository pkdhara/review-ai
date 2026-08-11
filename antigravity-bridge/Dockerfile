FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends procps iproute2 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn google-generativeai pydantic requests urllib3

COPY bridge.py .

EXPOSE 8899

CMD ["python3", "bridge.py"]
