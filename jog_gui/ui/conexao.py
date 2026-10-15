"""Conexao RS485: porta, endereco do drive e as transacoes Modbus."""

from tkinter import messagebox
from tkinter import ttk
import contextlib
import serial.tools.list_ports
import threading
import time
import tkinter as tk

from jog_gui.str6 import (
    BAUDRATES_SUPORTADOS,
    Barramento,
    Drive,
    DriveNaoConfirmou,
    REG_CORRENTE_EFETIVA,
    REG_ID,
    REG_PULSOS_VOLTA,
    REG_TENSAO,
)

from .tema import (
    ACCENT,
    BG2,
    BG3,
    FONT_BOLD,
    FONT_LABEL,
    FONT_MONO,
    GREEN,
    TEXT,
    TEXT_DIM,
    YELLOW,
)


class ConexaoMixin:
    """Conexao RS485: porta, endereco do drive e as transacoes Modbus."""


    def _card_conexao(self, parent):
        """Monta o card: porta COM, baud rate, eixo ativo e o botao."""
        f = self._card(parent, "CONEXAO RS485")

        row = tk.Frame(f, bg=BG2)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="Porta COM:", bg=BG2, fg=TEXT, font=FONT_LABEL, width=12, anchor="w").pack(side="left")
        self.cb_port = ttk.Combobox(row, textvariable=self.port_var, state="readonly",
                                    width=12, font=FONT_MONO)
        self.cb_port.pack(side="left")
        tk.Button(row, text="Atualizar", bg=BG3, fg=ACCENT, font=FONT_LABEL,
                  bd=0, padx=6, cursor="hand2",
                  command=self._refresh_ports).pack(side="left", padx=(4, 0))

        row2 = tk.Frame(f, bg=BG2)
        row2.pack(fill="x", pady=3)
        tk.Label(row2, text="Baud rate:", bg=BG2, fg=TEXT, font=FONT_LABEL, width=12, anchor="w").pack(side="left")
        cb_baud = ttk.Combobox(row2, textvariable=self.baud_var, state="readonly",
                               values=[str(b) for b in BAUDRATES_SUPORTADOS],
                               width=10)
        cb_baud.pack(side="left")
        tk.Label(row2, text="(DIP SW6/SW7)", bg=BG2, fg=TEXT_DIM,
                 font=FONT_LABEL).pack(side="left", padx=4)

        row3 = tk.Frame(f, bg=BG2)
        row3.pack(fill="x", pady=3)
        tk.Label(row3, text="Eixo ativo:", bg=BG2, fg=TEXT, font=FONT_LABEL,
                 width=12, anchor="w").pack(side="left")
        # Somente leitura de proposito: trocar o endereco sem passar por
        # _selecionar_eixo faria o painel apontar para outro drive mantendo na
        # tela os limites de curso do anterior. A troca e pela barra de eixos.
        self.lbl_eixo_ativo = tk.Label(row3, textvariable=self.slave, bg=BG3,
                                       fg=ACCENT, font=FONT_BOLD, width=5)
        self.lbl_eixo_ativo.pack(side="left")
        tk.Label(row3, text="(troque na barra de eixos, no topo)", bg=BG2,
                 fg=TEXT_DIM, font=FONT_LABEL).pack(side="left", padx=4)

        row4 = tk.Frame(f, bg=BG2)
        row4.pack(fill="x", pady=(8, 2))
        self.btn_connect = tk.Button(row4, text="CONECTAR", font=FONT_BOLD,
                                     bg=ACCENT, fg="white", bd=0,
                                     padx=18, pady=6, cursor="hand2",
                                     command=self._toggle_connect)
        self.btn_connect.pack(expand=True)

    # --- CONEXAO --------------------------------------------------------------

    def _refresh_ports(self):
        """Relista as portas seriais detectadas e seleciona a primeira.

        No Windows o numero da COM muda de maquina para maquina e de porta USB
        para porta USB -- nao ha porta padrao, e a escolha e sempre do operador.
        """
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.cb_port["values"] = ports
        if ports:
            self.port_var.set(ports[0])

    def _toggle_connect(self):
        """Botao unico CONECTAR/DESCONECTAR: decide pelo estado atual."""
        if self._conectado:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        """Abre a porta escolhida e dispara o ping do drive em thread.

        Abrir a porta nao prova nada sobre o barramento: o conversor USB-RS485
        abre igual com o cabo solto. Por isso o ping vem logo em seguida, e e
        ele que decide entre "Conectado | ID nn" e "Drive sem resposta".
        """
        port = self.port_var.get()
        baud = int(self.baud_var.get())
        if not port:
            messagebox.showwarning("Atencao", "Selecione uma porta COM.")
            return
        try:
            self.bus = Barramento.abrir(port, baudrate=baud, timeout=0.5,
                                        log=self._log)
        except Exception as e:
            messagebox.showerror("Erro de Conexao", str(e))
            return
        self._ligar_drives()
        self._set_connected(True)
        self._log("[CON] Porta {} aberta @ {} bps  |  Slave {}".format(
            port, baud, self.slave.get()))
        self._log("[CON] Aguardando resposta do drive...")
        self._thread_op(self._ping_drive)

    def _ping_drive(self):
        """Le ID (31), tensao (48), corrente efetiva (22) e pulsos/volta (1).

        O ID e o que confirma a comunicacao: o drive devolve o proprio
        endereco. Os outros tres vao para o log porque sao o primeiro
        diagnostico de bancada -- fonte desligada, corrente e subdivisao.
        """
        time.sleep(0.1)   # pequena espera para o driver USB estabilizar
        slave = self._slave_atual
        ident = self._ler_regs(REG_ID, 1)
        if ident is None:
            self._log("======================================================")
            self._log(" AVISO: Drive {} nao respondeu ao ping!".format(slave))
            self._log(" Verifique: DIP S1~S5 (endereco), SW6/SW7 (baud),")
            self._log(" SW8 (terminacao) e o cabeamento RS485.")
            self._log("======================================================")
            self.after(0, lambda: self.lbl_status.config(
                text="Conectado  |  Drive sem resposta", fg=YELLOW))
            return
        tensao = self._ler_regs(REG_TENSAO, 1)
        corrente = self._ler_regs(REG_CORRENTE_EFETIVA, 1)
        ppr = self._ler_regs(REG_PULSOS_VOLTA, 1)
        self._log("======================================================")
        self._log(" DRIVE RESPONDEU COM SUCESSO!")
        self._log(" ID (reg 31)        : {}".format(ident[0]))
        self._log(" Barramento (reg 48): {}".format(
            "?" if tensao is None else "{:.1f} V".format(tensao[0] / 10.0)))
        self._log(" Corrente efetiva   : {}".format(
            "?" if corrente is None else "{} mA".format(corrente[0])))
        self._log(" Pulsos por volta   : {}".format(
            "?" if ppr is None else ppr[0]))
        self._log("======================================================")
        if ident[0] != slave:
            self._log("[PING] ATENCAO: o drive respondeu no endereco {} mas "
                      "informa ID {} no reg 31".format(slave, ident[0]))
        if ppr is not None:
            self.after(0, lambda v=ppr[0]: self._ppr_lido_do_drive(slave, v))
        self.after(0, lambda: self.lbl_status.config(
            text="Conectado  |  ID {}".format(ident[0]), fg=GREEN))

    def _disconnect(self):
        """Para o monitor, desabilita o motor do eixo ativo e fecha a porta.

        A desabilitacao vai antes do close: com a porta ja fechada nao ha como
        pedir nada ao drive, e o motor ficaria energizado.
        """
        if self._poll_after:
            self.after_cancel(self._poll_after)
            self._poll_after = None
            self.btn_poll.config(text="Iniciar Monitor")
        if self.motor_on:
            self._motor_off()
        if self.bus:
            self.bus.close()
        self._set_connected(False)
        self._log("[DIS] Desconectado.")

    # --- SERIAL ---------------------------------------------------------------

    @property
    def _conectado(self) -> bool:
        """True se ha barramento aberto. O lock da porta vive no Barramento."""
        return bool(self.bus and self.bus.aberto)

    # --- endereco do drive por operacao ---------------------------------------
    #
    # O eixo ativo e um IntVar global da janela. Lido de dentro de uma thread
    # de trabalho, ele pode mudar NO MEIO de uma sequencia. Por isso o
    # endereco e congelado por operacao: _thread_op le o IntVar na thread da
    # interface, antes de comecar, e a thread inteira enxerga aquele valor via
    # _slave_atual.

    @property
    def _slave_atual(self) -> int:
        """Endereco do drive para a operacao em curso nesta thread."""
        congelado = getattr(self._slave_local, "valor", None)
        return self.slave.get() if congelado is None else congelado

    @contextlib.contextmanager
    def _slave_fixo(self, slave: int):
        """Congela o endereco do drive pela duracao do bloco, nesta thread."""
        anterior = getattr(self._slave_local, "valor", None)
        self._slave_local.valor = slave
        try:
            yield slave
        finally:
            self._slave_local.valor = anterior

    def _thread_op(self, target, *args, slave: int = None):
        """Dispara uma operacao em thread com o endereco do drive congelado.

        Chame sempre da thread da interface: e aqui que o eixo ativo e lido,
        uma vez so.
        """
        if slave is None:
            slave = self.slave.get()   # lido aqui, na thread da interface

        def _corpo():
            with self._slave_fixo(slave):
                target(*args)

        t = threading.Thread(target=_corpo, daemon=True)
        t.start()
        return t

    def _check_conn(self) -> bool:
        """True se ha conexao; senao avisa o operador e devolve False.

        E a primeira linha de quase todo handler de botao: a alternativa seria
        cada acao falhar silenciosamente com a porta fechada.
        """
        if not self._conectado:
            messagebox.showwarning("Atencao", "Drive nao conectado.")
            return False
        return True

    # --- transacoes do eixo desta operacao -------------------------------------
    #
    # Todas passam por str6.Drive, que valida a resposta e leva cada ESCRITA
    # ao log hexadecimal. As leituras nao vao ao log: o monitor le varias
    # vezes por segundo.

    def _drive(self):
        """O Drive do endereco desta operacao, ou None sem barramento."""
        if not self._conectado:
            return None
        return Drive(self.bus, self._slave_atual, log=self._log)

    def _write_reg(self, reg: int, value: int) -> bool:
        """FC06 - escreve registrador. Retorna True se o drive confirmou."""
        drive = self._drive()
        if drive is None:
            return False
        try:
            return drive.escrever(reg, value)
        except DriveNaoConfirmou:
            return False             # o Drive ja levou o quadro ao log

    def _write_regs(self, reg: int, valores) -> bool:
        """FC16 - escreve registradores consecutivos. True se confirmou."""
        drive = self._drive()
        if drive is None:
            return False
        try:
            return drive.escrever_multiplos(reg, valores)
        except DriveNaoConfirmou:
            return False

    def _write_reg_retry(self, reg: int, value: int, tentativas: int = 3) -> bool:
        """FC06 com retentativa - para comandos que nao podem falhar."""
        for _ in range(tentativas):
            if self._write_reg(reg, value):
                return True
            time.sleep(0.05)
        return False

    def _ler_regs(self, reg: int, count: int):
        """FC03 - lista de valores, ou None se o drive nao respondeu."""
        drive = self._drive()
        if drive is None:
            return None
        try:
            return drive.ler(reg, count)
        except DriveNaoConfirmou:
            return None

    def _ler_regs_espera(self, reg: int, count: int, segundos: float = 10.0):
        """Le registradores insistindo enquanto o drive estiver mudo.

        Uma leitura logo apos gravar parametros -- o gesto natural de quem
        quer conferir o que entrou -- pode cair num drive ocupado e aparecer
        como "erro ao ler" embora a gravacao tenha ido bem.

        Devolve (valores, motivo): motivo e a mensagem da ultima falha, ou ""
        quando leu.
        """
        limite = time.time() + segundos
        tentativas = 0
        motivo = "sem barramento"
        while True:
            drive = self._drive()
            if drive is None:
                return None, motivo
            try:
                vals = drive.ler(reg, count)
                if tentativas:
                    self._log("[LER] reg {} respondeu apos {} tentativa(s)".format(
                        reg, tentativas + 1))
                return vals, ""
            except DriveNaoConfirmou as e:
                motivo = str(e)
            tentativas += 1
            if time.time() >= limite:
                return None, motivo
            time.sleep(0.3)

    def _salvar_parametros(self) -> bool:
        """Salvar parametros (90 = 1) e espera a confirmacao do drive.

        O drive informa o fim do salvamento pela leitura do proprio 90 (manual
        p. 16); `Drive.salvar_parametros` pergunta em vez de esperar um tempo
        fixo. Roda em thread -- pode levar alguns segundos.
        """
        drive = self._drive()
        if drive is None:
            return False
        try:
            ok = drive.salvar_parametros()
        except DriveNaoConfirmou:
            ok = False
        self._log("[SALVAR] Salvar parametros (reg 90): {}".format(
            "confirmado" if ok else "NAO CONFIRMADO"))
        return ok
