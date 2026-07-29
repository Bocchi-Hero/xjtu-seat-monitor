FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY auth_session.py mailer.py monitor.py ./

# Mount config.yaml + session.json at runtime
CMD ["python", "-u", "monitor.py"]
