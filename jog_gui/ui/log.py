"""Card LOG HEX MODBUS: todo o trafego, quadro a quadro."""

from tkinter import scrolledtext
import time
import tkinter as tk

from .tema import (
    BG3,
    FONT_LABEL,
    FONT_MONO,
    TEXT_DIM,
)


class LogMixin:
    """Card LOG HEX MODBUS: todo o trafego, quadro a quadro."""


    def _card_log(self, parent):
        """Monta o painel de log e o botao de limpar."""
        f = self._card(parent, "LOG HEX MODBUS")

        self.txt_log = scrolledtext.ScrolledText(f, height=12, width=42,
                                                 bg=BG3, fg="#a0aec0",
                                                 font=FONT_MONO, bd=0,
                                                 state="disabled",
                                                 wrap="char")
        self.txt_log.pack(fill="both", expand=True)

        tk.Button(f, text="Limpar Log", bg=BG3, fg=TEXT_DIM,
                  font=FONT_LABEL, bd=0, cursor="hand2",
                  command=self._clear_log).pack(anchor="e", pady=(4, 0))

    # --- LOG ------------------------------------------------------------------

    def _log(self, msg: str):
        """Escreve uma linha carimbada com a hora no painel de log.

        Pode ser chamado de qualquer thread: a insercao e agendada com
        `after(0, ...)` para a thread da interface, que e a unica que pode
        tocar num widget Tk.
        """
        ts = time.strftime("%H:%M:%S")
        def _do():
            self.txt_log.config(state="normal")
            self.txt_log.insert("end", "{}  {}\n".format(ts, msg))
            self.txt_log.see("end")
            self.txt_log.config(state="disabled")
        self.after(0, _do)

    def _clear_log(self):
        """Esvazia o painel. So a thread da interface deve chamar."""
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.config(state="disabled")
