"""Ponto de entrada do Sistema Catraca avulso (.exe ou `python main.py`)."""

import sys

from PySide6.QtCore import QSettings
from tcm_ui.avulso import rodar_avulso

from sistema_catraca import dados
from sistema_catraca.modulo import MODULO

_TEMAS_1_0_0 = {"light": "claro", "dark": "escuro"}


def migrar_tema(config: QSettings) -> None:
    """Leva a preferência de tema da 1.0.0 (`theme`) para a chave nova (`aparencia/tema`)."""
    if config.contains("aparencia/tema"):
        return
    novo = _TEMAS_1_0_0.get(str(config.value("theme", "")))
    if novo:
        config.setValue("aparencia/tema", novo)


def main() -> None:
    migrar_tema(dados.configuracoes())
    sys.exit(rodar_avulso(MODULO))


if __name__ == "__main__":
    main()
