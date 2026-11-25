"""Grade que reorganiza em colunas sem impor largura mínima à página.

A `GradeResponsiva` do Tcm-ui informa como largura mínima a soma das colunas do momento; dentro de uma
`Pagina` (área rolável) isso trava a largura do conteúdo e aparece rolagem horizontal. Esta versão informa
só o item mais largo (uma coluna) e quebra em mais linhas quando a largura diminui.
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QGridLayout, QWidget
from tcm_ui.components import Texto
from tcm_ui.themes import ESPACO


def permitir_quebra(widget: QWidget) -> None:
    """Deixa todo texto dentro de `widget` quebrar linha, para não alargar o layout."""
    for texto in widget.findChildren(Texto):
        texto.setWordWrap(True)


class GradeFluida(QWidget):
    """Distribui widgets em colunas de ao menos `largura_min` (ou do item mais largo, se maior).

    `linhas_completas`: prefere linhas inteiras (4 itens: 4, 2 ou 1 coluna, nunca 3+1).
    """

    def __init__(self, largura_min: int = 220, espaco: int = ESPACO["lg"], linhas_completas: bool = True,
                 parent=None):
        super().__init__(parent)
        self._largura_min = largura_min
        self._linhas_completas = linhas_completas
        self._itens: list[QWidget] = []
        self._colunas = 0
        self._grade = QGridLayout(self)
        self._grade.setContentsMargins(0, 0, 0, 0)
        self._grade.setSpacing(espaco)

    def adicionar(self, widget: QWidget) -> None:
        self._itens.append(widget)
        self._colunas = 0
        self._reorganizar()

    def _largura_coluna(self) -> int:
        return max([self._largura_min, *(item.minimumSizeHint().width() for item in self._itens)])

    def minimumSizeHint(self) -> QSize:
        base = super().minimumSizeHint()
        return QSize(self._largura_coluna() if self._itens else 0, base.height())

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        self._reorganizar()

    def _reorganizar(self) -> None:
        espaco = self._grade.spacing()
        total = len(self._itens)
        if not total:
            return
        colunas = max(1, min(total, (self.width() + espaco) // (self._largura_coluna() + espaco)))
        while self._linhas_completas and total % colunas and colunas > 1:
            colunas -= 1
        if colunas == self._colunas:
            return
        self._colunas = colunas
        for widget in self._itens:
            self._grade.removeWidget(widget)
        for indice, widget in enumerate(self._itens):
            self._grade.addWidget(widget, indice // colunas, indice % colunas)
        for coluna in range(total):
            self._grade.setColumnStretch(coluna, 1 if coluna < colunas else 0)
        self.updateGeometry()
