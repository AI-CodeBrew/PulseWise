# The API as a Docker image, for Fly.io. Deploy from the backend folder:  fly deploy --ha=false
# (Fly builds the image on its own machines: Docker is not needed on this computer.)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# The libraries first: this layer is rebuilt only when requirements.txt changes, so most deploys are quick.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The code, and what "alembic upgrade head" needs (fly.toml runs it before every new version starts).
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

# Not as root. No .env is copied (see .dockerignore): settings and secrets come from `fly secrets`.
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8080

# --proxy-headers: behind Fly's proxy the visitor's real address is in a header (login limits and the audit log use it).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]
