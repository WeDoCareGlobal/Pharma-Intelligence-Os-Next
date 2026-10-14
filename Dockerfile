FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY pharma_next ./pharma_next
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home app && mkdir /data && chown app /data
USER app
ENV PHARMA_DATABASE=/data/cases.db
EXPOSE 8000
CMD ["uvicorn", "pharma_next.main:application", "--factory", "--host", "0.0.0.0", "--port", "8000"]
