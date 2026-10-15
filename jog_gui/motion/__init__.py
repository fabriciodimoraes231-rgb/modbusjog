"""Logica de movimento de um eixo de passo STR6-RS485, sem interface grafica.

Junta o mapa de registradores (str6/registradores.py) com o driver
(str6/drive.py) e e onde mora a regra de movimento.

    config.py    ConfigEixo: os ajustes de um eixo, lidos do eixos.json
    limites.py   faixa de trabalho em pulsos -- funcoes puras
    eixo.py      EixoMovimento: armar, jog, passo, ir_para, homing, parar

A GUI (jog_gui.ui) usa esta camada para todo movimento, e os scripts podem
usar tambem: a regra fica num lugar so.

Uso tipico num script:

    from jog_gui.str6 import conectar, Drive
    from jog_gui.motion import ConfigEixo, EixoMovimento

    bus = conectar()
    eixo = EixoMovimento(Drive(bus, 1), ConfigEixo(1, "socket"), log=print)
    try:
        eixo.armar()
        resultado = eixo.passo(+1, pulsos=1500)
        print(resultado.ok, resultado.causa, resultado.detalhe)
    finally:
        eixo.desarmar()
        bus.close()

Nao arbitra concorrencia: um Barramento RS-485 e half-duplex e quem decide qual
eixo fala e o chamador.
"""

from .config import (
    ENTRADA_LIM_NEG,
    ENTRADA_LIM_POS,
    FRENTE,
    SENTIDOS,
    TRAS,
    ConfigEixo,
    oposto,
)
from .eixo import (
    CAUSA_ALARME,
    CAUSA_CANCELADO,
    CAUSA_DRIVE_MUDO,
    CAUSA_FORA_DA_FAIXA,
    CAUSA_LIMITE,
    CAUSA_MOTOR_OFF,
    CAUSA_NAO_PARTIU,
    CAUSA_OK,
    CAUSA_RECUSADO,
    CAUSA_SEM_SENSOR,
    CAUSA_TIMEOUT,
    CAUSA_ZERO_INVALIDO,
    EixoMovimento,
    MovimentoRecusado,
    Resultado,
    em_falha,
    motivo_falha,
)

__all__ = [
    "ConfigEixo",
    "EixoMovimento",
    "MovimentoRecusado",
    "Resultado",
    "em_falha",
    "motivo_falha",
    "oposto",
    "FRENTE",
    "TRAS",
    "SENTIDOS",
    "ENTRADA_LIM_NEG",
    "ENTRADA_LIM_POS",
    "CAUSA_OK",
    "CAUSA_MOTOR_OFF",
    "CAUSA_FORA_DA_FAIXA",
    "CAUSA_ZERO_INVALIDO",
    "CAUSA_SEM_SENSOR",
    "CAUSA_DRIVE_MUDO",
    "CAUSA_ALARME",
    "CAUSA_TIMEOUT",
    "CAUSA_NAO_PARTIU",
    "CAUSA_CANCELADO",
    "CAUSA_RECUSADO",
    "CAUSA_LIMITE",
]
