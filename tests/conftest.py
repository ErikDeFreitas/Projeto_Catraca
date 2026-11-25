import os
import tempfile

# Antes de qualquer import do pacote: nenhum teste pode tocar a pasta real %LOCALAPPDATA%\SistemaCatraca.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CATRACA_DADOS"] = tempfile.mkdtemp(prefix="catraca_dados_")

import pytest  # noqa: E402
from PySide6 import QtCore  # noqa: E402


class _QSettingsIni(QtCore.QSettings):
    """QSettings(org, app) em arquivo .ini (pasta temporária), nunca no registro do Windows.

    No Qt 6, QSettings(org, app) ignora setDefaultFormat() e usa sempre o registro; por isso a classe é
    trocada em PySide6.QtCore antes de qualquer `from PySide6.QtCore import QSettings`.
    """

    def __init__(self, *args, **kwargs):
        if 1 <= len(args) <= 2 and not kwargs and all(isinstance(a, str) for a in args):
            super().__init__(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, *args)
        else:
            super().__init__(*args, **kwargs)


QtCore.QSettings = _QSettingsIni
from PySide6.QtCore import QSettings  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def _qsettings_fora_do_registro(tmp_path_factory):
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("qsettings")))


@pytest.fixture(autouse=True)
def configuracoes():
    """QSettings de ("TCM", "SistemaCatraca") limpo a cada teste."""
    config = QSettings("TCM", "SistemaCatraca")
    config.clear()
    config.sync()
    yield config
    config.clear()
    config.sync()


@pytest.fixture
def contexto(qtbot):
    """Contexto do módulo com uma janela de verdade como pai dos diálogos."""
    import logging

    from PySide6.QtWidgets import QWidget
    from tcm_ui.modulo import Contexto

    from sistema_catraca import dados

    janela = QWidget()
    qtbot.addWidget(janela)
    return Contexto("TCMSP\\teste", dados.PASTA, "avulso", logging.getLogger("teste"), janela)
