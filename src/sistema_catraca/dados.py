"""Pasta de dados e configurações do Sistema Catraca. Nada é criado ao importar."""

import os
from pathlib import Path

NOME_APLICACAO = "SistemaCatraca"
ORGANIZACAO = "TCM"


def pasta_dados() -> Path:
    var = os.environ.get("CATRACA_DADOS")
    if var:
        return Path(var)
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / NOME_APLICACAO


PASTA: Path = pasta_dados()


def configuracoes():
    """QSettings da aplicação (organização TCM)."""
    from PySide6.QtCore import QSettings

    return QSettings(ORGANIZACAO, NOME_APLICACAO)
