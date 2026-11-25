FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .
# API som default; worker startas med annat command i compose
CMD ["uvicorn", "mailroom.api:app", "--host", "0.0.0.0", "--port", "8080"]
