"""Ciclo completo de pick and place com os tres drives."""

import time

from jog_gui.str6 import (
    ID_NEMA1_SOCKET,
    ID_NEMA2_CABEC,
    ID_SPIN_MOTOR,
    PULSOS_VOLTA,
    Drive,
    DriveNaoConfirmou,
    conectar,
    desarmar_todos,
)


def graus_para_pulsos(graus):
    """Graus de eixo -> pulsos, pelos pulsos por volta de str6/config.py.

    PULSOS_VOLTA tem de casar com o registrador 1 de cada drive: trocar a
    subdivisao no drive muda o significado de todos os numeros deste ciclo.
    """
    return int(round(graus * PULSOS_VOLTA / 360.0))


def rpm_para_pps(rpm):
    """rpm -> pulsos/s, que e a unidade de velocidade do STR6 (64/65)."""
    return max(1, int(round(rpm * PULSOS_VOLTA / 60.0)))


def executar_movimento_seguro(client, slave_id, graus, vel_rpm=60, tempo_espera=2.0):
    """
    Sequencia rigorosa:
    1. Habilita (6 = 1)
    2. Dispara o movimento de comprimento fixo (perfil em 62~69 num FC16 so,
       e 70 = 1 frente / 2 tras)
    3. Aguarda o termino fisico
    4. Desabilita (6 = 0) -- no finally, para que uma falha ou um Ctrl+C
       durante a espera nunca deixe o motor energizado e esquentando.

    Levanta DriveNaoConfirmou se alguma escrita nao for confirmada: abortar o
    ciclo e mais seguro do que seguir para o proximo passo as cegas.
    """
    drive = Drive(client, slave_id)
    pulsos = graus_para_pulsos(graus)
    try:
        print(f"\n--- [Drive {slave_id}] Iniciando movimento ({graus} graus = "
              f"{pulsos} pulsos) ---")

        print(f"[Drive {slave_id}] Habilitando o motor...")
        drive.armar()
        time.sleep(0.2)  # pausa para estabilizar o campo antes de mover

        print(f"[Drive {slave_id}] Disparando deslocamento...")
        drive.mover_relativo(pulsos, rpm_para_pps(vel_rpm))

        # Aguarda o eixo completar o movimento fisico na bancada
        time.sleep(tempo_espera)

        print(f"[Drive {slave_id}] Movimento concluido.")

    finally:
        # Desabilita em qualquer saida: sucesso, erro Modbus ou
        # KeyboardInterrupt durante a espera.
        try:
            drive.desarmar()
            print(f"[Drive {slave_id}] Desabilitado.")
            time.sleep(0.1)
        except Exception as e:
            print(f"*** ATENCAO: Drive {slave_id} NAO confirmou a desabilitacao "
                  f"({e}). Verifique o motor manualmente!")


def executar_ciclo_pick_and_place():
    """Executa o ciclo completo: abre o soquete, pega, orienta e encaixa o chip.

    Encadeia `executar_movimento_seguro` nos tres drives, em passos com espera
    fixa entre eles (esta bancada move um eixo por vez). Cada movimento desarma
    o seu drive ao terminar, e o `finally` final desabilita todos, inclusive
    se o ciclo abortar entre dois passos.
    """
    client = conectar(descricao=__doc__)
    if client is None:
        return

    print("=== INICIANDO CICLO DE PICK AND PLACE ===")

    try:
        # Passo 0: seguranca inicial de barramento
        print("Inicializando: desabilitando todos os drives...")
        # `desarmar_todos` devolve a lista dos que NAO confirmaram. O caso com
        # falha nao pode passar em silencio: e justamente o desfecho em que o
        # ciclo esta prestes a movimentar um conjunto que ninguem garantiu.
        falhas = desarmar_todos(client)
        if falhas:
            print(f"\n*** Drives sem desabilitacao confirmada: {falhas}")
            print("*** NAO considere o conjunto seguro. Verifique a fiacao, "
                  "os IDs e a alimentacao antes de deixar o ciclo seguir.")
        else:
            print("Todos os motores desabilitados com sucesso.\n")
        time.sleep(0.5)

        # Passo 1: NEMA 17 1 (Drive 1) desce 90 graus para abrir o soquete
        print("[Passo 1] Abrindo o soquete (Drive 1)...")
        executar_movimento_seguro(client, ID_NEMA1_SOCKET, graus=-90, vel_rpm=60, tempo_espera=1.5)
        time.sleep(0.5)

        # Passo 2: NEMA 17 2 (Drive 2) desce o cabecote, espera e sobe
        print("\n[Passo 2A] Descendo o cabecote (Drive 2)...")
        executar_movimento_seguro(client, ID_NEMA2_CABEC, graus=90, vel_rpm=60, tempo_espera=1.5)

        time.sleep(1.0)  # tempo de espera no nivel inferior do pick and place

        print("\n[Passo 2B] Subindo o cabecote (Drive 2)...")
        executar_movimento_seguro(client, ID_NEMA2_CABEC, graus=-90, vel_rpm=60, tempo_espera=1.5)
        time.sleep(0.5)

        # Passo 3: Motor Spin (Drive 3) executa o giro de orientacao do chip
        print("\n[Passo 3] Girando o Motor Spin para orientar o chip (Drive 3)...")
        executar_movimento_seguro(client, ID_SPIN_MOTOR, graus=360, vel_rpm=40, tempo_espera=2.0)
        time.sleep(0.5)

        # Passo 4: NEMA 17 2 (Drive 2) desce novamente com o chip, espera e sobe
        print("\n[Passo 4A] Descendo com o chip posicionado (Drive 2)...")
        executar_movimento_seguro(client, ID_NEMA2_CABEC, graus=90, vel_rpm=60, tempo_espera=1.5)

        time.sleep(1.0)  # tempo de espera para o encaixe da peca

        print("\n[Passo 4B] Subindo o cabecote apos o encaixe (Drive 2)...")
        executar_movimento_seguro(client, ID_NEMA2_CABEC, graus=-90, vel_rpm=60, tempo_espera=1.5)
        time.sleep(0.5)

        # Passo 5: NEMA 17 1 (Drive 1) faz o retorno para fechar o soquete
        print("\n[Passo 5] Fechando o soquete (Drive 1)...")
        executar_movimento_seguro(client, ID_NEMA1_SOCKET, graus=90, vel_rpm=60, tempo_espera=1.5)

        print("\n=== CICLO DE PICK AND PLACE CONCLUIDO ===")

    except KeyboardInterrupt:
        print("\nInterrompido pelo usuario. Ciclo abortado.")
    except DriveNaoConfirmou as e:
        print(f"\n*** CICLO ABORTADO: {e}")
        print("O conjunto pode ter parado no meio do movimento. Verifique a bancada.")
    finally:
        # Rede de seguranca final: garante a desabilitacao de todos os drives
        # mesmo que o ciclo tenha abortado entre dois passos.
        print("\nDesabilitando todos os drives por seguranca...")
        falhas = desarmar_todos(client)
        if falhas:
            print(f"\n*** ATENCAO: drives sem desabilitacao confirmada: {falhas}")
            print("*** Pode haver motor energizado. Confira na bancada e, se "
                  "necessario, corte a energia.")
        client.close()


if __name__ == "__main__":
    executar_ciclo_pick_and_place()
