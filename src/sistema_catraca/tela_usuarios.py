"""Página "Usuários": a lista de quem entra no relatório, com marcação."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QStackedLayout, QVBoxLayout, QWidget
from tcm_ui.components import (
    BarraProgresso, Botao, Campo, CampoPesquisa, CampoSenha, CampoTexto, Cartao, EstadoVazio, Modal,
    Pagina, Tabela, Texto, repolir,
)
from tcm_ui.modulo import Contexto
from tcm_ui.themes import ESPACO

from sistema_catraca import catraca_core as core
from sistema_catraca.tarefa import TarefaFundo
from sistema_catraca.tela_relatorio import TelaRelatorio, plural
from sistema_catraca.usuarios import ListaUsuarios


class TabelaUsuarios(Tabela):
    """Tabela em que o Espaço pede para alternar a marcação da linha atual."""

    espaco_pressionado = Signal(int)

    def keyPressEvent(self, evento) -> None:
        if evento.key() == Qt.Key_Space and self.currentRow() >= 0:
            self.espaco_pressionado.emit(self.currentRow())
            return
        super().keyPressEvent(evento)


class TelaUsuarios(Pagina):
    """Lista de usuários com marcação: só os marcados entram no relatório."""

    MAX_NOMES_NA_MENSAGEM = 8

    def __init__(self, contexto: Contexto, lista: ListaUsuarios, relatorio: TelaRelatorio):
        super().__init__()
        self.contexto = contexto
        self._lista = lista
        self._relatorio = relatorio
        self._tarefa: TarefaFundo | None = None
        self._id_tarefa = 0
        self._construir()
        self._lista.mudou.connect(self._preencher)
        self._lista.marcacao_mudou.connect(self._sincronizar)
        self._preencher()
        self._atualizar_busca()

    # ------------------------------------------------------------ Construção
    def _construir(self) -> None:
        self.conteudo.addWidget(self._cartao_adicionar())
        self.conteudo.addWidget(self._cartao_lista(), 1)

    def _cartao_adicionar(self) -> Cartao:
        cartao = Cartao(
            "Adicionar usuários",
            "Busque todos os usuários cadastrados na catraca ou digite um nome exatamente como "
            "está nela. Maiúsculas e minúsculas não importam.",
        )
        linha = QHBoxLayout()
        linha.setSpacing(ESPACO["md"])
        self.botao_buscar = Botao("Buscar na catraca", "secundario", "md", "baixar")
        self.botao_buscar.clicked.connect(self._buscar)
        linha.addWidget(self.botao_buscar)
        estado = QVBoxLayout()
        estado.setSpacing(ESPACO["xs"])
        estado.addStretch(1)
        self.rotulo_busca = Texto("", "dica")
        self.progresso_busca = BarraProgresso()
        self.progresso_busca.setRange(0, 0)
        estado.addWidget(self.rotulo_busca)
        estado.addWidget(self.progresso_busca)
        estado.addStretch(1)
        linha.addLayout(estado, 1)
        cartao.corpo.addLayout(linha)

        self.campo_nome = CampoTexto("Nome do usuário")
        self.campo_nome.returnPressed.connect(self._adicionar)
        self.campo_nome.textEdited.connect(lambda _texto: self._erro_nome(None))
        self.botao_adicionar = Botao("Adicionar", "primario", "md", "mais")
        self.botao_adicionar.clicked.connect(self._adicionar)
        entrada = QWidget()
        caixa = QHBoxLayout(entrada)
        caixa.setContentsMargins(0, 0, 0, 0)
        caixa.setSpacing(ESPACO["sm"])
        caixa.addWidget(self.campo_nome, 1)
        caixa.addWidget(self.botao_adicionar)
        self._campo_nome = Campo("Adicionar pelo nome", entrada)
        cartao.corpo.addWidget(self._campo_nome)
        return cartao

    def _cartao_lista(self) -> Cartao:
        cartao = Cartao()
        self.rotulo_contagem = Texto("", "subtitulo")
        self.pesquisa = CampoPesquisa("Pesquisar usuário")
        self.pesquisa.setMinimumWidth(180)
        self.pesquisa.textChanged.connect(self._aplicar_pesquisa)
        self.botao_marcar_todos = Botao("Marcar todos", "secundario", "md", "check")
        self.botao_marcar_todos.clicked.connect(lambda: self._marcar_visiveis(True))
        self.botao_desmarcar_todos = Botao("Desmarcar todos", "secundario", "md", "fechar")
        self.botao_desmarcar_todos.clicked.connect(lambda: self._marcar_visiveis(False))
        self.botao_remover = Botao("Remover", "perigo", "md", "lixeira")
        self.botao_remover.clicked.connect(self._remover)
        # Duas linhas (contagem e pesquisa; depois as ações) para caber em janelas estreitas.
        busca = QHBoxLayout()
        busca.setSpacing(ESPACO["md"])
        busca.addWidget(self.rotulo_contagem)
        busca.addWidget(self.pesquisa, 1)
        cartao.corpo.addLayout(busca)
        acoes = QHBoxLayout()
        acoes.setSpacing(ESPACO["sm"])
        for botao in (self.botao_marcar_todos, self.botao_desmarcar_todos):
            acoes.addWidget(botao)
        acoes.addStretch(1)
        acoes.addWidget(self.botao_remover)
        cartao.corpo.addLayout(acoes)

        ajuda = Texto(
            "Marque quem deve entrar no relatório. A escolha fica salva para as próximas vezes. "
            "Com uma pesquisa ativa, Marcar e Desmarcar todos valem só para os nomes encontrados.",
            "suave",
        )
        ajuda.setWordWrap(True)
        cartao.corpo.addWidget(ajuda)

        self.tabela = TabelaUsuarios(["Usuário"])
        self.tabela.horizontalHeader().setSortIndicator(0, Qt.AscendingOrder)  # o padrão do Qt é decrescente
        self.tabela.itemSelectionChanged.connect(self._atualizar_remocao)
        self.tabela.cellClicked.connect(lambda linha, _coluna: self._alternar(linha))
        self.tabela.espaco_pressionado.connect(self._alternar)
        self.estado_vazio = EstadoVazio(
            "Nenhum usuário na lista",
            "Preencha o IP e o usuário na página Relatório de acessos e clique em Buscar na catraca, "
            "ou digite um nome acima e clique em Adicionar.",
            "usuarios",
        )
        self._pilha = QStackedLayout()
        for widget in (self.estado_vazio, self.tabela):
            widget.setMinimumHeight(360)
            self._pilha.addWidget(widget)
        cartao.corpo.addLayout(self._pilha, 1)
        return cartao

    # ------------------------------------------------------------ Lista e marcações
    def _preencher(self) -> None:
        nomes = self._lista.nomes
        tabela = self.tabela
        tabela.setSortingEnabled(False)
        tabela.setRowCount(len(nomes))
        # A marcação é feita pela página (clique na linha ou Espaço), não pelo item.
        marcas = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        for linha, nome in enumerate(nomes):
            item = tabela.definir_celula(linha, 0, nome, nome.casefold())
            item.setFlags(marcas)
        self._pilha.setCurrentWidget(self.tabela if nomes else self.estado_vazio)
        self._sincronizar()  # reativa a ordenação
        tabela.clearSelection()
        self._aplicar_pesquisa()
        self._atualizar_remocao()

    def _sincronizar(self) -> None:
        tabela = self.tabela
        tabela.setSortingEnabled(False)  # mudar a marcação não pode reordenar as linhas no meio do laço
        for linha in range(tabela.rowCount()):
            item = tabela.item(linha, 0)
            marcado = self._lista.esta_marcado(item.text())
            item.setCheckState(Qt.Checked if marcado else Qt.Unchecked)
        tabela.setSortingEnabled(True)
        total, marcados = len(self._lista.nomes), len(self._lista.marcados)
        self.rotulo_contagem.setText(f"{marcados} de {plural(total, 'usuário marcado', 'usuários marcados')}")

    def _alternar(self, linha: int) -> None:
        item = self.tabela.item(linha, 0)
        if item is not None:
            self._lista.marcar([item.text()], not self._lista.esta_marcado(item.text()))

    def _nomes_visiveis(self) -> list[str]:
        return [self.tabela.item(linha, 0).text() for linha in range(self.tabela.rowCount())
                if not self.tabela.isRowHidden(linha)]

    def _marcar_visiveis(self, marcado: bool) -> None:
        self._lista.marcar(self._nomes_visiveis(), marcado)

    def _aplicar_pesquisa(self, *_args) -> None:
        self.tabela.filtrar(self.pesquisa.text())

    def _atualizar_remocao(self) -> None:
        self.botao_remover.setEnabled(bool(self.tabela.selectedItems()))

    def _remover(self) -> None:
        selecionados = self.tabela.selectedItems()
        if not selecionados:
            return
        nome = selecionados[0].text()
        if Modal.confirmar(
            self.contexto.janela,
            "Remover usuário",
            f"{nome} deixará de aparecer nos próximos relatórios. Os arquivos já salvos não mudam.",
            texto_ok="Remover",
            destrutivo=True,
        ):
            self._lista.remover(nome)

    # ------------------------------------------------------------ Adicionar pelo nome
    def _erro_nome(self, mensagem: str | None) -> None:
        self._campo_nome.definir_erro(mensagem)
        self.campo_nome.setProperty("erro", bool(mensagem))  # borda vermelha no próprio campo de texto
        repolir(self.campo_nome)

    def _adicionar(self) -> None:
        try:
            self._lista.adicionar(self.campo_nome.text())
        except ValueError as erro:
            self._erro_nome(str(erro))
            self.campo_nome.setFocus()
            return
        self.campo_nome.clear()
        self._erro_nome(None)

    # ------------------------------------------------------------ Buscar na catraca
    @property
    def rodando(self) -> bool:
        return self._tarefa is not None

    def _buscar(self) -> None:
        if self.rodando:
            return
        ip, usuario, senha = self._relatorio.conexao()
        if not ip or not usuario:
            Modal.informar(
                self.contexto.janela,
                "Conexão incompleta",
                "Preencha o IP e o usuário da catraca na página Relatório de acessos.",
                "perigo",
            )
            return
        if not senha:
            senha = self.pedir_senha(ip, usuario)
            if not senha:
                return
        self._relatorio.lembrar_conexao(ip, usuario, senha)

        self._id_tarefa += 1
        self._tarefa = TarefaFundo(self._id_tarefa, lambda avisar: core.listar_usuarios(ip, usuario, senha, avisar))
        self._tarefa.conectar(self._ao_progredir, self._ao_concluir, self._ao_falhar)
        self.rotulo_busca.setText("Iniciando...")
        self._tarefa.iniciar()
        self._atualizar_busca()

    def pedir_senha(self, ip: str, usuario: str) -> str:
        """Pergunta a senha da catraca; devolve vazio se a pessoa cancelar. A senha não é salva."""
        modal = Modal("Senha da catraca",
                      f"Digite a senha do usuário {usuario} da catraca em {ip}. Ela não é salva.",
                      self.contexto.janela)
        campo = CampoSenha("Senha da catraca")
        modal.corpo.addWidget(Campo("Senha", campo))
        modal.adicionar_botao(Botao("Cancelar", "secundario")).clicked.connect(modal.reject)
        buscar = modal.adicionar_botao(Botao("Buscar"))
        buscar.setDefault(True)
        buscar.clicked.connect(modal.accept)
        campo.returnPressed.connect(buscar.click)
        campo.setFocus()
        aceito = modal.exec() == QDialog.DialogCode.Accepted
        return campo.text() if aceito else ""

    def cancelar(self) -> None:
        """Abandona a busca em andamento; o resultado dela é ignorado."""
        if self._tarefa is None:
            return
        self._tarefa.cancelar()
        self._terminar()

    def _terminar(self) -> None:
        self._tarefa = None
        self.rotulo_busca.setText("")
        self._atualizar_busca()

    def _ao_progredir(self, id_tarefa: int, mensagem: str) -> None:
        if id_tarefa == self._id_tarefa and self.rodando:
            self.rotulo_busca.setText(mensagem)

    def _ao_concluir(self, id_tarefa: int, encontrados: list[str]) -> None:
        if id_tarefa != self._id_tarefa or not self.rodando:
            return
        self._terminar()
        novos = self._lista.mesclar(encontrados)
        if novos:
            self.pesquisa.clear()
        Modal.informar(self.contexto.janela, "Usuários atualizados", self._resumo(encontrados, novos), "sucesso")

    def _resumo(self, encontrados: list[str], novos: list[str]) -> str:
        mensagem = f"{plural(len(encontrados), 'usuário encontrado', 'usuários encontrados')} na catraca."
        if novos:
            mensagem += (
                f" {plural(len(novos), 'novo foi adicionado', 'novos foram adicionados')} à lista, "
                "desmarcados: marque quem deve entrar no relatório."
            )
        else:
            mensagem += " Todos já estavam na lista."
        na_catraca = {nome.casefold() for nome in encontrados}
        faltam = [nome for nome in self._lista.nomes if nome.casefold() not in na_catraca]
        if faltam:
            mostrados = ", ".join(faltam[: self.MAX_NOMES_NA_MENSAGEM])
            if len(faltam) > self.MAX_NOMES_NA_MENSAGEM:
                mostrados += f" e mais {len(faltam) - self.MAX_NOMES_NA_MENSAGEM}"
            mensagem += (
                f"\n\nNão estão cadastrados na catraca com este nome: {mostrados}. "
                "Confira a grafia ou remova-os da lista."
            )
        return mensagem

    def _ao_falhar(self, id_tarefa: int, mensagem: str) -> None:
        if id_tarefa == self._id_tarefa and self.rodando:
            self._terminar()
            Modal.informar(self.contexto.janela, "Não foi possível buscar os usuários", mensagem, "perigo")

    def _atualizar_busca(self) -> None:
        rodando = self.rodando
        self.botao_buscar.setEnabled(not rodando)
        self.rotulo_busca.setVisible(rodando)
        self.progresso_busca.setVisible(rodando)
