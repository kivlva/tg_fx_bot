FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 RUN_MODE=polling
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home bot
COPY deploy/vm_entrypoint.py /app/vm_entrypoint.py
USER bot
CMD ["python", "/app/vm_entrypoint.py"]
