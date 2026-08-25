FROM python:3.11-slim

# HF Spaces runs as uid 1000 and mounts persistent storage (if enabled) at /data
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user app.py .
COPY --chown=user static ./static

USER user
ENV QUOTA_DB=/data/quota.db
EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
