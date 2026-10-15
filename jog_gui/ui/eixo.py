"""Um eixo do barramento: endereco, apelido e todo o estado que e dele.

A janela tem UM conjunto de widgets -- o painel detalhado mostra um eixo por
vez -- e a troca de eixo captura os valores do eixo que sai e aplica os do que
entra. Os widgets nao sabem que isso aconteceu. Sem isso, quem gravasse sem
reler antes escreveria num eixo o que tinha lido de outro.

    CAMPOS  o que e por eixo e persiste (corrente, homing, limites, jog)
    RUNTIME o que e por eixo e NAO persiste (leituras confirmadas do drive)

`armado` e `zero_valido` tambem sao runtime, mas moram no EixoMovimento do
eixo (`self.mov`): e ele quem os muda ao mover, referenciar e parar, e uma
copia aqui ficaria fora de sincronia.

O que nao esta em nenhuma das listas e global de verdade: a porta serial, o
barramento, o inspetor de registrador e as flags de operacao em curso -- esta
bancada move um eixo por vez, entao "tem algo rodando" e uma pergunta da
aplicacao, nao do eixo.
"""

from jog_gui.motion import ConfigEixo, EixoMovimento, FRENTE, SENTIDOS
from jog_gui.str6 import MALHA_ABERTA

from .sensores import PADRAO as SENSOR_PADRAO
from .sensores import tem_origem as _sensor_tem_origem

# Textos dos combobox do card de homing. Ficam aqui porque tambem sao o valor
# guardado no eixos.json -- e ConfigEixo.de_dict os traduz.
HOME_MODO_NATIVO = "Nativo do drive (reg 71)"
HOME_MODO_SOFTWARE = "Software - busca pelo sensor"
HOME_MODOS = (HOME_MODO_NATIVO, HOME_MODO_SOFTWARE)

HOME_ENTRADA_NEG = "Limite - (IN1)"
HOME_ENTRADA_POS = "Limite + (IN2)"
HOME_ENTRADAS = (HOME_ENTRADA_NEG, HOME_ENTRADA_POS)

# Versao do formato do eixos.json. Um arquivo de outra versao tem unidades
# diferentes (velocidade, pulsos por volta) e so aproveita id, apelido e
# modelo do sensor -- ver Eixo.de_json.
VERSAO_CADASTRO = 4

# (chave no arquivo, atributo da janela, valor padrao)
# O tipo do padrao decide como o valor volta do JSON: int ou str.
# Velocidades em pulsos/s; pontos de partida para 6000 pulsos/volta.
CAMPOS = (
    # --- JOG ---
    ("jog_velocidade",  "speed_var",       3000),
    ("jog_sentido",     "direction",       FRENTE),
    ("rampa_ms",        "rampa_ms",         200),

    # --- configuracao do drive (1, 2, 3, 13, 15, 16, 24, 26) ---
    ("corrente_pct",    "corr_oper_pct",     50),
    ("standby_pct",     "corr_standby",      50),
    ("standby_ms",      "standby_ms",       300),
    ("malha",           "modo_malha",  MALHA_ABERTA),
    ("autoajuste",      "autoajuste",         1),
    ("ganho_p",         "ganho_p",         1000),
    ("ganho_i",         "ganho_i",          200),

    # --- sensor de origem (catalogo em ui/sensores.py) ---
    ("sensor_tipo",     "sensor_tipo",  SENSOR_PADRAO),

    # --- homing (60, 64/65, 71, 73, 74) ---
    ("home_modo",       "home_modo",    HOME_MODO_NATIVO),
    ("home_entrada",    "home_entrada", HOME_ENTRADA_NEG),
    ("home_inv",        "home_inv",           0),
    ("home_filtro",     "home_filtro",        2),
    ("home_v_apr",      "home_v_apr",      6000),
    ("home_v_ras",      "home_v_ras",      1000),

    # --- limites de curso (so em arquivo; nada disso vai para o drive) ---
    ("limite_pos",      "lim_pos",            0),
    ("limite_neg",      "lim_neg",            0),
    ("pulsos_volta",    "lim_ppr",         6000),
    ("antecipacao",     "lim_margem",       400),
    ("tolerancia",      "lim_tol",           40),
    ("aplicar",         "lim_ativo",          0),
    ("sentido_pos",     "curso_sent_pos",  FRENTE),
    ("vel_rapida",      "curso_v_rap",    20000),
    ("vel_lenta",       "curso_v_len",     6000),
    ("janela_lenta",    "curso_janela",    1500),
    ("passo_pulsos",    "passo_pulsos",     200),
    ("passo_vel",       "passo_vel",       3000),
    ("curso_alvo",      "curso_alvo",         0),

    # --- seguranca ---
    ("soltar_em_emergencia", "soltar_emerg",  1),
)

# Estado de runtime: por eixo, mas sem sentido guardar entre sessoes. Sao a
# ultima leitura CONFIRMADA do drive, nao uma intencao.
RUNTIME = {
    "malha_lida": None,     # o que o drive respondeu em 24
    "status_lido": 0,       # ultimo 75 lido
    # A configuracao na tela veio de uma leitura deste drive, ou e so o
    # padrao? Enquanto for False, gravar significa escrever numeros que
    # ninguem conferiu contra este motor.
    "corrente_lida": False,
    "ppr_lido": None,       # pulsos por volta que o drive respondeu em 1
    "pico_lido": None,      # corrente de pico (0) que o drive respondeu, mA
}

# Campos de texto que so aceitam valores de uma lista fechada.
_OPCOES = {
    "sentido_pos": SENTIDOS,
    "jog_sentido": SENTIDOS,
    "home_modo": HOME_MODOS,
    "home_entrada": HOME_ENTRADAS,
}


class Eixo:
    """Endereco, apelido e estado de um drive do barramento."""

    def __init__(self, slave, apelido=None, config=None):
        """Cria o eixo com os padroes e, se houver, aplica a config recebida.

        Args:
            slave: endereco Modbus do drive.
            apelido: nome do eixo na barra de visao geral. Sem apelido, vira
                "eixo <slave>".
            config: dicionario no formato do eixos.json. Passa por `atualizar`,
                que ignora chave desconhecida e valor invalido -- um eixo novo
                nunca nasce com a faixa de curso de outro.
        """
        self.slave = int(slave)
        self.apelido = apelido or "eixo {}".format(self.slave)
        self.config = {chave: padrao for chave, _, padrao in CAMPOS}
        if config:
            self.atualizar(config)
        for nome, padrao in RUNTIME.items():
            setattr(self, nome, padrao)
        # O drive e ligado pela janela ao conectar; ate la, sem barramento.
        self.mov = EixoMovimento(None, self.config_movimento())

    def __repr__(self):
        """Endereco e apelido -- o par que identifica o eixo no log."""
        return "Eixo({}, {!r})".format(self.slave, self.apelido)

    # --- estado que mora no EixoMovimento ------------------------------------

    @property
    def armado(self):
        """O motor deste eixo esta habilitado (6 = 1 confirmado)?"""
        return self.mov.armado

    @armado.setter
    def armado(self, valor):
        self.mov.armado = bool(valor)

    @property
    def zero_valido(self):
        """Houve homing valido neste eixo desde a energizacao?"""
        return self.mov.zero_valido

    @zero_valido.setter
    def zero_valido(self, valor):
        self.mov.zero_valido = bool(valor)

    def config_movimento(self):
        """A ConfigEixo deste eixo, a partir do cadastro em memoria.

        A capacidade de estabelecer zero vem do catalogo de sensores, nao do
        JSON: o cadastro guarda o NOME do modelo.
        """
        return ConfigEixo.de_dict(
            self.slave, self.apelido, self.config,
            tem_origem=_sensor_tem_origem(self.config.get("sensor_tipo")))

    # --- conversao de valores -------------------------------------------------

    def atualizar(self, origem):
        """Absorve um dicionario, ignorando chave desconhecida ou valor invalido.

        Um arquivo editado a mao nao pode derrubar a aplicacao nem, pior,
        entrar com um limite absurdo.
        """
        for chave, _, padrao in CAMPOS:
            if chave not in origem:
                continue
            bruto = origem[chave]
            if isinstance(padrao, int):
                try:
                    self.config[chave] = int(bruto)
                except (TypeError, ValueError):
                    continue
            else:
                texto = str(bruto)
                if chave in _OPCOES and texto not in _OPCOES[chave]:
                    continue
                self.config[chave] = texto
        # Faixa e guardada como valor positivo; o sinal vem do lado usado.
        for chave in ("limite_pos", "limite_neg"):
            self.config[chave] = abs(self.config[chave])

    # --- ponte com os widgets da janela ---------------------------------------

    def capturar(self, app):
        """Le os widgets da janela para dentro deste eixo."""
        for chave, atributo, padrao in CAMPOS:
            var = getattr(app, atributo, None)
            if var is None:
                continue
            if isinstance(padrao, int):
                self.config[chave] = app._ivar(var, padrao)
            else:
                self.config[chave] = var.get()
        for chave in ("limite_pos", "limite_neg"):
            self.config[chave] = abs(self.config[chave])

    def aplicar(self, app):
        """Escreve este eixo nos widgets da janela."""
        for chave, atributo, padrao in CAMPOS:
            var = getattr(app, atributo, None)
            if var is None:
                continue
            valor = self.config.get(chave, padrao)
            try:
                var.set(int(valor) if isinstance(padrao, int) else str(valor))
            except Exception:
                var.set(padrao)

    # --- persistencia ---------------------------------------------------------

    def para_json(self):
        """Serializa o eixo para uma entrada da lista "eixos" do eixos.json.

        So os CAMPOS entram. O estado de runtime (armado, zero valido, ultimas
        leituras) fica de fora de proposito: ele descreve o motor agora, e
        guardar isso entre sessoes faria a tela abrir afirmando um zero que
        nenhum homing estabeleceu.
        """
        return {"id": self.slave, "apelido": self.apelido,
                "config": dict(self.config)}

    @classmethod
    def de_json(cls, d, versao=VERSAO_CADASTRO):
        """Reconstroi um Eixo a partir de uma entrada do eixos.json.

        Um arquivo de outra versao tem outras unidades: aproveitar uma
        velocidade ou um limite de la seria mover o eixo com um numero que
        significa outra coisa. Dele so vem o id, o apelido e o modelo do
        sensor; o resto entra com os padroes.

        Raises:
            KeyError: o registro nao tem "id". Quem carrega o arquivo trata
                isso pulando a entrada -- um eixo sem endereco nao tem como
                virar comando no barramento.
        """
        config = d.get("config") or {}
        if versao != VERSAO_CADASTRO:
            config = {k: v for k, v in config.items() if k == "sensor_tipo"}
        return cls(d["id"], d.get("apelido"), config)
