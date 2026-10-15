"""Controle de drives de passo STR6-RS485 por Modbus RTU sobre RS-485.

Subpacotes:

    str6/     protocolo, registradores, barramento e operacoes do drive
    motion/   a logica de movimento de um eixo, sem interface
    ui/       a interface grafica, um modulo por card da tela
    scripts/  rotinas de bancada, cada uma executavel com -m

O ponto de entrada da interface e __main__.py:

    python -m jog_gui
"""

__version__ = "0.4.0"
