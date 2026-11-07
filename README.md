# modbusjog: comissionamento de drives de passo STR6-RS485

[![CI](https://github.com/fabriciodimoraes231-rgb/modbusjog/actions/workflows/ci.yml/badge.svg)](https://github.com/fabriciodimoraes231-rgb/modbusjog/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-blue)

Interface gráfica (Tkinter) para colocar em operação drives de passo de malha fechada **STR6-RS485** (Kalatec) por **Modbus RTU** em RS-485: JOG, configuração do drive, homing pelo sensor de origem e limites de curso do eixo, com vários eixos no mesmo barramento.

## Destaques

- **Lógica de movimento separada da interface** (`motion/`): a tela, os scripts de bancada e os testes usam a mesma camada. Toda operação devolve um `Resultado` com causa enumerada, nunca só `True`/`False`.
- **237 testes sem hardware**: sem drive, sem porta serial e sem display. O protocolo é testado com os quadros de exemplo do próprio manual, e o relógio é virtual.
- **Segurança de um eixo vertical com garra**: watchdog no JOG (duas leituras perdidas param o eixo), parada escalonada (desacelera → para → desabilita), PARADA GERAL em todos os eixos e limites de curso por software.
- **Barramento disciplinado**: uma requisição por vez, em fila; conferência de endereço e CRC em todo quadro; silêncio garantido entre quadros; resumo de falhas por drive no log.
- **Gravação verificada**: cada escrita é relida, e o *Testar gravação* religa o drive e compara registrador por registrador para provar que o valor ficou na memória.
- **Homing** por software (busca pelo sensor, com aproximação e rastejo) ou nativo do drive, e um teste que descobre a entrada e o nível do sensor sem energizar o motor.

## Estrutura

```
jog_gui/
├── __main__.py   # ponto de entrada: python -m jog_gui
├── str6/         # biblioteca do drive: registradores, protocolo (CRC, quadros), barramento, drive
├── motion/       # regra de movimento de um eixo, sem interface
├── ui/           # a interface: um mixin por card da tela
├── scripts/      # rotinas de bancada (pick and place, corrente, desabilitação)
└── tests/        # unittest, sem hardware
```

## Como rodar

```bash
pip install -r requirements.txt
python -m jog_gui                                    # abre a interface
python -m unittest discover -s jog_gui/tests -t .    # roda os testes
```

No Linux, instale também o Tkinter (`sudo apt install python3-tk`) e coloque o usuário no grupo `dialout` para acessar a porta serial.

## Documentação

A documentação técnica completa fica em [`jog_gui/README.md`](jog_gui/README.md): arquitetura de cada módulo, todos os cards da interface, endereçamento pelas chaves DIP, como o eixo é movimentado, configuração do drive, homing, limites de curso, o orçamento do barramento e os pontos do manual que ainda pedem confirmação em bancada.

> **Validação:** o software foi escrito a partir do manual do fabricante e testado contra um drive simulado. Antes de usá-lo num processo controlado, ele precisa de ensaio e revisão por uma pessoa qualificada. O manual do STR6 é da Kalatec e não é distribuído aqui.

## Licença

[Apache 2.0](LICENSE) © Manuel Moraes
