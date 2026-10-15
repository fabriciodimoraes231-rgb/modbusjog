"""Card MOTOR: habilita/desabilita o eixo e limpa a falha."""

from tkinter import messagebox
import time
import tkinter as tk

from jog_gui.motion import em_falha, motivo_falha
from jog_gui.str6 import (
    MALHAS,
    REG_ALARME,
    REG_ENABLE,
    REG_MALHA,
    REG_STATUS,
)

from .tema import (
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


class MotorMixin:
    """Card MOTOR: habilita/desabilita o eixo e limpa a falha."""


    def _card_motor(self, parent):
        """Monta o card: MOTOR ON, MOTOR OFF, estado, LIMPAR FALHA e a trava
        do ultimo degrau da parada."""
        f = self._card(parent, "MOTOR")

        row = tk.Frame(f, bg=BG2)
        row.pack(fill="x", pady=4)
        self.btn_motor_on = tk.Button(row, text="MOTOR ON", font=FONT_BOLD,
                                      bg=GREEN, fg="white", bd=0,
                                      padx=16, pady=8, cursor="hand2",
                                      command=self._motor_on, state="disabled")
        self.btn_motor_on.pack(side="left", expand=True, fill="x", padx=(0, 4))

        self.btn_motor_off = tk.Button(row, text="MOTOR OFF", font=FONT_BOLD,
                                       bg=RED, fg="white", bd=0,
                                       padx=16, pady=8, cursor="hand2",
                                       command=self._motor_off, state="disabled")
        self.btn_motor_off.pack(side="right", expand=True, fill="x")

        self.lbl_motor_state = tk.Label(f, text="Motor: ---", bg=BG2, fg=TEXT_DIM,
                                        font=FONT_LABEL)
        self.lbl_motor_state.pack()

        row_alarm = tk.Frame(f, bg=BG2)
        row_alarm.pack(fill="x", pady=(6, 0))
        self.btn_reset_alarm = tk.Button(
            row_alarm, text="LIMPAR FALHA  (reg 93 = 1)",
            font=FONT_BOLD, bg="#7c3aed", fg="white", bd=0,
            padx=10, pady=6, cursor="hand2",
            command=self._reset_alarme, state="disabled")
        self.btn_reset_alarm.pack(fill="x")
        self.lbl_alarm_status = tk.Label(f, text="", bg=BG2, fg=TEXT_DIM, font=FONT_LABEL)
        self.lbl_alarm_status.pack()

        # Eixo vertical: o ultimo degrau da parada escalonada desabilita o
        # motor e a carga desce. Por eixo, salvo no cadastro.
        tk.Checkbutton(f, text="Parada: desabilitar o motor como ultimo recurso\n"
                               "(num eixo vertical isso DERRUBA A CARGA)",
                       variable=self.soltar_emerg, bg=BG2, fg=TEXT,
                       selectcolor=BG3, activebackground=BG2, justify="left",
                       font=("Segoe UI", 8)).pack(anchor="w", pady=(6, 0))

    # --- MOTOR ON/OFF  (reg 6) --------------------------------------------------

    def _motor_on(self):
        """Habilita o motor do eixo ativo, em thread.

        A sequencia completa mora em `_do_motor_on`: aqui so ficam a checagem
        de conexao e o feedback imediato no botao.
        """
        if not self._check_conn():
            return
        self.btn_motor_on.config(state="disabled", text="Iniciando...")
        mov = self._preparar_mov()
        self._thread_op(self._do_motor_on, mov)

    def _do_motor_on(self, mov):
        """
        Sequencia segura de habilitacao do motor:
          0. Le a malha (24) para a faixa do card de configuracao
          1. Le status (75) e alarme (115); se houver falha, limpa (93 = 1)
             e confere de novo -- habilitar sobre uma falha ativa so faria o
             drive recusar ou desarmar em seguida
          2. Habilita (6 = 1)
          3. Aguarda 200 ms e confere enable e alarme
        """
        self._log("[MOTOR] --- Sequencia de habilitacao ---")
        alvo = self._slave_atual

        malha = self._ler_regs(REG_MALHA, 1)
        if malha is not None:
            self.after(0, lambda v=malha[0]: self._badge_malha(v, slave=alvo))

        def _volta():
            self.btn_motor_on.config(state="normal", text="MOTOR ON")

        st, alm = self._ler_regs(REG_STATUS, 1), self._ler_regs(REG_ALARME, 1)
        if st is None or alm is None:
            self._log("[MOTOR] Drive sem resposta ao status/alarme - "
                      "habilitacao abortada.")
            self.after(0, _volta)
            return
        if em_falha(st[0], alm[0]):
            self._log("[MOTOR] Falha pendente: {} -> limpando (93 = 1)".format(
                motivo_falha(st[0], alm[0])))
            mov.limpar_alarme()
            time.sleep(0.2)
            st, alm = self._ler_regs(REG_STATUS, 1), self._ler_regs(REG_ALARME, 1)
            if st is None or alm is None or em_falha(st[0], alm[0]):
                motivo = ("sem resposta" if st is None or alm is None
                          else motivo_falha(st[0], alm[0]))
                self._log("[MOTOR] A falha nao saiu: {}".format(motivo))
                self.after(0, _volta)
                self.after(0, lambda: messagebox.showwarning(
                    "Falha no drive",
                    "O drive continua em falha depois de limpar:\n{}\n\n"
                    "Confira alimentacao, fases do motor e encoder (o LED "
                    "vermelho pisca o codigo - manual p. 7).".format(motivo)))
                return

        res = mov.armar()
        if not res.ok:
            self._log("[MOTOR] {}".format(res.detalhe))
            self.after(0, _volta)
            return
        time.sleep(0.2)

        enable = self._ler_regs(REG_ENABLE, 1)
        alm = self._ler_regs(REG_ALARME, 1)
        if alm is not None and alm[0]:
            mov.armado = False
            motivo = motivo_falha(0, alm[0])
            self._log("[MOTOR] ATENCAO: alarme apos habilitar: {}".format(motivo))
            self.after(0, _volta)
            self.after(0, lambda: messagebox.showwarning(
                "Alarme no drive",
                "Drive em alarme apos habilitar!\n{}\n\n"
                "Tente: Limpar falha -> Motor ON novamente.\n"
                "Se persistir, verifique alimentacao e cabeamento.".format(motivo)))
            return
        if enable is not None and enable[0] != 1:
            self._log("[MOTOR] AVISO: o reg 6 leu {} depois de escrever 1".format(
                enable[0]))

        malha_txt = MALHAS.get(malha[0], "malha ?") if malha else "malha ?"

        def _set_on():
            self.btn_motor_on.config(state="normal", text="MOTOR ON")
            if self._slave_operacao() == alvo:
                self.btn_jog.config(state="normal")
                self.lbl_motor_state.config(
                    text="Motor: HABILITADO  [{}]".format(malha_txt), fg=GREEN)
            self._log("[MOTOR] Eixo {} habilitado ({}).".format(alvo, malha_txt))
        self.after(0, _set_on)

    # --- LIMPAR FALHA -----------------------------------------------------------

    def _reset_alarme(self):
        """Escreve 1 no 93 (limpar a falha)."""
        if not self._check_conn():
            return
        self.lbl_alarm_status.config(text="Limpando...", fg=YELLOW)
        self._thread_op(self._do_reset_alarme)

    def _do_reset_alarme(self):
        """Limpa a falha, confere o 115 e mostra o desfecho por 3 s. Roda em thread."""
        res = self._mov().limpar_alarme()
        time.sleep(0.2)
        alm = self._ler_regs(REG_ALARME, 1)
        if res.ok and alm is not None and alm[0] == 0:
            msg, cor = "Falha limpa.", GREEN
        elif res.ok and alm is not None:
            msg, cor = "Comando aceito, mas o alarme continua: {}".format(
                motivo_falha(0, alm[0])), RED
        else:
            msg, cor = "Erro ao limpar a falha!", RED
        self._log("[ALM] {}".format(msg))
        self.after(0, lambda: self.lbl_alarm_status.config(text=msg, fg=cor))
        self.after(3000, lambda: self.lbl_alarm_status.config(text="", fg=TEXT_DIM))

    def _motor_off(self):
        """Desabilita o motor (6 = 0), parando o que estiver em curso.

        Interrompe homing e JOG antes de cortar o torque: soltar o motor com o
        drive ainda em movimento continuo deixaria um comando retido no drive
        para a proxima habilitacao.

        Desabilitar corta o torque de retencao -- num eixo vertical, a carga
        desce.
        """
        if not self._check_conn():
            return
        if self.home_ativo:
            self._parar_homing()
        if self.jog_active:
            self._jog_stop()
        mov = self._mov()
        mov.cancelar()
        mov.jog_parar()
        if mov.desarmar().ok:
            self.btn_jog.config(state="disabled")
            self.lbl_motor_state.config(text="Motor: DESABILITADO", fg=RED)
