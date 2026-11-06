"""Read-only explanations built from public task facts, without AI calls."""


STATUSES = {
    "pending", "approved", "executing", "testing", "committed", "rejected",
    "rolled_back", "failed", "running", "repairing", "unknown",
}


def diagnose_task(task):
    tests = task.get("tests")
    tests = tests if isinstance(tests, dict) else {}
    success = tests.get("success")
    success = success if type(success) is bool else None
    code = tests.get("returncode")
    code = code if type(code) is int and -65535 <= code <= 65535 else None
    attempts = task.get("repair_attempts")
    attempts = attempts if type(attempts) is int and 0 <= attempts <= 65535 else None
    status = task.get("status")
    status = status if isinstance(status, str) and status in STATUSES else "unknown"
    evidence = [
        "Sucesso dos testes: " + ({True: "Sim", False: "Não"}.get(success, "Não informado")),
        "Código de saída: " + (str(code) if code is not None else "Não informado"),
        "Tentativas de reparo: " + (str(attempts) if attempts is not None else "Não informado"),
    ]
    if task.get("rollback_error"):
        category = "rollback_failure"
        summary = "Há uma falha registrada durante a reversão. A restauração precisa ser verificada."
        steps = ["Confira o erro de rollback e o estado dos arquivos antes de aprovar outra alteração."]
    elif (success is True and code not in (None, 0)) or (
        status == "committed" and (success is False or code not in (None, 0))
    ):
        category = "inconsistent"
        summary = "O estado e os resultados dos testes apresentam informações inconsistentes."
        steps = ["Atualize os detalhes e confira os registros da transação antes de considerar a operação validada."]
    elif status == "pending":
        category = "pending"
        summary = "O plano está pendente de revisão humana. Não há execução confirmada."
        steps = ["Revise as alterações, os testes e os riscos antes de aprovar ou rejeitar no Studio."]
    elif status == "rejected":
        category = "rejected"
        summary = "O plano foi rejeitado. A rejeição não confirma uma execução."
        steps = ["Se a alteração ainda for necessária, revise a instrução e gere um novo plano."]
    elif status in {"approved", "executing", "testing", "running", "repairing"}:
        category = "in_progress"
        summary = "A operação ainda não tem um resultado final registrado."
        steps = ["Acompanhe a atualização automática e consulte novamente após a conclusão."]
    elif status == "committed":
        category = "completed"
        summary = "A operação foi registrada como concluída."
        steps = ["Confira o resultado no aplicativo e os arquivos incluídos no commit."]
    elif status == "unknown":
        category = "insufficient_data"
        summary = "O estado disponível não permite confirmar o resultado da operação."
        steps = ["Atualize os detalhes e confira a transação antes de repetir uma aprovação."]
    elif code is not None and code < 0:
        category = "interrupted"
        summary = f"O processo de testes terminou com código negativo ({code})."
        steps = ["Confira os registros do processo. O código isolado não comprova timeout nem defeito no código."]
    elif success is False or (code is not None and code != 0):
        category = "test_failure"
        summary = "O resultado registrado indica falha nos testes."
        steps = ["Revise Saída e Erros nos detalhes para localizar a falha antes de solicitar uma correção."]
    else:
        category = "failure"
        summary = "A operação terminou sem conclusão confirmada; os dados resumidos não revelam a causa."
        steps = ["Confira o erro da operação e os registros da transação antes de propor uma correção."]

    if status == "rolled_back":
        evidence.append("Estado: reversão registrada.")
    if task.get("error"):
        evidence.append("Há um erro da operação registrado nos detalhes.")
    git = task.get("git")
    commit = git.get("commit_hash") if isinstance(git, dict) else None
    evidence.append("Hash do commit: " + ("Disponível" if isinstance(commit, str) and commit.strip() else "Não informado"))
    return {
        "status": status,
        "category": category,
        "summary": summary,
        "evidence": evidence,
        "next_steps": steps,
        "limitations": "Análise dos dados públicos registrados, sem chamada à IA, execução de testes ou alteração de arquivos. A causa raiz pode exigir investigação adicional.",
    }
