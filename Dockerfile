FROM python:3.12-slim

WORKDIR /app

RUN groupadd -r kyf && useradd -r -g kyf kyf

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

RUN mkdir -p /app/data && chown -R kyf:kyf /app

USER kyf

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "kyf.main"]
