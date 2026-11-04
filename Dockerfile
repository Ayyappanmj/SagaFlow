FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend /app/backend
COPY migrations /app/migrations
ENV PYTHONPATH=/app/backend
RUN useradd -m app && chown -R app /app
USER app
CMD ["uvicorn", "api.app:get_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
