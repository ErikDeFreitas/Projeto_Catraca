"""
API - Relatorio de Acessos ControlID (TCM Logistica & Transporte)
====================================================================

Roda nesta mesma maquina onde a catraca e acessivel na rede local.
O site consome esta API pela internet (via IP publico / dominio / VPN,
conforme a infra de voces) e recebe apenas o link de download do CSV
quando o relatorio fica pronto.

Fluxo:
    1) POST /relatorio            -> cria o job e comeca a gerar em background
    2) GET  /relatorio/{job_id}   -> consulta o status do job
    3) GET  /relatorio/{job_id}/download -> baixa o CSV quando status = concluido

Como rodar:
    pip install -r requirements.txt
    cp .env.example .env      # e preencher com IP/usuario/senha da catraca
    uvicorn app:app --host 0.0.0.0 --port 8000

Documentacao interativa (Swagger) gerada automaticamente em:
    http://<ip-da-maquina>:8000/docs
"""

import os
import uuid
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from catraca_core import gerar_relatorio, CatracaError

load_dotenv()

# ======================================
# CONFIGURACAO (variaveis de ambiente / .env)
# ======================================

CATRACA_IP = os.environ.get("CATRACA_IP")
CATRACA_USUARIO = os.environ.get("CATRACA_USUARIO")
CATRACA_SENHA = os.environ.get("CATRACA_SENHA")

# Dominio(s) do site que vao consumir a API. Em producao, restrinja aqui
# em vez de usar "*". Ex: ["https://www.seusite.com.br"]
ORIGENS_PERMITIDAS = os.environ.get("ORIGENS_PERMITIDAS", "*").split(",")

PASTA_RELATORIOS = Path(os.environ.get("PASTA_RELATORIOS", "./relatorios")).resolve()
PASTA_RELATORIOS.mkdir(parents=True, exist_ok=True)

if not all([CATRACA_IP, CATRACA_USUARIO, CATRACA_SENHA]):
    raise RuntimeError(
        "Configure CATRACA_IP, CATRACA_USUARIO e CATRACA_SENHA "
        "(via .env ou variaveis de ambiente) antes de subir a API."
    )


# ======================================
# "BANCO" DE JOBS EM MEMORIA
# ======================================
# Simples e suficiente para uma unica maquina/processo. Se um dia a API
# rodar em varios processos/instancias, isso precisa virar Redis/DB.

JOBS: Dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


class StatusJob:
    PENDENTE = "pendente"
    PROCESSANDO = "processando"
    CONCLUIDO = "concluido"
    ERRO = "erro"


# ======================================
# MODELOS (request / response)
# ======================================

class PeriodoRequest(BaseModel):
    data_inicio: date
    data_fim: date

    @field_validator("data_fim")
    @classmethod
    def valida_periodo(cls, data_fim, info):
        data_inicio = info.data.get("data_inicio")
        if data_inicio and data_fim < data_inicio:
            raise ValueError("data_fim nao pode ser anterior a data_inicio")
        return data_fim


class JobCriadoResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    criado_em: datetime
    data_inicio: date
    data_fim: date
    total_registros: Optional[int] = None
    sem_registro: Optional[list] = None
    download_url: Optional[str] = None
    erro: Optional[str] = None


# ======================================
# APP
# ======================================

app = FastAPI(
    title="API Relatorio de Acessos - Catraca ControlID",
    description="Gera relatorios de acesso (CSV) a partir da catraca local, para consumo pelo site.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENS_PERMITIDAS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _executar_job(job_id: str, data_inicio: str, data_fim: str):
    with JOBS_LOCK:
        JOBS[job_id]["status"] = StatusJob.PROCESSANDO

    arquivo_saida = PASTA_RELATORIOS / f"{job_id}.csv"

    def log_fn(msg):
        # troque por logging "de verdade" se quiser (arquivo/console)
        print(f"[job {job_id}] {msg}")

    try:
        resultado = gerar_relatorio(
            CATRACA_IP,
            CATRACA_USUARIO,
            CATRACA_SENHA,
            data_inicio,
            data_fim,
            str(arquivo_saida),
            log_fn,
        )
        with JOBS_LOCK:
            JOBS[job_id].update(
                status=StatusJob.CONCLUIDO,
                total_registros=resultado["total_registros"],
                sem_registro=resultado["sem_registro"],
                arquivo=str(arquivo_saida),
            )
    except CatracaError as e:
        with JOBS_LOCK:
            JOBS[job_id].update(status=StatusJob.ERRO, erro=str(e))
    except Exception as e:  # erro inesperado, nao deixa o job travado em "processando"
        with JOBS_LOCK:
            JOBS[job_id].update(status=StatusJob.ERRO, erro=f"Erro inesperado: {e}")


@app.post("/relatorio", response_model=JobCriadoResponse)
def solicitar_relatorio(periodo: PeriodoRequest):
    job_id = str(uuid.uuid4())

    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": StatusJob.PENDENTE,
            "criado_em": datetime.now(),
            "data_inicio": periodo.data_inicio,
            "data_fim": periodo.data_fim,
            "total_registros": None,
            "sem_registro": None,
            "arquivo": None,
            "erro": None,
        }

    thread = threading.Thread(
        target=_executar_job,
        args=(job_id, periodo.data_inicio.isoformat(), periodo.data_fim.isoformat()),
        daemon=True,
    )
    thread.start()

    return JobCriadoResponse(job_id=job_id, status=StatusJob.PENDENTE)


@app.get("/relatorio/{job_id}", response_model=JobStatusResponse)
def consultar_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="job_id nao encontrado")

    download_url = f"/relatorio/{job_id}/download" if job["status"] == StatusJob.CONCLUIDO else None

    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        criado_em=job["criado_em"],
        data_inicio=job["data_inicio"],
        data_fim=job["data_fim"],
        total_registros=job["total_registros"],
        sem_registro=job["sem_registro"],
        download_url=download_url,
        erro=job["erro"],
    )


@app.get("/relatorio/{job_id}/download")
def baixar_relatorio(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="job_id nao encontrado")
    if job["status"] != StatusJob.CONCLUIDO:
        raise HTTPException(status_code=409, detail=f"Relatorio ainda nao esta pronto (status: {job['status']})")

    arquivo = job["arquivo"]
    if not arquivo or not os.path.exists(arquivo):
        raise HTTPException(status_code=410, detail="Arquivo do relatorio nao foi encontrado no servidor")

    nome_download = f"relatorio_acessos_{job['data_inicio']}_a_{job['data_fim']}.csv"
    return FileResponse(arquivo, media_type="text/csv", filename=nome_download)


@app.get("/health")
def health():
    return {"status": "ok"}
