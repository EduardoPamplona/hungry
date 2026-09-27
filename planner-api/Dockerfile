FROM python:3.12-slim

WORKDIR /app

# curl is used by nothing at runtime here, but keep image lean otherwise.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
