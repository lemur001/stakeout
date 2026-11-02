FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-postgres.txt ./
RUN pip install --no-cache-dir -r requirements-postgres.txt && useradd --create-home --uid 10001 civic
COPY . .
RUN mkdir -p /app/data && chown -R civic:civic /app
USER civic
ENV APP_MODE=production HOST=0.0.0.0 PORT=8080 DATABASE_PATH=/app/data/civic.sqlite3
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8080')+'/health',timeout=3)" || exit 1
CMD ["python", "run.py"]
