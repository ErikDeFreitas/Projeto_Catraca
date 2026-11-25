"""Usuários conhecidos e quais estão marcados para o relatório."""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QSettings, Signal

from sistema_catraca import catraca_core as core
from sistema_catraca import dados


def _ler_nomes(bruto: object) -> list[str] | None:
    if not bruto:
        return None
    try:
        nomes = json.loads(str(bruto))
    except ValueError:
        return None
    if isinstance(nomes, list) and all(isinstance(nome, str) for nome in nomes):
        return nomes
    return None


class ListaUsuarios(QObject):
    """Só é gravado depois da primeira alteração. Sem marcação salva, todos entram no relatório,
    como nas versões anteriores."""

    mudou = Signal()  # a lista mudou
    marcacao_mudou = Signal()  # as marcações mudaram
    _CHAVE_NOMES = "colaboradores"
    _CHAVE_MARCADOS = "selecionados"

    def __init__(self, configuracoes: QSettings | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._config = configuracoes if configuracoes is not None else dados.configuracoes()
        self._nomes = _ler_nomes(self._config.value(self._CHAVE_NOMES)) or list(core.COLABORADORES_PADRAO)
        marcados = _ler_nomes(self._config.value(self._CHAVE_MARCADOS))
        self._marcados = {nome.casefold() for nome in (self._nomes if marcados is None else marcados)}

    @property
    def nomes(self) -> list[str]:
        return list(self._nomes)

    @property
    def marcados(self) -> list[str]:
        return [nome for nome in self._nomes if self.esta_marcado(nome)]

    def esta_marcado(self, nome: str) -> bool:
        return nome.casefold() in self._marcados

    def marcar(self, nomes: list[str], marcado: bool) -> None:
        chaves = {nome.casefold() for nome in nomes}
        novos = self._marcados | chaves if marcado else self._marcados - chaves
        if novos != self._marcados:
            self._marcados = novos
            self._gravar_marcacao()

    def adicionar(self, nome: str) -> None:
        """Quem é digitado à mão já entra marcado."""
        nomes = core.adicionar_colaborador(self._nomes, nome)
        self._marcados.add(nomes[-1].casefold())
        self._gravar_nomes(nomes)
        self._gravar_marcacao()

    def remover(self, nome: str) -> None:
        self._marcados.discard(nome.casefold())
        self._gravar_nomes([existente for existente in self._nomes if existente != nome])
        self._gravar_marcacao()

    def mesclar(self, encontrados: list[str]) -> list[str]:
        """Acrescenta os usuários da catraca que faltam, desmarcados. Devolve os novos."""
        nomes, novos = core.mesclar_usuarios(self._nomes, encontrados)
        if novos:
            self._gravar_nomes(nomes)
        return novos

    def _gravar_nomes(self, nomes: list[str]) -> None:
        self._nomes = nomes
        self._config.setValue(self._CHAVE_NOMES, json.dumps(nomes, ensure_ascii=False))
        self.mudou.emit()

    def _gravar_marcacao(self) -> None:
        self._config.setValue(self._CHAVE_MARCADOS, json.dumps(self.marcados, ensure_ascii=False))
        self.marcacao_mudou.emit()
