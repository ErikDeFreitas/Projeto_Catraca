import threading

from PySide6.QtCore import QObject

from sistema_catraca import catraca_core as core
from sistema_catraca.tarefa import TarefaFundo


class Receptor(QObject):
    def __init__(self):
        super().__init__()
        self.recebidos = []

    def progresso(self, id_tarefa, mensagem):
        self.recebidos.append(("progresso", id_tarefa, mensagem))

    def sucesso(self, id_tarefa, resultado):
        self.recebidos.append(("sucesso", id_tarefa, resultado))

    def falha(self, id_tarefa, mensagem):
        self.recebidos.append(("falha", id_tarefa, mensagem))

    def final(self):
        return [r for r in self.recebidos if r[0] != "progresso"]


def _rodar(qtbot, trabalho):
    receptor = Receptor()
    tarefa = TarefaFundo(7, trabalho)
    tarefa.conectar(receptor.progresso, receptor.sucesso, receptor.falha)
    tarefa.iniciar()
    qtbot.waitUntil(lambda: bool(receptor.final()), timeout=5000)
    return receptor


def test_sucesso_chega_com_progresso(qtbot):
    def trabalho(avisar):
        avisar("Conectando...")
        return ["Ana Teste"]

    receptor = _rodar(qtbot, trabalho)
    assert receptor.recebidos == [("progresso", 7, "Conectando..."), ("sucesso", 7, ["Ana Teste"])]


def test_erro_da_catraca_chega_com_a_mensagem_pronta(qtbot):
    def trabalho(avisar):
        raise core.CatracaError("Não foi possível falar com a catraca em 127.0.0.1:1.")

    receptor = _rodar(qtbot, trabalho)
    assert receptor.final() == [("falha", 7, "Não foi possível falar com a catraca em 127.0.0.1:1.")]


def test_excecao_qualquer_vira_erro_inesperado(qtbot):
    def trabalho(avisar):
        raise ValueError("quebrou")

    receptor = _rodar(qtbot, trabalho)
    assert receptor.final() == [("falha", 7, "Erro inesperado: quebrou")]


def test_roda_em_thread_daemon_fora_da_principal(qtbot):
    visto = {}

    def trabalho(avisar):
        visto["thread"] = threading.current_thread()
        return 1

    _rodar(qtbot, trabalho)
    assert visto["thread"] is not threading.main_thread()
    assert visto["thread"].daemon


def test_cancelar_silencia_todos_os_sinais(qtbot):
    comecou, liberar = threading.Event(), threading.Event()

    def trabalho(avisar):
        comecou.set()
        liberar.wait(10)
        avisar("tarde demais")
        return "resultado tardio"

    receptor = Receptor()
    tarefa = TarefaFundo(1, trabalho)
    tarefa.conectar(receptor.progresso, receptor.sucesso, receptor.falha)
    tarefa.iniciar()
    assert comecou.wait(5)
    tarefa.cancelar()
    liberar.set()
    tarefa._thread.join(5)
    assert not tarefa._thread.is_alive()
    qtbot.wait(100)  # deixa passar qualquer sinal enfileirado
    assert receptor.recebidos == []


def test_cancelar_tambem_silencia_a_falha(qtbot):
    comecou, liberar = threading.Event(), threading.Event()

    def trabalho(avisar):
        comecou.set()
        liberar.wait(10)
        raise core.CatracaError("falha tardia")

    receptor = Receptor()
    tarefa = TarefaFundo(1, trabalho)
    tarefa.conectar(receptor.progresso, receptor.sucesso, receptor.falha)
    tarefa.iniciar()
    assert comecou.wait(5)
    tarefa.cancelar()
    liberar.set()
    tarefa._thread.join(5)
    qtbot.wait(100)
    assert receptor.recebidos == []
