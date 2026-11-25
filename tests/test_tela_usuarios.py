import json
import threading

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication
from tcm_ui.components import Botao, CampoSenha, Modal

from sistema_catraca import catraca_core as core
from sistema_catraca.tela_relatorio import TelaRelatorio
from sistema_catraca.tela_usuarios import TelaUsuarios
from sistema_catraca.usuarios import ListaUsuarios

NOMES = ["Ana Teste", "Bruno Teste", "Carla Teste"]


@pytest.fixture
def lista(configuracoes):
    configuracoes.setValue("colaboradores", json.dumps(NOMES))
    configuracoes.sync()
    return ListaUsuarios(configuracoes)


class Modais:
    def __init__(self, monkeypatch):
        self.informados = []
        self.confirmacoes = []
        self.confirmar = True
        monkeypatch.setattr(Modal, "informar", lambda *args, **kw: self.informados.append(args))
        monkeypatch.setattr(Modal, "confirmar", lambda *args, **kw: (self.confirmacoes.append((args, kw)),
                                                                     self.confirmar)[1])


@pytest.fixture
def modais(monkeypatch):
    return Modais(monkeypatch)


class Busca:
    """Troca `catraca_core.listar_usuarios` por um falso (nunca há rede nos testes)."""

    def __init__(self, monkeypatch):
        self.chamadas = []
        self.resultado = ["Ana Teste", "Bruno Teste", "Carla Teste", "Diego Teste"]
        self.erro = None
        self.travar: threading.Event | None = None
        monkeypatch.setattr(core, "listar_usuarios", self)

    def __call__(self, ip, usuario, senha, progresso=None):
        self.chamadas.append((ip, usuario, senha))
        if progresso:
            progresso("Buscando...")
        if self.travar is not None:
            self.travar.wait(10)
        if self.erro:
            raise self.erro
        return self.resultado


@pytest.fixture
def busca(monkeypatch):
    return Busca(monkeypatch)


@pytest.fixture
def relatorio(qtbot, contexto, lista):
    pagina = TelaRelatorio(contexto, lista)
    qtbot.addWidget(pagina)
    return pagina


@pytest.fixture
def tela(qtbot, contexto, lista, relatorio, monkeypatch):
    pagina = TelaUsuarios(contexto, lista, relatorio)
    qtbot.addWidget(pagina)
    pagina.pedidos_de_senha = []
    monkeypatch.setattr(pagina, "pedir_senha", lambda ip, usuario: (pagina.pedidos_de_senha.append((ip, usuario)),
                                                                    pagina.senha_digitada)[1])
    pagina.senha_digitada = ""
    return pagina


def conectar(relatorio, senha=""):
    relatorio.campo_ip.setText("127.0.0.1:8080")
    relatorio.campo_usuario.setText("admin_teste")
    relatorio.campo_senha.setText(senha)


def linha_de(tela, nome):
    return next(i for i in range(tela.tabela.rowCount()) if tela.tabela.item(i, 0).text() == nome)


def marcado(tela, nome):
    return tela.tabela.item(linha_de(tela, nome), 0).checkState() == Qt.Checked


def clicar_linha(qtbot, tela, nome):
    tela.show()
    qtbot.waitExposed(tela)
    centro = tela.tabela.visualItemRect(tela.tabela.item(linha_de(tela, nome), 0)).center()
    qtbot.mouseClick(tela.tabela.viewport(), Qt.LeftButton, pos=centro)


def visiveis(tela):
    return {tela.tabela.item(i, 0).text() for i in range(tela.tabela.rowCount()) if not tela.tabela.isRowHidden(i)}


def test_lista_toda_marcada_na_abertura(tela):
    assert [tela.tabela.item(i, 0).text() for i in range(3)] == NOMES
    assert all(marcado(tela, nome) for nome in NOMES)
    assert tela.rotulo_contagem.text() == "3 de 3 usuários marcados"
    assert tela._pilha.currentWidget() is tela.tabela


@pytest.fixture
def pagina_vazia(qtbot, contexto, configuracoes):
    """Primeira abertura do programa: nada salvo, lista vazia."""
    configuracoes.clear()
    configuracoes.sync()
    lista = ListaUsuarios(configuracoes)
    relatorio = TelaRelatorio(contexto, lista)
    qtbot.addWidget(relatorio)
    pagina = TelaUsuarios(contexto, lista, relatorio)
    qtbot.addWidget(pagina)
    return pagina


def test_primeira_abertura_sem_usuarios_mostra_estado_vazio(pagina_vazia):
    pagina = pagina_vazia
    assert pagina._pilha.currentWidget() is pagina.estado_vazio
    assert pagina.tabela.rowCount() == 0
    assert pagina.rotulo_contagem.text() == "0 de 0 usuários marcados"
    assert "Buscar na catraca" in pagina.estado_vazio.descricao


def test_estado_vazio_some_ao_adicionar_o_primeiro_usuario(pagina_vazia):
    pagina = pagina_vazia
    pagina.campo_nome.setText("Ana Teste")
    pagina.botao_adicionar.click()
    assert pagina._pilha.currentWidget() is pagina.tabela and pagina.tabela.rowCount() == 1


def test_clicar_na_linha_alterna_a_marcacao(qtbot, tela, lista):
    clicar_linha(qtbot, tela, "Bruno Teste")
    assert not lista.esta_marcado("Bruno Teste") and not marcado(tela, "Bruno Teste")
    assert tela.rotulo_contagem.text() == "2 de 3 usuários marcados"
    clicar_linha(qtbot, tela, "Bruno Teste")
    assert lista.esta_marcado("Bruno Teste") and marcado(tela, "Bruno Teste")


def test_espaco_alterna_a_linha_atual(qtbot, tela, lista):
    tela.tabela.setCurrentCell(linha_de(tela, "Carla Teste"), 0)
    qtbot.keyClick(tela.tabela, Qt.Key_Space)
    assert not lista.esta_marcado("Carla Teste") and not marcado(tela, "Carla Teste")
    qtbot.keyClick(tela.tabela, Qt.Key_Space)
    assert lista.esta_marcado("Carla Teste")


def test_marcacao_grava_no_formato_da_versao_1(qtbot, tela, configuracoes):
    clicar_linha(qtbot, tela, "Ana Teste")
    configuracoes.sync()
    assert json.loads(configuracoes.value("selecionados")) == ["Bruno Teste", "Carla Teste"]


def test_marcar_todos_e_desmarcar_todos(tela, lista):
    tela.botao_desmarcar_todos.click()
    assert lista.marcados == []
    assert not any(marcado(tela, nome) for nome in NOMES)
    tela.botao_marcar_todos.click()
    assert lista.marcados == NOMES


def test_marcar_todos_com_pesquisa_ativa_vale_so_para_os_visiveis(tela, lista):
    tela.botao_desmarcar_todos.click()
    tela.pesquisa.setText("an")  # Ana
    assert visiveis(tela) == {"Ana Teste"}
    tela.botao_marcar_todos.click()
    assert lista.marcados == ["Ana Teste"]
    tela.pesquisa.setText("")
    tela.botao_marcar_todos.click()
    tela.pesquisa.setText("bru")
    tela.botao_desmarcar_todos.click()
    assert lista.marcados == ["Ana Teste", "Carla Teste"]


def test_adicionar_entra_marcado_e_limpa_o_campo(tela, lista):
    tela.campo_nome.setText("  Diego   Teste ")
    tela.botao_adicionar.click()
    assert lista.nomes[-1] == "Diego Teste" and lista.esta_marcado("Diego Teste")
    assert tela.campo_nome.text() == ""
    assert marcado(tela, "Diego Teste")


def test_adicionar_pelo_enter(tela, lista):
    tela.campo_nome.setText("Diego Teste")
    tela.campo_nome.returnPressed.emit()
    assert "Diego Teste" in lista.nomes


def test_adicionar_repetido_mostra_erro_no_campo(tela, lista):
    tela.campo_nome.setText("ana teste")
    tela.botao_adicionar.click()
    assert lista.nomes == NOMES
    assert tela.campo_nome.property("erro") is True
    assert tela._campo_nome._rodape.text() == "Este colaborador já está na lista."
    tela.campo_nome.textEdited.emit("an")  # digitar limpa o erro
    assert tela.campo_nome.property("erro") is False
    assert tela._campo_nome._rodape.isHidden()


def test_adicionar_vazio_mostra_erro(tela, lista):
    tela.botao_adicionar.click()
    assert tela.campo_nome.property("erro") is True and lista.nomes == NOMES


def test_remover_pede_confirmacao(qtbot, tela, lista, modais):
    clicar_linha(qtbot, tela, "Bruno Teste")
    assert tela.botao_remover.isEnabled()
    modais.confirmar = False
    tela.botao_remover.click()
    assert lista.nomes == NOMES
    (args, kw), = modais.confirmacoes
    assert args[0] is tela.contexto.janela and args[1] == "Remover usuário"
    assert kw == {"texto_ok": "Remover", "destrutivo": True}
    modais.confirmar = True
    tela.botao_remover.click()
    assert lista.nomes == ["Ana Teste", "Carla Teste"]
    assert tela.tabela.rowCount() == 2


def test_remover_desabilitado_sem_selecao(tela):
    assert not tela.botao_remover.isEnabled()


def test_buscar_sem_ip_ou_usuario_avisa(tela, relatorio, busca, modais):
    relatorio.campo_ip.setText("127.0.0.1:8080")  # falta o usuário
    tela.botao_buscar.click()
    (janela, titulo, _texto, tom), = modais.informados
    assert janela is tela.contexto.janela and (titulo, tom) == ("Conexão incompleta", "perigo")
    assert busca.chamadas == [] and tela.pedidos_de_senha == []


def test_buscar_sem_senha_pede_a_senha_e_cancelar_nao_busca(tela, relatorio, busca, modais):
    conectar(relatorio)
    tela.senha_digitada = ""  # a pessoa cancelou
    tela.botao_buscar.click()
    assert tela.pedidos_de_senha == [("127.0.0.1:8080", "admin_teste")]
    assert busca.chamadas == [] and not tela.rodando
    assert relatorio.campo_senha.text() == ""


def test_buscar_com_senha_digitada_no_modal(qtbot, tela, relatorio, busca, modais):
    conectar(relatorio)
    tela.senha_digitada = "segredo_teste"
    tela.botao_buscar.click()
    qtbot.waitUntil(lambda: not tela.rodando, timeout=5000)
    assert busca.chamadas == [("127.0.0.1:8080", "admin_teste", "segredo_teste")]
    assert relatorio.campo_senha.text() == "segredo_teste"  # fica no campo, nunca no disco


def test_buscar_usa_a_senha_do_relatorio_sem_perguntar(qtbot, tela, relatorio, busca, modais):
    conectar(relatorio, "segredo_teste")
    tela.botao_buscar.click()
    qtbot.waitUntil(lambda: not tela.rodando, timeout=5000)
    assert tela.pedidos_de_senha == []
    assert busca.chamadas == [("127.0.0.1:8080", "admin_teste", "segredo_teste")]


def test_sucesso_mescla_novos_desmarcados_e_lista_quem_nao_existe(qtbot, tela, relatorio, lista, busca, modais):
    lista.adicionar("Eva Teste")  # entra marcada, mas não existe na catraca
    conectar(relatorio, "segredo_teste")
    busca.resultado = ["Ana Teste", "Diego Teste"]
    tela.botao_buscar.click()
    qtbot.waitUntil(lambda: not tela.rodando, timeout=5000)

    assert lista.nomes == [*NOMES, "Eva Teste", "Diego Teste"]
    assert lista.esta_marcado("Eva Teste") and not lista.esta_marcado("Diego Teste")
    assert not marcado(tela, "Diego Teste")
    (janela, titulo, texto, tom), = modais.informados
    assert janela is tela.contexto.janela and (titulo, tom) == ("Usuários atualizados", "sucesso")
    assert texto.startswith("2 usuários encontrados na catraca. 1 novo foi adicionado à lista, desmarcados")
    assert "Não estão cadastrados na catraca com este nome: Bruno Teste, Carla Teste, Eva Teste." in texto


def test_sucesso_sem_novos_diz_que_todos_ja_estavam(qtbot, tela, relatorio, busca, modais):
    conectar(relatorio, "segredo_teste")
    busca.resultado = list(NOMES)
    tela.botao_buscar.click()
    qtbot.waitUntil(lambda: not tela.rodando, timeout=5000)
    assert modais.informados[0][2] == "3 usuários encontrados na catraca. Todos já estavam na lista."


def test_resumo_limita_os_nomes_que_faltam(tela, lista):
    nomes = [f"Pessoa {i:02d} Teste" for i in range(12)]
    for nome in nomes:
        lista.adicionar(nome)
    texto = tela._resumo(["Outra Teste"], [])
    # 15 nomes na lista, nenhum na catraca: os 8 primeiros aparecem e o resto vira "e mais 7"
    assert "Pessoa 04 Teste e mais 7." in texto and "Pessoa 05 Teste" not in texto


def test_primeira_busca_preenche_a_lista_vazia(qtbot, contexto, configuracoes, busca, modais):
    lista = ListaUsuarios(configuracoes)
    relatorio = TelaRelatorio(contexto, lista)
    qtbot.addWidget(relatorio)
    pagina = TelaUsuarios(contexto, lista, relatorio)
    qtbot.addWidget(pagina)
    conectar(relatorio, "segredo_teste")
    pagina.botao_buscar.click()
    qtbot.waitUntil(lambda: not pagina.rodando, timeout=5000)
    assert pagina.tabela.rowCount() == 4 and pagina._pilha.currentWidget() is pagina.tabela
    assert lista.marcados == []  # os novos entram desmarcados


def test_falha_da_busca_mostra_modal_e_libera_o_botao(qtbot, tela, relatorio, busca, modais):
    busca.erro = core.CatracaError("Não foi possível falar com a catraca em 127.0.0.1:8080.")
    conectar(relatorio, "segredo_teste")
    tela.botao_buscar.click()
    qtbot.waitUntil(lambda: not tela.rodando, timeout=5000)
    (_janela, titulo, texto, tom), = modais.informados
    assert (titulo, tom) == ("Não foi possível buscar os usuários", "perigo")
    assert texto.startswith("Não foi possível falar com a catraca")
    assert tela.botao_buscar.isEnabled() and tela.progresso_busca.isHidden()


def test_cancelar_abandona_a_busca_e_ignora_o_resultado_tardio(qtbot, tela, relatorio, lista, busca, modais):
    busca.travar = threading.Event()
    conectar(relatorio, "segredo_teste")
    tela.botao_buscar.click()
    assert tela.rodando and not tela.botao_buscar.isEnabled() and not tela.progresso_busca.isHidden()
    tela.cancelar()
    assert not tela.rodando and tela.botao_buscar.isEnabled()
    busca.travar.set()
    qtbot.wait(300)
    assert lista.nomes == NOMES and modais.informados == []


def _responder_ao_modal(acao):
    """Agenda `acao(modal)` para quando o diálogo aberto por `exec()` estiver na tela."""
    def executar():
        modal = QApplication.activeModalWidget()
        assert isinstance(modal, Modal)
        acao(modal)

    QTimer.singleShot(0, executar)


def test_pedir_senha_devolve_o_que_foi_digitado(qtbot, contexto, lista, relatorio):
    pagina = TelaUsuarios(contexto, lista, relatorio)
    qtbot.addWidget(pagina)

    def digitar_e_buscar(modal):
        modal.findChild(CampoSenha).setText("segredo_teste")
        botoes = {b.text().strip(): b for b in modal.findChildren(Botao)}
        botoes["Buscar"].click()

    _responder_ao_modal(digitar_e_buscar)
    assert pagina.pedir_senha("127.0.0.1:8080", "admin_teste") == "segredo_teste"


def test_pedir_senha_cancelado_devolve_vazio(qtbot, contexto, lista, relatorio):
    pagina = TelaUsuarios(contexto, lista, relatorio)
    qtbot.addWidget(pagina)

    def cancelar(modal):
        modal.findChild(CampoSenha).setText("digitada_e_desistiu")
        {b.text().strip(): b for b in modal.findChildren(Botao)}["Cancelar"].click()

    _responder_ao_modal(cancelar)
    assert pagina.pedir_senha("127.0.0.1:8080", "admin_teste") == ""


def test_pedir_senha_enter_confirma(qtbot, contexto, lista, relatorio):
    pagina = TelaUsuarios(contexto, lista, relatorio)
    qtbot.addWidget(pagina)

    def enter(modal):
        campo = modal.findChild(CampoSenha)
        campo.setText("segredo_teste")
        campo.returnPressed.emit()

    _responder_ao_modal(enter)
    assert pagina.pedir_senha("127.0.0.1:8080", "admin_teste") == "segredo_teste"
