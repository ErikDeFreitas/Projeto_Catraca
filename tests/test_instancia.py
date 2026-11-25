import threading

import pytest
from PySide6.QtWidgets import QApplication
from tcm_ui.components import Modal

from sistema_catraca import catraca_core as core
from sistema_catraca.instancia import Catraca
from sistema_catraca.tela_relatorio import TelaRelatorio
from sistema_catraca.tela_usuarios import TelaUsuarios


@pytest.fixture
def inst(qtbot, contexto):
    objeto = Catraca(contexto)
    yield objeto
    for pagina in (objeto.relatorio, objeto.usuarios):
        if pagina is not None:
            qtbot.addWidget(pagina)


@pytest.fixture
def modais(monkeypatch):
    informados = []
    monkeypatch.setattr(Modal, "informar", lambda *args, **kw: informados.append(args))
    return informados


class Presa:
    """Consulta falsa presa num Event: simula a catraca que não responde."""

    def __init__(self, monkeypatch, nome, resultado):
        self.liberar = threading.Event()
        self.comecou = threading.Event()
        self.resultado = resultado
        monkeypatch.setattr(core, nome, self)

    def __call__(self, *args, **kwargs):
        self.comecou.set()
        self.liberar.wait(10)
        return self.resultado


def preparar(inst):
    relatorio = inst.widget("relatorio")
    relatorio.lembrar_conexao("127.0.0.1:8080", "admin_teste", "segredo_teste")
    inst.lista.adicionar("Ana Teste")  # sem ninguém marcado o relatório nem começa


def test_widget_e_criado_uma_vez_por_pagina(inst):
    relatorio, usuarios = inst.widget("relatorio"), inst.widget("usuarios")
    assert isinstance(relatorio, TelaRelatorio) and isinstance(usuarios, TelaUsuarios)
    assert inst.widget("relatorio") is relatorio and inst.widget("usuarios") is usuarios
    assert relatorio is not usuarios


def test_pagina_desconhecida(inst):
    with pytest.raises(KeyError):
        inst.widget("outra")
    assert inst.relatorio is None  # nada foi criado à toa


def test_usuarios_antes_do_relatorio_funciona(inst):
    usuarios = inst.widget("usuarios")
    assert usuarios._relatorio is inst.widget("relatorio")
    assert usuarios._lista is inst.relatorio._lista  # as duas páginas dividem a mesma lista


def test_sem_acoes_no_cabecalho(inst):
    assert inst.acoes_cabecalho("relatorio") == [] and inst.acoes_cabecalho("usuarios") == []


def test_pode_fechar_antes_de_abrir_qualquer_pagina(inst):
    assert inst.pode_fechar()


def test_relatorio_na_tela_sem_salvar_nao_bloqueia(inst):
    inst.widget("relatorio")
    inst.widget("usuarios")
    assert inst.pode_fechar()


def test_pode_fechar_so_sem_consulta_do_relatorio(qtbot, inst, monkeypatch, modais):
    presa = Presa(monkeypatch, "gerar_relatorio", None)
    preparar(inst)
    inst.widget("relatorio").gerar()
    try:
        assert presa.comecou.wait(5)
        assert not inst.pode_fechar()
    finally:
        presa.liberar.set()
    qtbot.waitUntil(inst.pode_fechar, timeout=5000)


def test_pode_fechar_so_sem_busca_de_usuarios(qtbot, inst, monkeypatch, modais):
    presa = Presa(monkeypatch, "listar_usuarios", ["Ana Teste"])
    preparar(inst)
    inst.widget("usuarios").botao_buscar.click()
    try:
        assert presa.comecou.wait(5)
        assert not inst.pode_fechar()
    finally:
        presa.liberar.set()
    qtbot.waitUntil(inst.pode_fechar, timeout=5000)


def test_ao_sair_do_programa_cancela_as_duas_paginas_sem_esperar_a_rede(qtbot, inst, monkeypatch, modais):
    presa_relatorio = Presa(monkeypatch, "gerar_relatorio", None)
    presa_usuarios = Presa(monkeypatch, "listar_usuarios", ["Diego Teste"])
    preparar(inst)
    relatorio, usuarios = inst.widget("relatorio"), inst.widget("usuarios")
    relatorio.gerar()
    usuarios.botao_buscar.click()
    assert presa_relatorio.comecou.wait(5) and presa_usuarios.comecou.wait(5)
    assert relatorio.rodando and usuarios.rodando

    QApplication.instance().aboutToQuit.emit()
    assert not relatorio.rodando and not usuarios.rodando  # na hora, com a "rede" ainda presa
    assert inst.pode_fechar()

    presa_relatorio.liberar.set()
    presa_usuarios.liberar.set()
    qtbot.wait(300)  # nenhum sinal chega depois
    assert modais == []
    assert relatorio.relatorio is None
    assert "Diego Teste" not in inst.relatorio._lista.nomes
