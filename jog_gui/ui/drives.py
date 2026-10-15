"""Cadastro dos eixos do barramento, varredura e a barra de visao geral.

Um conversor RS-485 atende varios enderecos, e a bancada usa varios. Este
modulo responde por:

  - o cadastro dos eixos (ID + apelido + configuracao), em eixos.json;
  - a varredura do barramento, que diz quem de fato respondeu;
  - a barra de visao geral, sempre visivel, com uma linha por eixo;
  - a troca do eixo ativo, que leva TODO o estado junto (ver ui/eixo.py);
  - as acoes de seguranca sobre o conjunto: desabilitar um, parar todos.

O painel detalhado embaixo mostra um eixo por vez -- o eixo ativo.
"""

import json
import os
import time
import tkinter as tk
from tkinter import messagebox

from jog_gui.str6 import (
    Drive,
    DriveNaoConfirmou,
    REG_ALARME,
    REG_ENABLE,
    REG_PULSOS_L,
    REG_STATUS,
    SLAVE_MAX,
    SLAVE_MIN,
    ST_EM_MOVIMENTO,
    ST_FALHA,
    VARREDURA_MAX,
    de_palavras_32,
)

from .eixo import VERSAO_CADASTRO, Eixo
from .tema import (
    ACCENT,
    BG,
    BG2,
    BG3,
    FONT_BOLD,
    FONT_LABEL,
    FONT_MONO,
    GREEN,
    RED,
    TEXT,
    TEXT_DIM,
    YELLOW,
)


class DrivesMixin:
    """Cadastro de eixos, varredura do barramento e barra de visao geral."""

    _EIXOS_ARQ = "eixos.json"

    # --- acesso a colecao de eixos --------------------------------------------

    def eixos_ordenados(self):
        """Os eixos cadastrados por endereco crescente.

        A ordem fixa e o que faz a barra de visao geral nao embaralhar as
        linhas a cada remontagem.
        """
        return [self.eixos[i] for i in sorted(self.eixos)]

    @property
    def eixo_ativo(self):
        """O Eixo do endereco selecionado. Nunca None depois de _carregar_eixos."""
        return self.eixos.get(self.slave.get())

    # --- o EixoMovimento de cada eixo -------------------------------------------

    def _ligar_drives(self):
        """Amarra o EixoMovimento de cada eixo ao barramento recem-aberto."""
        for eixo in self.eixos.values():
            self._ligar_drive(eixo)

    def _ligar_drive(self, eixo):
        """Da ao eixo um Drive no barramento atual, com o log da janela."""
        eixo.mov.log = self._log
        eixo.mov.drive = (Drive(self.bus, eixo.slave, log=self._log)
                          if self.bus is not None else None)

    def _desligar_drives(self):
        """Solta os drives: sem barramento, toda escrita do eixo falha em vez
        de tentar uma porta fechada."""
        for eixo in self.eixos.values():
            eixo.mov.drive = None

    def _mov(self, slave=None):
        """O EixoMovimento do eixo desta operacao (ou de `slave`).

        Pode ser chamado de qualquer thread: nao toca em variavel Tk.
        """
        eixo = self.eixos[self._slave_operacao() if slave is None else slave]
        if self.bus is not None and (eixo.mov.drive is None
                                     or eixo.mov.drive.barramento is not self.bus):
            self._ligar_drive(eixo)
        return eixo.mov

    def _preparar_mov(self):
        """Captura a tela no eixo ativo e devolve o EixoMovimento pronto.

        So na thread da interface: e aqui que os campos sao lidos, UMA vez,
        para virar a ConfigEixo da operacao. A thread que vai mover nunca le
        widget -- Tk nao aceita isso fora da thread principal.
        """
        eixo = self.eixo_ativo
        eixo.capturar(self)
        mov = self._mov(eixo.slave)
        mov.config = eixo.config_movimento()
        mov.on_progress = self._progresso_mov
        return mov

    def _progresso_mov(self, dados):
        """Leva a posicao de um movimento em curso para a regua do curso.

        Chamado da thread do movimento; a pintura vai para a da interface.
        """
        pos = dados.get("pos")
        if pos is not None:
            self.after(0, lambda p=pos: self._curso_ui(p))

    # --- estado de runtime, delegado ao eixo ativo ----------------------------
    #
    # Sao propriedades para que todo codigo que escreve self.motor_on grave no
    # eixo certo.

    def _slave_operacao(self):
        """O endereco a que o estado de runtime pertence NESTA thread.

        Dentro de uma thread aberta por `_thread_op` (ou de um bloco
        `_slave_fixo`) e o endereco congelado da operacao; na thread da
        interface, o eixo selecionado na barra.

        Sem isso, trocar de eixo na barra no meio de uma transacao do monitor
        carimbaria a leitura de um drive no cadastro de outro -- inclusive o
        zero, que e quem autoriza os limites de curso.
        """
        local = getattr(self, "_slave_local", None)     # antes do __init__ montar
        congelado = getattr(local, "valor", None)
        return self.slave.get() if congelado is None else congelado

    def _runtime_de(self, slave, nome, valor=None, escrever=False):
        """Le ou grava um campo de runtime no eixo de endereco `slave`.

        Use com endereco EXPLICITO quando quem grava e um callback de
        `after(0, ...)`: ele roda na thread da interface, onde o congelamento
        da operacao ja nao vale.

        Antes de `_carregar_eixos` -- comeco de `__init__` -- ainda nao ha eixo
        onde guardar, e os valores ficam numa reserva temporaria.
        """
        eixo = self.eixos.get(slave) if hasattr(self, "eixos") else None
        if eixo is None:
            reserva = self.__dict__.setdefault("_runtime_reserva", {})
            if escrever:
                reserva[nome] = valor
            return reserva.get(nome, False if nome != "status_lido" else 0)
        if escrever:
            setattr(eixo, nome, valor)
        return getattr(eixo, nome)

    def _runtime(self, nome, valor=None, escrever=False):
        """Le ou grava um campo de runtime no eixo DESTA operacao."""
        return self._runtime_de(self._slave_operacao(), nome, valor, escrever)

    @property
    def motor_on(self):
        """O EIXO ATIVO esta habilitado (6 = 1 confirmado)?"""
        return self._runtime("armado")

    @motor_on.setter
    def motor_on(self, v):
        self._runtime("armado", v, escrever=True)

    @property
    def zero_valido(self):
        """Houve homing valido neste eixo desde a energizacao?

        E o que autoriza os limites de curso: sem zero, a contagem do drive nao
        corresponde a faixa configurada.
        """
        return self._runtime("zero_valido")

    @zero_valido.setter
    def zero_valido(self, v):
        self._runtime("zero_valido", v, escrever=True)

    @property
    def _malha_lida(self):
        """Malha que o drive CONFIRMOU no 24 -- nao a selecionada na tela."""
        return self._runtime("malha_lida")

    @_malha_lida.setter
    def _malha_lida(self, v):
        self._runtime("malha_lida", v, escrever=True)

    @property
    def corrente_lida(self):
        """A configuracao na tela veio de uma leitura deste drive?

        Enquanto for False, gravar significa escrever numeros que ninguem
        conferiu contra este motor.
        """
        return self._runtime("corrente_lida")

    @corrente_lida.setter
    def corrente_lida(self, v):
        self._runtime("corrente_lida", v, escrever=True)

    @property
    def _status_lido(self):
        """Ultimo 75 lido deste eixo (status, inclusive os sinais de limite)."""
        return self._runtime("status_lido")

    @_status_lido.setter
    def _status_lido(self, v):
        self._runtime("status_lido", v, escrever=True)

    # --- persistencia ----------------------------------------------------------

    def _arq(self, nome):
        """Caminho de um arquivo de dados dentro do pacote jog_gui/.

        Absoluto e derivado do modulo, nao do diretorio de trabalho: o
        eixos.json precisa ser o mesmo arquivo qualquer que seja a pasta de
        onde a aplicacao foi iniciada.
        """
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(raiz, nome)

    def _ler_json(self, nome):
        """Le um JSON do pacote. None se nao existe ou esta ilegivel.

        Arquivo corrompido vira uma linha no log, nao uma excecao: a aplicacao
        precisa abrir mesmo com o cadastro danificado, senao nao ha como
        recadastrar os eixos.
        """
        caminho = self._arq(nome)
        if not os.path.exists(caminho):
            return None
        try:
            with open(caminho, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except (OSError, ValueError) as e:
            self._log("[EIXOS] {} ilegivel: {}".format(nome, e))
            return None

    def _carregar_eixos(self):
        """Monta self.eixos. Sem arquivo, comeca com um eixo no endereco 1."""
        self.eixos = {}
        d = self._ler_json(self._EIXOS_ARQ)
        ativo = None

        if d and isinstance(d.get("eixos"), list):
            versao = d.get("versao")
            for item in d["eixos"]:
                try:
                    eixo = Eixo.de_json(item, versao)
                except (KeyError, TypeError, ValueError):
                    continue
                if SLAVE_MIN <= eixo.slave <= SLAVE_MAX:
                    self.eixos.setdefault(eixo.slave, eixo)
            ativo = d.get("ativo")
            if versao != VERSAO_CADASTRO and self.eixos:
                self._log("[EIXOS] {} e da versao {} (esperada {}): so ID, "
                          "apelido e sensor foram aproveitados; o resto entrou "
                          "com os padroes.".format(self._EIXOS_ARQ, versao,
                                                   VERSAO_CADASTRO))

        if not self.eixos:
            self.eixos[1] = Eixo(1)
            ativo = 1

        if ativo not in self.eixos:
            ativo = sorted(self.eixos)[0]
        self.slave.set(ativo)
        self.eixo_ativo.aplicar(self)
        self._atualizar_painel_sensor()

    def _salvar_eixos(self):
        """Grava o cadastro inteiro, com o eixo ativo ja capturado da tela."""
        if self.eixo_ativo is not None:
            self.eixo_ativo.capturar(self)
        dados = {
            "versao": VERSAO_CADASTRO,
            "ativo": self.slave.get(),
            "eixos": [e.para_json() for e in self.eixos_ordenados()],
        }
        try:
            with open(self._arq(self._EIXOS_ARQ), "w", encoding="utf-8") as fp:
                json.dump(dados, fp, indent=2, ensure_ascii=False)
        except OSError as e:
            self._log("[EIXOS] Nao foi possivel salvar: {}".format(e))
            return False
        return True

    def _novo_eixo(self, ident, apelido=None):
        """Cadastra um eixo com os padroes e ja o liga ao barramento aberto."""
        eixo = Eixo(ident, apelido)
        self.eixos[ident] = eixo
        if self.bus is not None:
            self._ligar_drive(eixo)
        return eixo

    # --- card de cadastro ------------------------------------------------------

    def _card_drives(self, parent):
        """Monta o card de cadastro: ID, apelido, adicionar/remover e varrer."""
        card = self._card(parent, "EIXOS DO BARRAMENTO")

        linha = tk.Frame(card, bg=BG2)
        linha.pack(fill="x", pady=(0, 6))
        tk.Label(linha, text="ID:", font=FONT_LABEL, bg=BG2,
                 fg=TEXT_DIM).pack(side="left")
        self.novo_id = tk.IntVar(value=1)
        tk.Spinbox(linha, from_=SLAVE_MIN, to=SLAVE_MAX, textvariable=self.novo_id,
                   width=4, font=FONT_BOLD, bg=BG3, fg=TEXT, buttonbackground=BG3,
                   relief="flat", insertbackground=TEXT).pack(side="left", padx=(4, 10))
        tk.Label(linha, text="Apelido:", font=FONT_LABEL, bg=BG2,
                 fg=TEXT_DIM).pack(side="left")
        self.novo_apelido = tk.StringVar()
        tk.Entry(linha, textvariable=self.novo_apelido, width=12, font=FONT_LABEL,
                 bg=BG3, fg=TEXT, relief="flat",
                 insertbackground=TEXT).pack(side="left", padx=4)

        botoes = tk.Frame(card, bg=BG2)
        botoes.pack(fill="x")
        self.btn_drive_add = tk.Button(
            botoes, text="Adicionar", font=FONT_LABEL, bg=ACCENT, fg="white",
            relief="flat", cursor="hand2", command=self._drive_adicionar)
        self.btn_drive_add.pack(side="left")
        self.btn_drive_del = tk.Button(
            botoes, text="Remover", font=FONT_LABEL, bg=BG3, fg=TEXT,
            relief="flat", cursor="hand2", command=self._drive_remover)
        self.btn_drive_del.pack(side="left", padx=4)
        self.btn_varrer = tk.Button(
            botoes, text="Varrer barramento", font=FONT_LABEL, bg=BG3, fg=TEXT,
            relief="flat", cursor="hand2", command=self._varrer_barramento)
        self.btn_varrer.pack(side="left", padx=4)

        self.lbl_drives_status = tk.Label(
            card, text="", font=FONT_LABEL, bg=BG2, fg=TEXT_DIM,
            anchor="w", justify="left")
        self.lbl_drives_status.pack(fill="x", pady=(6, 0))
        self._atualizar_contagem()

    def _atualizar_contagem(self, texto=None, cor=TEXT_DIM):
        """Escreve a linha de status do card. Sem texto, mostra a contagem."""
        if hasattr(self, "lbl_drives_status"):
            self.lbl_drives_status.config(
                text=texto or "{} eixo(s) cadastrado(s)".format(len(self.eixos)),
                fg=cor)

    def _drive_adicionar(self):
        """Cadastra um eixo com o ID e o apelido digitados.

        Recusa endereco fora da faixa e endereco repetido. O eixo novo nasce
        com os PADROES e a faixa de curso zerada -- nunca com a faixa do eixo
        anterior, que seria o caminho mais curto para mandar um eixo alem do
        fim de curso.
        """
        ident = self._ivar(self.novo_id, 0)
        if not SLAVE_MIN <= ident <= SLAVE_MAX:
            messagebox.showwarning(
                "Endereco invalido",
                "Use um endereco de {} a {}.".format(SLAVE_MIN, SLAVE_MAX))
            return
        if ident in self.eixos:
            messagebox.showwarning("Endereco repetido",
                                   "O eixo {} ja esta cadastrado.".format(ident))
            return
        apelido = self.novo_apelido.get().strip() or None
        self._novo_eixo(ident, apelido)
        self.novo_apelido.set("")
        self._salvar_eixos()
        self._montar_barra_eixos()
        self._log("[EIXOS] Cadastrado: {} ({})".format(
            ident, self.eixos[ident].apelido))

    def _drive_remover(self):
        """Remove o eixo do cadastro, sob confirmacao.

        Leva junto a configuracao dele -- limites, corrente e homing -- e por
        isso o dialogo diz isso com todas as letras. Sempre resta ao menos um
        eixo cadastrado.
        """
        ident = self._ivar(self.novo_id, 0)
        eixo = self.eixos.get(ident)
        if eixo is None:
            messagebox.showwarning("Nao cadastrado",
                                   "O eixo {} nao esta na lista.".format(ident))
            return
        if len(self.eixos) == 1:
            messagebox.showwarning("Ultimo eixo",
                                   "Deixe ao menos um eixo cadastrado.")
            return
        if not messagebox.askyesno(
                "Remover eixo",
                "Remover o eixo {} ({}) do cadastro?\n\n"
                "A configuracao dele (limites, corrente, homing) sera perdida."
                .format(ident, eixo.apelido)):
            return
        era_ativo = (self.slave.get() == ident)
        del self.eixos[ident]
        if era_ativo:
            # Nao passa por _selecionar_eixo: o eixo que sairia ja nao existe.
            self.slave.set(sorted(self.eixos)[0])
            self.eixo_ativo.aplicar(self)
            self._atualizar_painel_sensor()
        self._salvar_eixos()
        self._montar_barra_eixos()
        self._log("[EIXOS] Removido do cadastro: {}".format(ident))

    def _varrer_barramento(self):
        """Pergunta de 1 a 31 (faixa dos DIP) quem responde. So leitura."""
        if not self._check_conn():
            return
        self.btn_varrer.config(state="disabled", text="Varrendo...")
        self._thread_op(self._do_varrer)

    def _do_varrer(self):
        """Le o ID (31) de cada endereco de 1 a 31. Roda em thread.

        Cadastra automaticamente quem apareceu de novo e nomeia no log os
        cadastrados que ficaram mudos -- DIP errado, cabo solto ou drive sem
        alimentacao. Menos enderecos respondendo do que drives ligados significa
        endereco duplicado nos DIP.
        """
        achados = []
        for ident in range(SLAVE_MIN, VARREDURA_MAX + 1):
            if not self._conectado:
                break
            if Drive(self.bus, ident).responde():
                achados.append(ident)
            time.sleep(0.01)

        def _fim():
            self.btn_varrer.config(state="normal", text="Varrer barramento")
            if not achados:
                self._atualizar_contagem("Varredura: ninguem respondeu", RED)
                self._log("[VARRER] Nenhum eixo respondeu de {} a {}. Verifique "
                          "DIP S1~S5, baud (SW6/SW7), terminacao (SW8), fiacao "
                          "e alimentacao.".format(SLAVE_MIN, VARREDURA_MAX))
                return
            novos = [i for i in achados if i not in self.eixos]
            sumidos = sorted(i for i in set(self.eixos) - set(achados)
                             if i <= VARREDURA_MAX)
            self._log("[VARRER] Responderam: {}".format(
                ", ".join(str(i) for i in achados)))
            if sumidos:
                self._log("[VARRER] Cadastrados que NAO responderam: {} - DIP "
                          "errado, cabo solto ou drive sem alimentacao."
                          .format(", ".join(str(i) for i in sumidos)))
            for ident in novos:
                self._novo_eixo(ident)
            if novos:
                self._salvar_eixos()
                self._montar_barra_eixos()
                self._log("[VARRER] Cadastrados automaticamente: {}".format(
                    ", ".join(str(i) for i in novos)))
            self._atualizar_contagem(
                "Varredura: {} respondeu(ram){}".format(
                    len(achados),
                    ", {} sem resposta".format(len(sumidos)) if sumidos else ""),
                YELLOW if sumidos else GREEN)

        self.after(0, _fim)

    # --- barra de visao geral --------------------------------------------------

    def _barra_eixos(self, parent):
        """Cria o container fixo da barra. As linhas vem em _montar_barra_eixos."""
        self._barra = tk.Frame(parent, bg=BG)
        self._barra.pack(fill="x", padx=20, pady=(8, 0))
        self._linhas_eixo = {}
        self._montar_barra_eixos()

    def _montar_barra_eixos(self):
        """Refaz as linhas da barra a partir do cadastro."""
        for w in self._barra.winfo_children():
            w.destroy()
        self._linhas_eixo = {}

        cab = tk.Frame(self._barra, bg=BG)
        cab.pack(fill="x")
        for texto, largura in (("ID", 4), ("APELIDO", 14), ("ESTADO", 12),
                               ("POSICAO", 12)):
            tk.Label(cab, text=texto, font=FONT_LABEL, bg=BG, fg=TEXT_DIM,
                     width=largura, anchor="w").pack(side="left")
        tk.Label(cab, text="", bg=BG).pack(side="left", expand=True, fill="x")
        tk.Button(cab, text="PARADA GERAL", font=FONT_BOLD, bg=RED, fg="white",
                  relief="flat", cursor="hand2",
                  command=self._parada_geral).pack(side="right")

        for eixo in self.eixos_ordenados():
            self._linha_eixo(eixo)
        self._realcar_eixo_ativo()
        self._atualizar_contagem()

    def _linha_eixo(self, eixo):
        """Cria a linha de um eixo na barra e guarda seus widgets.

        Os rotulos tambem respondem ao clique, nao so o botao Selecionar: a
        linha inteira e a area de acerto.
        """
        ident = eixo.slave
        linha = tk.Frame(self._barra, bg=BG2, pady=2)
        linha.pack(fill="x", pady=1)

        lbl_id = tk.Label(linha, text=str(ident), font=FONT_BOLD, bg=BG2,
                          fg=TEXT, width=4, anchor="w")
        lbl_id.pack(side="left")
        lbl_ap = tk.Label(linha, text=eixo.apelido, font=FONT_LABEL, bg=BG2,
                          fg=TEXT, width=14, anchor="w")
        lbl_ap.pack(side="left")
        lbl_st = tk.Label(linha, text="--", font=FONT_LABEL, bg=BG2,
                          fg=TEXT_DIM, width=12, anchor="w")
        lbl_st.pack(side="left")
        lbl_pos = tk.Label(linha, text="--", font=FONT_MONO, bg=BG2,
                           fg=TEXT_DIM, width=12, anchor="w")
        lbl_pos.pack(side="left")
        tk.Label(linha, text="", bg=BG2).pack(side="left", expand=True, fill="x")

        btn_sel = tk.Button(linha, text="Selecionar", font=FONT_LABEL, bg=BG3,
                            fg=TEXT, relief="flat", cursor="hand2",
                            command=lambda i=ident: self._selecionar_eixo(i))
        btn_sel.pack(side="right", padx=(4, 0))
        btn_off = tk.Button(linha, text="Desabilitar", font=FONT_LABEL, bg=BG3,
                            fg=TEXT, relief="flat", cursor="hand2",
                            command=lambda i=ident: self._eixo_release(i))
        btn_off.pack(side="right", padx=2)

        for w in (linha, lbl_id, lbl_ap, lbl_st, lbl_pos):
            w.bind("<Button-1>", lambda e, i=ident: self._selecionar_eixo(i))

        self._linhas_eixo[ident] = {
            "frame": linha, "id": lbl_id, "apelido": lbl_ap,
            "estado": lbl_st, "posicao": lbl_pos, "sel": btn_sel, "off": btn_off,
        }

    def _realcar_eixo_ativo(self):
        """Destaca a linha do eixo ativo -- o unico que o painel detalhado opera."""
        ativo = self.slave.get()
        for ident, ws in self._linhas_eixo.items():
            sel = (ident == ativo)
            fundo = BG3 if sel else BG2
            for chave in ("frame", "id", "apelido", "estado", "posicao"):
                ws[chave].config(bg=fundo)
            ws["id"].config(fg=ACCENT if sel else TEXT)
            ws["sel"].config(text="ATIVO" if sel else "Selecionar",
                             bg=ACCENT if sel else BG3,
                             fg="white" if sel else TEXT)

    # --- troca de eixo ---------------------------------------------------------

    def _selecionar_eixo(self, ident):
        """Torna `ident` o eixo ativo do painel detalhado.

        Leva TODO o estado junto: limites, configuracao do drive, homing e
        velocidade de JOG.

        Recusa a troca com um eixo em movimento: o painel inteiro passaria a
        apontar para outro drive no meio da operacao, inclusive os botoes de
        parada.
        """
        if ident == self.slave.get() or ident not in self.eixos:
            return
        if self.jog_active or self.curso_mov or self.home_ativo or self.teste_ativo:
            messagebox.showwarning(
                "Operacao em curso",
                "Termine ou pare a operacao do eixo {} antes de trocar."
                .format(self.slave.get()))
            return

        self.eixo_ativo.capturar(self)      # guarda o eixo que sai
        self.slave.set(ident)
        entrando = self.eixo_ativo
        entrando.aplicar(self)              # traz o eixo que entra

        # A trava dos ganhos e um consentimento por sessao de edicao, nao uma
        # configuracao: nunca segue de um eixo para outro.
        self.ganhos_edit.set(0)
        # Leituras que pertenciam ao eixo anterior.
        self._curso_pos_atual = None
        self._curso_pos_ts = 0.0

        self._realcar_eixo_ativo()
        self._atualizar_painel_sensor()
        self._badge_malha()
        self._curso_resumo()
        self._salvar_eixos()

        self._log("[EIXO] Ativo: {} ({}) - limites, configuracao e homing deste "
                  "eixo carregados".format(ident, entrando.apelido))
        self.lbl_status.config(text="Eixo {} - {}".format(ident, entrando.apelido))

    # --- acoes de seguranca ----------------------------------------------------

    def _eixo_release(self, ident):
        """Desabilita o motor de um eixo (6 = 0), seja ele o ativo ou nao."""
        if not self._check_conn():
            return
        self._thread_op(self._do_eixo_release, ident, slave=ident)

    def _do_eixo_release(self, ident):
        """Escreve a desabilitacao com retentativa. Roda em thread."""
        mov = self._mov(ident)
        ok = False
        for _ in range(3):
            if mov.desarmar().ok:
                ok = True
                break
            time.sleep(0.05)
        self._log("[EIXO {}] {}".format(
            ident, "Desabilitado." if ok else "NAO confirmou a desabilitacao!"))

    def _parada_geral(self):
        """Para e desabilita TODOS os eixos cadastrados.

        Nao aborta no primeiro que falhar: um drive mudo nao pode impedir a
        tentativa de desarmar os outros. O que falhou vai para o log e para um
        aviso na tela -- um eixo energizado que ninguem viu e o pior desfecho.
        """
        if not self._check_conn():
            return
        if not messagebox.askyesno(
                "Parada geral",
                "Parar e desabilitar TODOS os {} eixos cadastrados?\n\n"
                "Os eixos ficam soltos e podem ceder ao peso da carga."
                .format(len(self.eixos))):
            return
        self.jog_active = False
        self.curso_mov = False
        self.home_ativo = False
        for eixo in self.eixos.values():
            eixo.mov.cancelar()
        self._thread_op(self._do_parada_geral)

    def _do_parada_geral(self):
        """Parada + desabilitacao em todos os eixos, um a um. Roda em thread.

        Quem nao confirmou e nomeado num erro na tela, porque o conjunto NAO
        pode ser considerado seguro.
        """
        falhas = []
        for eixo in self.eixos_ordenados():
            mov = self._mov(eixo.slave)
            parou = mov.jog_parar().ok
            time.sleep(0.05)
            soltou = mov.desarmar().ok or mov.desarmar().ok
            if not soltou:
                falhas.append(eixo.slave)
            self._log("[PARADA] Eixo {}: {}{}".format(
                eixo.slave,
                "desabilitado" if soltou else "NAO CONFIRMOU A DESABILITACAO",
                "" if parou else " (parada nao confirmada)"))

        def _fim():
            if falhas:
                messagebox.showerror(
                    "Parada geral incompleta",
                    "Estes eixos nao confirmaram a desabilitacao: {}\n\n"
                    "NAO considere o conjunto seguro. Verifique a fiacao e, se "
                    "necessario, corte a energia.".format(
                        ", ".join(str(i) for i in falhas)))
            else:
                self._log("[PARADA] Todos os {} eixos desabilitados.".format(
                    len(self.eixos)))

        self.after(0, _fim)

    def _desarmar_todos_silencioso(self):
        """Desabilita todos, sem dialogo -- usado no fechamento da janela."""
        if not self._conectado:
            return
        for eixo in self.eixos_ordenados():
            try:
                mov = self._mov(eixo.slave)
                mov.jog_parar()
                mov.desarmar()
            except Exception:
                pass

    # --- rodizio de leitura dos eixos secundarios ------------------------------

    def _proximo_secundario(self):
        """Devolve o proximo eixo do rodizio, pulando o ativo e os que estao
        em pausa por nao terem respondido (ver `_poll_secundarios`)."""
        agora = time.time()
        outros = [i for i in sorted(self.eixos) if i != self.slave.get()
                  and self._secundario_mudo_ate.get(i, 0) <= agora]
        if not outros:
            return None
        self._rodizio = getattr(self, "_rodizio", 0) % len(outros)
        ident = outros[self._rodizio]
        self._rodizio = (self._rodizio + 1) % len(outros)
        return ident

    def _ler_resumo_eixo(self, ident):
        """Status (75), alarme (115), posicao (39/40) e enable (6) de um eixo.

        Quatro quadros curtos: os registradores nao sao vizinhos. Devolve um
        dicionario, ou None se o eixo nao respondeu.
        """
        if not self._conectado:
            return None
        lido_em = time.time()
        drive = Drive(self.bus, ident)
        try:
            status = drive.ler(REG_STATUS)[0]
            alarme = drive.ler(REG_ALARME)[0]
            baixa, alta = drive.ler(REG_PULSOS_L, 2)
            enable = drive.ler(REG_ENABLE)[0]
        except DriveNaoConfirmou:
            return None
        return {"status": status, "alarme": alarme, "enable": enable,
                "pos": de_palavras_32(baixa, alta), "lido_em": lido_em}

    def _texto_estado(self, resumo):
        """Traduz o resumo lido em (texto, cor) para a barra.

        Em ordem de gravidade: alarme, falha no status, movendo, habilitado,
        livre.
        """
        if resumo["alarme"]:
            return "ALARME {}".format(resumo["alarme"]), RED
        if resumo["status"] & ST_FALHA:
            return "FALHA", RED
        if resumo["status"] & ST_EM_MOVIMENTO:
            return "movendo", YELLOW
        if resumo["enable"]:
            return "habilitado", GREEN
        return "livre", TEXT_DIM

    def _atualizar_linha(self, ident, resumo):
        """Pinta a linha de um eixo com o resumo lido. Na thread da interface.

        Args:
            ident: endereco do eixo.
            resumo: dicionario de `_ler_resumo_eixo`, ou None quando o eixo nao
                respondeu -- a linha passa a dizer "sem resposta".

        Para os eixos que nao sao o ativo, e daqui que vem a noticia de que o
        drive foi desabilitado: o painel detalhado so olha um.
        """
        ws = self._linhas_eixo.get(ident)
        if not ws:
            return
        if resumo is None:
            ws["estado"].config(text="sem resposta", fg=RED)
            ws["posicao"].config(text="--", fg=TEXT_DIM)
            return
        # O drive e a fonte de verdade so para DESABILITAR: um eixo so passa a
        # aceitar movimento depois de um MOTOR ON nesta sessao. E so com
        # leitura mais nova que a habilitacao (ver StatusMixin._do_poll).
        if not resumo["enable"] and self._desabilitado_depois_de_armar(
                ident, resumo.get("lido_em", 0.0)):
            self.eixos[ident].armado = False
        texto, cor = self._texto_estado(resumo)
        ws["estado"].config(text=texto, fg=cor)
        ws["posicao"].config(text="{:+d}".format(resumo["pos"]), fg=TEXT)
