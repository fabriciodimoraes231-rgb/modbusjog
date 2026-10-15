"""Mapa de registradores do STR6-RS485 -- fonte unica para a GUI e os scripts.

Referencia: Manual-DRIVER-STR6-RS485.pdf (Kalatec, rev. 1.0), secao
"Definicao de Endereco de Registro MODBUS", p. 13-17. O manual numera os
enderecos em DECIMAL, e aqui eles ficam em decimal tambem: conferir um numero
contra a tabela do manual nao pode exigir conversao de cabeca.

Nenhum endereco deve aparecer como literal fora daqui. Duplicar um endereco em
dois lugares e o caminho mais curto para as duas copias divergirem.

Valores de 32 bits ocupam dois registradores consecutivos com a palavra BAIXA
no endereco menor (exemplo de FC16 do manual, p. 19: 14464 em 68 e 1 em 69 dao
80000 pulsos) -- ver protocolo.palavras_32.
"""

# --- Corrente, subdivisao e standby (p. 13) ------------------------------------

# Na bancada o 0 NAO aceita escrita por RS-485: ecoa o FC06 e mantem o valor.
# Ele muda quando se escreve o 26 -- a GUI ajusta a corrente pelo 26 e trata o
# 0 como leitura do resultado. A relacao entre os dois nao esta no manual.
REG_CORRENTE_PICO = 0        # mA, 50~7800 (fabrica 3000)
REG_PULSOS_VOLTA = 1         # subdivisao: pulsos por volta, 200~51200 (fabrica 6000)
REG_STANDBY_TEMPO = 2        # ms ate o drive entrar em standby, 100~10000 (fabrica 300)
REG_STANDBY_PCT = 3          # % da corrente em standby, 0~100 (fabrica 50)
REG_CHAVE_ROTATIVA = 4       # R: codigo da chave rotativa (dial)
REG_FUNCAO_SAIDA1 = 5        # 0 alarme, 1 em posicao, 2 freio (fabrica 0)

# PONTO EM ABERTO: o manual chama o 6 de "Nivel de Habilitacao (Enable)",
# 0~1, fabrica 1, sem descrever os valores. Nao ha terminal ENA no conector de
# controle (p. 8), entao este codigo o trata como o enable por software:
# 1 = motor habilitado, 0 = desabilitado. Confirmar em bancada antes de
# confiar no MOTOR OFF como liberacao do eixo.
REG_ENABLE = 6
REG_ACAO_DESABILITADO = 7    # 0 = motor livre, 1 = eixo travado (fabrica 0)
REG_FILTRO_HAB = 9           # filtro de comando: 0 desliga, 1 liga (fabrica 1)
REG_FILTRO_TEMPO = 10        # us, 50~25600 (fabrica 4000)

# --- Malha de corrente (p. 13) -------------------------------------------------

REG_AUTOAJUSTE = 13          # autoajuste da malha de corrente: 0/1 (fabrica 1)
# Com o autoajuste ligado, Kp e Ki sao somente leitura (manual p. 13).
REG_KP = 15                  # 10~32767 (fabrica 1000)
REG_KI = 16                  # 0~32767 (fabrica 200)

# --- Comunicacao e monitoracao (p. 13-14) --------------------------------------

REG_BAUD = 18                # 96 = 9600 (unico valor exemplificado no manual)
REG_CORRENTE_EFETIVA = 22    # R: mA, 1~4200
REG_MALHA = 24               # 1 = malha aberta, 2 = malha fechada (fabrica 2)
REG_CORRENTE_OPER_PCT = 26   # % da corrente operacional, 0~100; muda o 0 (bancada)
REG_ID = 31                  # R: endereco do equipamento
# Contador de pulsos: e a posicao usada por este programa. O manual o chama
# de "pulsos externos recebidos", mas a secao de retorno a zero (p. 18) manda
# zera-lo depois do homing para o modo de posicao absoluta -- o que so faz
# sentido se ele contar tambem o movimento interno. PONTO EM ABERTO: confirmar
# em bancada comparando com o encoder (41/42).
REG_PULSOS_L = 39            # R: palavra baixa
REG_PULSOS_H = 40            # R/W: palavra alta; escrever 1 ZERA o contador
REG_ENCODER_L = 41           # R: realimentacao do encoder, palavra baixa
REG_ENCODER_H = 42           # R/W: palavra alta; escrever 1 zera a contagem
REG_TENSAO = 48              # R: tensao do barramento, unidade 0,1 V
REG_DIRECAO = 51             # 0 = sentido inalterado, 1 = invertido (fabrica 1)
REG_DETECCAO_FALHA = 56      # selecao de deteccao de falha (fabrica 327)
REG_LIMPA_FALHA_ENABLE = 57  # 1 = o sinal de enable tambem limpa a falha

# --- Movimento (p. 14-15) ------------------------------------------------------
# 62~69 sao consecutivos de proposito: o perfil inteiro (desaceleracao,
# velocidade, aceleracao e curso) vai num unico FC16, sem que o drive possa
# disparar com metade dos valores novos.

REG_VEL_HOME = 60            # pulsos/s, velocidade da etapa final do retorno a zero
REG_DESACEL_L = 62           # pulsos/s^2, 32 bits (fabrica 9 * 65536 + 10176)
REG_DESACEL_H = 63
REG_VEL_L = 64               # pulsos/s, 32 bits (fabrica 6000)
REG_VEL_H = 65
REG_ACEL_L = 66              # pulsos/s^2, 32 bits (fabrica 9 * 65536 + 10176)
REG_ACEL_H = 67
REG_CURSO_L = 68             # pulsos, 32 bits sem sinal (fabrica 6000)
REG_CURSO_H = 69
REG_COMANDO = 70             # ver CMD_*; volta sozinho para 6 depois de aceito
REG_HOME = 71                # ver HOME_*
REG_MODO_POSICAO = 72        # 0 = incremental, 1 = absoluto (fabrica 0)
REG_CONTROLE = 73            # ver CTRL_*
REG_FILTRO_LIMITE = 74       # filtro das entradas de limite, unidade 50 us (fabrica 10)
REG_STATUS = 75              # R: ver ST_*

# --- Persistencia e falhas (p. 16) ---------------------------------------------

# PONTO EM ABERTO: o manual diz que a leitura do 90 devolve 0 (incompleto) ou
# 1 (concluido), mas nao se o 1 volta a 0 depois. Se nao voltar, um 1 lido
# logo apos o pedido pode ser o do salvamento ANTERIOR -- ver
# Drive.salvar_parametros e o teste de religamento (Drive.aguardar_religamento).
REG_SALVAR = 90              # escrever 1 grava; a leitura devolve 1 ao concluir
REG_FABRICA = 91             # escrever 1 restaura o padrao; a leitura devolve 1 ao concluir
REG_LIMPA_FALHA = 93         # escrever 1 limpa a falha; volta sozinho para 0
REG_ROTOR_TRAVADO = 104      # limiar do alarme de rotor travado (fabrica 650)
REG_AMOSTRA_FASE_A = 106     # R
REG_AMOSTRA_FASE_B = 107     # R
REG_ALARME = 115             # R: ver ALARMES
REG_FLANGE = 135             # ver FLANGES
REG_FUNCAO_SAIDA2 = 147      # 0 alarme, 1 em posicao, 2 freio (fabrica 2)

# --- Comando de movimento (70) -------------------------------------------------

CMD_DESACELERAR = 0          # desacelera ate parar
CMD_FRENTE = 1               # comprimento fixo para a frente (curso em 68/69)
CMD_TRAS = 2                 # comprimento fixo para tras
CMD_CONTINUO_FRENTE = 3
CMD_CONTINUO_TRAS = 4
CMD_PARADA_IMEDIATA = 5
CMD_OCIOSO = 6               # valor que o registrador assume depois de aceitar

# --- Retorno a zero (71, p. 18) ------------------------------------------------

HOME_SAIR = 0                # sai do retorno a zero e desacelera
HOME_LIMITE_POS = 1          # vai para a frente ate o limite positivo (IN2)
HOME_LIMITE_NEG = 2          # vai para tras ate o limite negativo (IN1)

# --- Registrador de controle (73, p. 17) ---------------------------------------
# Bit em 1 (fabrica): o limite ocorre com o optoacoplador CONDUZINDO.
# Bit em 0: o limite ocorre com o optoacoplador desligado.
# PONTO EM ABERTO: a tabela de bits cita IN3 como limite negativo, enquanto a
# tabela do conector (p. 8) diz IN1 = limite negativo e IN2 = limite positivo,
# IN3 reservado. Este codigo segue a tabela do conector.

CTRL_NIVEL_LIM_POS = 0x0001  # bit 0
CTRL_NIVEL_LIM_NEG = 0x0002  # bit 1
CTRL_MOVIMENTO_IO = 0x0040   # bit 6: permite disparar movimento pela entrada

# --- Registrador de status (75, p. 17) -----------------------------------------

ST_SOBRECORRENTE = 0x0001    # bit 0
ST_SOBRETENSAO = 0x0002      # bit 1
ST_LIMITE_POS = 0x0010       # bit 4: sinal de limite positivo presente
ST_LIMITE_NEG = 0x0020       # bit 5: sinal de limite negativo presente
# bit 7: 0 = envio de pulsos interno concluido, 1 = nao concluido. A mesma
# tabela da 1 como "valor padrao" deste bit -- PONTO EM ABERTO, e por isso o
# fim de um movimento nunca e decidido so por ele (ver EixoMovimento).
ST_EM_MOVIMENTO = 0x0080
ST_FALHA = ST_SOBRECORRENTE | ST_SOBRETENSAO

# --- Valores de malha (24) -----------------------------------------------------

MALHA_ABERTA = 1
MALHA_FECHADA = 2
MALHAS = {MALHA_ABERTA: "malha aberta", MALHA_FECHADA: "malha fechada"}

# --- Codigos de alarme (115, p. 16) --------------------------------------------
# O 0 nao esta na tabela do manual; e tratado como "sem alarme".

ALARMES = {
    0: "sem alarme",
    1: "sobrecorrente",
    2: "sobretensao",
    3: "subtensao",
    4: "perda de fase",
    6: "rotor travado em malha aberta",
    7: "rotor travado em malha fechada",
    9: "falha do drive",
}

# --- Flange do motor (135, p. 16) ----------------------------------------------

FLANGES = {200: "28", 400: "42", 500: "57", 600: "60", 800: "86"}

# --- Faixas aceitas (p. 13) ----------------------------------------------------

CORRENTE_MIN_MA = 50
CORRENTE_MAX_MA = 7800
PULSOS_VOLTA_MIN = 200
PULSOS_VOLTA_MAX = 51200
PULSOS_VOLTA_FABRICA = 6000
STANDBY_TEMPO_MIN = 100
STANDBY_TEMPO_MAX = 10000
FILTRO_LIMITE_US = 50        # unidade do registrador 74

# --- Configuracao gravada na memoria do drive ----------------------------------
# O que o card CONFIGURACAO DO DRIVE escreve e o que tem de sobreviver a um
# religamento. 0~3 sao vizinhos e vem num quadro so (Drive.ler_configuracao).
# O 0 fica na lista mesmo sem ser escrito: e o efeito do 26 que se quer ver
# sobreviver ao religamento.

REGS_CONFIGURACAO = (REG_CORRENTE_PICO, REG_PULSOS_VOLTA, REG_STANDBY_TEMPO,
                     REG_STANDBY_PCT, REG_AUTOAJUSTE, REG_KP, REG_KI, REG_MALHA,
                     REG_CORRENTE_OPER_PCT)


def nome_alarme(codigo):
    """Texto do codigo de alarme (115); descreve ate o codigo desconhecido."""
    return ALARMES.get(codigo, "alarme desconhecido (cod. {})".format(codigo))


def nomes_status(status):
    """Os bits ligados do status (75), por extenso, na ordem da tabela."""
    nomes = []
    if status & ST_EM_MOVIMENTO:
        nomes.append("em movimento")
    if status & ST_LIMITE_NEG:
        nomes.append("limite -")
    if status & ST_LIMITE_POS:
        nomes.append("limite +")
    if status & ST_SOBRETENSAO:
        nomes.append("SOBRETENSAO")
    if status & ST_SOBRECORRENTE:
        nomes.append("SOBRECORRENTE")
    return nomes


# Nomes curtos para o inspetor de registrador e para o log.
CONHECIDOS = {
    REG_CORRENTE_PICO: "corrente de pico (mA)",
    REG_PULSOS_VOLTA: "pulsos por volta",
    REG_STANDBY_TEMPO: "tempo de standby (ms)",
    REG_STANDBY_PCT: "corrente de standby (%)",
    REG_CHAVE_ROTATIVA: "chave rotativa",
    REG_FUNCAO_SAIDA1: "funcao da saida 1",
    REG_ENABLE: "enable",
    REG_ACAO_DESABILITADO: "acao com o motor desabilitado",
    REG_FILTRO_HAB: "filtro de comando ligado",
    REG_FILTRO_TEMPO: "tempo do filtro de comando (us)",
    REG_AUTOAJUSTE: "autoajuste da malha de corrente",
    REG_KP: "Kp da malha de corrente",
    REG_KI: "Ki da malha de corrente",
    REG_BAUD: "baud rate",
    REG_CORRENTE_EFETIVA: "corrente efetiva (mA)",
    REG_MALHA: "malha aberta/fechada",
    REG_CORRENTE_OPER_PCT: "corrente operacional (%)",
    REG_ID: "endereco do equipamento",
    REG_PULSOS_L: "contador de pulsos (baixa)",
    REG_PULSOS_H: "contador de pulsos (alta)",
    REG_ENCODER_L: "encoder (baixa)",
    REG_ENCODER_H: "encoder (alta)",
    REG_TENSAO: "tensao do barramento (0,1 V)",
    REG_DIRECAO: "direcao invertida",
    REG_DETECCAO_FALHA: "deteccao de falha",
    REG_LIMPA_FALHA_ENABLE: "limpa falha pelo enable",
    REG_VEL_HOME: "velocidade de retorno a zero (p/s)",
    REG_DESACEL_L: "desaceleracao (baixa)",
    REG_DESACEL_H: "desaceleracao (alta)",
    REG_VEL_L: "velocidade (baixa)",
    REG_VEL_H: "velocidade (alta)",
    REG_ACEL_L: "aceleracao (baixa)",
    REG_ACEL_H: "aceleracao (alta)",
    REG_CURSO_L: "curso (baixa)",
    REG_CURSO_H: "curso (alta)",
    REG_COMANDO: "comando de movimento",
    REG_HOME: "comando de retorno a zero",
    REG_MODO_POSICAO: "modo incremental/absoluto",
    REG_CONTROLE: "registrador de controle",
    REG_FILTRO_LIMITE: "filtro dos limites (x50 us)",
    REG_STATUS: "registrador de status",
    REG_SALVAR: "salvar parametros",
    REG_FABRICA: "restaurar padrao de fabrica",
    REG_LIMPA_FALHA: "limpar falha",
    REG_ROTOR_TRAVADO: "limiar de rotor travado",
    REG_AMOSTRA_FASE_A: "amostra da fase A",
    REG_AMOSTRA_FASE_B: "amostra da fase B",
    REG_ALARME: "codigo de alarme",
    REG_FLANGE: "flange do motor",
    REG_FUNCAO_SAIDA2: "funcao da saida 2",
}
