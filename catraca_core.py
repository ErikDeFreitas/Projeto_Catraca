"""
Core de integracao com a catraca ControlID.

Extraido do script original (relatorio_controlid_gui.py), removendo toda a
parte de interface grafica (tkinter). Mantem exatamente a mesma logica de
autenticacao, consulta e filtragem de acessos.
"""

import csv
from datetime import datetime, timedelta

import requests
from requests.adapters import HTTPAdapter, Retry


# ======================================
# LISTA DE USUARIOS PADRAO
# (usada somente se a API/chamador nao informar uma lista de nomes)
# ======================================

USUARIOS_PADRAO = [
    "Agdo",
    "Aline",
    "Andreza",
    "Dario",
    "Edneya",
    "Equiberto",
    "Erivelto",
    "Gabriel Correa",
    "Givaldo",
    "Joao",
    "Marcos Oliveira",
    "Richard",
    "Robert",
    "Tiago Torre",
    "Wellington Souza",
]


class CatracaError(Exception):
    """Erro de negocio ao falar com a catraca (login, timeout, etc)."""


def cria_sessao_http():
    sessao = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    sessao.mount("http://", HTTPAdapter(max_retries=retries))
    sessao.mount("https://", HTTPAdapter(max_retries=retries))
    return sessao


def login(http, ip, usuario, senha, log_fn):
    log_fn(f"Conectando em {ip}...")
    try:
        resp = http.post(
            f"http://{ip}/login.fcgi",
            json={"login": usuario, "password": senha},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise CatracaError(f"Falha ao conectar/autenticar na catraca ({ip}): {e}") from e

    session_id = resp.json().get("session")
    if not session_id:
        raise CatracaError("Login na catraca nao retornou uma sessao valida.")

    log_fn(f"Sessao iniciada: {session_id}")
    return session_id


def consulta_acessos(http, ip, sessao, inicio_ts, fim_ts, log_fn):
    payload = {
        "object": "access_logs",
        "delimiter": ";",
        "line_break": "\r\n",
        "header": "Nome;Data/Hora",
        "where": [
            {
                "object": "access_logs",
                "field": "time",
                "operator": ">=",
                "value": inicio_ts,
                "connector": "AND",
            },
            {
                "object": "access_logs",
                "field": "time",
                "operator": "<=",
                "value": fim_ts,
            },
        ],
        "columns": [
            {"type": "object_field", "object": "users", "field": "name"},
            {
                "type": "object_field",
                "object": "access_logs",
                "field": "time",
                "format": {"format": "%d/%m/%Y %H:%M:%S"},
            },
        ],
    }

    log_fn("Consultando todos os acessos do periodo...")
    try:
        r = http.post(
            f"http://{ip}/report_generate.fcgi?session={sessao}",
            json=payload,
            timeout=300,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        raise CatracaError(f"Falha ao consultar acessos na catraca: {e}") from e

    r.encoding = r.encoding or "utf-8"
    linhas = r.text.splitlines()

    if not linhas:
        log_fn("Aviso: consulta nao retornou nenhuma linha.")
        return []

    reader = csv.reader(linhas[1:], delimiter=";")
    return list(reader)


def gerar_relatorio(ip, usuario, senha, data_inicio, data_fim, arquivo_saida, usuarios=None, log_fn=print):
    """
    Gera o relatorio de acessos no periodo informado e salva em `arquivo_saida`.

    data_inicio / data_fim: strings no formato "YYYY-MM-DD".
    usuarios: lista de nomes a filtrar. Se nao for informado (None), usa
              USUARIOS_PADRAO.

    Retorna um dicionario com o resumo do processamento:
        {
            "total_registros": int,
            "contagem": {nome: qtd, ...},
            "sem_registro": [nomes sem nenhum acesso no periodo],
            "arquivo": arquivo_saida,
        }
    """
    if not usuarios:
        usuarios = USUARIOS_PADRAO

    inicio_ts = int(datetime.strptime(data_inicio, "%Y-%m-%d").timestamp())
    fim_ts = int(
        (
            datetime.strptime(data_fim, "%Y-%m-%d")
            + timedelta(hours=23, minutes=59, seconds=59)
        ).timestamp()
    )

    http = cria_sessao_http()
    sessao = login(http, ip, usuario, senha, log_fn)
    todas_linhas = consulta_acessos(http, ip, sessao, inicio_ts, fim_ts, log_fn)

    usuarios_lower = {u.lower(): u for u in usuarios}
    contagem = {u: 0 for u in usuarios}
    linhas_filtradas = []

    for linha in todas_linhas:
        if not linha:
            continue
        nome_lower = linha[0].strip().lower()
        if nome_lower in usuarios_lower:
            nome_original = usuarios_lower[nome_lower]
            contagem[nome_original] += 1
            linhas_filtradas.append(linha)

    with open(arquivo_saida, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";", lineterminator="\r\n")
        writer.writerow(["Nome", "Data/Hora"])
        writer.writerows(linhas_filtradas)

    log_fn(f"Relatorio salvo em: {arquivo_saida}")
    log_fn(f"Total de registros: {len(linhas_filtradas)}")

    sem_registro = [u for u, c in contagem.items() if c == 0]

    return {
        "total_registros": len(linhas_filtradas),
        "contagem": contagem,
        "sem_registro": sem_registro,
        "arquivo": arquivo_saida,
    }