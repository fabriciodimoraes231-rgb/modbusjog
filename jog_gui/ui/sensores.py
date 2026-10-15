"""Catalogo dos sensores de origem usados na bancada, um por modelo.

Cada eixo do barramento aponta para uma entrada daqui (campo `sensor_tipo` do
Eixo). O modelo decide tres coisas:

  - se o eixo tem origem fisica (`tem_origem`). Sem sensor nao ha homing, e
    sem zero nao ha limite de curso por software -- o card de curso passa a
    dizer isso em vez de mandar fazer um homing impossivel;
  - os valores sugeridos de filtro, aproximacao e rastejo, que dependem do
    tempo de resposta e da repetibilidade do sensor;
  - o texto de fiacao mostrado no card.

Fiacao no STR6-RS485 (manual p. 8): as entradas de baixa velocidade tem anodo
comum em IN+ (5~24 V) e o catodo de cada uma em IN1 (limite -) e IN2
(limite +). Um sensor NPN drena corrente: IN+ vai ao +24 V e a saida do sensor
ao IN1 ou IN2.

IMPORTANTE -- procedencia dos numeros:

  - As VELOCIDADES seguem a pratica corrente de homing em dois estagios --
    aproximacao entre 10% e 20% da velocidade maxima, rastejo entre 2% e 5%,
    razao de 5:1 a 10:1 -- sobre o teto de config.VEL_MAX_PPS. Nao foram
    medidas com este drive.
  - O filtro do garfo (2 ms) e o valor de partida da bancada; os demais sao
    pontos de partida pelo tipo de sensor.
  - Por isso todos os modelos com origem estao com `confirmado=False` e a
    interface avisa antes de aplicar. Medir o homing -- e, junto, a
    repetibilidade do zero -- e o que devolve o `confirmado=True`.

Nada aqui e aplicado sozinho: trocar o modelo no card nao sobrescreve valores
ja ajustados. A aplicacao dos sugeridos e um botao separado, porque esses
numeros custam horas de bancada e nao podem ser perdidos num clique errado.
"""


class Sensor:
    """Um modelo de sensor de origem, com o que o card de homing precisa saber."""

    __slots__ = ("nome", "tem_origem", "confirmado", "filtro_ms",
                 "v_aproximacao", "v_rastejo", "repetibilidade", "fiacao")

    def __init__(self, nome, tem_origem, confirmado, filtro_ms,
                 v_aproximacao, v_rastejo, repetibilidade, fiacao):
        """Descreve um modelo de sensor de origem.

        Args:
            nome: rotulo exibido no combobox e gravado em `sensor_tipo`.
            tem_origem: False num eixo sem sensor -- desliga homing e, por
                consequencia, os limites de curso por software.
            confirmado: True so quando os numeros foram MEDIDOS nesta bancada.
                False faz a interface avisar antes de aplicar os sugeridos.
            filtro_ms: valor de partida do filtro das entradas de limite (74).
            v_aproximacao: pulsos/s da busca rapida (64/65).
            v_rastejo: pulsos/s da reaproximacao final (60).
            repetibilidade: texto livre com a procedencia do numero.
            fiacao: instrucoes de ligacao mostradas no card de homing.
        """
        self.nome = nome
        self.tem_origem = tem_origem
        self.confirmado = confirmado
        self.filtro_ms = filtro_ms
        self.v_aproximacao = v_aproximacao
        self.v_rastejo = v_rastejo
        self.repetibilidade = repetibilidade
        self.fiacao = fiacao

    def __repr__(self):
        """O nome do modelo -- e o que identifica a entrada no catalogo."""
        return "Sensor({!r})".format(self.nome)

    @property
    def sugeridos(self):
        """Os tres valores que o botao 'aplicar sugeridos' escreve na tela."""
        return {
            "home_filtro": self.filtro_ms,
            "home_v_apr": self.v_aproximacao,
            "home_v_ras": self.v_rastejo,
        }


SEM_SENSOR = "Sem sensor"

# A ordem aqui e a ordem do combobox.
SENSORES = {}


def _reg(sensor):
    """Cadastra um sensor no catalogo e o devolve.

    A ordem das chamadas e a ordem do combobox na tela: dict preserva insercao.
    """
    SENSORES[sensor.nome] = sensor
    return sensor


_reg(Sensor(
    nome="Garfo NPN (MOTEE UX954-WR)",
    tem_origem=True,
    confirmado=False,
    filtro_ms=2,
    v_aproximacao=6000,
    v_rastejo=1000,
    repetibilidade="0,03 mm (catalogo MOTEE, serie UX95)",
    fiacao="UX954-WR: ranhura 5 mm, NPN 4 fios, repetib. 0,03 mm\n"
           "marrom=+24V   azul=0V   preto=Dark-on -> IN1 ou IN2 (usar)\n"
           "branco=Light-on (isolar)   IN+=+24V",
))

_reg(Sensor(
    nome="Indutivo NPN (3 fios)",
    tem_origem=True,
    confirmado=False,
    # Indutivo comum responde bem mais devagar que o garfo optico e a face de
    # deteccao e larga, entao o came e encontrado cedo: filtro maior e rastejo
    # menor para a borda nao depender de quando a leitura chegou.
    filtro_ms=5,
    v_aproximacao=6000,
    v_rastejo=800,
    repetibilidade="depende do alvo e da distancia - medir antes de confiar",
    fiacao="Indutivo NPN 3 fios: marrom=+24V   azul=0V   preto=sinal -> IN1/IN2\n"
           "IN+=+24V. Confirme NO/NF e a distancia de acionamento no "
           "catalogo do modelo.",
))

_reg(Sensor(
    nome="Optico reflexivo / barreira",
    tem_origem=True,
    confirmado=False,
    # Optico responde rapido, mas reflexivo sofre com sujeira e com a cor do
    # alvo: filtro intermediario para nao transformar ruido em borda.
    filtro_ms=3,
    v_aproximacao=6000,
    v_rastejo=1000,
    repetibilidade="boa se o alvo for fosco e limpo - medir antes de confiar",
    fiacao="Optico NPN: marrom=+24V   azul=0V   preto=sinal -> IN1/IN2\n"
           "IN+=+24V. Em reflexivo, confira se a saida e Light-on ou "
           "Dark-on antes de decidir o nivel (reg 73).",
))

_reg(Sensor(
    nome=SEM_SENSOR,
    tem_origem=False,
    confirmado=True,
    filtro_ms=0,
    v_aproximacao=0,
    v_rastejo=0,
    repetibilidade="nao se aplica",
    fiacao="Este eixo nao tem sensor de origem.\n"
           "Sem origem fisica nao ha homing, e sem zero os limites de curso "
           "por software nao tem referencia - ficam indisponiveis.",
))

PADRAO = "Garfo NPN (MOTEE UX954-WR)"


def obter(nome):
    """O sensor com este nome, ou o padrao da bancada se o nome nao existir.

    Um eixos.json de versao anterior nao tem o campo, e um editado a mao pode
    trazer qualquer coisa -- inclusive um tipo que nem serve de chave de
    dicionario. Nenhum desses casos pode derrubar a janela.
    """
    try:
        achado = SENSORES.get(nome)
    except TypeError:               # nome nao-hasheavel (lista, dict, ...)
        achado = None
    return achado or SENSORES[PADRAO]


def tem_origem(nome) -> bool:
    """O eixo com este sensor consegue estabelecer um zero?"""
    return obter(nome).tem_origem


def nomes():
    """Nomes na ordem de cadastro, para alimentar o combobox."""
    return list(SENSORES)
