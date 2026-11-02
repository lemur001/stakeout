FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock && useradd --create-home --uid 10001 civic
COPY . .
RUN mkdir -p /app/data && chown civic:civic /app/data && chmod 700 /app/data
ENV APP_MODE=production HOST=0.0.0.0 PORT=8080 DATABASE_PATH=/app/data/civic.sqlite3
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8080')+'/health',timeout=3)" || exit 1
# Railway volumes arrive owned by root. The entrypoint fixes only the data
# directory, drops all groups and uid/gid to 10001, then execs the server.
CMD ["python", "docker_entrypoint.py"]
