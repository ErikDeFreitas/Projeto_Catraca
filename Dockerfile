FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py catraca_core.py ./

# Pasta onde os CSVs gerados ficam salvos - montar como volume no docker-compose
RUN mkdir -p /app/relatorios

EXPOSE 8000

# 1 worker: os jobs ficam em memoria (dict Python) - mais de 1 worker
# faria cada processo ter sua propria lista de jobs, quebrando o polling.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
