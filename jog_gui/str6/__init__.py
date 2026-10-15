"""Biblioteca de controle do drive de passo STR6-RS485 por Modbus RTU.

Fonte unica de protocolo, registradores e configuracao para a GUI e para os
scripts de bancada (scripts/). Referencia dos registradores:
Manual-DRIVER-STR6-RS485.pdf (Kalatec, rev. 1.0) -- documento do fabricante,
fora deste repositorio.

Organizacao:

    config.py         baudrate, IDs dos drives, correntes, tempos
    registradores.py  enderecos REG_* e bits -- nenhum literal fora daqui
    protocolo.py      CRC, montagem e parse de quadros (funcoes puras)
    barramento.py     a porta serial compartilhada e a transacao validada
    drive.py          um drive: escritas verificadas e operacoes

Uso tipico num script:

    from jog_gui.str6 import conectar, desarmar_todos, Drive

    bus = conectar(descricao=__doc__)
    if bus is None:
        return
    try:
        Drive(bus, 1).armar()
    finally:
        desarmar_todos(bus)
        bus.close()

Todos os drives compartilham um unico barramento: o endereco de slave vai em
cada transacao, nunca no objeto de conexao.
"""

import serial

from .config import (
    BAUDRATE,
    BAUDRATES_SUPORTADOS,
    CORRENTES_MA,
    ESPERA_SALVAR,
    ID_NEMA1_SOCKET,
    ID_NEMA2_CABEC,
    ID_SPIN_MOTOR,
    MALHA_PADRAO,
    PAUSA_QUADRO,
    PULSOS_VOLTA,
    RAMPA_MS,
    SLAVE_MAX,
    SLAVE_MIN,
    TIMEOUT,
    TODOS_OS_DRIVES,
    VARREDURA_MAX,
    VEL_MAX_PPS,
)
from .barramento import Barramento, listar_portas, resolver_porta
from .drive import (
    RELIGA_DESLIGADO,
    RELIGA_ESPERANDO,
    RELIGA_RELIGADO,
    Drive,
    DriveNaoConfirmou,
    aceleracao_da_rampa,
    comparar_configuracao,
    desarmar_todos,
    perfil_movimento,
    varrer,
)
from .protocolo import (
    build_read_regs,
    build_write_multi,
    build_write_single,
    bytes_resposta_leitura,
    crc16,
    crc_ok,
    de_palavras_32,
    descrever_excecao,
    palavras_32,
    parse_read_response,
)
from .registradores import *  # noqa: F401,F403 -- os REG_* sao a interface
from . import registradores


def conectar(descricao=None, porta=None, baudrate=BAUDRATE, log=None):
    """Abre o barramento RS-485. Devolve um Barramento conectado, ou None.

    Nenhuma escrita acontece aqui -- so a abertura da porta. O chamador fecha
    com .close().
    """
    if descricao:
        print(descricao.strip())
        print("-" * 60)

    if porta is None:
        porta = resolver_porta()

    if porta is None:
        print("Erro: informe a porta serial com --porta (ex.: --porta COM5) ou "
              "defina a variavel de ambiente MODBUS_PORT.")
        portas = listar_portas()
        if portas:
            print("\nPortas detectadas nesta maquina:")
            for device, desc in portas:
                print("  {}  -  {}".format(device, desc))
        else:
            print("\nNenhuma porta serial detectada. O conversor USB-RS485 esta ligado?")
        return None

    try:
        bus = Barramento.abrir(porta, baudrate=baudrate, log=log)
    except (serial.SerialException, OSError) as e:
        print("Erro: nao foi possivel abrir {} a {} bps ({}).".format(
            porta, baudrate, e))
        print("Verifique se a porta existe, se nao esta ocupada por outro "
              "programa e se voce tem permissao de acesso.")
        return None

    print("Barramento aberto em {} a {} bps (8N1).".format(porta, baudrate))
    return bus


__all__ = [
    # conexao
    "conectar", "Barramento", "resolver_porta", "listar_portas",
    # drives
    "Drive", "DriveNaoConfirmou", "desarmar_todos", "varrer",
    "aceleracao_da_rampa", "perfil_movimento", "comparar_configuracao",
    "RELIGA_ESPERANDO", "RELIGA_DESLIGADO", "RELIGA_RELIGADO",
    # protocolo
    "crc16", "crc_ok", "build_read_regs", "build_write_single",
    "build_write_multi", "parse_read_response", "bytes_resposta_leitura",
    "descrever_excecao", "palavras_32", "de_palavras_32",
    # configuracao
    "BAUDRATE", "BAUDRATES_SUPORTADOS", "TIMEOUT", "PAUSA_QUADRO",
    "CORRENTES_MA", "TODOS_OS_DRIVES", "SLAVE_MIN", "SLAVE_MAX",
    "VARREDURA_MAX", "ID_NEMA1_SOCKET", "ID_NEMA2_CABEC", "ID_SPIN_MOTOR",
    "MALHA_PADRAO", "PULSOS_VOLTA", "VEL_MAX_PPS", "RAMPA_MS", "ESPERA_SALVAR",
] + [n for n in dir(registradores)
     if n.isupper() or n in ("nome_alarme", "nomes_status")]
