"""Desabilitacao isolada de um drive -- pergunta o ID no terminal.

Use para validar a comunicacao com um drive por vez.
"""

import time

from jog_gui.str6 import (
    MALHA_ABERTA,
    REG_CORRENTE_PICO,
    REG_ID,
    REG_MALHA,
    Drive,
    DriveNaoConfirmou,
    conectar,
)


def testar_desarme_individual():
    """Desabilita um unico drive, escolhido pelo ID digitado no terminal.

    E o teste mais barato de comunicacao: pergunta o ID, le o reg 31 (o drive
    devolve o proprio endereco), desabilita o motor (6 = 0), forca malha
    aberta e corrente baixa (em RAM, sem salvar), e pede que se confira o eixo
    com a mao. Se o drive nao confirmar, o problema esta no ID (DIP S1~S5), no
    baudrate (SW6/SW7), na terminacao (SW8) ou na fiacao RS-485 -- nao no
    roteiro.
    """
    print("=== TESTE DE DESABILITACAO ISOLADA ===")

    client = conectar(descricao=__doc__)
    if client is None:
        return

    try:
        drive_id = int(input("Digite o ID do drive conectado (1 a 31): "))
    except ValueError:
        print("Erro: Digite um numero valido.")
        client.close()
        return

    try:
        drive = Drive(client, drive_id)
        print(f"\nDrive informa ID {drive.ler(REG_ID)[0]} no reg 31.")
        print(f"Desabilitando o Drive ID {drive_id}...")

        drive.parar()
        drive.desarmar()
        time.sleep(0.2)

        # Malha aberta e corrente baixa (200 mA) para que o drive nao alarme
        # por falta de encoder nem esquente o motor. Nao salva: vale ate
        # religar.
        drive.escrever(REG_MALHA, MALHA_ABERTA)
        drive.escrever(REG_CORRENTE_PICO, 200)

        print(f"Sucesso! O Drive ID {drive_id} confirmou todos os comandos.")
        print(">> Va ate o motor e tente girar o eixo com a mao. Ele deve "
              "estar LIVRE (reg 7 = 0, padrao de fabrica).")

    except DriveNaoConfirmou as e:
        print(f"\n*** FALHA NA COMUNICACAO: {e}")
        print("O drive nao respondeu ou rejeitou o comando. Verifique o ID, "
              "a fiacao RS-485, o baudrate e a terminacao.")
    except Exception as e:
        print(f"Erro de comunicacao Modbus com o Drive {drive_id}: {e}")
    finally:
        client.close()


if __name__ == "__main__":
    testar_desarme_individual()
