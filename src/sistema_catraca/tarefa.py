"""Executa uma consulta à catraca numa thread própria, para a interface nunca travar."""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal

from sistema_catraca import catraca_core as core


class TarefaFundo(QObject):
    """A biblioteca HTTP não permite interromper uma espera. Por isso a thread é daemon e, ao
    cancelar ou fechar o programa, a tarefa apenas silencia os sinais: o resultado é descartado."""

    progresso = Signal(int, str)
    sucesso = Signal(int, object)
    falha = Signal(int, str)

    def __init__(self, id_tarefa: int, tarefa: Callable[[Callable[[str], None]], object],
                 parent: QObject | None = None):
        super().__init__(parent)
        self._id = id_tarefa
        self._tarefa = tarefa
        self._cancelada = threading.Event()
        self._thread: threading.Thread | None = None

    def iniciar(self) -> None:
        self._thread = threading.Thread(target=self._executar, daemon=True)
        self._thread.start()

    def cancelar(self) -> None:
        """Depois disto a thread (que pode ainda estar esperando a rede) não emite mais nada."""
        self._cancelada.set()

    def conectar(self, ao_progresso, ao_sucesso, ao_falha) -> None:
        enfileirada = Qt.ConnectionType.QueuedConnection
        self.progresso.connect(ao_progresso, enfileirada)
        self.sucesso.connect(ao_sucesso, enfileirada)
        self.falha.connect(ao_falha, enfileirada)

    def _executar(self) -> None:
        try:
            resultado = self._tarefa(lambda mensagem: self._emitir(self.progresso, mensagem))
        except core.CatracaError as erro:
            self._emitir(self.falha, str(erro))
        except Exception as erro:  # a interface precisa sempre sair do estado "ocupado"
            self._emitir(self.falha, f"Erro inesperado: {erro}")
        else:
            self._emitir(self.sucesso, resultado)

    def _emitir(self, sinal, valor) -> None:
        if self._cancelada.is_set():
            return
        try:
            sinal.emit(self._id, valor)
        except RuntimeError:  # o objeto Qt já foi destruído (programa fechando)
            pass
