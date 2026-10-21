"""Cores, fontes e estilos ttk da interface."""

import sys
from tkinter import ttk


BG          = "#0f1117"
BG2         = "#1a1d27"
BG3         = "#22263a"
ACCENT      = "#4f8ef7"
ACCENT2     = "#7c3aed"
GREEN       = "#22c55e"
RED         = "#ef4444"
YELLOW      = "#f59e0b"
TEXT        = "#e2e8f0"
TEXT_DIM    = "#64748b"
BORDER      = "#2d3748"
JOG_CLR     = "#f59e0b"
JOG_ACTIVE  = "#dc2626"

# Segoe UI e Consolas so existem no Windows. No Linux o Tk trocaria por uma
# fonte qualquer, de largura diferente, e os cards desalinhariam: la vale a
# DejaVu, que vem em toda distribuicao.
if sys.platform.startswith("win"):
    FAMILIA, FAMILIA_MONO = "Segoe UI", "Consolas"
else:
    FAMILIA, FAMILIA_MONO = "DejaVu Sans", "DejaVu Sans Mono"


def fonte(tamanho, *estilo):
    """Fonte da interface no tamanho pedido: fonte(8), fonte(11, "bold")."""
    return (FAMILIA, tamanho) + estilo


FONT_TITLE  = fonte(16, "bold")
FONT_LABEL  = fonte(9)
FONT_BOLD   = fonte(9, "bold")
FONT_MONO   = (FAMILIA_MONO, 8)
FONT_BIG    = fonte(20, "bold")
FONT_JOG    = fonte(13, "bold")


def amperes_txt(ma: int) -> str:
    """Formata a corrente de pico do STR6 (registrador 0, em mA) em amperes.

    O valor bruto vai junto para conferencia com o manual e com o log.
    """
    return "{:.2f} A  ({} mA)".format(ma / 1000.0, ma)


def vel_txt(pps: int, pulsos_volta: int) -> str:
    """Velocidade em pulsos/s com o equivalente em rpm.

    O rpm depende dos pulsos por volta (registrador 1) e e so informativo: o
    drive recebe pulsos/s.
    """
    rpm = pps * 60.0 / max(1, pulsos_volta)
    return "{} p/s  (~{:.0f} rpm)".format(pps, rpm)


def apply_styles():
    """Aplica o tema escuro aos widgets ttk (hoje, os Combobox).

    Os widgets tk classicos recebem cor por argumento na criacao; os ttk so
    obedecem via Style, e por isso precisam deste passo a parte.
    """
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TCombobox",
                    fieldbackground=BG3,
                    background=BG3,
                    foreground=TEXT,
                    selectbackground=ACCENT,
                    selectforeground="white",
                    bordercolor=BORDER,
                    arrowcolor=ACCENT)
    style.map("TCombobox",
              fieldbackground=[("readonly", BG3)],
              foreground=[("readonly", TEXT)])
