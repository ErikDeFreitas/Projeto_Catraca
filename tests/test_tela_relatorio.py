import json
import threading
from datetime import date, datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog
from tcm_ui.components import CampoData, CampoSenha, Etiqueta, Modal

from sistema_catraca import catraca_core as core
from sistema_catraca import tela_relatorio
from sistema_catraca.tela_relatorio import TelaRelatorio, limpar_host
from sistema_catraca.usuarios import ListaUsuarios

NOMES = ["Ana Teste", "Bruno Teste", "Carla Teste"]


def relatorio_falso(inicio=date(2026, 10, 1), fim=date(2026, 10, 15)):
    """Ana com 2 registros, Bruno com 10 e Carla sem nenhum ("10" < "2" se ordenar como texto)."""
    linhas = [["Ana Teste", f"0{dia}/10/2026 08:00:00"] for dia in (1, 2)]
    linhas += [["Bruno Teste", f"{dia:02d}/10/2026 {hora:02d}:15:00"] for dia in range(3, 8) for hora in (8, 17)]
    return core.montar_relatorio(linhas, NOMES, inicio, fim)


@pytest.fixture
def lista(configuracoes):
    configuracoes.setValue("colaboradores", json.dumps(NOMES))
    configuracoes.sync()
    return ListaUsuarios(configuracoes)


class Modais:
    """Troca os diálogos por falsos: guarda o que foi mostrado e devolve a escolha configurada."""

    def __init__(self, monkeypatch):
        self.informados = []
        self.escolhas = []
        self.resposta = "fechar"
        monkeypatch.setattr(Modal, "informar", lambda *args, **kw: self.informados.append(args))
        monkeypatch.setattr(Modal, "escolher", lambda *args, **kw: (self.escolhas.append(args), self.resposta)[1])


@pytest.fixture
def modais(monkeypatch):
    return Modais(monkeypatch)


class Consulta:
    """Troca `catraca_core.gerar_relatorio` por um falso (nunca há rede nos testes)."""

    def __init__(self, monkeypatch):
        self.chamadas = []
        self.resultado = relatorio_falso()
        self.erro = None
        self.travar: threading.Event | None = None
        self.comecou = threading.Event()
        monkeypatch.setattr(core, "gerar_relatorio", self)

    def __call__(self, ip, usuario, senha, inicio, fim, colaboradores, progresso=None):
        self.chamadas.append((ip, usuario, senha, inicio, fim, list(colaboradores)))
        if progresso:
            progresso("Consultando...")
        self.comecou.set()
        if self.travar is not None:
            self.travar.wait(10)
        if self.erro:
            raise self.erro
        return self.resultado


@pytest.fixture
def consulta(monkeypatch):
    return Consulta(monkeypatch)


@pytest.fixture
def tela(qtbot, contexto, lista):
    pagina = TelaRelatorio(contexto, lista)
    qtbot.addWidget(pagina)
    return pagina


def preencher(tela, ip="127.0.0.1:8080", usuario="admin_teste", senha="segredo_teste"):
    tela.campo_ip.setText(ip)
    tela.campo_usuario.setText(usuario)
    tela.campo_senha.setText(senha)


def gerar_e_esperar(qtbot, tela):
    tela.gerar()
    qtbot.waitUntil(lambda: not tela.rodando, timeout=5000)


def visiveis(tabela, coluna):
    return {tabela.item(i, coluna).text() for i in range(tabela.rowCount()) if not tabela.isRowHidden(i)}


def texto_etiqueta(tela, linha):
    return tela.tabela_resumo.cellWidget(linha, 4).findChild(Etiqueta).text()


def test_primeira_abertura_tem_campos_vazios_e_placeholders_genericos(tela):
    assert tela.campo_ip.text() == "" and tela.campo_usuario.text() == "" and tela.campo_senha.text() == ""
    assert tela.campo_ip.placeholderText() == "ex.: endereço da catraca"
    assert isinstance(tela.campo_senha, CampoSenha)
    assert isinstance(tela.data_inicial, CampoData) and isinstance(tela.data_final, CampoData)


def test_le_ip_e_usuario_gravados_antes(qtbot, contexto, lista, configuracoes):
    configuracoes.setValue("catraca/ip", "10.0.0.10")
    configuracoes.setValue("catraca/usuario", "admin_teste")
    configuracoes.sync()
    pagina = TelaRelatorio(contexto, lista)
    qtbot.addWidget(pagina)
    assert pagina.conexao() == ("10.0.0.10", "admin_teste", "")


def test_abre_na_quinzena_atual(tela):
    inicio, fim = core.quinzena_de(date.today())
    assert (tela.data_inicial.valor(), tela.data_final.valor()) == (inicio, fim)


def test_limpar_host_aceita_endereco_colado():
    assert limpar_host(" http://10.0.0.10/ ") == "10.0.0.10"
    assert limpar_host("https://10.0.0.10:8080//") == "10.0.0.10:8080"
    assert limpar_host("10.0.0.10") == "10.0.0.10"


def test_rotulo_de_marcados_acompanha_a_lista(tela, lista):
    assert tela.rotulo_marcados.text() == (
        "3 de 3 usuários marcados para o relatório. Altere na página Usuários.")
    lista.marcar(["Ana Teste", "Carla Teste"], False)
    assert tela.rotulo_marcados.text().startswith("1 de 3 usuários marcados")


def test_campos_vazios_mostram_erro_e_nao_consultam(tela, consulta, modais):
    tela.campo_ip.setText("127.0.0.1:8080")
    tela.campo_usuario.setText("admin_teste")
    tela.gerar()  # senha vazia
    assert tela.campo_senha.property("erro") is True
    assert tela.campo_ip.property("erro") is False
    assert consulta.chamadas == [] and not tela.rodando
    tela.campo_senha.textEdited.emit("s")  # digitar limpa o erro
    assert tela.campo_senha.property("erro") is False


def test_primeiro_campo_vazio_recebe_o_foco(tela, consulta, monkeypatch):
    # O foco real depende da janela estar ativa (não está no modo offscreen): confere o pedido de foco.
    focados = []
    for nome in ("campo_ip", "campo_usuario", "campo_senha"):
        monkeypatch.setattr(getattr(tela, nome), "setFocus", lambda n=nome: focados.append(n))
    tela.gerar()
    assert tela.campo_ip.property("erro") is True and tela.campo_usuario.property("erro") is True
    assert focados == ["campo_ip"]
    tela.campo_ip.setText("127.0.0.1:8080")
    tela.gerar()
    assert focados == ["campo_ip", "campo_usuario"]
    assert tela.campo_ip.property("erro") is False  # o erro some assim que o campo é preenchido e validado
    assert consulta.chamadas == []


def test_data_final_antes_da_inicial_avisa_sem_conectar(tela, consulta, modais):
    preencher(tela)
    tela.data_inicial.definir_valor(date(2026, 10, 10))
    tela.data_final.definir_valor(date(2026, 10, 9))
    tela.gerar()
    assert consulta.chamadas == [] and not tela.rodando
    (janela, titulo, _texto, tom), = modais.informados
    assert (titulo, tom) == ("Período inválido", "perigo")
    assert janela is tela.contexto.janela


def test_nenhum_usuario_marcado_avisa_sem_conectar(tela, lista, consulta, modais):
    preencher(tela)
    lista.marcar(NOMES, False)
    tela.gerar()
    assert consulta.chamadas == []
    assert modais.informados[0][1:4:2] == ("Nenhum usuário marcado", "perigo")
    assert "Marque ao menos um usuário" in modais.informados[0][2]


def test_lista_vazia_explica_como_preencher(qtbot, contexto, configuracoes, consulta, modais):
    pagina = TelaRelatorio(contexto, ListaUsuarios(configuracoes))
    qtbot.addWidget(pagina)
    preencher(pagina)
    pagina.gerar()
    assert consulta.chamadas == []
    assert "Buscar na catraca" in modais.informados[0][2]


def test_atalho_mes_anterior_preenche_as_datas(tela):
    tela.botoes_periodo[3].click()
    inicio, fim = core.mes_anterior(date.today())
    assert (tela.data_inicial.valor(), tela.data_final.valor()) == (inicio, fim)


def test_os_cinco_atalhos(tela):
    assert [b.text() for b in tela.botoes_periodo] == [
        "Quinzena atual", "Quinzena anterior", "Mês atual", "Mês anterior", "Últimos 15 dias"]
    tela.botoes_periodo[4].click()
    assert (tela.data_inicial.valor(), tela.data_final.valor()) == core.ultimos_15_dias(date.today())


def test_sucesso_preenche_indicadores_resumo_e_acessos(qtbot, tela, consulta, modais, configuracoes):
    preencher(tela, ip="http://127.0.0.1:8080/", usuario=" admin_teste ")
    tela.data_inicial.definir_valor(date(2026, 10, 1))
    tela.data_final.definir_valor(date(2026, 10, 15))
    gerar_e_esperar(qtbot, tela)

    assert consulta.chamadas == [("127.0.0.1:8080", "admin_teste", "segredo_teste",
                                  date(2026, 10, 1), date(2026, 10, 15), NOMES)]
    assert tela.relatorio is consulta.resultado and not tela.rodando
    assert [tela.ind_registros._valor.text(), tela.ind_colaboradores._valor.text(),
            tela.ind_com._valor.text(), tela.ind_sem._valor.text()] == ["12", "3", "2", "1"]
    assert tela.rotulo_resumo.text().startswith("Período de 01/10/2026 a 15/10/2026.")
    assert "1 colaborador sem registro" in tela.rotulo_resumo.text()

    assert tela.tabela_resumo.rowCount() == 3
    por_nome = {tela.tabela_resumo.item(i, 0).text(): i for i in range(3)}
    assert texto_etiqueta(tela, por_nome["Carla Teste"]) == "Sem registro"
    assert texto_etiqueta(tela, por_nome["Ana Teste"]) == "Com registro"
    assert tela.tabela_resumo.item(por_nome["Bruno Teste"], 2).text() == "03/10/2026 08:15"
    assert tela.tabela_acessos.rowCount() == 12
    assert tela.botao_salvar.isEnabled()
    assert tela._pilha.currentWidget() is tela.tabela_resumo


def test_sucesso_grava_ip_e_usuario_mas_nao_a_senha(qtbot, tela, consulta, modais, configuracoes):
    preencher(tela)
    gerar_e_esperar(qtbot, tela)
    configuracoes.sync()
    assert configuracoes.value("catraca/ip") == "127.0.0.1:8080"
    assert configuracoes.value("catraca/usuario") == "admin_teste"
    assert "segredo_teste" not in Path(configuracoes.fileName()).read_text(encoding="utf-8")
    assert tela.campo_senha.text() == "segredo_teste"  # só no campo, em memória


def test_indicadores_e_acessos_ordenados_por_data(qtbot, tela, consulta, modais):
    preencher(tela)
    gerar_e_esperar(qtbot, tela)
    datas = [tela.tabela_acessos.item(i, 1).text() for i in range(tela.tabela_acessos.rowCount())]
    assert datas == sorted(datas, key=lambda d: datetime.strptime(d, "%d/%m/%Y"))
    assert tela.tabela_acessos.item(0, 3).text() == "Quinta"  # 01/10/2026


def test_falha_da_catraca_mostra_modal_e_devolve_os_botoes(qtbot, tela, consulta, modais):
    consulta.erro = core.CatracaError("Não foi possível falar com a catraca em 127.0.0.1:8080.")
    preencher(tela)
    gerar_e_esperar(qtbot, tela)
    (janela, titulo, texto, tom), = modais.informados
    assert janela is tela.contexto.janela
    assert titulo == "Não foi possível gerar o relatório" and tom == "perigo"
    assert texto.startswith("Não foi possível falar com a catraca")
    assert tela.botao_gerar.isEnabled() and tela.botao_cancelar.isHidden() and tela.progresso.isHidden()
    assert tela.campo_ip.isEnabled() and tela.data_inicial.isEnabled()
    assert tela.relatorio is None


def test_durante_a_consulta_a_tela_fica_ocupada(qtbot, tela, consulta, modais):
    consulta.travar = threading.Event()
    preencher(tela)
    tela.gerar()
    try:
        assert tela.rodando
        assert not tela.botao_gerar.isEnabled() and not tela.botao_cancelar.isHidden()
        assert not tela.progresso.isHidden() and tela.rotulo_marcados.isHidden()
        assert not tela.campo_senha.isEnabled() and not tela.data_final.isEnabled()
        assert not any(b.isEnabled() for b in tela.botoes_periodo)
        qtbot.waitUntil(lambda: tela.rotulo_progresso.text() == "Consultando...", timeout=5000)
        tela.gerar()  # segundo clique é ignorado
        assert len(consulta.chamadas) == 1
    finally:
        consulta.travar.set()
        qtbot.waitUntil(lambda: not tela.rodando, timeout=5000)


def test_cancelar_no_meio_devolve_a_tela_e_ignora_o_resultado_tardio(qtbot, tela, consulta, modais):
    consulta.travar = threading.Event()
    preencher(tela)
    tela.gerar()
    assert consulta.comecou.wait(5)
    tela.cancelar()
    assert not tela.rodando and tela.botao_gerar.isEnabled() and tela.botao_cancelar.isHidden()
    assert tela.rotulo_progresso.text() == ""
    consulta.travar.set()  # a "rede" responde depois
    qtbot.wait(300)
    assert tela.relatorio is None
    assert modais.informados == []
    assert tela.tabela_resumo.rowCount() == 0


def test_cancelar_e_gerar_de_novo_nao_mistura_resultados(qtbot, tela, consulta, modais):
    consulta.travar = threading.Event()
    preencher(tela)
    tela.gerar()
    assert consulta.comecou.wait(5)
    tela.cancelar()
    consulta.resultado = relatorio_falso(date(2026, 9, 1), date(2026, 9, 15))
    consulta.travar = None
    gerar_e_esperar(qtbot, tela)
    assert tela.relatorio.inicio == date(2026, 9, 1)


def test_estado_vazio_antes_do_primeiro_relatorio(tela):
    assert tela._pilha.currentWidget() is tela.estado_vazio
    assert not tela.botao_salvar.isEnabled()
    assert tela.ind_registros._valor.text() == "–"


def test_visao_todos_os_acessos_e_pesquisa(qtbot, tela, consulta, modais):
    preencher(tela)
    gerar_e_esperar(qtbot, tela)
    assert tela._pilha.currentWidget() is tela.tabela_resumo
    tela.selecao_visao.setCurrentIndex(1)
    assert tela._pilha.currentWidget() is tela.tabela_acessos
    tela.pesquisa.setText("ana")  # espera 150 ms antes de filtrar
    qtbot.waitUntil(lambda: visiveis(tela.tabela_acessos, 0) == {"Ana Teste"}, timeout=3000)
    tela.pesquisa.setText("07/10/2026")
    qtbot.waitUntil(lambda: visiveis(tela.tabela_acessos, 1) == {"07/10/2026"}, timeout=3000)
    assert sum(not tela.tabela_acessos.isRowHidden(i) for i in range(12)) == 2  # 08:15 e 17:15 de Bruno


def test_pesquisa_espera_antes_de_filtrar(qtbot, tela, consulta, modais):
    preencher(tela)
    gerar_e_esperar(qtbot, tela)
    tela.pesquisa.setText("zzz")
    assert not tela.tabela_resumo.isRowHidden(0)  # ainda não filtrou
    qtbot.waitUntil(lambda: all(tela.tabela_resumo.isRowHidden(i) for i in range(3)), timeout=3000)


def test_ordenar_resumo_por_registros_e_numerico(qtbot, tela, consulta, modais):
    preencher(tela)
    gerar_e_esperar(qtbot, tela)
    tela.tabela_resumo.sortItems(1, Qt.AscendingOrder)
    assert [tela.tabela_resumo.item(i, 1).text() for i in range(3)] == ["0", "2", "10"]
    tela.tabela_resumo.sortItems(1, Qt.DescendingOrder)
    assert [tela.tabela_resumo.item(i, 1).text() for i in range(3)] == ["10", "2", "0"]
    # a Etiqueta de cada linha acompanha o nome depois de ordenar
    for linha in range(3):
        esperado = "Sem registro" if tela.tabela_resumo.item(linha, 1).text() == "0" else "Com registro"
        assert texto_etiqueta(tela, linha) == esperado


def test_ordenar_resumo_por_situacao_e_por_ultimo_acesso(qtbot, tela, consulta, modais):
    preencher(tela)
    gerar_e_esperar(qtbot, tela)
    tela.tabela_resumo.sortItems(4, Qt.AscendingOrder)
    assert tela.tabela_resumo.item(2, 0).text() == "Carla Teste"  # "Sem registro" por último
    tela.tabela_resumo.sortItems(3, Qt.DescendingOrder)
    assert tela.tabela_resumo.item(0, 0).text() == "Bruno Teste"


def test_clicar_na_linha_com_registro_abre_os_acessos_do_colaborador(qtbot, tela, consulta, modais):
    preencher(tela)
    gerar_e_esperar(qtbot, tela)
    tela.show()
    qtbot.waitExposed(tela)
    linha = next(i for i in range(3) if tela.tabela_resumo.item(i, 0).text() == "Bruno Teste")
    centro = tela.tabela_resumo.visualItemRect(tela.tabela_resumo.item(linha, 0)).center()
    qtbot.mouseClick(tela.tabela_resumo.viewport(), Qt.LeftButton, pos=centro)
    assert tela.pesquisa.text() == "Bruno Teste"
    assert tela.selecao_visao.currentIndex() == 1
    assert tela._pilha.currentWidget() is tela.tabela_acessos


def test_clicar_na_linha_sem_registro_nao_faz_nada(qtbot, tela, consulta, modais):
    preencher(tela)
    gerar_e_esperar(qtbot, tela)
    linha = next(i for i in range(3) if tela.tabela_resumo.item(i, 0).text() == "Carla Teste")
    tela.tabela_resumo.cellClicked.emit(linha, 0)
    assert tela.pesquisa.text() == "" and tela.selecao_visao.currentIndex() == 0


def test_salvar_grava_o_csv_com_o_nome_sugerido(qtbot, tela, consulta, modais, configuracoes, tmp_path, monkeypatch):
    preencher(tela)
    tela.data_inicial.definir_valor(date(2026, 10, 1))
    tela.data_final.definir_valor(date(2026, 10, 15))
    gerar_e_esperar(qtbot, tela)
    configuracoes.setValue("ultima_pasta", str(tmp_path))
    configuracoes.sync()
    abertos = []

    def dialogo(pai, titulo, inicial, filtro):
        abertos.append((pai, inicial))
        return inicial, filtro  # aceita o nome sugerido

    monkeypatch.setattr(QFileDialog, "getSaveFileName", dialogo)
    tela.salvar_csv()

    assert abertos == [(tela.contexto.janela, str(tmp_path / "Relatório 1° Quinzena Outubro.csv"))]
    csv = (tmp_path / "Relatório 1° Quinzena Outubro.csv").read_text(encoding="utf-8")
    assert csv.splitlines()[0] == "Nome;Data/Hora"
    assert len(csv.splitlines()) == 13
    configuracoes.sync()
    assert configuracoes.value("ultima_pasta") == str(tmp_path)
    (_janela, titulo, texto, _opcoes, tom), = modais.escolhas
    assert titulo == "Relatório salvo" and tom == "sucesso" and "12 registros salvos" in texto


def test_salvar_acrescenta_csv_e_lembra_a_pasta(qtbot, tela, consulta, modais, configuracoes, tmp_path, monkeypatch):
    preencher(tela)
    gerar_e_esperar(qtbot, tela)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(tmp_path / "saida"), ""))
    tela.salvar_csv()
    assert (tmp_path / "saida.csv").exists()
    configuracoes.sync()
    assert configuracoes.value("ultima_pasta") == str(tmp_path)


def test_salvar_cancelado_nao_grava_nada(qtbot, tela, consulta, modais, tmp_path, monkeypatch):
    preencher(tela)
    gerar_e_esperar(qtbot, tela)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: ("", ""))
    tela.salvar_csv()
    assert modais.escolhas == []


def test_salvar_com_arquivo_bloqueado_mostra_o_erro(qtbot, tela, consulta, modais, tmp_path, monkeypatch):
    preencher(tela)
    gerar_e_esperar(qtbot, tela)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(tmp_path / "x.csv"), ""))

    def bloqueado(relatorio, caminho):
        raise core.CatracaError("Não foi possível gravar o arquivo.")

    monkeypatch.setattr(core, "salvar_csv", bloqueado)
    tela.salvar_csv()
    assert modais.informados[-1][1:4:2] == ("Falha ao salvar", "perigo")
    assert modais.escolhas == []


def test_salvar_abre_a_pasta_so_se_escolhido(qtbot, tela, consulta, modais, tmp_path, monkeypatch):
    preencher(tela)
    gerar_e_esperar(qtbot, tela)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(tmp_path / "x.csv"), ""))
    abertas = []
    monkeypatch.setattr(tela_relatorio.QDesktopServices, "openUrl", lambda url: abertas.append(url.toLocalFile()))
    tela.salvar_csv()
    assert abertas == []
    modais.resposta = "abrir"
    tela.salvar_csv()
    assert [Path(a) for a in abertas] == [tmp_path]



@pytest.mark.parametrize("largura", [660, 880, 1040, 1360])
@pytest.mark.parametrize("com_resultado", [False, True])
def test_pagina_nao_estoura_a_largura(qtbot, qapp, tela, consulta, largura, com_resultado):
    from tcm_ui.themes import tema

    estilo = qapp.styleSheet()
    tema.aplicar(qapp)  # as larguras mínimas dependem do QSS
    try:
        tela.resize(largura, 700)
        tela.show()
        qtbot.waitExposed(tela)
        if com_resultado:
            preencher(tela)
            tela.gerar()
            qtbot.waitUntil(lambda: not tela.rodando)
        qtbot.wait(50)
        assert tela.horizontalScrollBar().maximum() == 0
    finally:
        qapp.setStyleSheet(estilo)
