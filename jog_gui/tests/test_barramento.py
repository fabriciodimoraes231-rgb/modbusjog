"""Barramento: silencio entre quadros e contagem de desfechos por drive.

Sem porta serial: uma serial falsa devolve respostas roteirizadas e anota a
hora de cada escrita.

Rodar da pasta que contem jog_gui/:

    python -m unittest discover -s jog_gui/tests -t . -v
"""
import errno
import threading
import time
import unittest

from jog_gui.str6 import (
    PAUSA_APOS_FALHA,
    PAUSA_QUADRO,
    Barramento,
    build_read_regs,
    crc16,
    explicar_erro_porta,
    portas_para_escolha,
)


def _resposta(slave, valor):
    """Resposta valida de FC03 com um registrador."""
    corpo = bytes([slave, 0x03, 2, valor >> 8, valor & 0xFF])
    return corpo + crc16(corpo)


class SerialFalsa:
    """O minimo de pyserial que o Barramento usa."""

    is_open = True

    def __init__(self, respostas):
        self.respostas = list(respostas)   # um item por write; b"" = mudo
        self.escritas = []                 # hora (monotonic) de cada write

    def reset_input_buffer(self):
        pass

    def write(self, cmd):
        self.escritas.append(time.monotonic())

    def read(self, n):
        return self.respostas.pop(0) if self.respostas else b""

    def close(self):
        self.is_open = False


class TestSilencioEntreQuadros(unittest.TestCase):

    def test_respeita_a_pausa_depois_de_uma_resposta(self):
        ser = SerialFalsa([_resposta(3, 1), _resposta(3, 2)])
        bus = Barramento(ser)
        cmd = build_read_regs(3, 75, 1)
        bus.transact(cmd, 7)
        bus.transact(cmd, 7)
        self.assertGreaterEqual(ser.escritas[1] - ser.escritas[0],
                                PAUSA_QUADRO * 0.9)

    def test_pausa_maior_depois_de_uma_falha(self):
        # Uma resposta atrasada pode estar chegando: o proximo pedido espera.
        ser = SerialFalsa([b"", _resposta(3, 2)])
        bus = Barramento(ser)
        cmd = build_read_regs(3, 75, 1)
        self.assertIsNone(bus.transact(cmd, 7))
        bus.transact(cmd, 7)
        self.assertGreaterEqual(ser.escritas[1] - ser.escritas[0],
                                PAUSA_APOS_FALHA * 0.9)

    def test_a_pausa_vale_entre_threads(self):
        # O caso real: monitor e vigilancia do JOG em threads diferentes.
        ser = SerialFalsa([_resposta(3, i) for i in range(6)])
        bus = Barramento(ser)
        cmd = build_read_regs(3, 75, 1)

        def _tres():
            for _ in range(3):
                bus.transact(cmd, 7)

        ts = [threading.Thread(target=_tres) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        gaps = [b - a for a, b in zip(ser.escritas, ser.escritas[1:])]
        self.assertEqual(len(ser.escritas), 6)
        self.assertGreaterEqual(min(gaps), PAUSA_QUADRO * 0.9)


class TestFila(unittest.TestCase):

    def test_atende_na_ordem_de_chegada(self):
        # Quem pediu primeiro transmite primeiro, mesmo com a linha ocupada.
        ser = SerialFalsa([_resposta(s, 0) for s in (1, 2, 3, 4)])
        ordem = []
        escrever = ser.write
        ser.write = lambda cmd: (ordem.append(cmd[0]), escrever(cmd))
        bus = Barramento(ser)
        with bus._vez():                 # linha ocupada: todos entram na fila
            ts = []
            for slave in (1, 2, 3, 4):
                t = threading.Thread(target=bus.transact,
                                     args=(build_read_regs(slave, 75, 1), 7))
                t.start()
                ts.append(t)
                while bus._proxima_senha < slave + 1:   # garante a ordem da fila
                    time.sleep(0.001)
        for t in ts:
            t.join()
        self.assertEqual(ordem, [1, 2, 3, 4])

    def test_excecao_na_transacao_nao_trava_a_fila(self):
        ser = SerialFalsa([_resposta(3, 1)])

        def _quebra(cmd):
            raise OSError("cabo arrancado")

        ser.write = _quebra
        bus = Barramento(ser)
        self.assertIsNone(bus.transact(build_read_regs(3, 75, 1), 7))
        ser.write = lambda cmd: None
        self.assertIsNotNone(bus.transact(build_read_regs(3, 75, 1), 7))


class TestPortas(unittest.TestCase):

    def test_nome_estavel_vem_primeiro_e_sem_repetir(self):
        # O by-id e um link para um /dev/ttyUSB*; sem link real no disco, o
        # realpath devolve o proprio caminho -- entao so o que nao repete fica.
        portas = portas_para_escolha(
            por_id=["/dev/serial/by-id/usb-FTDI_RS485-if00-port0"],
            detectadas=["/dev/serial/by-id/usb-FTDI_RS485-if00-port0",
                        "/dev/ttyUSB1"])
        self.assertEqual(portas, ["/dev/serial/by-id/usb-FTDI_RS485-if00-port0",
                                  "/dev/ttyUSB1"])

    def test_windows_lista_as_com(self):
        self.assertEqual(portas_para_escolha(por_id=[], detectadas=["COM3"]),
                         ["COM3"])

    def test_sem_permissao_explica_o_grupo_dialout(self):
        e = OSError(errno.EACCES, "Permission denied: '/dev/ttyUSB0'")
        self.assertIn("dialout", explicar_erro_porta("/dev/ttyUSB0", e))

    def test_porta_ocupada_aponta_o_outro_programa(self):
        e = OSError("Could not exclusively lock port /dev/ttyUSB0: "
                    "[Errno 11] Resource temporarily unavailable")
        self.assertIn("outro programa", explicar_erro_porta("/dev/ttyUSB0", e))

    def test_erro_desconhecido_passa_o_texto_original(self):
        e = OSError("algo inesperado")
        self.assertEqual(explicar_erro_porta("COM3", e), "algo inesperado")


class TestEstatisticas(unittest.TestCase):

    def test_conta_cada_desfecho_por_drive(self):
        corrompida = bytearray(_resposta(3, 5))
        corrompida[-1] ^= 0xFF
        ser = SerialFalsa([_resposta(3, 1), b"", bytes(corrompida),
                           _resposta(2, 1), _resposta(1, 1)])
        bus = Barramento(ser)
        for slave in (3, 3, 3, 3, 1):
            bus.transact(build_read_regs(slave, 75, 1), 7)
        est = bus.estatisticas()
        self.assertEqual(est[3], {"ok": 1, "mudo": 1, "crc": 1,
                                  "outro_slave": 1, "erro": 0})
        self.assertEqual(est[1]["ok"], 1)

    def test_zera_depois_de_ler(self):
        bus = Barramento(SerialFalsa([b""]))
        bus.transact(build_read_regs(3, 75, 1), 7)
        self.assertEqual(bus.estatisticas()[3]["mudo"], 1)
        self.assertEqual(bus.estatisticas(), {})

    def test_sem_zerar_mantem_a_contagem(self):
        bus = Barramento(SerialFalsa([b""]))
        bus.transact(build_read_regs(3, 75, 1), 7)
        bus.estatisticas(zerar=False)
        self.assertEqual(bus.estatisticas()[3]["mudo"], 1)


if __name__ == "__main__":
    unittest.main()
