"""Card INSPETOR DE REGISTRADOR: le e vigia um registrador qualquer."""

from tkinter import messagebox
import time
import tkinter as tk

from jog_gui.str6 import CONHECIDOS

from .tema import (
    ACCENT2,
    BG2,
    BG3,
    FONT_BOLD,
    FONT_LABEL,
    GREEN,
    RED,
    TEXT,
    TEXT_DIM,
    YELLOW,
)


class InspetorMixin:
    """Card INSPETOR DE REGISTRADOR: le e vigia um registrador qualquer."""


    # ==========================================================================
    # INSPETOR DE REGISTRADOR
    # ==========================================================================
    #
    # Aponta um endereco e acompanha aquele registrador especifico, avisando no
    # instante em que o valor muda. Existe porque conferir uma alteracao pelo
    # log hexadecimal exige decodificar o quadro na mao, e um registrador que
    # muda sozinho - por acao do drive, por um ciclo de energia ou por outro
    # comando - nao aparece no log de jeito nenhum, ja que ninguem o escreveu.
    #
    # So le (FC03). Nao escreve nada. Os enderecos seguem o manual do STR6,
    # que numera os registradores em DECIMAL.

    # Os nomes vem do mapa de registradores: uma tabela so para o inspetor e
    # para o resto do programa.
    _REG_CONHECIDOS = CONHECIDOS

    def _card_inspetor(self, parent):
        """Monta o card: endereco, intervalo, valor em destaque e os botoes."""
        f = self._card(parent, "INSPETOR DE REGISTRADOR")

        row = tk.Frame(f, bg=BG2)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Endereco:", bg=BG2, fg=TEXT, font=FONT_LABEL,
                 width=10, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=self.reg_endereco, width=10, bg=BG3, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 font=FONT_LABEL).pack(side="left")
        tk.Label(row, text="ex.: 24 ou 0x18", bg=BG2, fg=TEXT_DIM,
                 font=("Segoe UI", 8)).pack(side="left", padx=4)

        row = tk.Frame(f, bg=BG2)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Intervalo:", bg=BG2, fg=TEXT, font=FONT_LABEL,
                 width=10, anchor="w").pack(side="left")
        tk.Spinbox(row, from_=200, to=10000, increment=100,
                   textvariable=self.reg_intervalo, width=7, bg=BG3, fg=TEXT,
                   buttonbackground=BG3, insertbackground=TEXT, relief="flat",
                   font=FONT_LABEL).pack(side="left")
        tk.Label(row, text="ms", bg=BG2, fg=TEXT_DIM,
                 font=FONT_LABEL).pack(side="left", padx=4)

        # Valor atual em destaque: e o que responde "mudou ou nao" de relance
        self.lbl_reg_valor = tk.Label(f, text="---", bg=BG3, fg=TEXT_DIM,
                                      font=("Segoe UI", 13, "bold"), pady=6)
        self.lbl_reg_valor.pack(fill="x", pady=(4, 2))
        self.lbl_reg_nome = tk.Label(f, text="", bg=BG2, fg=TEXT_DIM,
                                     font=("Segoe UI", 8))
        self.lbl_reg_nome.pack()
        self.lbl_reg_mudanca = tk.Label(f, text="Sem mudanca registrada",
                                        bg=BG2, fg=TEXT_DIM, font=FONT_LABEL,
                                        wraplength=300, justify="left")
        self.lbl_reg_mudanca.pack(fill="x", pady=(2, 0))

        row_b = tk.Frame(f, bg=BG2)
        row_b.pack(fill="x", pady=(6, 2))
        self.btn_reg_ler = tk.Button(row_b, text="Ler agora", font=FONT_BOLD,
                                     bg=ACCENT2, fg="white", bd=0, padx=8,
                                     pady=6, cursor="hand2",
                                     command=self._reg_ler_uma_vez,
                                     state="disabled")
        self.btn_reg_ler.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_reg_vigiar = tk.Button(row_b, text="Vigiar", font=FONT_BOLD,
                                        bg=YELLOW, fg="white", bd=0, padx=8,
                                        pady=6, cursor="hand2",
                                        command=self._reg_toggle_vigia,
                                        state="disabled")
        self.btn_reg_vigiar.pack(side="right", expand=True, fill="x")

    # --- leitura e vigilancia ---------------------------------------------------

    def _reg_endereco_num(self):
        """
        Converte o que foi digitado em endereco. Aceita 75, 0x4B e 4Bh.

        So digitos sao lidos como DECIMAL, que e como o manual do STR6 numera
        os registradores. Hexadecimal pede o prefixo 0x ou o sufixo h; letras
        a-f sem marcador tambem sao lidas como hexadecimal.
        """
        txt = self.reg_endereco.get().strip().lower().replace(" ", "")
        if not txt:
            return None
        try:
            if txt.startswith("0x"):
                return int(txt[2:], 16)
            if txt.endswith("h"):
                return int(txt[:-1], 16)
            if any(c in "abcdef" for c in txt):
                return int(txt, 16)
            return int(txt, 10)
        except ValueError:
            return None

    def _reg_mostra(self, reg: int, valor: int, anterior=None):
        """Pinta o valor atual e, se houve mudanca, registra de onde para onde."""
        self.lbl_reg_valor.config(
            text="reg {} = {}   (0x{:04X})".format(reg, valor, valor),
            bg=BG3, fg=TEXT)
        nome = self._REG_CONHECIDOS.get(reg)
        bits = format(valor, "016b")
        self.lbl_reg_nome.config(
            text="{}bits: {} {} {} {}".format(
                nome + "   |   " if nome else "",
                bits[0:4], bits[4:8], bits[8:12], bits[12:16]))
        if anterior is not None and anterior != valor:
            self.lbl_reg_mudanca.config(
                text="MUDOU as {}:  {} -> {}   (0x{:04X} -> 0x{:04X})".format(
                    time.strftime("%H:%M:%S"), anterior, valor, anterior, valor),
                fg=GREEN)
            self.lbl_reg_valor.config(bg=GREEN, fg="white")
            self._log("[REG] reg {} mudou: {} -> {}".format(
                reg, anterior, valor))

    def _reg_ler_uma_vez(self):
        """Le o registrador digitado uma unica vez e mostra o valor.

        So conta como "mudanca" se o valor anterior for do MESMO endereco:
        antes, trocar de registrador anunciava uma mudanca que nunca ocorreu.
        """
        reg = self._reg_endereco_num()
        if reg is None:
            messagebox.showwarning("Endereco invalido",
                                   "Digite um endereco como 24 ou 0x18.")
            return
        if not self._check_conn():
            return

        def _tarefa():
            vals, motivo = self._ler_regs_espera(reg, 1, segundos=2.0)
            if vals is None:
                self._log("[REG] reg {}: {}".format(reg, motivo))
                self.after(0, lambda: self.lbl_reg_valor.config(
                    text="reg {} = sem resposta".format(reg), bg=BG3, fg=RED))
                return
            valor = vals[0]
            # So e "mudanca" se o valor anterior for do MESMO endereco: senao,
            # trocar de registrador anunciava uma mudanca que nunca ocorreu
            anterior = self._reg_ultimo if self._reg_ultimo_end == reg else None
            self._reg_ultimo = valor
            self._reg_ultimo_end = reg
            self._log("[REG] reg {} = {} (0x{:04X})".format(reg, valor, valor))
            self.after(0, lambda: self._reg_mostra(reg, valor, anterior))

        self._thread_op(_tarefa)

    def _reg_toggle_vigia(self):
        """Liga ou desliga a vigilancia periodica do registrador digitado.

        Ligar zera o historico e prende a vigilancia naquele endereco -- mudar
        o campo depois nao redireciona a leitura, e preciso parar e religar.
        """
        if self.reg_vigiando:
            self.reg_vigiando = False
            self.btn_reg_vigiar.config(text="Vigiar", bg=YELLOW)
            self.lbl_reg_mudanca.config(
                text="Vigilancia parada ({} mudanca(s) vistas)".format(
                    self._reg_mudancas), fg=TEXT_DIM)
            return
        reg = self._reg_endereco_num()
        if reg is None:
            messagebox.showwarning("Endereco invalido",
                                   "Digite um endereco como 24 ou 0x18.")
            return
        if not self._check_conn():
            return
        self.reg_vigiando = True
        self._reg_ultimo = None
        self._reg_ultimo_end = reg
        self._reg_mudancas = 0
        self.btn_reg_vigiar.config(text="Parar vigilancia", bg=RED)
        self.lbl_reg_mudanca.config(text="Vigiando o reg {}...".format(reg),
                                    fg=YELLOW)
        self._log("[REG] Vigiando o reg {} a cada {} ms".format(
            reg, self._ivar(self.reg_intervalo, 500)))
        self._thread_op(self._reg_loop_vigia, reg)

    def _reg_loop_vigia(self, reg: int):
        """
        Le o registrador em intervalo fixo e avisa a cada mudanca de valor.

        Le so 1 registrador por vez de proposito: quem esta investigando quer
        saber daquele endereco, e um quadro curto disputa menos o barramento
        com o monitor de status.
        """
        intervalo = max(0.2, self._ivar(self.reg_intervalo, 500) / 1000.0)
        falhas = 0
        while self.reg_vigiando and self._conectado:
            vals = self._ler_regs(reg, 1)
            if vals is None:
                falhas += 1
                if falhas == 3:
                    self._log("[REG] reg {} sem resposta - o drive pode estar "
                              "gravando; a vigilancia continua".format(reg))
                time.sleep(intervalo)
                continue
            falhas = 0
            valor = vals[0]
            anterior = self._reg_ultimo
            if anterior is None or valor != anterior:
                if anterior is not None:
                    self._reg_mudancas += 1
                self._reg_ultimo = valor
                self._reg_ultimo_end = reg
                self.after(0, lambda v=valor, a=anterior: self._reg_mostra(
                    reg, v, a))
            time.sleep(intervalo)
        self.reg_vigiando = False
