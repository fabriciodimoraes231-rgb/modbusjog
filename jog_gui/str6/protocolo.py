"""Montagem e validacao de quadros Modbus RTU -- funcoes puras, sem I/O.

Implementacao propria em vez de uma biblioteca: o log hexadecimal da GUI mostra
o quadro exato que foi para o fio, o que e o que permite depurar barramento na
bancada. Como nao ha biblioteca conferindo nada por baixo, a validacao da
resposta (endereco + CRC) e obrigatoria -- ver Barramento.transact.

O STR6-RS485 aceita FC03, FC06 e FC16 (manual p. 12) e usa o CRC-16 Modbus
padrao (rotina em C do manual, p. 20).
"""

import struct

# Function codes usados
FC_READ = 0x03       # ler N registradores
FC_WRITE_1 = 0x06    # escrever um registrador
FC_WRITE_N = 0x10    # escrever N registradores consecutivos

# Toda resposta de excecao tem o bit 7 setado no function code.
BIT_EXCECAO = 0x80

# Uma confirmacao de escrita (FC06 ou FC16) tem sempre 8 bytes.
BYTES_ECO_ESCRITA = 8

# Codigos de excecao do padrao Modbus. O manual do STR6 nao lista os seus.
EXCECOES = {
    0x01: "codigo de funcao ilegal",
    0x02: "endereco de registrador ilegal",
    0x03: "dado ilegal - valor fora da faixa ou registrador nao gravavel",
    0x04: "falha no escravo",
}


def crc16(data: bytes) -> bytes:
    """Calcula CRC-16 Modbus e retorna 2 bytes (low, high)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def crc_ok(frame: bytes) -> bool:
    """
    Confere o CRC-16 de um quadro recebido (dados + 2 bytes de CRC no fim).

    Num barramento com varios drives isso deixa de ser luxo: sem conferir o CRC,
    um quadro truncado ou colidido e aceito como leitura valida e vira posicao
    ou status errado na tela - e, no card de curso, movimento sobre um numero
    que nunca chegou inteiro.
    """
    if len(frame) < 4:
        return False
    return crc16(frame[:-2]) == frame[-2:]


def build_write_single(slave: int, reg: int, value: int) -> bytes:
    """FC 06 - escreve um unico registrador (16 bits)."""
    payload = struct.pack(">BBHH", slave, FC_WRITE_1, reg, value & 0xFFFF)
    return payload + crc16(payload)


def build_write_multi(slave: int, reg_start: int, valores) -> bytes:
    """
    FC 16 (0x10) - escreve varios registradores de uma vez.

    Os valores de 32 bits do STR6 (velocidade, aceleracao, curso) ocupam dois
    registradores, e o perfil de movimento inteiro (62~69) vai num quadro so.
    Em escritas FC06 separadas o drive poderia disparar com metade dos valores
    atualizada.
    """
    valores = list(valores)
    corpo = struct.pack(">BBHHB", slave, FC_WRITE_N, reg_start, len(valores),
                        len(valores) * 2)
    for v in valores:
        corpo += struct.pack(">H", v & 0xFFFF)
    return corpo + crc16(corpo)


def build_read_regs(slave: int, reg_start: int, count: int) -> bytes:
    """FC 03 - le N registradores."""
    payload = struct.pack(">BBHH", slave, FC_READ, reg_start, count)
    return payload + crc16(payload)


def bytes_resposta_leitura(count: int) -> int:
    """Tamanho da resposta FC03: ADR + FC + ByteCount + dados + CRC."""
    return 5 + count * 2


def parse_read_response(raw: bytes, expected_count: int):
    """
    Parseia resposta FC03. Retorna lista de inteiros ou None em erro.

    So confere a estrutura (function code, byte count, comprimento). Endereco de
    slave e CRC ja foram validados em Barramento.transact, que e por onde todo
    quadro passa - nao repita a checagem aqui.
    """
    if not raw or len(raw) < bytes_resposta_leitura(expected_count):
        return None
    if raw[1] != FC_READ:
        return None
    if raw[2] != expected_count * 2:
        return None
    return [struct.unpack(">H", raw[3 + i * 2:5 + i * 2])[0]
            for i in range(expected_count)]


def descrever_excecao(resp) -> str:
    """Descreve a resposta se ela for uma excecao Modbus. String vazia se nao for."""
    if resp and len(resp) >= 3 and resp[1] & BIT_EXCECAO:
        cod = resp[2]
        return "EXCECAO {:02X}h: {}".format(
            cod, EXCECOES.get(cod, "codigo desconhecido"))
    return ""


def palavras_32(valor: int):
    """Parte um inteiro de 32 bits em [baixa, alta] -- a ordem dos registradores.

    No STR6 a palavra BAIXA fica no endereco MENOR: o exemplo de FC16 do manual
    (p. 19) escreve 14464 em 68 e 1 em 69 para um curso de 80000 pulsos. A
    lista ja sai na ordem em que vai para o FC16.
    """
    bruto = int(valor) & 0xFFFFFFFF
    return [bruto & 0xFFFF, (bruto >> 16) & 0xFFFF]


def de_palavras_32(baixa: int, alta: int) -> int:
    """Junta [baixa, alta] num inteiro COM SINAL.

    O manual nao declara se o contador de pulsos (39/40) tem sinal. Ler com
    sinal e o que mantem a posicao continua quando o eixo passa abaixo do zero.
    """
    bruto = ((alta & 0xFFFF) << 16) | (baixa & 0xFFFF)
    return bruto - 0x100000000 if bruto >= 0x80000000 else bruto
