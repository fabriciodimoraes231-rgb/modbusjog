"""O barramento RS-485: uma porta serial, um lock, N drives.

Um conversor USB-RS485 e uma linha so, half-duplex: nunca pode haver duas
requisicoes em voo. Por isso existe um unico Barramento compartilhado por todos
os drives, e o endereco de slave vai em cada transacao -- nunca no objeto.
"""

import os
import sys
import threading
import time

import serial

from . import config
from .protocolo import crc_ok


def listar_portas():
    """Portas seriais detectadas, como lista de (device, descricao)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [(p.device, p.description) for p in list_ports.comports()]


def resolver_porta(argv=None):
    """Descobre a porta serial. Precedencia: --porta -> $MODBUS_PORT -> default.

    No Windows nao ha default: o numero da COM muda de maquina para maquina e de
    porta USB para porta USB, e abrir a porta errada numa bancada significa
    conversar com outro equipamento. Devolve None quando nao da para decidir.
    """
    argv = list(sys.argv[1:] if argv is None else argv)

    for i, arg in enumerate(argv):
        if arg in ("--porta", "-p"):
            return argv[i + 1] if i + 1 < len(argv) else None
        if arg.startswith("--porta="):
            return arg.split("=", 1)[1]

    do_ambiente = os.environ.get("MODBUS_PORT")
    if do_ambiente:
        return do_ambiente

    if sys.platform.startswith("win"):
        return None
    return "/dev/ttyUSB0"


class Barramento:
    """Porta serial + lock + transacao validada.

    Compartilhe uma instancia entre todos os drives. O log e opcional: a GUI
    passa o proprio painel de log, os scripts passam print ou nada.
    """

    def __init__(self, ser, log=None):
        """Recebe uma serial.Serial ja aberta e, opcionalmente, um callable de log.

        Args:
            ser: porta serial aberta (pyserial). O Barramento nao a configura:
                quem abre decide baudrate, paridade e timeout -- ver `abrir`.
            log: funcao de um argumento (str) para as mensagens de descarte e
                erro. A GUI passa o painel de log; os scripts passam `print`
                ou nada, e nesse caso as mensagens somem.
        """
        self.ser = ser
        self._lock = threading.Lock()
        self._log = log or (lambda msg: None)

    @classmethod
    def abrir(cls, porta, baudrate=config.BAUDRATE, timeout=config.TIMEOUT, log=None):
        """Abre a porta em 8N1. Levanta serial.SerialException se nao conseguir."""
        ser = serial.Serial(porta, baudrate=baudrate, bytesize=8,
                            parity="N", stopbits=1, timeout=timeout)
        return cls(ser, log=log)

    @property
    def aberto(self):
        """True enquanto a porta serial existe e esta aberta."""
        return bool(self.ser and self.ser.is_open)

    def close(self):
        """Fecha a porta, se ainda estiver aberta. Chamar duas vezes nao quebra."""
        if self.aberto:
            self.ser.close()

    def transact(self, cmd: bytes, expected_bytes: int):
        """
        Envia cmd e le a resposta, sob o lock do barramento.

        Este e o unico ponto por onde passa todo quadro, entao e aqui que a
        resposta e validada -- endereco de slave e CRC. O slave esperado e o
        primeiro byte do proprio comando, logo a checagem vale para leituras e
        escritas sem que nenhum chamador precise repassar o endereco.

        Com um drive so a validacao e redundante. Com varios ela e o que impede
        o caso silencioso: um quadro atrasado do drive 2 chegando enquanto se
        espera o drive 1 e sendo aceito como resposta dele.

        Devolve o quadro cru, ou None se nao houve resposta valida.
        """
        if not self.aberto:
            return None

        with self._lock:
            try:
                self.ser.reset_input_buffer()
                self.ser.write(cmd)
                time.sleep(0.005)
                raw = self.ser.read(expected_bytes)
                if not raw:
                    return None

                esperado = cmd[0]
                if raw[0] != esperado:
                    self._log("[DESCARTE] resposta do slave {} chegou na espera "
                              "do slave {} - quadro ignorado: {}".format(
                                  raw[0], esperado, raw.hex(" ").upper()))
                    self.ser.reset_input_buffer()   # o stream pode estar deslocado
                    return None

                # Uma excecao Modbus tem 5 bytes: com `expected_bytes` maior, o
                # read devolve o quadro curto depois do timeout. O CRC dele e
                # conferido do mesmo jeito.
                if not crc_ok(raw):
                    self._log("[DESCARTE] CRC invalido - quadro ignorado: {}".format(
                        raw.hex(" ").upper()))
                    self.ser.reset_input_buffer()
                    return None

                return raw
            except Exception as e:
                self._log("[ERR] {}".format(e))
                return None
