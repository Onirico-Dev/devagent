# DevAgent

Agente de desenvolvimento em Python para planejar tarefas, propor alterações em arquivos, executar mudanças sob aprovação humana, testar resultados e gerenciar transações com mecanismos de recuperação.

## 1. Estado da versão

- **Versão do pacote:** `0.6.8`
- **Python mínimo:** `3.14`
- **Marco de validação:** `devagent-v0.6.8-validation-20261029`
- **Commit validado:** `0646a0d9ee24dd3c4cf04a81b7c116ebd5236b03`

Na validação de 29 de outubro de 2026, a suíte registrou 2.190 testes aprovados e 100% de cobertura de linhas. Também foram validados os fluxos essenciais de criação, aprovação, rejeição e persistência de tarefas pela CLI e pela API.

Esses resultados representam o estado validado naquele momento. Não garantem ausência de defeitos em todos os cenários nem certificação de segurança para produção.

## 2. Funcionalidades

- Planejamento e validação estrutural de tarefas.
- Criação, modificação e remoção controlada de arquivos.
- Aprovação e rejeição explícitas.
- Execução de testes após alterações.
- Transações, rollback e recuperação.
- Ciclos de reparo com limite de tentativas.
- Integração com Git para commits controlados.
- Histórico persistente de tarefas.
- Observações e propostas de execução supervisionada.
- Interface de linha de comando (CLI).
- API HTTP local.
- Adaptadores de IA, incluindo Mock e Groq.

## 3. Requisitos

- Python 3.14 ou superior.
- `requests`, como dependência de execução.
- Git para fluxos que utilizam repositórios e commits.
- `pytest` e `pytest-cov` para executar a suíte de testes.

O adaptador Mock destina-se principalmente a testes e desenvolvimento. Não deve ser confundido com um modelo de IA capaz de interpretar instruções arbitrárias com a mesma flexibilidade.

## 4. Instalação

Clone o repositório e entre no diretório:

```bash
git clone https://github.com/Onirico-Dev/devagent.git
cd devagent
```

Instale o pacote:

```bash
python -m pip install .
```

Para instalar as dependências de desenvolvimento:

```bash
python -m pip install ".[dev]"
```

Verifique a instalação:

```bash
devagent --version
devagent --help
python -m core --version
python -m core --help
```

A versão esperada para este marco é `0.6.8`.

## 5. Primeiro uso

Execute o DevAgent a partir do diretório do projeto que deseja administrar.

A CLI e a API inicializam o agente e o gateway com a raiz `"."`. O diretório de trabalho influencia, portanto, os arquivos que podem ser alterados e os locais usados para persistir estado.

Inicie a CLI:

```bash
cd /caminho/do/projeto
devagent
```

Alternativamente:

```bash
python -m core
```

Os comandos seguintes devem ser digitados no prompt `DevAgent >`.

### 5.1. Criar um plano

```text
plan Crie exemplo.py contendo print("Olá, mundo")
```

O DevAgent apresenta a tarefa e as alterações planejadas. Criar um plano não significa que a alteração já foi executada.

### 5.2. Consultar tarefas

```text
tasks
latest
status 1
```

- `tasks`: lista tarefas registradas.
- `latest`: consulta a tarefa mais recente.
- `status 1`: consulta a tarefa pelo identificador.

Substitua `1` pelo identificador real.

### 5.3. Aprovar uma tarefa

```text
approve 1
```

A aprovação inicia o fluxo supervisionado de execução. O DevAgent apresenta o resultado, o estado da tarefa, informações da transação, resultados dos testes e tentativas de reparo, quando disponíveis.

Revise o plano e os caminhos afetados antes de autorizar alterações.

### 5.4. Rejeitar uma tarefa

```text
reject 1
```

A rejeição registra a tarefa como rejeitada. No fluxo validado, a tarefa rejeitada não cria o arquivo planejado.

### 5.5. Registrar uma observação

```text
observe Investigar a cobertura de testes do módulo X
```

As observações apoiam o fluxo de trabalho. Uma observação não equivale a uma alteração executada.

### 5.6. Encerrar a CLI

```text
sair
```

Também são reconhecidos `exit` e `quit`.

## 6. Execução supervisionada e autonomia

Executar uma rodada:

```text
autonomy
```

Executar três iterações:

```text
autonomy 3
```

Executar o modo contínuo com intervalo de cinco segundos e limite de três iterações:

```text
autonomy continuous 5 3
```

O intervalo padrão do modo contínuo é de um segundo quando não informado. O loop pode ser interrompido com `Ctrl+C`.

Comece com uma única rodada e revise as propostas. Não use execução contínua sem compreender os efeitos do fluxo configurado e sem monitorar o estado do projeto.

A geração de propostas, a aprovação e a execução de alterações são etapas distintas. Não presuma que uma proposta tenha sido executada só porque foi gerada.

## 7. API HTTP local

Inicie a API na raiz do projeto:

```bash
python api.py
```

O serviço usa o endereço local:

```text
http://127.0.0.1:8765
```

### 7.1. Consultar a saúde

```bash
curl -i http://127.0.0.1:8765/health
```

### 7.2. Listar tarefas

```bash
curl -i http://127.0.0.1:8765/tasks
```

### 7.3. Consultar a tarefa mais recente

```bash
curl -i http://127.0.0.1:8765/tasks/latest
```

### 7.4. Consultar uma tarefa pelo identificador

```bash
curl -i http://127.0.0.1:8765/tasks/1
```

Substitua `1` pelo identificador real. Uma tarefa inexistente retorna HTTP 404.

### 7.5. Criar um plano

A rota `POST /plan` recebe um objeto JSON com o campo obrigatório `instruction`:

```bash
curl -i -X POST \
  http://127.0.0.1:8765/plan \
  -H 'Content-Type: application/json' \
  -d '{"instruction":"Crie api_exemplo.py contendo print(\"API_OK\")"}'
```

A resposta contém os dados da tarefa e o identificador de aprovação retornado pelo serviço.

### 7.6. Aprovar uma tarefa

Use o identificador de aprovação retornado pela criação do plano:

```bash
curl -i -X POST \
  http://127.0.0.1:8765/approve/1
```

### 7.7. Rejeitar uma tarefa

```bash
curl -i -X POST \
  http://127.0.0.1:8765/reject/1
```

Substitua `1` pelo identificador de aprovação real. Não presuma que ele seja intercambiável com um identificador interno de transação.

A API retorna HTTP 400 para erros de validação da requisição de planejamento e HTTP 404 para rotas inexistentes ou tarefas não encontradas nas rotas GET correspondentes. Exceções tratadas pelo manipulador geral são encaminhadas ao caminho de erro da API.

Antes de integrar um cliente externo, consulte os testes e o código para verificar os formatos exatos das respostas e os códigos de erro de cada operação.

**Segurança:** não exponha a API diretamente à Internet sem autenticação, autorização, controles de acesso e proteção de transporte apropriados. O endereço local, por si só, não constitui autenticação.

## 8. Persistência e diretório de trabalho

O estado é distribuído entre componentes. Entre os locais relevantes estão:

- `logs/session.json`: sessão persistente do agente.
- `transactions/`: estado relacionado a transações e histórico operacional.
- Outros arquivos de estado usados pelos componentes de observação e execução supervisionada.

Os caminhos efetivos dependem da raiz fornecida a cada componente e da configuração de execução.

Antes de iniciar o DevAgent em outro projeto, confirme o diretório atual:

```bash
pwd
```

Antes de aprovar alterações, verifique o estado do Git:

```bash
git status --short
```

Não remova manualmente diretórios de transação, histórico, backups ou estado durante uma execução ou recuperação. Isso pode comprometer o diagnóstico e a recuperação de falhas.

## 9. Testes e cobertura

Instale as dependências de desenvolvimento:

```bash
python -m pip install ".[dev]"
```

Execute os testes do frontend (Node.js 24 ou compatível):

```bash
bash scripts/test_frontend.sh
```

Essa validação verifica a sintaxe JavaScript e executa os testes automatizados
da interface DevAgent Studio. Ela é independente da suíte Python.


Execute toda a suíte:

```bash
python -m pytest -q
```

O `pyproject.toml` configura cobertura mínima de 100% de linhas. Para executar a cobertura explicitamente:

```bash
python -m pytest -q \
  --cov=core \
  --cov=api \
  --cov=agent \
  --cov-report=term-missing
```

A cobertura de linhas não demonstra, isoladamente, que todas as ramificações, sequências de eventos, condições de corrida ou cenários de recuperação estejam corretos.

Após modificar o código, execute a suíte e examine os resultados antes de criar um novo marco de validação.

## 10. Segurança e recuperação

O DevAgent contém mecanismos de validação de caminhos, execução controlada, transações, testes e reparo. Esses mecanismos reduzem determinados riscos, mas não eliminam a possibilidade de erros.

Práticas recomendadas:

1. Trabalhe em um repositório Git e mantenha alterações importantes registradas.
2. Revise o plano antes de aprovar.
3. Evite executar tarefas em diretórios com dados importantes sem backup.
4. Inspecione os resultados dos testes e o estado final do Git.
5. Preserve logs e dados de transação quando ocorrer uma falha.
6. Consulte o estado da tarefa antes de repetir operações de aprovação ou recuperação.
7. Não presuma que todos os efeitos foram revertidos apenas porque uma tarefa apresenta status de falha.

Em caso de falha, consulte a tarefa, os logs, os arquivos afetados e o estado do repositório antes de tentar novamente.

## 11. Desenvolvimento

A configuração de empacotamento e dependências está em `pyproject.toml`.

Dependência de execução:

```text
requests>=2.34,<3
```

Dependências de desenvolvimento:

```text
pytest>=9,<10
pytest-cov>=7,<8
```

O entry point da CLI é:

```text
devagent = core.__main__:main
```

Para consultar o histórico e o estado do repositório:

```bash
git log -5 --oneline
git status --short
```

O marco de validação de 29 de outubro de 2026 é identificado pela tag:

```text
devagent-v0.6.8-validation-20261029
```

Essa tag identifica uma referência de validação do código. Não garante que o pacote tenha sido publicado em um registro público.

## 12. Licença

O projeto é distribuído sob a licença MIT. Consulte o arquivo `LICENSE` para os termos completos.
