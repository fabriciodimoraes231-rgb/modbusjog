"""Zona de ajuste -- e aqui que se mexe.

Um lugar so para baudrate, IDs, correntes e tempos, para que a GUI e os
scripts de bancada nunca divirjam.
"""

from .registradores import MALHA_ABERTA, PULSOS_VOLTA_FABRICA

# Tem de casar com os DIP SW6/SW7 de TODOS os drives do barramento (manual
# p. 12): on/on = 9600 (padrao), off/on = 19200, on/off = 38400,
# off/off = 115200. Formato fixo 8N1.
BAUDRATE = 9600

BAUDRATES_SUPORTADOS = (9600, 19200, 38400, 115200)

# Espera por resposta. Rotinas que gravam parametros usam esperas proprias.
TIMEOUT = 1.0

# Silencio entre quadros. Modbus RTU exige 3,5 caracteres entre transacoes
# (~4 ms a 9600 bps, ~0,4 ms a 115200). Com varios drives na mesma linha,
# encurtar isso faz um drive atropelar a resposta do outro. O Barramento o
# garante entre o fim de uma transacao e o inicio da proxima, venham elas da
# thread que vierem.
PAUSA_QUADRO = 0.01

# Silencio depois de uma transacao que falhou (sem resposta, CRC ou endereco
# errado). Uma resposta atrasada pode ainda estar chegando: mandar o proximo
# pedido em cima dela colide na linha e derruba mais um quadro.
PAUSA_APOS_FALHA = 0.05

# --- Drives do barramento -----------------------------------------------------
# O endereco vem dos DIP S1~S5 (1~31) e so vale apos religar (manual p. 11):
# ID = 1*S1 + 2*S2 + 4*S3 + 8*S4 + 16*S5, com on = 0 e off = 1.
# Atencao: S1~S5 todos em ON e o "reservado (padrao)", ID 0 = broadcast -- NAO
# e o endereco 1. Para o ID 1: S1 off, S2~S5 on. SW8 on liga o resistor de
# terminacao, obrigatorio no drive da ponta da rede.

ID_NEMA1_SOCKET = 1   # abre/fecha o soquete
ID_NEMA2_CABEC = 2    # desce/sobe o cabecote de pick and place
ID_SPIN_MOTOR = 3     # aspiracao (simulada) e giro/orientacao do chip

TODOS_OS_DRIVES = (ID_NEMA1_SOCKET, ID_NEMA2_CABEC, ID_SPIN_MOTOR)

# O manual aceita ID de 1 a 255 por software; o Modbus RTU reserva 248~255.
SLAVE_MIN = 1
SLAVE_MAX = 247
# A varredura cobre so a faixa dos DIP: a 9600 bps cada endereco mudo custa o
# timeout inteiro, e 247 enderecos levariam minutos.
VARREDURA_MAX = 31

# Corrente de pico por drive, em mA (registrador 0). Ponto de partida
# conservador para os NEMA17 da bancada -- nao medido com este drive.
# Confirmar aquecimento e torque de retencao antes de subir.
CORRENTES_MA = {
    ID_NEMA1_SOCKET: 1000,
    ID_NEMA2_CABEC: 1000,
    ID_SPIN_MOTOR: 200,
}

# Malha usada pelos scripts de configuracao. O fabrica do drive e malha
# fechada, que exige encoder ligado: sem ele o drive alarma (LED vermelho com
# 7 piscadas, manual p. 7). Confirmar se os motores da bancada tem encoder.
MALHA_PADRAO = MALHA_ABERTA

# Pulsos por volta assumidos pelos scripts para converter graus em pulsos.
# Tem de casar com o registrador 1 de cada drive.
PULSOS_VOLTA = PULSOS_VOLTA_FABRICA

# Teto de velocidade aceito pela interface e pela camada de movimento, em
# pulsos/s. Com 6000 pulsos/volta equivale a 400 rpm.
VEL_MAX_PPS = 40000

# Tempo de rampa padrao (aceleracao e desaceleracao) dos movimentos, em ms.
RAMPA_MS = 200

# Espera maxima pela conclusao de um "Salvar parametros" (registrador 90).
# O drive informa o fim pela leitura do proprio 90; o prazo so cobre o caso
# de ele nunca confirmar. Vale como numero de consultas (uma a cada 0,2 s),
# nao como relogio: espera na fila do barramento nao conta.
ESPERA_SALVAR = 10.0
