FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml .
COPY server.py tools.py ./
RUN pip install --no-cache-dir .
CMD ["python", "server.py"]
