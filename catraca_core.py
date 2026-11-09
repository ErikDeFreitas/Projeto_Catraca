"""Regras de negócio do relatório de acessos da catraca ControlID. Não depende da interface.

A consulta à catraca e o formato do CSV são os mesmos do programa original (V1.0):
os relatórios gerados aqui são idênticos aos antigos, byte a byte.
"""

from __future__ import annotations

import csv
import json
from calendar import monthrange
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter, Retry

IP_PADRAO = "192.168.0.130"
USUARIO_PADRAO = "admin"

COLABORADORES_PADRAO = (
    "Agdo",
    "Aline",
    "Andreza",
    "Dario",
    "Edneya",
    "Equiberto",
    "Erivelto",
    "Gabriel Correa",
    "Givaldo",
    "Marcos Oliveira",
    "Richard",
    "Robert",
    "Tiago Torre",
    "Wellington Souza",
    "Gustavo",
    "Joseildo",
    "Matheus Hiroshi",
    "Braz",
    "Diego Oliveira",
    "Nathalia Cezar",
)

CABECALHO_CSV = ["Nome", "Data/Hora"]
FORMATO_DATA_HORA = "%d/%m/%Y %H:%M:%S"
TIMEOUT_LOGIN = (10, 30)  # segundos: (conectar, aguardar resposta)
TIMEOUT_RELATORIO = (10, 300)  # períodos longos demoram para a catraca gerar
TIMEOUT_USUARIOS = (10, 60)

_MESES = (
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
    "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)

Progresso = Callable[[str], None]


class CatracaError(Exception):
    """Erro com mensagem pronta para ser exibida ao usuário."""


@dataclass(frozen=True)
class Acesso:
    nome: str
    data_hora: datetime | None  # None se a catraca devolver uma data em formato inesperado
    texto_original: str


@dataclass(frozen=True)
class ResumoColaborador:
    nome: str
    total: int
    primeiro: datetime | None
    ultimo: datetime | None


@dataclass(frozen=True)
class Relatorio:
    inicio: date
    fim: date
    acessos: tuple[Acesso, ...]
    resumos: tuple[ResumoColaborador, ...]
    linhas_csv: tuple[tuple[str, ...], ...]

    @property
    def total_registros(self) -> int:
        return len(self.linhas_csv)

    @property
    def sem_registro(self) -> list[str]:
        return [resumo.nome for resumo in self.resumos if resumo.total == 0]


# ------------------------------------------------------------ Colaboradores
def normalizar_nome(nome: str) -> str:
    return " ".join(nome.split())


def adicionar_colaborador(nomes: Iterable[str], novo: str) -> list[str]:
    """Devolve a lista com o novo nome. A catraca compara sem diferenciar maiúsculas."""
    nomes = list(nomes)
    nome = normalizar_nome(novo)
    if not nome:
        raise ValueError("Digite o nome do colaborador.")
    if nome.casefold() in {existente.casefold() for existente in nomes}:
        raise ValueError("Este colaborador já está na lista.")
    return [*nomes, nome]


def mesclar_usuarios(existentes: Iterable[str], encontrados: Iterable[str]) -> tuple[list[str], list[str]]:
    """Acrescenta à lista os nomes que ainda não estão nela. Devolve (lista completa, novos)."""
    lista = list(existentes)
    conhecidos = {nome.casefold() for nome in lista}
    novos = []
    for encontrado in encontrados:
        nome = normalizar_nome(encontrado)
        if nome and nome.casefold() not in conhecidos:
            conhecidos.add(nome.casefold())
            novos.append(nome)
    return [*lista, *novos], novos


# ------------------------------------------------------------ Períodos
def mes_de(dia: date) -> tuple[date, date]:
    return dia.replace(day=1), dia.replace(day=monthrange(dia.year, dia.month)[1])


def mes_anterior(hoje: date) -> tuple[date, date]:
    return mes_de(hoje.replace(day=1) - timedelta(days=1))


def quinzena_de(dia: date) -> tuple[date, date]:
    if dia.day <= 15:
        return dia.replace(day=1), dia.replace(day=15)
    return dia.replace(day=16), mes_de(dia)[1]


def quinzena_anterior(hoje: date) -> tuple[date, date]:
    return quinzena_de(quinzena_de(hoje)[0] - timedelta(days=1))


def ultimos_15_dias(hoje: date) -> tuple[date, date]:
    return hoje - timedelta(days=15), hoje


def nome_sugerido(inicio: date, fim: date) -> str:
    """Segue o padrão já usado nos arquivos: "Relatório 2° Quinzena Outubro.csv"."""
    mes = _MESES[inicio.month - 1]
    if (inicio, fim) == mes_de(inicio):
        return f"Relatório {mes}.csv"
    if (inicio, fim) == quinzena_de(inicio):
        return f"Relatório {1 if inicio.day == 1 else 2}° Quinzena {mes}.csv"
    return f"Relatório {inicio:%d-%m-%Y} a {fim:%d-%m-%Y}.csv"


# ------------------------------------------------------------ Comunicação com a catraca
def criar_sessao_http() -> requests.Session:
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


def _mensagem_de_rede(ip: str, erro: requests.RequestException) -> str:
    if isinstance(erro, (requests.ConnectionError, requests.Timeout)):
        return (
            f"Não foi possível falar com a catraca em {ip}. Confira o IP e se este "
            "computador está na rede da empresa."
        )
    return f"A catraca em {ip} respondeu com erro: {erro}"


def fazer_login(http: requests.Session, ip: str, usuario: str, senha: str) -> str:
    try:
        resposta = http.post(
            f"http://{ip}/login.fcgi",
            json={"login": usuario, "password": senha},
            timeout=TIMEOUT_LOGIN,
        )
        if resposta.status_code in (400, 401, 403):
            raise CatracaError("A catraca recusou o login. Confira o usuário e a senha.")
        resposta.raise_for_status()
    except requests.RequestException as erro:
        raise CatracaError(_mensagem_de_rede(ip, erro)) from erro

    try:
        sessao = resposta.json().get("session")
    except (ValueError, AttributeError):
        sessao = None
    if not sessao:
        raise CatracaError("A catraca não devolveu uma sessão válida no login.")
    return sessao


def _payload_acessos(inicio_ts: int, fim_ts: int) -> dict:
    return {
        "object": "access_logs",
        "delimiter": ";",
        "line_break": "\r\n",
        "header": ";".join(CABECALHO_CSV),
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
                "format": {"format": FORMATO_DATA_HORA},
            },
        ],
    }


def _decodificar(conteudo: bytes) -> str:
    # Não confia no charset do cabeçalho HTTP: sem ele, a biblioteca assume latin-1 e
    # um nome acentuado deixaria de coincidir com o cadastro.
    try:
        return conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return conteudo.decode("latin-1")


def consultar_acessos(
    http: requests.Session, ip: str, sessao: str, inicio: date, fim: date
) -> list[list[str]]:
    inicio_ts = int(datetime.combine(inicio, time.min).timestamp())
    fim_ts = int(datetime.combine(fim, time(23, 59, 59)).timestamp())
    try:
        resposta = http.post(
            f"http://{ip}/report_generate.fcgi?session={sessao}",
            json=_payload_acessos(inicio_ts, fim_ts),
            timeout=TIMEOUT_RELATORIO,
        )
        resposta.raise_for_status()
    except requests.RequestException as erro:
        raise CatracaError(_mensagem_de_rede(ip, erro)) from erro

    linhas = _decodificar(resposta.content).splitlines()
    return list(csv.reader(linhas[1:], delimiter=";"))


def consultar_usuarios(http: requests.Session, ip: str, sessao: str) -> list[str]:
    """Nomes de todos os usuários cadastrados na catraca, sem repetidos e em ordem alfabética."""
    try:
        resposta = http.post(
            f"http://{ip}/load_objects.fcgi?session={sessao}",
            json={"object": "users"},
            timeout=TIMEOUT_USUARIOS,
        )
        resposta.raise_for_status()
    except requests.RequestException as erro:
        raise CatracaError(_mensagem_de_rede(ip, erro)) from erro

    try:
        usuarios = json.loads(_decodificar(resposta.content))["users"]
        nomes = [normalizar_nome(str(usuario.get("name") or "")) for usuario in usuarios]
    except (ValueError, KeyError, TypeError, AttributeError) as erro:
        raise CatracaError("A catraca devolveu a lista de usuários em um formato inesperado.") from erro
    _todos, unicos = mesclar_usuarios([], nomes)
    return sorted(unicos, key=str.casefold)


def listar_usuarios(ip: str, usuario: str, senha: str, progresso: Progresso | None = None) -> list[str]:
    avisar = progresso or (lambda _mensagem: None)
    http = criar_sessao_http()
    try:
        avisar(f"Conectando à catraca em {ip}...")
        sessao = fazer_login(http, ip, usuario, senha)
        avisar("Buscando os usuários cadastrados...")
        return consultar_usuarios(http, ip, sessao)
    finally:
        http.close()


# ------------------------------------------------------------ Relatório
def _ler_data_hora(texto: str) -> datetime | None:
    try:
        return datetime.strptime(texto.strip(), FORMATO_DATA_HORA)
    except ValueError:
        return None


def montar_relatorio(
    linhas: Iterable[list[str]], colaboradores: Iterable[str], inicio: date, fim: date
) -> Relatorio:
    """Mantém só os colaboradores da lista, na ordem em que a catraca devolveu."""
    colaboradores = list(colaboradores)
    por_nome = {nome.casefold(): nome for nome in colaboradores}
    acessos: list[Acesso] = []
    linhas_csv: list[tuple[str, ...]] = []
    for linha in linhas:
        if not linha:
            continue
        nome = por_nome.get(linha[0].strip().casefold())
        if nome is None:
            continue
        texto = linha[1].strip() if len(linha) > 1 else ""
        acessos.append(Acesso(nome, _ler_data_hora(texto), texto))
        linhas_csv.append(tuple(linha))

    resumos = []
    for nome in colaboradores:
        do_colaborador = [a for a in acessos if a.nome == nome]
        datas = [a.data_hora for a in do_colaborador if a.data_hora]
        resumos.append(
            ResumoColaborador(
                nome,
                len(do_colaborador),
                min(datas, default=None),
                max(datas, default=None),
            )
        )
    return Relatorio(inicio, fim, tuple(acessos), tuple(resumos), tuple(linhas_csv))


def gerar_relatorio(
    ip: str,
    usuario: str,
    senha: str,
    inicio: date,
    fim: date,
    colaboradores: Iterable[str],
    progresso: Progresso | None = None,
) -> Relatorio:
    avisar = progresso or (lambda _mensagem: None)
    if fim < inicio:
        raise CatracaError("A data final não pode ser anterior à data inicial.")

    http = criar_sessao_http()
    try:
        avisar(f"Conectando à catraca em {ip}...")
        sessao = fazer_login(http, ip, usuario, senha)
        avisar("Consultando os acessos do período...")
        linhas = consultar_acessos(http, ip, sessao, inicio, fim)
        avisar("Organizando o resultado...")
        return montar_relatorio(linhas, colaboradores, inicio, fim)
    finally:
        http.close()


def salvar_csv(relatorio: Relatorio, caminho: str | Path) -> None:
    try:
        with open(caminho, "w", encoding="utf-8", newline="") as arquivo:
            escritor = csv.writer(arquivo, delimiter=";", lineterminator="\r\n")
            escritor.writerow(CABECALHO_CSV)
            escritor.writerows(relatorio.linhas_csv)
    except PermissionError as erro:
        raise CatracaError(
            "Não foi possível gravar o arquivo. Se ele estiver aberto no Excel, feche-o e "
            "tente de novo."
        ) from erro
    except OSError as erro:
        raise CatracaError(f"Não foi possível gravar o arquivo: {erro}") from erro
