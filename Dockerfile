FROM python:3.14-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml ./
COPY src ./src
COPY data/ats-board-directory.csv ./data/ats-board-directory.csv
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home board
CMD ["python", "-m", "applications.volume_entrypoint"]
