"""Interface da atualização automática: consulta, download, instalação e reinício."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QApplication, QWidget

import updater
from components import Button, Modal, ProgressBar, text_label
from version import __version__


class TaskThread(QThread):
    """Executa uma tarefa fora da thread da interface e informa o progresso."""

    progressed = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, task: Callable[[Callable[[int, int], None]], object], parent=None):
        super().__init__(parent)
        self._task = task

    def run(self) -> None:
        try:
            self.succeeded.emit(self._task(self.progressed.emit))
        except updater.UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # a interface precisa sempre sair do estado "ocupado"
            self.failed.emit(f"Erro inesperado: {exc}")


def format_megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):.1f}".replace(".", ",")


class UpdateDialog(Modal):
    """Mostra o download da atualização e guarda como ele terminou."""

    def __init__(self, parent: QWidget, version: str, cancel: threading.Event):
        super().__init__(
            parent,
            "Atualizando o programa",
            f"Baixando a versão {version}. O programa será reiniciado ao final.",
            "info",
        )
        self._cancel = cancel
        self.downloaded = False
        self.error: str | None = None

        self._bar = ProgressBar()
        self._caption = text_label("Conectando...", "caption")
        self.content.addWidget(self._bar)
        self.content.addWidget(self._caption)

        self._cancel_button = Button("Cancelar", "secondary")
        self._cancel_button.clicked.connect(self.request_cancel)
        self.actions.addWidget(self._cancel_button)

    def set_progress(self, done: int, total: int) -> None:
        if total:
            percent = min(int(done * 100 / total), 100)
            self._bar.setValue(percent)
            self._caption.setText(
                f"{format_megabytes(done)} MB de {format_megabytes(total)} MB ({percent}%)"
            )
        else:
            self._caption.setText(f"{format_megabytes(done)} MB")

    def request_cancel(self) -> None:
        self._cancel.set()
        self._cancel_button.setEnabled(False)
        self._cancel_button.setText("Cancelando...")

    def on_success(self, downloaded: bool) -> None:
        self.downloaded = downloaded
        self.done(0)

    def on_failure(self, message: str) -> None:
        self.error = message
        self.done(0)

    # Esc e o X cancelam o download; a janela só fecha quando ele realmente parar.
    def reject(self) -> None:
        self.request_cancel()

    def closeEvent(self, event) -> None:
        event.ignore()
        self.request_cancel()


class UpdateController(QObject):
    """Procura atualização ao abrir e conduz o download, a instalação e o reinício."""

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self._window = window
        self._check_thread: TaskThread | None = None
        self._stop_check = threading.Event()

    def start(self) -> None:
        if not updater.can_self_update():
            return  # rodando pelo código-fonte: não há executável para substituir
        updater.start_cleanup()
        self._check_thread = TaskThread(
            lambda _progress: updater.find_update(stop=self._stop_check), self
        )
        self._check_thread.succeeded.connect(self._on_checked)
        self._check_thread.start()

    def wait(self) -> None:
        self._stop_check.set()
        if self._check_thread is not None:
            self._check_thread.wait()

    def _on_checked(self, release: updater.ReleaseInfo | None) -> None:
        # Nunca reinicia sobre um trabalho do usuário; a atualização fica para a próxima abertura.
        if (
            release is None
            or self._window.has_work_in_progress()
            or QApplication.activeModalWidget() is not None
        ):
            return
        self._download_and_install(release)

    def _download_and_install(self, release: updater.ReleaseInfo) -> None:
        executable = Path(sys.executable)
        new_file = updater.download_path(executable)
        cancel = threading.Event()
        dialog = UpdateDialog(self._window, release.version, cancel)
        thread = TaskThread(
            lambda progress: updater.download_update(release, new_file, progress, cancel), self
        )
        thread.progressed.connect(dialog.set_progress)
        thread.succeeded.connect(dialog.on_success)
        thread.failed.connect(dialog.on_failure)
        thread.start()
        dialog.exec()
        thread.wait()

        if dialog.error:
            self._show_failure(dialog.error)
        elif dialog.downloaded:
            try:
                updater.install_and_restart(new_file, executable)
            except updater.UpdateError as exc:
                self._show_failure(str(exc))
            else:
                QApplication.quit()

    def _show_failure(self, message: str) -> None:
        Modal.ask(
            self._window,
            "Não foi possível atualizar",
            f"{message}\n\nVocê pode continuar usando a versão {__version__}.",
            "danger",
            [("ok", "Continuar", "primary")],
        )
