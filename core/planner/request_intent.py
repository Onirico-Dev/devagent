"""Conservative routing for explicit read-only requests, not general NLP."""

import re


ACTION = re.compile(
    r"(?<![\w./])(?:criar|crie|create|adicionar|adicione|alterar|altere|"
    r"modificar|modifique|modify|editar|edite|corrigir|corrija|remover|remova|deletar|delete)(?![\w./])",
    re.IGNORECASE,
)
NEGATION = re.compile(r"\b(?:não|nao|nunca|jamais|sem|never|do\s+not|don't)\b", re.IGNORECASE)


def has_requested_changes(instruction):
    for clause in re.split(r"[\n;!?:]+|\.(?=\s|$)|,|\bmas\b|\bporém\b|\bbut\b|"
                           r"\be\s+(?=(?:crie|adicione|altere|modifique|edite|corrija|remova|delete)\b)", instruction.lower()):
        # These expressions request an action rather than forbid it.
        clause = re.sub(r"\bnão\s+(?:só|somente|apenas)\b|\bnão\s+deixe\s+de\b", "", clause)
        for match in ACTION.finditer(clause):
            if not NEGATION.search(clause[:match.start()]):
                return True
    return False


def is_read_only_request(instruction):
    analysis = re.search(r"\b(?:investigue|investigar|analise|analisar|análise|examine|examinar|"
                         r"explique|verifique|verificar|inspecione|diagnóstico)\b", instruction, re.IGNORECASE)
    explicit = re.search(r"somente\s+(?:de\s+)?leitura|apenas\s+leitura|sem\s+(?:alterações|escrita|modificar|alterar|editar)|"
                         r"read.only|(?:não|nao|nunca)\s+(?:modificar|modifique|alterar|altere|editar|edite|criar|crie)",
                         instruction, re.IGNORECASE)
    return bool(analysis and explicit and not has_requested_changes(instruction))
