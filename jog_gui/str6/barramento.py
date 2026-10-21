"""O barramento RS-485: uma porta serial, uma fila, N drives.

Um conversor USB-RS485 e uma linha so, half-duplex: nunca pode haver duas
requisicoes em voo. Por isso existe um unico Barramento compartilhado por todos
os drives, e o endereco de slave vai em cada transacao -- nunca no objeto.

Roda no Windows (COMn) e no Linux (/dev/ttyUSBn, /dev/serial/by-id/...). As
diferencas ficam aqui: a lista de portas, a trava exclusiva da porta e o modo
de baixa latencia do conversor.
"""

import errno
import glob
import os
import sys
import threading
import time
from contextlib import contextmanager

import serial

from . import config
from .protocolo import crc_ok

# No Linux, os nomes estaveis dos conversores: nao mudam com a ordem em que
# os USB foram ligados, ao contrario de /dev/ttyUSB0, /dev/ttyUSB1...
PASTA_POR_ID = "/dev/serial/by-id"


def listar_portas():
    """Portas seriais detectadas, como lista de (device, descricao)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [(p.device, p.description) for p in list_ports.comports()]


def portas_para_escolha(por_id=None, detectadas=None):
    """Portas para o operador escolher, a mais estavel primeiro.

    No Linux vem primeiro /dev/serial/by-id/..., que aponta sempre para o
    mesmo conversor; depois as /dev/tty* que nenhum desses nomes cobre. No
    Windows a lista e a das COM.

    Args:
        por_id: links de /dev/serial/by-id (padrao: lidos do disco).
        detectadas: devices do pyserial (padrao: `listar_portas`).
    """
    if por_id is None:
        por_id = sorted(glob.glob(os.path.join(PASTA_POR_ID, "*")))
    if detectadas is None:
        detectadas = [d for d, _ in listar_portas()]
    cobertas = {os.path.realpath(p) for p in por_id}
    return list(por_id) + [d for d in detectadas
                           if os.path.realpath(d) not in cobertas]


def resolver_porta(argv=None):
    """Descobre a porta serial. Precedencia: --porta -> $MODBUS_PORT -> default.

    No Windows nao ha default: o numero da COM muda de maquina para maquina e de
    porta USB para porta USB, e abrir a porta errada numa bancada significa
    conversar com outro equipamento. No Linux o default e o unico conversor de
    /dev/serial/by-id, se houver exatamente um, e senao /dev/ttyUSB0. Devolve
    None quando nao da para decidir.
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
    por_id = sorted(glob.glob(os.path.join(PASTA_POR_ID, "*")))
    if len(por_id) == 1:
        return por_id[0]
    return "/dev/ttyUSB0"


def explicar_erro_porta(porta, exc):
    """Texto para o operador quando a porta nao abre, com o que fazer.

    Os dois casos comuns no Linux tem causa e remedio conhecidos e uma
    mensagem do sistema que nao diz nenhum dos dois.
    """
    texto = str(exc)
    num = getattr(exc, "errno", None)
    if num == errno.EACCES or "Permission denied" in texto:
        return ("Sem permissao para abrir {}.\n\nNo Linux, o usuario precisa "
                "estar no grupo 'dialout':\n    sudo usermod -aG dialout $USER\n"
                "e depois sair da sessao e entrar de novo.\n\n({})".format(
                    porta, texto))
    if (num in (errno.EBUSY, errno.EAGAIN) or "exclusively lock" in texto
            or "busy" in texto.lower()):
        return ("A porta {} ja esta aberta por outro programa.\n\nFeche a outra "
                "janela do jog_gui, pare o stepper_node (ROS) ou qualquer "
                "terminal serial nessa porta. Dois programas no mesmo "
                "barramento colidem e derrubam a comunicacao.\n\n({})".format(
                    porta, texto))
    if "No such file" in texto or num == errno.ENOENT:
        return ("A porta {} nao existe. O conversor USB-RS485 esta ligado? "
                "Clique em atualizar a lista de portas.\n\n({})".format(
                    porta, texto))
    return texto


class Barramento:
    """Porta serial + fila de transacoes + validacao da resposta.

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
        self._log = log or (lambda msg: None)
        # Fila por senha: uma transacao por vez, NA ORDEM em que foram pedidas.
        # Um Lock simples nao garante ordem -- a thread que acabou de soltar
        # podia pegar de novo e deixar as outras esperando.
        self._fila = threading.Condition()
        self._proxima_senha = 0
        self._senha_da_vez = 0
        # Momento (monotonic) a partir do qual a linha pode receber o proximo
        # pedido: ver `transact`.
        self._livre_em = 0.0
        # slave -> {"ok", "mudo", "crc", "outro_slave", "erro"}: ver `estatisticas`
        self._contagem = {}
        self._lock_contagem = threading.Lock()

    @classmethod
    def abrir(cls, porta, baudrate=config.BAUDRATE, timeout=config.TIMEOUT, log=None):
        """Abre a porta em 8N1. Levanta serial.SerialException se nao conseguir.

        No Linux a porta abre com trava EXCLUSIVA: um segundo programa na mesma
        porta (outra janela, o stepper_node) falha ao abrir, em vez de os dois
        conversarem ao mesmo tempo e um derrubar as respostas do outro. No
        Windows a porta ja e exclusiva por natureza.

        Tambem no Linux, pede ao conversor o modo de baixa latencia: o FTDI
        segura os bytes recebidos por ate 16 ms antes de entrega-los, o que
        pesa em cada uma das centenas de transacoes por minuto. Se o driver
        nao aceitar, segue sem ele e o log avisa.
        """
        extra = {"exclusive": True} if os.name == "posix" else {}
        ser = serial.Serial(porta, baudrate=baudrate, bytesize=8,
                            parity="N", stopbits=1, timeout=timeout, **extra)
        bus = cls(ser, log=log)
        if sys.platform.startswith("linux") and hasattr(ser, "set_low_latency_mode"):
            try:
                ser.set_low_latency_mode(True)
            except (OSError, ValueError, serial.SerialException) as e:
                bus._log("[CON] {}: modo de baixa latencia indisponivel ({}) - "
                         "seguindo sem ele".format(porta, e))
        return bus

    @property
    def aberto(self):
        """True enquanto a porta serial existe e esta aberta."""
        return bool(self.ser and self.ser.is_open)

    def close(self):
        """Fecha a porta, se ainda estiver aberta. Chamar duas vezes nao quebra."""
        if self.aberto:
            self.ser.close()

    @contextmanager
    def _vez(self):
        """Espera a vez na fila e a devolve ao sair, aconteca o que acontecer."""
        with self._fila:
            senha = self._proxima_senha
            self._proxima_senha += 1
            while senha != self._senha_da_vez:
                self._fila.wait()
        try:
            yield
        finally:
            with self._fila:
                self._senha_da_vez += 1
                self._fila.notify_all()

    def transact(self, cmd: bytes, expected_bytes: int):
        """
        Envia cmd e le a resposta: uma transacao por vez, na ordem da fila.

        Este e o unico ponto por onde passa todo quadro, entao e aqui que a
        resposta e validada -- endereco de slave e CRC. O slave esperado e o
        primeiro byte do proprio comando, logo a checagem vale para leituras e
        escritas sem que nenhum chamador precise repassar o endereco.

        Com um drive so a validacao e redundante. Com varios ela e o que impede
        o caso silencioso: um quadro atrasado do drive 2 chegando enquanto se
        espera o drive 1 e sendo aceito como resposta dele.

        O silencio entre quadros (config.PAUSA_QUADRO, ou PAUSA_APOS_FALHA
        depois de uma falha) e garantido AQUI, na vez de cada um: o monitor, a
        vigilancia do JOG e o inspetor rodam em threads proprias, e sem isso
        uma pegava a linha no instante em que a outra recebia o ultimo byte --
        o drive, ainda saindo da transmissao, perdia o pedido e a leitura
        caia por timeout.

        Devolve o quadro cru, ou None se nao houve resposta valida.
        """
        if not self.aberto:
            return None

        with self._vez():
            espera = self._livre_em - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            desfecho = "erro"
            try:
                self.ser.reset_input_buffer()
                self.ser.write(cmd)
                time.sleep(0.005)
                raw = self.ser.read(expected_bytes)
                if not raw:
                    desfecho = "mudo"
                    return None

                esperado = cmd[0]
                if raw[0] != esperado:
                    desfecho = "outro_slave"
                    self._log("[DESCARTE] resposta do slave {} chegou na espera "
                              "do slave {} - quadro ignorado: {}".format(
                                  raw[0], esperado, raw.hex(" ").upper()))
                    self.ser.reset_input_buffer()   # o stream pode estar deslocado
                    return None

                # Uma excecao Modbus tem 5 bytes: com `expected_bytes` maior, o
                # read devolve o quadro curto depois do timeout. O CRC dele e
                # conferido do mesmo jeito.
                if not crc_ok(raw):
                    desfecho = "crc"
                    self._log("[DESCARTE] CRC invalido - quadro ignorado: {}".format(
                        raw.hex(" ").upper()))
                    self.ser.reset_input_buffer()
                    return None

                desfecho = "ok"
                return raw
            except Exception as e:
                self._log("[ERR] {}".format(e))
                return None
            finally:
                with self._lock_contagem:
                    cont = self._contagem.setdefault(cmd[0], dict.fromkeys(
                        ("ok", "mudo", "crc", "outro_slave", "erro"), 0))
                    cont[desfecho] += 1
                self._livre_em = time.monotonic() + (
                    config.PAUSA_QUADRO if desfecho == "ok"
                    else config.PAUSA_APOS_FALHA)

    def estatisticas(self, zerar=True):
        """Transacoes por slave desde a ultima chamada: {slave: {desfecho: n}}.

        Desfechos: ok, mudo (sem resposta no timeout), crc (quadro corrompido,
        tipico de ruido), outro_slave (resposta de outro endereco, tipica de
        colisao, endereco duplicado ou outro programa na mesma linha) e erro
        (excecao da porta). E o que separa ruido de cabo, endereco errado e
        drive desligado.
        """
        with self._lock_contagem:
            copia = {s: dict(c) for s, c in self._contagem.items()}
            if zerar:
                self._contagem = {}
        return copia
