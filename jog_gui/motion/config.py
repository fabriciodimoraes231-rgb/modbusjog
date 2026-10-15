"""A configuracao de UM eixo, como dado -- o que antes eram os IntVar da janela.

As chaves sao as mesmas do bloco `config` de cada eixo em eixos.json, entao
`ConfigEixo.de_dict(...)` le o cadastro sem tradutor no meio.

Por que uma classe e nao o dicionario cru: os mixins da tela leem todo campo
por `self._ivar(self.x, padrao)`, que aplica int() e um padrao. Sem isso, um
campo ausente ou em texto viraria TypeError la no meio de um movimento. A
conversao e o padrao ficam aqui, uma vez, na construcao.

Unidades: velocidades em PULSOS/S e posicoes em PULSOS, que e o que o STR6
recebe (registradores 60, 64/65 e 68/69). A conversao para rpm depende dos
pulsos por volta (registrador 1) e e so de exibicao.
"""

from jog_gui.str6.config import RAMPA_MS

# Os dois sentidos de movimento, com os nomes do manual (comandos 1/3 e 2/4).
FRENTE = "FRENTE"
TRAS = "TRAS"
SENTIDOS = (FRENTE, TRAS)

# Entradas que o sensor de origem pode ocupar (manual p. 8): IN1 e o limite
# negativo, IN2 o positivo. O drive so le sensor nessas duas.
ENTRADA_LIM_NEG = "LIM_NEG"
ENTRADA_LIM_POS = "LIM_POS"


def oposto(sentido):
    """O outro sentido."""
    return TRAS if sentido == FRENTE else FRENTE


def _inteiro(valores, chave, padrao):
    """int() tolerante: campo ausente, vazio ou nao numerico cai no padrao.

    E o equivalente do `_ivar` da janela. Silenciar o erro e deliberado: o
    cadastro e editado a mao e um campo estragado nao pode impedir o eixo de
    ser carregado -- ele entra com o padrao, que e sempre o valor conservador.
    """
    try:
        return int(valores[chave])
    except (KeyError, TypeError, ValueError):
        return padrao


def _sentido(valores, chave, padrao):
    """Campo de sentido: so FRENTE ou TRAS passam; o resto cai no padrao."""
    valor = str(valores.get(chave, "")).strip().upper()
    return valor if valor in SENTIDOS else padrao


class ConfigEixo:
    """Os ajustes de um eixo. Sem I/O, sem tela, sem estado de runtime.

    O estado que muda durante a operacao -- armado, zero valido, posicao -- NAO
    vive aqui: e do EixoMovimento. Aqui fica so o que o operador configurou.
    """

    __slots__ = (
        "slave", "apelido",
        # jog continuo
        "jog_velocidade", "jog_sentido", "rampa_ms",
        # homing
        "sensor_tem_origem", "home_modo", "home_entrada", "home_v_apr",
        "home_v_ras",
        # curso e limites
        "limite_pos", "limite_neg", "pulsos_volta", "antecipacao",
        "tolerancia", "limites_ativos", "sentido_pos",
        "vel_rapida", "vel_lenta", "janela_lenta", "passo_pulsos", "passo_vel",
        # seguranca
        "soltar_em_emergencia",
    )

    def __init__(self, slave, apelido="", **kwargs):
        """Monta a configuracao. Todo campo tem padrao conservador.

        Args:
            slave: endereco do drive.
            apelido: nome do eixo, usado no log.
            **kwargs: qualquer campo dos __slots__.

        Os padroes seguem os do cadastro (eixos.json) e da tela, com duas
        excecoes deliberadas: `limite_pos`/`limite_neg` nascem em 0 e
        `limites_ativos` em False. Um eixo nunca configurado nunca deve herdar
        a faixa de outro -- seria o caminho mais curto para manda-lo alem do
        fim de curso.

        As velocidades padrao sao pontos de partida para 6000 pulsos/volta
        (fabrica do registrador 1), NAO medidas: 3000 p/s = 30 rpm.
        """
        self.slave = slave
        self.apelido = apelido or "eixo {}".format(slave)

        self.jog_velocidade = kwargs.get("jog_velocidade", 3000)
        self.jog_sentido = kwargs.get("jog_sentido", FRENTE)
        self.rampa_ms = kwargs.get("rampa_ms", RAMPA_MS)

        self.sensor_tem_origem = kwargs.get("sensor_tem_origem", True)
        self.home_modo = kwargs.get("home_modo", "nativo")
        self.home_entrada = kwargs.get("home_entrada", ENTRADA_LIM_NEG)
        self.home_v_apr = kwargs.get("home_v_apr", 6000)
        self.home_v_ras = kwargs.get("home_v_ras", 1000)

        self.limite_pos = kwargs.get("limite_pos", 0)
        self.limite_neg = kwargs.get("limite_neg", 0)
        self.pulsos_volta = kwargs.get("pulsos_volta", 6000)
        self.antecipacao = kwargs.get("antecipacao", 400)
        self.tolerancia = kwargs.get("tolerancia", 40)
        self.limites_ativos = bool(kwargs.get("limites_ativos", False))
        self.sentido_pos = kwargs.get("sentido_pos", FRENTE)

        self.vel_rapida = kwargs.get("vel_rapida", 20000)
        self.vel_lenta = kwargs.get("vel_lenta", 6000)
        self.janela_lenta = kwargs.get("janela_lenta", 1500)
        self.passo_pulsos = kwargs.get("passo_pulsos", 200)
        self.passo_vel = kwargs.get("passo_vel", 3000)

        # Eixo vertical: o ultimo degrau da parada escalonada desabilita o
        # motor, o que DERRUBA A CARGA. Configuravel por eixo para que a
        # mecanica vertical possa recusar esse degrau, aceitando uma parada
        # com um recurso menos.
        self.soltar_em_emergencia = bool(kwargs.get("soltar_em_emergencia", True))

    @classmethod
    def de_dict(cls, slave, apelido, valores, tem_origem=True):
        """Constroi a partir do bloco `config` de um eixo do eixos.json.

        Args:
            slave: o `id` do eixo no cadastro.
            apelido: o `apelido` do cadastro.
            valores: o dicionario `config` do cadastro.
            tem_origem: se o modelo de sensor daquele eixo estabelece zero.
                Vem do catalogo (ui/sensores.py) e nao do JSON, porque o
                cadastro guarda o NOME do modelo, nao a capacidade.

        Os nomes divergentes entre cadastro e codigo sao traduzidos aqui, num
        lugar so: `aplicar` -> `limites_ativos`, `home_modo` "Software - ..."
        -> "software", `home_entrada` "Limite + (IN2)" -> LIM_POS.
        """
        valores = valores or {}
        return cls(
            slave=slave,
            apelido=apelido,
            jog_velocidade=_inteiro(valores, "jog_velocidade", 3000),
            jog_sentido=_sentido(valores, "jog_sentido", FRENTE),
            rampa_ms=_inteiro(valores, "rampa_ms", RAMPA_MS),
            sensor_tem_origem=tem_origem,
            home_modo=("software"
                       if str(valores.get("home_modo", "")).strip().lower()
                       .startswith("software") else "nativo"),
            home_entrada=entrada_home(valores.get("home_entrada")),
            home_v_apr=_inteiro(valores, "home_v_apr", 6000),
            home_v_ras=_inteiro(valores, "home_v_ras", 1000),
            limite_pos=_inteiro(valores, "limite_pos", 0),
            limite_neg=_inteiro(valores, "limite_neg", 0),
            pulsos_volta=_inteiro(valores, "pulsos_volta", 6000),
            antecipacao=_inteiro(valores, "antecipacao", 400),
            tolerancia=_inteiro(valores, "tolerancia", 40),
            limites_ativos=bool(_inteiro(valores, "aplicar", 0)),
            sentido_pos=_sentido(valores, "sentido_pos", FRENTE),
            vel_rapida=_inteiro(valores, "vel_rapida", 20000),
            vel_lenta=_inteiro(valores, "vel_lenta", 6000),
            janela_lenta=_inteiro(valores, "janela_lenta", 1500),
            passo_pulsos=_inteiro(valores, "passo_pulsos", 200),
            passo_vel=_inteiro(valores, "passo_vel", 3000),
            soltar_em_emergencia=bool(
                _inteiro(valores, "soltar_em_emergencia", 1)),
        )

    @property
    def home_sentido(self):
        """Para onde o homing procura o sensor.

        Decorre da entrada: o drive chama de "frente" o caminho ate o limite
        positivo (retorno a zero modo 1, manual p. 18), e de "tras" o caminho
        ate o negativo. Nao e configuravel a parte de proposito -- buscar o
        sensor do limite + andando para tras nunca o encontraria.
        """
        return FRENTE if self.home_entrada == ENTRADA_LIM_POS else TRAS

    @property
    def sentido_oposto_pos(self):
        """O sentido que subtrai pulsos neste eixo."""
        return oposto(self.sentido_pos)

    def __repr__(self):
        return "ConfigEixo({}, {!r})".format(self.slave, self.apelido)


def entrada_home(valor):
    """Entrada do sensor: 'Limite + (IN2)', 'IN2' ou 'LIM_POS' -> LIM_POS.

    Qualquer outra coisa cai em LIM_NEG (IN1), o padrao do cadastro.
    """
    texto = str(valor or "").upper()
    if "IN2" in texto or "LIM_POS" in texto or "+" in texto:
        return ENTRADA_LIM_POS
    return ENTRADA_LIM_NEG
