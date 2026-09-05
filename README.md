# DevAgent

DevAgent é um agente de desenvolvimento em Python com planejamento, validação de mudanças, execução segura, transações, testes, aprovação e recuperação por ciclos de reparo.

## Status

Versão atual: **0.4.4**

A versão `v0.4.4` está publicada com a suíte completa de testes passando e cobertura de produção em 100%. A série `v0.4.x` também concluiu a decomposição estrutural do Gateway, com fluxos de reparo e transação extraídos para componentes especializados e as operações seguras de filesystem centralizadas em `SecureFileSystem`.

## Principais componentes

- Planejamento de tarefas.
- Validação estrutural de planos.
- Política de segurança para caminhos e conteúdo.
- Execução segura de criação, modificação e remoção de arquivos.
- Transações com recuperação e rollback.
- Persistência de estado.
- Sistema de aprovação de tarefas.
- Execução e verificação de testes.
- Ciclo de reparo automático com limite de tentativas.
- Integração com Git para commits controlados.
- API HTTP local.
- CLI interativa.
- Adaptadores de IA, incluindo Mock e Groq.

## Requisitos

- Python **3.14+**
- `requests`

Para desenvolvimento:

- `pytest`
- `pytest-cov`

## Instalação

Clone o repositório e instale o pacote:

```bash
git clone https://github.com/Onirico-Dev/devagent.git
cd devagent
python -m pip install .
```

Para instalar as dependências de desenvolvimento:

```bash
python -m pip install ".[dev]"
```

## Uso

Após a instalação, o comando `devagent` inicia a interface de linha de comando:

```bash
devagent
```

Também é possível executar a CLI diretamente a partir do código-fonte:

```bash
python -m core
```

A API local pode ser iniciada com:

```bash
python api.py
```

O endpoint da API é disponibilizado localmente em:

```text
http://127.0.0.1:8765
```

## Testes

Execute toda a suíte:

```bash
pytest -q
```

Para verificar a cobertura da produção:

```bash
pytest -q --cov=core --cov=api --cov=agent --cov-report=term-missing
```

## Segurança

O DevAgent aplica validações para impedir operações fora da raiz do projeto, caminhos absolutos não autorizados, traversal de diretórios e condições de corrida envolvendo arquivos e links simbólicos.

As alterações são executadas dentro de transações e a confirmação definitiva depende da verificação dos testes e do commit controlado.

## Desenvolvimento

O projeto utiliza `pyproject.toml` como configuração de empacotamento.

Dependências de runtime:

```text
requests>=2.34,<3
```

Dependências de desenvolvimento:

```text
pytest>=9,<10
pytest-cov>=7,<8
```

## Licença

Este projeto é distribuído sob a licença MIT. Consulte o arquivo `LICENSE` para os termos completos.
