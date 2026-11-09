"""Sistema Catraca: consulta os acessos da catraca ControlID e exporta o relatório em CSV."""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QLocale, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QMainWindow,
    QScrollArea,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import catraca_core as core
from components import (
    BADGE_TONE_ROLE,
    Button,
    Card,
    ComboBox,
    DataTable,
    DateInput,
    EmptyState,
    FormField,
    Header,
    Modal,
    PasswordInput,
    ProgressBar,
    ResponsiveRow,
    SearchInput,
    Sidebar,
    SortableItem,
    StatCard,
    TextInput,
    ThemeFade,
    text_label,
    themed_icon,
)
from themes import SPACING, app_settings, default_font, theme
from update_ui import UpdateController
from version import __version__

APP_NAME = "Sistema Catraca"
SEARCH_DELAY_MS = 150
VIEW_SUMMARY, VIEW_ACCESSES = 0, 1
SUMMARY_COLUMNS = ["Colaborador", "Registros", "Primeiro acesso", "Último acesso", "Situação"]
ACCESS_COLUMNS = ["Colaborador", "Data", "Hora", "Dia da semana"]
COL_SITUATION = 4
WEEKDAYS = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")


def page_scroll_area(content: QWidget) -> QScrollArea:
    content.setProperty("surface", "content")
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(content)
    return scroll


def plural(count: int, singular: str, plural_form: str) -> str:
    return f"{count} {singular if count == 1 else plural_form}"


def format_datetime(value: datetime | None) -> str:
    return value.strftime("%d/%m/%Y %H:%M") if value else "–"


def clean_host(text: str) -> str:
    """Aceita o endereço colado do navegador: http://192.168.0.130/ vira 192.168.0.130."""
    host = text.strip().removeprefix("http://").removeprefix("https://")
    return host.rstrip("/")


def search_matches(table: DataTable, row: int, query: str) -> bool:
    return any(
        query in table.item(row, column).text().casefold() for column in range(table.columnCount())
    )


def _load_names(raw: object) -> list[str] | None:
    if not raw:
        return None
    try:
        names = json.loads(str(raw))
    except ValueError:
        return None
    if isinstance(names, list) and all(isinstance(name, str) for name in names):
        return names
    return None


class UserStore(QObject):
    """Usuários conhecidos e quais estão marcados para o relatório.

    Só é gravado depois da primeira alteração. Sem marcação salva, todos entram no relatório,
    como nas versões anteriores.
    """

    changed = Signal()  # a lista mudou
    selection_changed = Signal()  # as marcações mudaram
    _KEY_NAMES = "colaboradores"
    _KEY_SELECTED = "selecionados"

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        settings = app_settings()
        self._names = _load_names(settings.value(self._KEY_NAMES)) or list(core.COLABORADORES_PADRAO)
        selected = _load_names(settings.value(self._KEY_SELECTED))
        self._selected = {name.casefold() for name in (self._names if selected is None else selected)}

    @property
    def names(self) -> list[str]:
        return list(self._names)

    @property
    def selected(self) -> list[str]:
        return [name for name in self._names if self.is_selected(name)]

    def is_selected(self, name: str) -> bool:
        return name.casefold() in self._selected

    def set_selected(self, names: list[str], checked: bool) -> None:
        keys = {name.casefold() for name in names}
        selected = self._selected | keys if checked else self._selected - keys
        if selected != self._selected:
            self._selected = selected
            self._save_selection()

    def add(self, name: str) -> None:
        """Quem é digitado à mão já entra marcado."""
        names = core.adicionar_colaborador(self._names, name)
        self._selected.add(names[-1].casefold())
        self._save_names(names)
        self._save_selection()

    def remove(self, name: str) -> None:
        self._selected.discard(name.casefold())
        self._save_names([existing for existing in self._names if existing != name])
        self._save_selection()

    def merge(self, found: list[str]) -> list[str]:
        """Acrescenta os usuários da catraca que faltam, desmarcados. Devolve os novos."""
        names, new = core.mesclar_usuarios(self._names, found)
        if new:
            self._save_names(names)
        return new

    def _save_names(self, names: list[str]) -> None:
        self._names = names
        app_settings().setValue(self._KEY_NAMES, json.dumps(names, ensure_ascii=False))
        self.changed.emit()

    def _save_selection(self) -> None:
        app_settings().setValue(self._KEY_SELECTED, json.dumps(self.selected, ensure_ascii=False))
        self.selection_changed.emit()


class BackgroundJob(QObject):
    """Consulta a catraca em uma thread própria.

    A biblioteca HTTP não permite interromper uma espera. Por isso a thread é daemon e, ao
    cancelar ou fechar o programa, a página apenas ignora o resultado dela (pelo `job_id`).
    """

    progressed = Signal(int, str)
    succeeded = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, job_id: int, task: Callable[[Callable[[str], None]], object]):
        super().__init__()
        self._job_id = job_id
        self._task = task

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            result = self._task(lambda message: self.progressed.emit(self._job_id, message))
        except core.CatracaError as exc:
            self.failed.emit(self._job_id, str(exc))
        except Exception as exc:  # a interface precisa sempre sair do estado "ocupado"
            self.failed.emit(self._job_id, f"Erro inesperado: {exc}")
        else:
            self.succeeded.emit(self._job_id, result)

    def connect_to(self, on_progress, on_success, on_failure) -> None:
        queued = Qt.ConnectionType.QueuedConnection
        self.progressed.connect(on_progress, queued)
        self.succeeded.connect(on_success, queued)
        self.failed.connect(on_failure, queued)


class ReportPage(QWidget):
    def __init__(self, store: UserStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("surface", "content")
        self._store = store
        self._settings = app_settings()
        self._report: core.Relatorio | None = None
        self._job: BackgroundJob | None = None
        self._job_id = 0
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self._apply_search)
        self._build_ui()
        self._set_period(core.quinzena_de(date.today()))
        self._show_report(None)
        self._store.changed.connect(self._update_selection_label)
        self._store.selection_changed.connect(self._update_selection_label)
        self._update_selection_label()
        self._refresh_actions()

    # ------------------------------------------------------------ Construção
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        margin = SPACING["xl"]
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(SPACING["lg"])

        top_row = ResponsiveRow(320, (2, 1))
        top_row.add(self._build_connection_card())
        top_row.add(self._build_period_card())
        layout.addWidget(top_row)
        layout.addLayout(self._build_action_row())

        stats = ResponsiveRow(135, (4, 2, 1))
        self._stat_records = StatCard("Registros", "layers", "primary")
        self._stat_people = StatCard("Colaboradores", "users")
        self._stat_with = StatCard("Com registro", "user-check", "success")
        self._stat_without = StatCard("Sem registro", "user-x", "danger")
        for card in (self._stat_records, self._stat_people, self._stat_with, self._stat_without):
            stats.add(card)
        layout.addWidget(stats)
        layout.addWidget(self._build_result_card(), 1)

    def _build_connection_card(self) -> Card:
        card = Card("Conexão com a catraca", "A senha não é salva: digite-a a cada abertura do programa.")
        self._ip_input = TextInput("Ex.: 192.168.0.130")
        self._ip_input.setText(str(self._settings.value("catraca/ip", core.IP_PADRAO)))
        self._user_input = TextInput("Usuário da catraca")
        self._user_input.setText(str(self._settings.value("catraca/usuario", core.USUARIO_PADRAO)))
        self._password_input = PasswordInput("Senha da catraca")
        self._password_input.returnPressed.connect(self._start_report)
        for field in (self._ip_input, self._user_input, self._password_input):
            field.textEdited.connect(lambda _text, target=field: target.set_invalid(False))

        fields = ResponsiveRow(120, (3, 1), SPACING["md"])
        fields.add(FormField("IP", self._ip_input))
        fields.add(FormField("Usuário", self._user_input))
        fields.add(FormField("Senha", self._password_input))
        card.body.addWidget(fields)
        card.body.addStretch()
        return card

    def _build_period_card(self) -> Card:
        card = Card("Período do relatório")
        self._start_input = DateInput()
        self._end_input = DateInput()
        dates = ResponsiveRow(140, (2, 1), SPACING["md"])
        dates.add(FormField("Data inicial", self._start_input))
        dates.add(FormField("Data final", self._end_input))
        card.body.addWidget(dates)

        shortcuts = ResponsiveRow(110, (5, 3, 2), SPACING["sm"])
        self._shortcut_buttons = []
        for text, period in (
            ("Quinzena atual", core.quinzena_de),
            ("Quinzena anterior", core.quinzena_anterior),
            ("Mês atual", core.mes_de),
            ("Mês anterior", core.mes_anterior),
            ("Últimos 15 dias", core.ultimos_15_dias),
        ):
            button = Button(text, "secondary", "sm")
            button.clicked.connect(lambda _checked, fn=period: self._set_period(fn(date.today())))
            shortcuts.add(button)
            self._shortcut_buttons.append(button)
        card.body.addWidget(shortcuts)
        card.body.addStretch()
        return card

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(SPACING["md"])
        self._generate_button = Button("Gerar relatório", "primary", "lg", "file-text")
        self._generate_button.clicked.connect(self._start_report)
        row.addWidget(self._generate_button)

        status = QVBoxLayout()
        status.setSpacing(SPACING["xs"])
        status.addStretch()
        self._progress = ProgressBar()
        self._progress.set_busy(True)
        self._progress_label = text_label("", "caption")
        self._selection_label = text_label("", "muted")
        status.addWidget(self._selection_label)
        status.addWidget(self._progress_label)
        status.addWidget(self._progress)
        status.addStretch()
        row.addLayout(status, 1)

        self._cancel_button = Button("Cancelar", "secondary", "md")
        self._cancel_button.clicked.connect(self._cancel_report)
        row.addWidget(self._cancel_button)
        return row

    def _build_result_card(self) -> Card:
        card = Card()
        toolbar = ResponsiveRow(170, (4, 2, 1), SPACING["sm"])
        self._search = SearchInput("Pesquisar por nome ou data")
        self._search.textChanged.connect(lambda _text: self._search_timer.start())
        self._view_filter = ComboBox(["Por colaborador", "Todos os acessos"])
        self._view_filter.currentIndexChanged.connect(self._on_view_changed)
        self._save_button = Button("Salvar CSV", "secondary", "md", "download")
        self._save_button.clicked.connect(self._save_report)
        toolbar.add(text_label("Resultado", "section"))
        toolbar.add(self._search)
        toolbar.add(self._view_filter)
        toolbar.add(self._save_button)
        card.body.addWidget(toolbar)

        self._summary_label = text_label("", "muted", wrap=True)
        card.body.addWidget(self._summary_label)

        self._summary_table = DataTable(SUMMARY_COLUMNS, 0, COL_SITUATION)
        self._summary_table.setSortingEnabled(True)
        self._summary_table.cellClicked.connect(self._on_summary_clicked)
        self._access_table = DataTable(ACCESS_COLUMNS, 0)
        self._access_table.setSortingEnabled(True)
        # Pode ter milhares de linhas: as larguras são medidas ao preencher, não a cada troca de tema.
        for column in range(1, len(ACCESS_COLUMNS)):
            self._access_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.Interactive
            )
        self._empty_state = EmptyState(
            "file-text",
            "Nenhum relatório gerado",
            "Informe a senha e o período, e clique em Gerar relatório.",
        )
        self._result_stack = QStackedLayout()
        for widget in (self._empty_state, self._summary_table, self._access_table):
            widget.setMinimumHeight(360)
            self._result_stack.addWidget(widget)
        card.body.addLayout(self._result_stack, 1)
        return card

    # ------------------------------------------------------------ Período
    def _set_period(self, period: tuple[date, date]) -> None:
        self._start_input.set_value(period[0])
        self._end_input.set_value(period[1])

    def _update_selection_label(self) -> None:
        total, selected = len(self._store.names), len(self._store.selected)
        self._selection_label.setText(
            f"{selected} de {plural(total, 'usuário marcado', 'usuários marcados')} para o relatório. "
            "Altere na página Usuários."
        )

    # ------------------------------------------------------------ Conexão
    def connection(self) -> tuple[str, str, str]:
        """IP, usuário e senha como estão nos campos (a senha pode estar vazia)."""
        return clean_host(self._ip_input.text()), self._user_input.text().strip(), self._password_input.text()

    def remember_connection(self, host: str, user: str, password: str) -> None:
        """Salva IP e usuário; a senha fica só no campo, até fechar o programa."""
        self._settings.setValue("catraca/ip", host)
        self._settings.setValue("catraca/usuario", user)
        self._ip_input.setText(host)
        self._user_input.setText(user)
        self._password_input.setText(password)

    # ------------------------------------------------------------ Geração
    def _validated_connection(self) -> tuple[str, str, str] | None:
        host = clean_host(self._ip_input.text())
        user = self._user_input.text().strip()
        password = self._password_input.text()
        fields = ((self._ip_input, host), (self._user_input, user), (self._password_input, password))
        for field, value in fields:
            field.set_invalid(not value)
        for field, value in fields:
            if not value:
                field.setFocus()
                return None
        return host, user, password

    def _start_report(self) -> None:
        if self._is_busy():
            return
        connection = self._validated_connection()
        if connection is None:
            return
        host, user, password = connection
        start, end = self._start_input.value(), self._end_input.value()
        if end < start:
            Modal.ask(
                self,
                "Período inválido",
                "A data final não pode ser anterior à data inicial.",
                "danger",
                [("ok", "Entendi", "primary")],
            )
            return
        names = self._store.selected
        if not names:
            Modal.ask(
                self,
                "Nenhum usuário marcado",
                "Marque ao menos um usuário na página Usuários.",
                "danger",
                [("ok", "Entendi", "primary")],
            )
            return

        self.remember_connection(host, user, password)
        self._show_report(None)

        self._job_id += 1
        self._job = BackgroundJob(
            self._job_id,
            lambda progress: core.gerar_relatorio(host, user, password, start, end, names, progress),
        )
        self._job.connect_to(self._on_progress, self._on_success, self._on_failure)
        self._progress_label.setText("Iniciando...")
        self._job.start()
        self._refresh_actions()

    def _cancel_report(self) -> None:
        self._finish_job()

    def _on_progress(self, job_id: int, message: str) -> None:
        if job_id == self._job_id and self._is_busy():
            self._progress_label.setText(message)

    def _on_success(self, job_id: int, report: core.Relatorio) -> None:
        if job_id == self._job_id and self._is_busy():
            self._finish_job()
            self._show_report(report)

    def _on_failure(self, job_id: int, message: str) -> None:
        if job_id == self._job_id and self._is_busy():
            self._finish_job()
            Modal.ask(self, "Não foi possível gerar o relatório", message, "danger",
                      [("ok", "Entendi", "primary")])

    def _finish_job(self) -> None:
        self._job = None
        self._progress_label.setText("")
        self._refresh_actions()

    def _is_busy(self) -> bool:
        return self._job is not None

    def has_work_in_progress(self) -> bool:
        return self._is_busy() or self._report is not None

    def _refresh_actions(self) -> None:
        busy = self._is_busy()
        self._generate_button.setEnabled(not busy)
        self._cancel_button.setVisible(busy)
        self._progress.setVisible(busy)
        self._progress_label.setVisible(busy)
        self._selection_label.setVisible(not busy)
        self._save_button.setEnabled(not busy and bool(self._report and self._report.total_registros))
        widgets = (self._ip_input, self._user_input, self._password_input, self._start_input,
                   self._end_input, *self._shortcut_buttons)
        for widget in widgets:
            widget.setEnabled(not busy)

    # ------------------------------------------------------------ Resultado
    def _show_report(self, report: core.Relatorio | None) -> None:
        self._report = report
        self._search.clear()
        self._view_filter.setCurrentIndex(VIEW_SUMMARY)
        self._fill_summary(report)
        self._fill_accesses(report)
        self._update_stats(report)
        self._on_view_changed(VIEW_SUMMARY)
        self._refresh_actions()

    def _fill_summary(self, report: core.Relatorio | None) -> None:
        table = self._summary_table
        table.setSortingEnabled(False)
        resumos = report.resumos if report else ()
        table.setRowCount(len(resumos))
        for row, resumo in enumerate(resumos):
            has_records = resumo.total > 0
            status = SortableItem("Com registro" if has_records else "Sem registro")
            status.setData(BADGE_TONE_ROLE, "success" if has_records else "danger")
            items = (
                SortableItem(resumo.nome, resumo.nome.casefold()),
                SortableItem(str(resumo.total), resumo.total),
                SortableItem(format_datetime(resumo.primeiro),
                             resumo.primeiro.isoformat() if resumo.primeiro else ""),
                SortableItem(format_datetime(resumo.ultimo),
                             resumo.ultimo.isoformat() if resumo.ultimo else ""),
                status,
            )
            for column, item in enumerate(items):
                item.setToolTip("Clique para ver os acessos" if has_records else
                                "Sem acessos no período: confira o nome cadastrado na catraca")
                table.setItem(row, column, item)
        table.setSortingEnabled(True)

    def _fill_accesses(self, report: core.Relatorio | None) -> None:
        table = self._access_table
        table.setSortingEnabled(False)
        acessos = report.acessos if report else ()
        table.setRowCount(len(acessos))
        for row, acesso in enumerate(acessos):
            moment = acesso.data_hora
            items = (
                SortableItem(acesso.nome, acesso.nome.casefold()),
                SortableItem(moment.strftime("%d/%m/%Y") if moment else acesso.texto_original or "–",
                             moment.isoformat() if moment else ""),
                SortableItem(moment.strftime("%H:%M:%S") if moment else "–",
                             moment.strftime("%H:%M:%S") if moment else ""),
                SortableItem(WEEKDAYS[moment.weekday()] if moment else "–",
                             moment.weekday() if moment else -1),
            )
            for column, item in enumerate(items):
                table.setItem(row, column, item)
        table.setSortingEnabled(True)
        table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        for column in range(1, len(ACCESS_COLUMNS)):
            table.resizeColumnToContents(column)

    def _update_stats(self, report: core.Relatorio | None) -> None:
        cards = (self._stat_records, self._stat_people, self._stat_with, self._stat_without)
        if report is None:
            for card in cards:
                card.set_value("–")
            self._summary_label.setText("")
            self._summary_label.hide()
            return
        without = len(report.sem_registro)
        self._stat_records.set_value(report.total_registros)
        self._stat_people.set_value(len(report.resumos))
        self._stat_with.set_value(len(report.resumos) - without)
        self._stat_without.set_value(without)
        summary = f"Período de {report.inicio:%d/%m/%Y} a {report.fim:%d/%m/%Y}."
        if without:
            summary += f" {plural(without, 'colaborador', 'colaboradores')} sem registro: confira o nome cadastrado na catraca."
        self._summary_label.setText(summary)
        self._summary_label.show()

    def _on_view_changed(self, index: int) -> None:
        if self._report is None:
            self._result_stack.setCurrentWidget(self._empty_state)
        elif index == VIEW_ACCESSES:
            self._result_stack.setCurrentWidget(self._access_table)
        else:
            self._result_stack.setCurrentWidget(self._summary_table)
        self._apply_search()

    def _on_summary_clicked(self, row: int, _column: int) -> None:
        if int(self._summary_table.item(row, 1).text()) > 0:
            self._search.setText(self._summary_table.item(row, 0).text())
            self._view_filter.setCurrentIndex(VIEW_ACCESSES)

    def _apply_search(self) -> None:
        self._search_timer.stop()
        query = self._search.text().strip().casefold()
        table = (
            self._access_table if self._view_filter.currentIndex() == VIEW_ACCESSES
            else self._summary_table
        )
        table.setUpdatesEnabled(False)
        for row in range(table.rowCount()):
            table.setRowHidden(row, bool(query) and not search_matches(table, row, query))
        table.setUpdatesEnabled(True)

    # ------------------------------------------------------------ Exportação
    def _save_report(self) -> None:
        report = self._report
        if report is None:
            return
        suggested = core.nome_sugerido(report.inicio, report.fim)
        folder = self._settings.value("ultima_pasta", "")
        start = str(Path(str(folder)) / suggested) if folder else suggested
        path, _ = QFileDialog.getSaveFileName(self, "Salvar relatório", start, "Arquivo CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            core.salvar_csv(report, path)
        except core.CatracaError as exc:
            Modal.ask(self, "Falha ao salvar", str(exc), "danger", [("ok", "Entendi", "primary")])
            return
        saved = Path(path)
        self._settings.setValue("ultima_pasta", str(saved.parent))
        choice = Modal.ask(
            self,
            "Relatório salvo",
            f"{plural(report.total_registros, 'registro salvo', 'registros salvos')} em:\n{saved}",
            "success",
            [("close", "Fechar", "secondary"), ("open", "Abrir pasta", "primary")],
        )
        if choice == "open":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(saved.parent)))


class UsersPage(QWidget):
    """Lista de usuários com marcação: só os marcados entram no relatório."""

    MAX_NAMES_IN_MESSAGE = 8

    def __init__(self, store: UserStore, report_page: ReportPage, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("surface", "content")
        self._store = store
        self._report_page = report_page
        self._job: BackgroundJob | None = None
        self._job_id = 0
        self._build_ui()
        self._store.changed.connect(self._populate)
        self._store.selection_changed.connect(self._sync_checks)
        self._populate()
        self._refresh_import()

    # ------------------------------------------------------------ Construção
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        margin = SPACING["xl"]
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(SPACING["lg"])

        add_card = Card(
            "Adicionar usuários",
            "Busque todos os usuários cadastrados na catraca ou digite um nome exatamente como "
            "está nela. Maiúsculas e minúsculas não importam.",
        )
        import_row = QHBoxLayout()
        import_row.setSpacing(SPACING["md"])
        self._import_button = Button("Buscar na catraca", "secondary", "md", "download")
        self._import_button.clicked.connect(self._start_import)
        import_row.addWidget(self._import_button)
        status = QVBoxLayout()
        status.setSpacing(SPACING["xs"])
        status.addStretch()
        self._import_label = text_label("", "caption")
        self._import_progress = ProgressBar()
        self._import_progress.set_busy(True)
        status.addWidget(self._import_label)
        status.addWidget(self._import_progress)
        status.addStretch()
        import_row.addLayout(status, 1)
        add_card.body.addLayout(import_row)

        self._name_input = TextInput("Nome do usuário")
        self._name_input.returnPressed.connect(self._add)
        self._name_input.textEdited.connect(self._clear_error)
        self._add_button = Button("Adicionar", "primary", "md", "plus")
        self._add_button.clicked.connect(self._add)
        input_row = QWidget()
        row = QHBoxLayout(input_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACING["sm"])
        row.addWidget(self._name_input, 1)
        row.addWidget(self._add_button)
        self._name_field = FormField("Adicionar pelo nome", input_row)
        add_card.body.addWidget(self._name_field)
        layout.addWidget(add_card)

        list_card = Card()
        toolbar = ResponsiveRow(150, (5, 3, 1), SPACING["sm"])
        self._count_label = text_label("", "section")
        self._search = SearchInput("Pesquisar usuário")
        self._search.textChanged.connect(self._apply_search)
        self._check_all_button = Button("Marcar todos", "secondary", "md", "check")
        self._check_all_button.clicked.connect(lambda: self._set_visible_checked(True))
        self._uncheck_all_button = Button("Desmarcar todos", "secondary", "md", "x")
        self._uncheck_all_button.clicked.connect(lambda: self._set_visible_checked(False))
        self._remove_button = Button("Remover", "danger", "md", "trash")
        self._remove_button.clicked.connect(self._remove_selected)
        for widget in (self._count_label, self._search, self._check_all_button,
                       self._uncheck_all_button, self._remove_button):
            toolbar.add(widget)
        list_card.body.addWidget(toolbar)
        list_card.body.addWidget(text_label(
            "Marque quem deve entrar no relatório. A escolha fica salva para as próximas vezes. "
            "Com uma pesquisa ativa, Marcar e Desmarcar todos valem só para os nomes encontrados.",
            "muted", wrap=True,
        ))

        self._table = DataTable(["Usuário"], 0)
        self._table.setSortingEnabled(True)
        self._table.setMinimumHeight(360)
        self._table.itemSelectionChanged.connect(self._refresh_actions)
        self._table.cellClicked.connect(lambda row, _column: self._toggle_row(row))
        self._table.installEventFilter(self)
        list_card.body.addWidget(self._table, 1)
        layout.addWidget(list_card, 1)

    # ------------------------------------------------------------ Lista e marcações
    def _populate(self) -> None:
        names = self._store.names
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(names))
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        for row, name in enumerate(names):
            item = SortableItem(name, name.casefold())
            # A marcação é feita pela página (clique na linha ou Espaço), não pelo item.
            item.setFlags(flags)
            self._table.setItem(row, 0, item)
        self._table.setSortingEnabled(True)
        self._table.clearSelection()
        self._sync_checks()
        self._apply_search()
        self._refresh_actions()

    def _sync_checks(self) -> None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            checked = self._store.is_selected(item.text())
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        total, selected = len(self._store.names), len(self._store.selected)
        self._count_label.setText(f"{selected} de {plural(total, 'usuário marcado', 'usuários marcados')}")

    def _toggle_row(self, row: int) -> None:
        item = self._table.item(row, 0)
        if item is not None:
            self._store.set_selected([item.text()], not self._store.is_selected(item.text()))

    def _visible_names(self) -> list[str]:
        return [
            self._table.item(row, 0).text()
            for row in range(self._table.rowCount())
            if not self._table.isRowHidden(row)
        ]

    def _set_visible_checked(self, checked: bool) -> None:
        self._store.set_selected(self._visible_names(), checked)

    def eventFilter(self, watched, event) -> bool:
        if (watched is self._table and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Space and self._table.currentRow() >= 0):
            self._toggle_row(self._table.currentRow())
            return True
        return super().eventFilter(watched, event)

    def _apply_search(self, *_args) -> None:
        query = self._search.text().strip().casefold()
        for row in range(self._table.rowCount()):
            self._table.setRowHidden(row, query not in self._table.item(row, 0).text().casefold())

    def _refresh_actions(self) -> None:
        self._remove_button.setEnabled(bool(self._table.selectedItems()))

    # ------------------------------------------------------------ Buscar na catraca
    def _start_import(self) -> None:
        if self.is_busy():
            return
        host, user, password = self._report_page.connection()
        if not host or not user:
            Modal.ask(
                self,
                "Conexão incompleta",
                "Preencha o IP e o usuário da catraca na página Relatório de acessos.",
                "danger",
                [("ok", "Entendi", "primary")],
            )
            return
        if not password:
            password = self._ask_password(host, user)
            if not password:
                return
        self._report_page.remember_connection(host, user, password)

        self._job_id += 1
        self._job = BackgroundJob(
            self._job_id, lambda progress: core.listar_usuarios(host, user, password, progress)
        )
        self._job.connect_to(self._on_import_progress, self._on_import_success, self._on_import_failure)
        self._import_label.setText("Iniciando...")
        self._job.start()
        self._refresh_import()

    def _ask_password(self, host: str, user: str) -> str:
        modal = Modal(
            self,
            "Senha da catraca",
            f"Digite a senha do usuário {user} da catraca em {host}. Ela não é salva.",
        )
        field = PasswordInput("Senha da catraca")
        modal.content.addWidget(FormField("Senha", field))
        modal.add_action("cancel", "Cancelar", "secondary")
        confirm = modal.add_action("ok", "Buscar", "primary")
        confirm.setDefault(True)
        field.returnPressed.connect(confirm.click)
        field.setFocus()
        modal.exec()
        return field.text() if modal.result_key == "ok" else ""

    def _on_import_progress(self, job_id: int, message: str) -> None:
        if job_id == self._job_id and self.is_busy():
            self._import_label.setText(message)

    def _on_import_success(self, job_id: int, found: list[str]) -> None:
        if job_id != self._job_id or not self.is_busy():
            return
        self._finish_import()
        new = self._store.merge(found)
        if new:
            self._search.clear()
        Modal.ask(self, "Usuários atualizados", self._import_summary(found, new), "success",
                  [("ok", "Entendi", "primary")])

    def _import_summary(self, found: list[str], new: list[str]) -> str:
        message = f"{plural(len(found), 'usuário encontrado', 'usuários encontrados')} na catraca."
        if new:
            message += (
                f" {plural(len(new), 'novo foi adicionado', 'novos foram adicionados')} à lista, "
                "desmarcados: marque quem deve entrar no relatório."
            )
        else:
            message += " Todos já estavam na lista."
        on_device = {name.casefold() for name in found}
        missing = [name for name in self._store.names if name.casefold() not in on_device]
        if missing:
            shown = ", ".join(missing[: self.MAX_NAMES_IN_MESSAGE])
            if len(missing) > self.MAX_NAMES_IN_MESSAGE:
                shown += f" e mais {len(missing) - self.MAX_NAMES_IN_MESSAGE}"
            message += (
                f"\n\nNão estão cadastrados na catraca com este nome: {shown}. "
                "Confira a grafia ou remova-os da lista."
            )
        return message

    def _on_import_failure(self, job_id: int, message: str) -> None:
        if job_id == self._job_id and self.is_busy():
            self._finish_import()
            Modal.ask(self, "Não foi possível buscar os usuários", message, "danger",
                      [("ok", "Entendi", "primary")])

    def _finish_import(self) -> None:
        self._job = None
        self._import_label.setText("")
        self._refresh_import()

    def is_busy(self) -> bool:
        return self._job is not None

    def _refresh_import(self) -> None:
        busy = self.is_busy()
        self._import_button.setEnabled(not busy)
        self._import_label.setVisible(busy)
        self._import_progress.setVisible(busy)

    def _clear_error(self, _text: str = "") -> None:
        self._name_input.set_invalid(False)
        self._name_field.set_helper("")

    def _add(self) -> None:
        try:
            self._store.add(self._name_input.text())
        except ValueError as exc:
            self._name_input.set_invalid(True)
            self._name_field.set_helper(str(exc))
            self._name_input.setFocus()
            return
        self._name_input.clear()
        self._clear_error()

    def _remove_selected(self) -> None:
        selected = self._table.selectedItems()
        if not selected:
            return
        name = selected[0].text()
        choice = Modal.ask(
            self,
            "Remover usuário",
            f"{name} deixará de aparecer nos próximos relatórios. Os arquivos já salvos não mudam.",
            "danger",
            [("cancel", "Cancelar", "secondary"), ("remove", "Remover", "danger")],
        )
        if choice == "remove":
            self._store.remove(name)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(860, 600)
        self.resize(1240, 820)

        self.updates = UpdateController(self)
        self.store = UserStore(self)
        self.sidebar = Sidebar(APP_NAME, "door-open", f"Versão {__version__}")
        self.header = Header()
        self.stack = QStackedWidget()
        self.report_page = ReportPage(self.store)
        self.users_page = UsersPage(self.store, self.report_page)
        self._pages = [
            ("Relatório de acessos", "file-text", self.report_page),
            ("Usuários", "users", self.users_page),
        ]
        for title, icon, page in self._pages:
            self.sidebar.add_page(title, icon)
            self.stack.addWidget(page_scroll_area(page))
        self.sidebar.page_selected.connect(self._show_page)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self.header)
        right.addWidget(self.stack, 1)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.sidebar)
        root.addLayout(right, 1)
        self.setCentralWidget(central)
        self._show_page(0)
        # Evita o anel de foco em um controle ao abrir; Tab continua navegando normalmente.
        central.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        central.setFocus()
        theme.about_to_change.connect(self._fade_theme)

    def _show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.header.set_title(self._pages[index][0])

    def _fade_theme(self) -> None:
        if self.isVisible():
            ThemeFade(self)

    def has_work_in_progress(self) -> bool:
        return self.report_page.has_work_in_progress() or self.users_page.is_busy()

    def closeEvent(self, event) -> None:
        self.hide()
        self.updates.wait()
        super().closeEvent(event)


def create_application(argv: list[str]) -> QApplication:
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setFont(default_font())
    QLocale.setDefault(QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil))
    theme.apply()
    app.setWindowIcon(_window_icon())
    return app


def _window_icon() -> QIcon:
    return themed_icon("door-open", "primary", 32)


def main() -> int:
    app = create_application(sys.argv)
    window = MainWindow()
    window.show()
    QTimer.singleShot(0, window.updates.start)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
