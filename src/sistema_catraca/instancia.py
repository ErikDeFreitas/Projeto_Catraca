"""Instância do Sistema Catraca aberta na casca ou no avulso."""

from PySide6.QtWidgets import QApplication, QWidget
from tcm_ui.modulo import Contexto

from sistema_catraca.tela_relatorio import TelaRelatorio
from sistema_catraca.tela_usuarios import TelaUsuarios
from sistema_catraca.usuarios import ListaUsuarios


class Catraca:
    def __init__(self, contexto: Contexto):
        self.contexto = contexto
        self.lista: ListaUsuarios | None = None
        self.relatorio: TelaRelatorio | None = None
        self.usuarios: TelaUsuarios | None = None

    def _criar_relatorio(self) -> TelaRelatorio:
        # A página Usuários usa a conexão do Relatório; por isso o Relatório nasce primeiro, seja qual for a aberta.
        if self.relatorio is None:
            self.lista = ListaUsuarios()
            self.relatorio = TelaRelatorio(self.contexto, self.lista)
            self._cancelar_ao_sair(self.relatorio)
        return self.relatorio

    def _cancelar_ao_sair(self, pagina) -> None:
        # Ao sair, só descarta a consulta (não espera a rede). A conexão com um método de QObject
        # some sozinha quando a página é destruída.
        QApplication.instance().aboutToQuit.connect(pagina.cancelar)

    def widget(self, chave_pagina: str) -> QWidget:
        if chave_pagina not in ("relatorio", "usuarios"):
            raise KeyError(chave_pagina)
        relatorio = self._criar_relatorio()
        if chave_pagina == "relatorio":
            return relatorio
        if self.usuarios is None:
            self.usuarios = TelaUsuarios(self.contexto, self.lista, relatorio)
            self._cancelar_ao_sair(self.usuarios)
        return self.usuarios

    def acoes_cabecalho(self, chave_pagina: str) -> list[QWidget]:
        return []

    def pode_fechar(self) -> bool:
        paginas = (self.relatorio, self.usuarios)
        return not any(pagina is not None and pagina.rodando for pagina in paginas)  # relatório na tela não bloqueia
