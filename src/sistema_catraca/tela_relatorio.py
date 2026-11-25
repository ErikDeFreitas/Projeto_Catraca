"""Página "Relatório de acessos": consulta a catraca no período e salva o resultado em CSV."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QHeaderView, QStackedLayout, QVBoxLayout
from tcm_ui.components import (
    BarraProgresso, Botao, Campo, CampoData, CampoPesquisa, CampoSenha, CampoTexto, Cartao,
    CartaoIndicador, EstadoVazio, Etiqueta, Modal, Pagina, Selecao, Tabela, Texto,
)
from tcm_ui.modulo import Contexto
from tcm_ui.themes import ESPACO

from sistema_catraca import catraca_core as core
from sistema_catraca import dados
from sistema_catraca.grade_fluida import GradeFluida, permitir_quebra
from sistema_catraca.tarefa import TarefaFundo
from sistema_catraca.usuarios import ListaUsuarios

ESPERA_PESQUISA_MS = 150
VISAO_RESUMO, VISAO_ACESSOS = 0, 1
COLUNAS_RESUMO = ["Colaborador", "Registros", "Primeiro acesso", "Último acesso", "Situação"]
COLUNAS_ACESSOS = ["Colaborador", "Data", "Hora", "Dia da semana"]
COL_REGISTROS = 1
DIAS_DA_SEMANA = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")
ATALHOS_PERIODO = (
    ("Quinzena atual", core.quinzena_de),
    ("Quinzena anterior", core.quinzena_anterior),
    ("Mês atual", core.mes_de),
    ("Mês anterior", core.mes_anterior),
    ("Últimos 15 dias", core.ultimos_15_dias),
)


def plural(quantidade: int, singular: str, plural_: str) -> str:
    return f"{quantidade} {singular if quantidade == 1 else plural_}"


def formatar_data_hora(valor: datetime | None) -> str:
    return valor.strftime("%d/%m/%Y %H:%M") if valor else "–"


def limpar_host(texto: str) -> str:
    """Aceita o endereço colado do navegador: http://10.0.0.10/ vira 10.0.0.10."""
    host = texto.strip().removeprefix("http://").removeprefix("https://")
    return host.rstrip("/")


class TelaRelatorio(Pagina):
    def __init__(self, contexto: Contexto, lista: ListaUsuarios):
        super().__init__()
        self.contexto = contexto
        self._lista = lista
        self._config = dados.configuracoes()
        self._relatorio: core.Relatorio | None = None
        self._tarefa: TarefaFundo | None = None
        self._id_tarefa = 0
        self._timer_pesquisa = QTimer(self, singleShot=True, interval=ESPERA_PESQUISA_MS)
        self._timer_pesquisa.timeout.connect(self._aplicar_pesquisa)
        self._construir()
        self._definir_periodo(core.quinzena_de(date.today()))
        self._mostrar(None)
        self._lista.mudou.connect(self._atualizar_marcados)
        self._lista.marcacao_mudou.connect(self._atualizar_marcados)
        self._atualizar_marcados()
        self._atualizar_acoes()

    # ------------------------------------------------------------ Construção
    def _construir(self) -> None:
        topo = GradeFluida(320)
        for cartao in (self._cartao_conexao(), self._cartao_periodo()):
            permitir_quebra(cartao)  # título longo quebra em vez de alargar a página
            topo.adicionar(cartao)
        self.conteudo.addWidget(topo)
        self.conteudo.addLayout(self._linha_acao())

        indicadores = GradeFluida(160)
        self.ind_registros = CartaoIndicador("Registros", "–", "camadas", "primaria")
        self.ind_colaboradores = CartaoIndicador("Colaboradores", "–", "usuarios", "neutro")
        self.ind_com = CartaoIndicador("Com registro", "–", "usuario_check", "sucesso")
        self.ind_sem = CartaoIndicador("Sem registro", "–", "usuario_x", "perigo")
        for indicador in (self.ind_registros, self.ind_colaboradores, self.ind_com, self.ind_sem):
            permitir_quebra(indicador)
            indicadores.adicionar(indicador)
        self.conteudo.addWidget(indicadores)
        self.conteudo.addWidget(self._cartao_resultado(), 1)

    def _cartao_conexao(self) -> Cartao:
        cartao = Cartao("Conexão com a catraca", "A senha não é salva: digite-a a cada abertura do programa.")
        self.campo_ip = CampoTexto("ex.: endereço da catraca")
        self.campo_ip.setText(str(self._config.value("catraca/ip", core.IP_PADRAO)))
        self.campo_usuario = CampoTexto("ex.: usuário de acesso da catraca")
        self.campo_usuario.setText(str(self._config.value("catraca/usuario", core.USUARIO_PADRAO)))
        self.campo_senha = CampoSenha("Senha da catraca")
        self.campo_senha.returnPressed.connect(self.gerar)
        self._campos = {
            self.campo_ip: Campo("IP", self.campo_ip),
            self.campo_usuario: Campo("Usuário", self.campo_usuario),
            self.campo_senha: Campo("Senha", self.campo_senha),
        }
        grade = GradeFluida(150)
        for campo in self._campos.values():
            grade.adicionar(campo)
        for controle in self._campos:
            controle.textEdited.connect(lambda _texto, c=controle: self._campos[c].definir_erro(None))
        cartao.corpo.addWidget(grade)
        cartao.corpo.addStretch(1)
        return cartao

    def _cartao_periodo(self) -> Cartao:
        cartao = Cartao("Período do relatório")
        self.data_inicial = CampoData()
        self.data_final = CampoData()
        datas = GradeFluida(150)
        datas.adicionar(Campo("Data inicial", self.data_inicial))
        datas.adicionar(Campo("Data final", self.data_final))
        cartao.corpo.addWidget(datas)

        atalhos = GradeFluida(0, ESPACO["sm"], linhas_completas=False)
        self.botoes_periodo: list[Botao] = []
        for texto, periodo in ATALHOS_PERIODO:
            botao = Botao(texto, "secundario", "sm")
            botao.clicked.connect(lambda _marcado=False, p=periodo: self._definir_periodo(p(date.today())))
            atalhos.adicionar(botao)
            self.botoes_periodo.append(botao)
        cartao.corpo.addWidget(atalhos)
        cartao.corpo.addStretch(1)
        return cartao

    def _linha_acao(self) -> QHBoxLayout:
        linha = QHBoxLayout()
        linha.setSpacing(ESPACO["md"])
        self.botao_gerar = Botao("Gerar relatório", "primario", "lg", "arquivo")
        self.botao_gerar.clicked.connect(self.gerar)
        linha.addWidget(self.botao_gerar)

        estado = QVBoxLayout()
        estado.setSpacing(ESPACO["xs"])
        estado.addStretch(1)
        self.rotulo_marcados = Texto("", "suave")
        self.rotulo_progresso = Texto("", "dica")
        for rotulo in (self.rotulo_marcados, self.rotulo_progresso):
            rotulo.setWordWrap(True)  # texto longo não pode alargar a página
        self.progresso = BarraProgresso()
        self.progresso.setRange(0, 0)  # indeterminado: a catraca não informa o andamento
        estado.addWidget(self.rotulo_marcados)
        estado.addWidget(self.rotulo_progresso)
        estado.addWidget(self.progresso)
        estado.addStretch(1)
        linha.addLayout(estado, 1)

        self.botao_cancelar = Botao("Cancelar", "secundario", "md")
        self.botao_cancelar.clicked.connect(self.cancelar)
        linha.addWidget(self.botao_cancelar)
        return linha

    def _cartao_resultado(self) -> Cartao:
        cartao = Cartao()
        barra = QHBoxLayout()
        barra.setSpacing(ESPACO["sm"])
        self.pesquisa = CampoPesquisa("Pesquisar por nome ou data")
        self.pesquisa.textChanged.connect(lambda _texto: self._timer_pesquisa.start())
        self.selecao_visao = Selecao(["Por colaborador", "Todos os acessos"])
        self.selecao_visao.currentIndexChanged.connect(self._ao_mudar_visao)
        self.botao_salvar = Botao("Salvar CSV", "secundario", "md", "baixar")
        self.botao_salvar.clicked.connect(self.salvar_csv)
        barra.addWidget(Texto("Resultado", "subtitulo"))
        barra.addWidget(self.pesquisa, 1)
        cartao.corpo.addLayout(barra)

        # Segunda linha: numa janela estreita, os quatro controles lado a lado alargariam a página.
        opcoes = QHBoxLayout()
        opcoes.setSpacing(ESPACO["sm"])
        opcoes.addWidget(self.selecao_visao)
        opcoes.addStretch(1)
        opcoes.addWidget(self.botao_salvar)
        cartao.corpo.addLayout(opcoes)

        self.rotulo_resumo = Texto("", "suave")
        self.rotulo_resumo.setWordWrap(True)
        cartao.corpo.addWidget(self.rotulo_resumo)

        self.tabela_resumo = Tabela(COLUNAS_RESUMO, alinhar_direita=(COL_REGISTROS,))
        self.tabela_resumo.horizontalHeader().setSortIndicator(0, Qt.AscendingOrder)  # o padrão do Qt é decrescente
        self.tabela_resumo.cellClicked.connect(self._ao_clicar_resumo)
        self.tabela_acessos = Tabela(COLUNAS_ACESSOS)
        # Pode ter milhares de linhas: as larguras são medidas ao preencher, não a cada alteração.
        cabecalho = self.tabela_acessos.horizontalHeader()
        for coluna in range(1, len(COLUNAS_ACESSOS)):
            cabecalho.setSectionResizeMode(coluna, QHeaderView.ResizeMode.Interactive)
        self.estado_vazio = EstadoVazio(
            "Nenhum relatório gerado",
            "Informe a senha e o período, e clique em Gerar relatório.",
            "arquivo",
        )
        self._pilha = QStackedLayout()
        for widget in (self.estado_vazio, self.tabela_resumo, self.tabela_acessos):
            widget.setMinimumHeight(360)
            self._pilha.addWidget(widget)
        cartao.corpo.addLayout(self._pilha, 1)
        return cartao

    # ------------------------------------------------------------ Período e marcados
    def _definir_periodo(self, periodo: tuple[date, date]) -> None:
        self.data_inicial.definir_valor(periodo[0])
        self.data_final.definir_valor(periodo[1])

    def _atualizar_marcados(self) -> None:
        total, marcados = len(self._lista.nomes), len(self._lista.marcados)
        self.rotulo_marcados.setText(
            f"{marcados} de {plural(total, 'usuário marcado', 'usuários marcados')} para o relatório. "
            "Altere na página Usuários."
        )

    # ------------------------------------------------------------ Conexão
    def conexao(self) -> tuple[str, str, str]:
        """IP, usuário e senha como estão nos campos (a senha pode estar vazia)."""
        return limpar_host(self.campo_ip.text()), self.campo_usuario.text().strip(), self.campo_senha.text()

    def lembrar_conexao(self, ip: str, usuario: str, senha: str) -> None:
        """Grava IP e usuário; a senha fica só no campo, até fechar o programa."""
        self._config.setValue("catraca/ip", ip)
        self._config.setValue("catraca/usuario", usuario)
        self.campo_ip.setText(ip)
        self.campo_usuario.setText(usuario)
        self.campo_senha.setText(senha)

    def _validar_conexao(self) -> tuple[str, str, str] | None:
        conexao = self.conexao()
        avisos = {self.campo_ip: "Informe o IP da catraca.", self.campo_usuario: "Informe o usuário da catraca.",
                  self.campo_senha: "Informe a senha da catraca."}
        vazios = [campo for campo, valor in zip(avisos, conexao) if not valor]
        for campo, aviso in avisos.items():
            self._campos[campo].definir_erro(aviso if campo in vazios else None)
        if vazios:
            vazios[0].setFocus()
            return None
        return conexao

    # ------------------------------------------------------------ Geração
    @property
    def rodando(self) -> bool:
        return self._tarefa is not None

    @property
    def relatorio(self) -> core.Relatorio | None:
        return self._relatorio

    def gerar(self) -> None:
        if self.rodando:
            return
        conexao = self._validar_conexao()
        if conexao is None:
            return
        ip, usuario, senha = conexao
        inicio, fim = self.data_inicial.valor(), self.data_final.valor()
        if fim < inicio:
            Modal.informar(self.contexto.janela, "Período inválido",
                           "A data final não pode ser anterior à data inicial.", "perigo")
            return
        nomes = self._lista.marcados
        if not nomes:
            orientacao = ("Marque ao menos um usuário na página Usuários." if self._lista.nomes else
                          "A lista de usuários está vazia. Na página Usuários, use Buscar na catraca "
                          "ou adicione um nome.")
            Modal.informar(self.contexto.janela, "Nenhum usuário marcado", orientacao, "perigo")
            return

        self.lembrar_conexao(ip, usuario, senha)
        self._mostrar(None)
        self._id_tarefa += 1
        self._tarefa = TarefaFundo(
            self._id_tarefa,
            lambda avisar: core.gerar_relatorio(ip, usuario, senha, inicio, fim, nomes, avisar),
        )
        self._tarefa.conectar(self._ao_progredir, self._ao_concluir, self._ao_falhar)
        self.rotulo_progresso.setText("Iniciando...")
        self._tarefa.iniciar()
        self._atualizar_acoes()

    def cancelar(self) -> None:
        """Devolve a tela na hora; a consulta em andamento é abandonada e o resultado dela, ignorado."""
        if self._tarefa is None:
            return
        self._tarefa.cancelar()
        self._terminar()

    def _terminar(self) -> None:
        self._tarefa = None
        self.rotulo_progresso.setText("")
        self._atualizar_acoes()

    def _ao_progredir(self, id_tarefa: int, mensagem: str) -> None:
        if id_tarefa == self._id_tarefa and self.rodando:
            self.rotulo_progresso.setText(mensagem)

    def _ao_concluir(self, id_tarefa: int, relatorio: core.Relatorio) -> None:
        if id_tarefa == self._id_tarefa and self.rodando:
            self._terminar()
            self._mostrar(relatorio)

    def _ao_falhar(self, id_tarefa: int, mensagem: str) -> None:
        if id_tarefa == self._id_tarefa and self.rodando:
            self._terminar()
            Modal.informar(self.contexto.janela, "Não foi possível gerar o relatório", mensagem, "perigo")

    def _atualizar_acoes(self) -> None:
        rodando = self.rodando
        self.botao_gerar.setEnabled(not rodando)
        self.botao_cancelar.setVisible(rodando)
        self.progresso.setVisible(rodando)
        self.rotulo_progresso.setVisible(rodando)
        self.rotulo_marcados.setVisible(not rodando)
        self.botao_salvar.setEnabled(not rodando and bool(self._relatorio and self._relatorio.total_registros))
        for widget in (self.campo_ip, self.campo_usuario, self.campo_senha, self.data_inicial,
                       self.data_final, *self.botoes_periodo):
            widget.setEnabled(not rodando)

    # ------------------------------------------------------------ Resultado
    def _mostrar(self, relatorio: core.Relatorio | None) -> None:
        self._relatorio = relatorio
        self.pesquisa.clear()
        self.selecao_visao.setCurrentIndex(VISAO_RESUMO)
        self._preencher_resumo(relatorio)
        self._preencher_acessos(relatorio)
        self._atualizar_indicadores(relatorio)
        self._ao_mudar_visao(VISAO_RESUMO)
        self._atualizar_acoes()

    def _preencher_resumo(self, relatorio: core.Relatorio | None) -> None:
        tabela = self.tabela_resumo
        tabela.setSortingEnabled(False)
        resumos = relatorio.resumos if relatorio else ()
        tabela.setRowCount(len(resumos))
        for linha, resumo in enumerate(resumos):
            com_registro = resumo.total > 0
            situacao = Etiqueta("Com registro" if com_registro else "Sem registro",
                                "sucesso" if com_registro else "perigo")
            celulas = (
                (resumo.nome, resumo.nome.casefold()),
                (str(resumo.total), resumo.total),
                (formatar_data_hora(resumo.primeiro), resumo.primeiro.isoformat() if resumo.primeiro else ""),
                (formatar_data_hora(resumo.ultimo), resumo.ultimo.isoformat() if resumo.ultimo else ""),
                (situacao, 0 if com_registro else 1),
            )
            dica = ("Clique para ver os acessos" if com_registro
                    else "Sem acessos no período: confira o nome cadastrado na catraca")
            for coluna, (valor, ordem) in enumerate(celulas):
                item = tabela.definir_celula(linha, coluna, valor, ordem)
                item.setToolTip(dica)
        tabela.setSortingEnabled(True)

    def _preencher_acessos(self, relatorio: core.Relatorio | None) -> None:
        tabela = self.tabela_acessos
        tabela.setUpdatesEnabled(False)
        tabela.setSortingEnabled(False)
        acessos = relatorio.acessos if relatorio else ()
        tabela.setRowCount(len(acessos))
        for linha, acesso in enumerate(acessos):
            momento = acesso.data_hora
            celulas = (
                (acesso.nome, acesso.nome.casefold()),
                (momento.strftime("%d/%m/%Y") if momento else acesso.texto_original or "–",
                 momento.isoformat() if momento else ""),
                (momento.strftime("%H:%M:%S") if momento else "–", momento.strftime("%H:%M:%S") if momento else ""),
                (DIAS_DA_SEMANA[momento.weekday()] if momento else "–", momento.weekday() if momento else -1),
            )
            for coluna, (valor, ordem) in enumerate(celulas):
                tabela.definir_celula(linha, coluna, valor, ordem)
        tabela.setSortingEnabled(True)
        tabela.sortItems(1, Qt.AscendingOrder)
        for coluna in range(1, len(COLUNAS_ACESSOS)):
            tabela.resizeColumnToContents(coluna)
        tabela.setUpdatesEnabled(True)

    def _atualizar_indicadores(self, relatorio: core.Relatorio | None) -> None:
        indicadores = (self.ind_registros, self.ind_colaboradores, self.ind_com, self.ind_sem)
        if relatorio is None:
            for indicador in indicadores:
                indicador.definir_valor("–")
            self.rotulo_resumo.setText("")
            self.rotulo_resumo.hide()
            return
        sem = len(relatorio.sem_registro)
        self.ind_registros.definir_valor(str(relatorio.total_registros))
        self.ind_colaboradores.definir_valor(str(len(relatorio.resumos)))
        self.ind_com.definir_valor(str(len(relatorio.resumos) - sem))
        self.ind_sem.definir_valor(str(sem))
        texto = f"Período de {relatorio.inicio:%d/%m/%Y} a {relatorio.fim:%d/%m/%Y}."
        if sem:
            texto += (f" {plural(sem, 'colaborador', 'colaboradores')} sem registro: "
                      "confira o nome cadastrado na catraca.")
        self.rotulo_resumo.setText(texto)
        self.rotulo_resumo.show()

    def _ao_mudar_visao(self, indice: int) -> None:
        if self._relatorio is None:
            self._pilha.setCurrentWidget(self.estado_vazio)
        elif indice == VISAO_ACESSOS:
            self._pilha.setCurrentWidget(self.tabela_acessos)
        else:
            self._pilha.setCurrentWidget(self.tabela_resumo)
        self._aplicar_pesquisa()

    def _ao_clicar_resumo(self, linha: int, _coluna: int) -> None:
        registros = self.tabela_resumo.item(linha, COL_REGISTROS)
        if registros is not None and int(registros.text()) > 0:
            self.pesquisa.setText(self.tabela_resumo.item(linha, 0).text())
            self.selecao_visao.setCurrentIndex(VISAO_ACESSOS)

    def _aplicar_pesquisa(self) -> None:
        self._timer_pesquisa.stop()
        tabela = self.tabela_acessos if self.selecao_visao.currentIndex() == VISAO_ACESSOS else self.tabela_resumo
        tabela.setUpdatesEnabled(False)
        tabela.filtrar(self.pesquisa.text())
        tabela.setUpdatesEnabled(True)

    # ------------------------------------------------------------ Exportação
    def salvar_csv(self) -> None:
        relatorio = self._relatorio
        if relatorio is None:
            return
        sugerido = core.nome_sugerido(relatorio.inicio, relatorio.fim)
        pasta = self._config.value("ultima_pasta", "")
        inicial = str(Path(str(pasta)) / sugerido) if pasta else sugerido
        caminho, _filtro = QFileDialog.getSaveFileName(
            self.contexto.janela, "Salvar relatório", inicial, "Arquivo CSV (*.csv)")
        if not caminho:
            return
        if not caminho.lower().endswith(".csv"):
            caminho += ".csv"
        try:
            core.salvar_csv(relatorio, caminho)
        except core.CatracaError as erro:
            Modal.informar(self.contexto.janela, "Falha ao salvar", str(erro), "perigo")
            return
        salvo = Path(caminho)
        self._config.setValue("ultima_pasta", str(salvo.parent))
        escolha = Modal.escolher(
            self.contexto.janela,
            "Relatório salvo",
            f"{plural(relatorio.total_registros, 'registro salvo', 'registros salvos')} em:\n{salvo}",
            [("Fechar", "secundario", "fechar"), ("Abrir pasta", "primario", "abrir")],
            "sucesso",
        )
        if escolha == "abrir":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(salvo.parent)))
