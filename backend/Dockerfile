FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml .
COPY src ./src

RUN pip install --no-cache-dir .

EXPOSE 8020

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8500"]
