"""Testes de str6.protocolo -- funcoes puras, nao precisam de drive nem porta.

Rodar da pasta que contem jog_gui/:

    python -m unittest discover -s jog_gui/tests -t . -v

Os vetores de CRC nao sao gerados por crc16(): sao quadros publicados -- o
exemplo classico da especificacao Modbus RTU e os exemplos do manual do STR6
(p. 19). Um teste que comparasse a funcao com ela mesma passaria mesmo com o
polinomio trocado.
"""
import unittest

from jog_gui.str6.protocolo import (
    BYTES_ECO_ESCRITA,
    FC_READ,
    FC_WRITE_1,
    FC_WRITE_N,
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
from jog_gui.str6.registradores import (
    REG_COMANDO,
    REG_CORRENTE_PICO,
    REG_CURSO_L,
    REG_DESACEL_L,
    REG_ENABLE,
    REG_PULSOS_L,
    REG_STATUS,
    REG_VEL_L,
)


class TestCRC16(unittest.TestCase):
    """CRC-16/MODBUS: poly 0xA001 refletido, init 0xFFFF, transmitido low-first."""

    def test_vetor_da_especificacao_modbus(self):
        # Exemplo classico da especificacao Modbus RTU: slave 0x11, FC03,
        # registrador 0x006B, 3 registradores -> CRC vai no fio como 76 87
        # (byte baixo primeiro).
        self.assertEqual(crc16(bytes.fromhex("1103006B0003")),
                         bytes.fromhex("7687"))

    def test_vetor_leitura_simples(self):
        # slave 1, FC03, registrador 0, 1 registrador (manual p. 19).
        self.assertEqual(crc16(bytes.fromhex("010300000001")),
                         bytes.fromhex("840A"))

    def test_vetores_do_manual_do_str6(self):
        # Manual p. 19: resposta com a corrente de pico (2700 mA = 0x0A8C) e
        # eco do FC16 de curso a partir do registrador 68.
        self.assertEqual(crc16(bytes.fromhex("0103020A8C")),
                         bytes.fromhex("BF41"))
        self.assertEqual(crc16(bytes.fromhex("011000440002")),
                         bytes.fromhex("01DD"))

    def test_retorna_sempre_dois_bytes(self):
        for dado in (b"", b"\x00", b"\xff" * 64):
            self.assertEqual(len(crc16(dado)), 2)

    def test_crc_de_vazio_e_o_valor_inicial(self):
        # Sem nenhum byte processado o registrador continua em 0xFFFF.
        self.assertEqual(crc16(b""), bytes([0xFF, 0xFF]))

    def test_e_sensivel_a_ordem_dos_bytes(self):
        # Um CRC que ignorasse a ordem nao pegaria bytes trocados na recepcao.
        self.assertNotEqual(crc16(b"\x01\x02"), crc16(b"\x02\x01"))


class TestCrcOk(unittest.TestCase):
    """crc_ok e a unica barreira contra quadro truncado ou colidido."""

    def setUp(self):
        corpo = bytes.fromhex("1103006B0003")
        self.quadro = corpo + crc16(corpo)

    def test_aceita_quadro_integro(self):
        self.assertTrue(crc_ok(self.quadro))

    def test_rejeita_bit_trocado_nos_dados(self):
        adulterado = bytearray(self.quadro)
        adulterado[3] ^= 0x01
        self.assertFalse(crc_ok(bytes(adulterado)))

    def test_rejeita_crc_trocado(self):
        adulterado = bytearray(self.quadro)
        adulterado[-1] ^= 0xFF
        self.assertFalse(crc_ok(bytes(adulterado)))

    def test_rejeita_quadro_truncado(self):
        # Colisao no barramento costuma chegar como quadro cortado.
        self.assertFalse(crc_ok(self.quadro[:-1]))

    def test_rejeita_quadro_curto_demais_sem_estourar(self):
        # Menos de 4 bytes nao tem dados + CRC: precisa retornar False,
        # nao levantar IndexError no meio da leitura da bancada.
        for n in range(4):
            self.assertFalse(crc_ok(b"\x00" * n), "len={}".format(n))


class TestBuildWriteSingle(unittest.TestCase):
    """FC 06: ADR FC REG_H REG_L VAL_H VAL_L CRC_L CRC_H, sempre 8 bytes."""

    def test_exemplo_do_manual(self):
        # Manual p. 19: 1600 (0x0640) no registrador 64 (velocidade, baixa).
        self.assertEqual(build_write_single(1, REG_VEL_L, 1600),
                         bytes.fromhex("0106004006408A4E"))

    def test_estrutura_do_quadro(self):
        q = build_write_single(1, REG_ENABLE, 1)
        self.assertEqual(q[:6], bytes.fromhex("010600060001"))
        self.assertEqual(len(q), 8)
        self.assertTrue(crc_ok(q))

    def test_function_code(self):
        self.assertEqual(build_write_single(3, REG_CORRENTE_PICO, 1000)[1],
                         FC_WRITE_1)

    def test_valor_negativo_vira_complemento_de_dois(self):
        q = build_write_single(1, REG_COMANDO, -1)
        self.assertEqual(q[4:6], b"\xff\xff")
        self.assertTrue(crc_ok(q))

    def test_eco_de_escrita_tem_o_tamanho_esperado(self):
        self.assertEqual(len(build_write_single(1, REG_ENABLE, 1)),
                         BYTES_ECO_ESCRITA)


class TestBuildWriteMulti(unittest.TestCase):
    """FC16 existe para o perfil de movimento ir inteiro num quadro so."""

    def test_exemplo_do_manual(self):
        # Manual p. 19: curso de 80000 pulsos = 14464 (0x3880) em 68 e 1 em 69.
        self.assertEqual(
            build_write_multi(1, REG_CURSO_L, palavras_32(80000)),
            bytes.fromhex("01100044000204388000013B24"))

    def test_contagem_e_bytecount_conferem_com_os_valores(self):
        for n in (1, 2, 8):
            q = build_write_multi(1, REG_DESACEL_L, list(range(n)))
            self.assertEqual(int.from_bytes(q[4:6], "big"), n)  # qtd registradores
            self.assertEqual(q[6], n * 2)                       # byte count
            self.assertEqual(len(q), 9 + n * 2)

    def test_aceita_qualquer_iteravel(self):
        self.assertEqual(build_write_multi(1, REG_CURSO_L, (1, 2)),
                         build_write_multi(1, REG_CURSO_L, [1, 2]))

    def test_valores_negativos_viram_complemento_de_dois(self):
        q = build_write_multi(1, REG_CURSO_L, [-1, -1])
        self.assertEqual(q[7:11], b"\xff\xff\xff\xff")


class TestBuildReadRegs(unittest.TestCase):
    """FC 03: os vetores conferidos sao exemplos publicados."""

    def test_estrutura_do_quadro(self):
        self.assertEqual(build_read_regs(0x11, 0x006B, 3),
                         bytes.fromhex("1103006B00037687"))

    def test_exemplo_do_manual(self):
        # Manual p. 19: le 1 registrador a partir do 0 (corrente de pico).
        self.assertEqual(build_read_regs(1, REG_CORRENTE_PICO, 1),
                         bytes.fromhex("010300000001840A"))

    def test_function_code(self):
        self.assertEqual(build_read_regs(1, REG_STATUS, 1)[1], FC_READ)


class TestBytesRespostaLeitura(unittest.TestCase):
    """O tamanho esperado da resposta FC03: ADR + FC + ByteCount + 2N + CRC.

    E o numero que vai para `Barramento.transact`: pedir menos bytes deixa
    resto no buffer e desloca o proximo quadro.
    """

    def test_conta_adr_fc_bytecount_dados_e_crc(self):
        # 1 + 1 + 1 + 2N + 2
        self.assertEqual(bytes_resposta_leitura(1), 7)
        self.assertEqual(bytes_resposta_leitura(3), 11)

    def test_bate_com_o_tamanho_de_uma_resposta_real(self):
        corpo = bytes.fromhex("010306") + b"\x00\x01\x00\x02\x00\x03"
        self.assertEqual(len(corpo + crc16(corpo)), bytes_resposta_leitura(3))


class TestParseReadResponse(unittest.TestCase):
    """Leitura dos valores e recusa de quadro malformado.

    Endereco e CRC ja foram validados em `Barramento.transact`; aqui so se
    confere a estrutura -- function code, byte count e comprimento.
    """

    def _resposta(self, valores):
        corpo = bytes([0x01, FC_READ, len(valores) * 2])
        for v in valores:
            corpo += v.to_bytes(2, "big")
        return corpo + crc16(corpo)

    def test_resposta_do_manual(self):
        # Manual p. 19: o drive devolve 2700 mA de corrente de pico.
        self.assertEqual(
            parse_read_response(bytes.fromhex("0103020A8CBF41"), 1), [2700])

    def test_le_os_valores_na_ordem(self):
        self.assertEqual(parse_read_response(self._resposta([1, 2, 3]), 3),
                         [1, 2, 3])

    def test_big_endian_dentro_do_registrador(self):
        self.assertEqual(parse_read_response(self._resposta([0xABCD]), 1),
                         [0xABCD])

    def test_recusa_resposta_curta(self):
        # Leitura parcial da serial: prometeu 3 registradores, chegou espaco p/ 2.
        self.assertIsNone(parse_read_response(self._resposta([1, 2]), 3))

    def test_recusa_function_code_diferente(self):
        # Excecao (FC 0x83) nao pode ser lida como leitura valida.
        crua = bytearray(self._resposta([1]))
        crua[1] = 0x83
        self.assertIsNone(parse_read_response(bytes(crua), 1))

    def test_recusa_bytecount_incoerente(self):
        crua = bytearray(self._resposta([1, 2]))
        crua[2] = 2                      # diz 1 registrador, pediram-se 2
        self.assertIsNone(parse_read_response(bytes(crua), 2))

    def test_recusa_quadro_vazio_sem_estourar(self):
        self.assertIsNone(parse_read_response(b"", 1))
        self.assertIsNone(parse_read_response(None, 1))


class TestDescreverExcecao(unittest.TestCase):
    """Resposta de excecao (bit 7 no function code) vira texto; o resto, "" ."""

    def test_string_vazia_para_resposta_normal(self):
        self.assertEqual(
            descrever_excecao(bytes.fromhex("010306000100020003")), "")

    def test_string_vazia_para_resposta_ausente(self):
        for resp in (None, b"", b"\x01", b"\x01\x83"):
            self.assertEqual(descrever_excecao(resp), "")

    def test_reconhece_dado_ilegal(self):
        texto = descrever_excecao(bytes.fromhex("018603"))
        self.assertIn("03h", texto)
        self.assertIn("dado ilegal", texto)

    def test_codigo_fora_da_tabela_nao_quebra(self):
        texto = descrever_excecao(bytes.fromhex("0183FF"))
        self.assertIn("FFh", texto)
        self.assertIn("desconhecido", texto)

    def test_detecta_excecao_em_qualquer_function_code(self):
        for fc in (FC_READ, FC_WRITE_1, FC_WRITE_N):
            self.assertTrue(descrever_excecao(bytes([0x01, fc | 0x80, 0x02])))


class TestPalavras32(unittest.TestCase):
    """Perfil de movimento (62~69) e contador de pulsos (39/40).

    No STR6 a palavra BAIXA vai no endereco MENOR. Inverter a ordem so quebra
    acima de 16 bits, entao os testes passam desse limite.
    """

    def test_valor_pequeno_so_ocupa_a_palavra_baixa(self):
        self.assertEqual(palavras_32(100), [100, 0])

    def test_zero(self):
        self.assertEqual(palavras_32(0), [0, 0])

    def test_menos_um_e_tudo_ligado(self):
        self.assertEqual(palavras_32(-1), [0xFFFF, 0xFFFF])

    def test_baixa_primeiro(self):
        self.assertEqual(palavras_32(0x00012345), [0x2345, 0x0001])

    def test_exemplo_do_manual(self):
        # Manual p. 19: 80000 pulsos = 14464 baixa + 1 alta.
        self.assertEqual(palavras_32(80000), [14464, 1])

    def test_ida_e_volta(self):
        for v in (0, 1, -1, 100, -100, 6000, -6000,
                  0xFFFF, 0x10000, -0x10000, 1_000_000, -1_000_000,
                  0x7FFFFFFF, -0x80000000):
            with self.subTest(valor=v):
                self.assertEqual(de_palavras_32(*palavras_32(v)), v)

    def test_de_palavras_interpreta_com_sinal(self):
        self.assertEqual(de_palavras_32(0xFFFF, 0xFFFF), -1)
        self.assertEqual(de_palavras_32(0x0000, 0x8000), -0x80000000)
        self.assertEqual(de_palavras_32(0xFFFF, 0x7FFF), 0x7FFFFFFF)

    def test_de_palavras_ignora_bits_acima_de_16_em_cada_palavra(self):
        self.assertEqual(de_palavras_32(0x10005, 0x10000), 5)


class TestIntegracaoQuadros(unittest.TestCase):
    """Os quadros montados aqui precisam sobreviver a propria validacao."""

    def test_todo_quadro_montado_passa_no_crc_ok(self):
        quadros = [
            build_read_regs(1, REG_STATUS, 1),
            build_read_regs(31, REG_PULSOS_L, 2),
            build_write_single(1, REG_ENABLE, 1),
            build_write_single(31, REG_COMANDO, 3),
            build_write_multi(1, REG_CURSO_L, palavras_32(12345)),
            build_write_multi(2, REG_DESACEL_L, [1, 2, 3, 4, 5, 6, 7, 8]),
        ]
        for q in quadros:
            with self.subTest(quadro=q.hex()):
                self.assertTrue(crc_ok(q))

    def test_o_endereco_de_slave_vai_no_primeiro_byte(self):
        for slave in (1, 2, 3, 31, 247):
            self.assertEqual(build_read_regs(slave, REG_STATUS, 1)[0], slave)
            self.assertEqual(build_write_single(slave, REG_ENABLE, 1)[0], slave)
            self.assertEqual(build_write_multi(slave, REG_CURSO_L, [0])[0], slave)


if __name__ == "__main__":
    unittest.main()
