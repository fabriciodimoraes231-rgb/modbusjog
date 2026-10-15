"""Interface grafica do controle de drives STR6-RS485.

A janela e ui.app.JogApp; cada card da tela vive no seu proprio modulo
e entra na janela como mixin.
"""

from .app import JogApp
from .tema import apply_styles

__all__ = ["JogApp", "apply_styles"]
