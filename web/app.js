"use strict";

(() => {
  const $ = (id) => document.getElementById(id);

  const elements = {
    healthIndicator: $("health-indicator"),
    healthLabel: $("health-label"),
    apiStatus: $("api-status"),
    refreshButton: $("refresh-button"),
    instructionForm: $("instruction-form"),
    instruction: $("instruction"),
    planButton: $("plan-button"),
    planPanel: $("plan-panel"),
    planStatus: $("plan-status"),
    planContent: $("plan-content"),
    approvalActions: $("approval-actions"),
    approveButton: $("approve-button"),
    rejectButton: $("reject-button"),
    operationDetails: $("operation-details"),
    taskCount: $("task-count"),
    taskList: $("task-list"),
    notification: $("notification"),
  };

  const state = {
    selectedTaskId: null,
    selectedTask: null,
    pendingApprovalId: null,
    busy: false,
    notificationTimer: null,
    selectionSequence: 0,
  };

  const STATUS_LABELS = {
    pending: "Pendente",
    approved: "Aprovada",
    executing: "Executando",
    testing: "Em testes",
    committed: "Concluída",
    rejected: "Rejeitada",
    rolled_back: "Revertida",
    failed: "Falhou",
    running: "Em execução",
  };

  function text(value, fallback = "—") {
    if (value === null || value === undefined || value === "") {
      return fallback;
    }

    if (typeof value === "object") {
      return JSON.stringify(value, null, 2);
    }

    return String(value);
  }

  function element(tag, className, content) {
    const node = document.createElement(tag);

    if (className) {
      node.className = className;
    }

    if (content !== undefined) {
      node.textContent = text(content, "");
    }

    return node;
  }

  function showNotification(message, type = "info") {
    const notification = elements.notification;

    notification.textContent = message;
    notification.className = `notification ${type}`;
    notification.hidden = false;

    if (state.notificationTimer) {
      window.clearTimeout(state.notificationTimer);
    }

    state.notificationTimer = window.setTimeout(() => {
      notification.hidden = true;
    }, 5000);
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
      cache: "no-store",
    });

    const raw = await response.text();
    let data = {};

    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch {
        throw new Error("A API retornou uma resposta inválida.");
      }
    }

    if (!response.ok) {
      throw new Error(
        data.error || `Erro HTTP ${response.status}.`
      );
    }

    return data;
  }

  function setBusy(busy, message = null) {
    state.busy = busy;

    elements.planButton.disabled = busy;
    elements.refreshButton.disabled = busy;
    elements.approveButton.disabled = busy;
    elements.rejectButton.disabled = busy;
    elements.instruction.disabled = busy;

    if (message) {
      showNotification(message);
    }
  }

  function statusLabel(status) {
    const normalized = String(status || "unknown").toLowerCase();

    return STATUS_LABELS[normalized] || normalized.replaceAll("_", " ");
  }

  function setHealth(online, label) {
    elements.healthIndicator.className =
      `indicator ${online ? "online" : "offline"}`;

    elements.healthLabel.textContent = label;
    elements.apiStatus.textContent = online ? "Online" : "Offline";
  }

  async function checkHealth() {
    try {
      const result = await request("/health");

      if (result.status !== "ok") {
        throw new Error("Estado inesperado da API.");
      }

      setHealth(true, "Serviço conectado");
      return true;
    } catch (error) {
      setHealth(false, "Serviço indisponível");
      return false;
    }
  }

  function clearNode(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function appendField(container, label, value) {
    const wrapper = element("div", "detail-field");
    const heading = element("strong", "detail-label", label);
    const content = element("div", "detail-value", value);

    wrapper.append(heading, content);
    container.append(wrapper);
  }

  function renderPlan(plan) {
    clearNode(elements.planContent);

    if (!plan || typeof plan !== "object") {
      elements.planContent.append(
        element("p", "empty-state", "O plano não foi disponibilizado pela API.")
      );
      return;
    }

    appendField(
      elements.planContent,
      "Objetivo",
      plan.objective || plan.instruction
    );

    const changes = Array.isArray(plan.changes) ? plan.changes : [];
    const tests = Array.isArray(plan.tests) ? plan.tests : [];
    const risks = Array.isArray(plan.risks) ? plan.risks : [];

    const changesSection = element("section", "plan-section");
    changesSection.append(
      element("h3", "", `Alterações propostas (${changes.length})`)
    );

    if (changes.length === 0) {
      changesSection.append(
        element("p", "muted", "Nenhuma alteração de arquivo listada.")
      );
    }

    changes.forEach((change, index) => {
      const card = element("article", "change-card");

      card.append(
        element(
          "strong",
          "change-title",
          `${index + 1}. ${text(change.change_type, "Alteração").toUpperCase()}`
        ),
        element("code", "change-path", change.path || "Caminho não informado")
      );

      if (change.reason) {
        card.append(element("p", "muted", change.reason));
      }

      if (change.content !== null && change.content !== undefined) {
        const details = document.createElement("details");
        const summary = element("summary", "", "Visualizar conteúdo proposto");
        const pre = element("pre", "code-preview", change.content);

        details.append(summary, pre);
        card.append(details);
      }

      changesSection.append(card);
    });

    elements.planContent.append(changesSection);

    const testsSection = element("section", "plan-section");
    testsSection.append(element("h3", "", `Testes previstos (${tests.length})`));

    if (tests.length === 0) {
      testsSection.append(
        element("p", "muted", "Nenhum teste especificado no plano.")
      );
    } else {
      const list = document.createElement("ul");

      tests.forEach((test) => {
        list.append(element("li", "", test));
      });

      testsSection.append(list);
    }

    elements.planContent.append(testsSection);

    const risksSection = element("section", "plan-section");
    risksSection.append(element("h3", "", `Riscos (${risks.length})`));

    if (risks.length === 0) {
      risksSection.append(
        element("p", "muted", "Nenhum risco listado.")
      );
    } else {
      const list = document.createElement("ul");

      risks.forEach((risk) => {
        list.append(element("li", "", risk));
      });

      risksSection.append(list);
    }

    elements.planContent.append(risksSection);
  }

  function renderPlanPanel(task) {
    const plan = task.plan || null;
    const status = task.status || "pending";

    elements.planPanel.hidden = false;
    elements.planStatus.textContent = statusLabel(status).toUpperCase();

    renderPlan(plan);

    const canDecide =
      status === "pending" &&
      Boolean(task.approval_id);

    elements.approvalActions.hidden = !canDecide;

    state.pendingApprovalId = canDecide
      ? task.approval_id
      : null;
  }

  function renderOperation(task) {
    clearNode(elements.operationDetails);

    if (!task) {
      elements.operationDetails.className = "empty-state";
      elements.operationDetails.textContent = "Nenhuma operação selecionada.";
      return;
    }

    elements.operationDetails.className = "operation-content";

    const grid = element("div", "details-grid");

    appendField(grid, "Identificador", task.approval_id);
    appendField(grid, "Estado", statusLabel(task.status));
    appendField(grid, "Transação", task.transaction_id);
    appendField(grid, "Criada em", task.created_at);
    appendField(grid, "Atualizada em", task.updated_at);

    elements.operationDetails.append(grid);

    if (task.instruction) {
      appendField(
        elements.operationDetails,
        "Instrução original",
        task.instruction
      );
    }

    if (task.tests) {
      const tests = task.tests;
      const section = element("section", "result-section");

      section.append(element("h3", "", "Resultado dos testes"));

      if (typeof tests === "object") {
        appendField(section, "Sucesso", tests.success ? "Sim" : "Não");
        appendField(section, "Código de saída", tests.returncode);

        if (tests.stdout) {
          appendField(section, "Saída", tests.stdout);
        }

        if (tests.stderr) {
          appendField(section, "Erros", tests.stderr);
        }
      } else {
        appendField(section, "Resultado", tests);
      }

      elements.operationDetails.append(section);
    }

    if (task.repair_attempts !== undefined) {
      appendField(
        elements.operationDetails,
        "Tentativas de reparo",
        task.repair_attempts
      );
    }

    if (task.error) {
      appendField(elements.operationDetails, "Erro", task.error);
    }

    if (task.rollback_error) {
      appendField(
        elements.operationDetails,
        "Erro durante rollback",
        task.rollback_error
      );
    }

    if (task.git) {
      appendField(
        elements.operationDetails,
        "Git",
        task.git
      );
    }
  }

  function sortTasksByUpdatedAt(tasks) {
    const timestamp = (task) => {
      const updated = Date.parse(task.updated_at || "");
      if (Number.isFinite(updated)) {
        return updated;
      }

      const created = Date.parse(task.created_at || "");
      return Number.isFinite(created) ? created : 0;
    };

    return [...tasks].sort(
      (left, right) => timestamp(right) - timestamp(left)
    );
  }

  function renderTaskList(tasks) {
    tasks = sortTasksByUpdatedAt(tasks);
    clearNode(elements.taskList);

    elements.taskCount.textContent = String(tasks.length);

    if (tasks.length === 0) {
      elements.taskList.append(
        element("p", "empty-state", "Nenhuma tarefa registrada.")
      );
      return;
    }

    tasks.forEach((task) => {
      const id = task.approval_id;

      if (!id) {
        return;
      }

      const button = element("button", "task-entry");
      button.type = "button";
      button.setAttribute("data-task-id", id);

      const title = element(
        "strong",
        "task-title",
        task.instruction || id
      );

      const metadata = element(
        "small",
        "task-meta",
        `${statusLabel(task.status)} · ${task.created_at || "Sem data"}`
      );

      button.append(title, metadata);

      if (id === state.selectedTaskId) {
        button.classList.add("selected");
        button.setAttribute("aria-current", "true");
      }

      button.addEventListener("click", () => {
        selectTask(id);
      });

      elements.taskList.append(button);
    });
  }

  async function refreshTasks(preserveSelection = true) {
    const result = await request("/tasks");
    const tasks = sortTasksByUpdatedAt(
      Array.isArray(result.tasks) ? result.tasks : []
    );

    renderTaskList(tasks);

    const selectedTaskExists = tasks.some(
      (task) => task.approval_id === state.selectedTaskId
    );

    if (
      preserveSelection &&
      state.selectedTaskId &&
      selectedTaskExists
    ) {
      await selectTask(state.selectedTaskId, false);
      return;
    }

    const mostRecentTask = tasks.find(
      (task) => Boolean(task.approval_id)
    );

    if (mostRecentTask) {
      await selectTask(mostRecentTask.approval_id, false);
      return;
    }

    state.selectedTaskId = null;
    state.selectedTask = null;
    state.pendingApprovalId = null;

    elements.planPanel.hidden = true;
    elements.approvalActions.hidden = true;
    renderOperation(null);
  }
  async function selectTask(taskId, updateList = true) {
    const sequence = ++state.selectionSequence;

    try {
      const task = await request(
        `/tasks/${encodeURIComponent(taskId)}`
      );

      if (sequence !== state.selectionSequence) {
        return;
      }

      if (!task || task.approval_id !== taskId) {
        throw new Error(
          "A tarefa retornada não corresponde ao approval_id solicitado."
        );
      }

      state.selectedTaskId = task.approval_id;
      state.selectedTask = task;

      renderPlanPanel(task);
      renderOperation(task);

      if (updateList) {
        const result = await request("/tasks");

        if (sequence !== state.selectionSequence) {
          return;
        }

        renderTaskList(Array.isArray(result.tasks) ? result.tasks : []);
      }
    } catch (error) {
      if (sequence !== state.selectionSequence) {
        return;
      }

      showNotification(
        `Não foi possível carregar a tarefa: ${error.message}`,
        "error"
      );
    }
  }

  async function createPlan(event) {
    event.preventDefault();

    if (state.busy) {
      return;
    }

    const instruction = elements.instruction.value.trim();

    if (!instruction) {
      showNotification("Informe uma instrução.", "error");
      return;
    }

    setBusy(true);

    try {
      const result = await request("/plan", {
        method: "POST",
        body: JSON.stringify({ instruction }),
      });

      const approvalId = result.approval_id;

      if (!approvalId) {
        throw new Error("A API não retornou approval_id.");
      }

      state.selectedTaskId = approvalId;
      state.selectedTask = {
        ...result,
        task_id: approvalId,
        approval_id: approvalId,
        instruction,
      };

      renderPlanPanel(state.selectedTask);
      renderOperation(state.selectedTask);

      showNotification("Plano recebido. Revise antes de aprovar.", "success");

      await refreshTasks(true);
      await selectTask(approvalId);
    } catch (error) {
      showNotification(`Falha ao gerar plano: ${error.message}`, "error");
    } finally {
      setBusy(false);
    }
  }

  async function decideTask(action) {
    if (state.busy || !state.pendingApprovalId) {
      return;
    }

    const approvalId = state.pendingApprovalId;

    if (
      action === "approve" &&
      !window.confirm(
        "Confirma a aprovação? O DevAgent poderá modificar arquivos e executar testes."
      )
    ) {
      return;
    }

    if (
      action === "reject" &&
      !window.confirm("Confirma a rejeição deste plano?")
    ) {
      return;
    }

    setBusy(true);

    try {
      const result = await request(
        `/${action}/${encodeURIComponent(approvalId)}`,
        { method: "POST" }
      );

      const resultStatus = result.status || (
        action === "reject" ? "rejected" : "executing"
      );

      showNotification(
        action === "approve"
          ? `Operação finalizada: ${statusLabel(resultStatus)}.`
          : "Plano rejeitado.",
        resultStatus === "failed" ? "error" : "success"
      );

      await refreshTasks(false);
      await selectTask(approvalId);
    } catch (error) {
      showNotification(
        `Não foi possível ${action === "approve" ? "aprovar" : "rejeitar"}: ${error.message}`,
        "error"
      );

      await refreshTasks(false);
    } finally {
      setBusy(false);
    }
  }

  async function refreshAll() {
    if (state.busy) {
      return;
    }

    setBusy(true);

    try {
      const online = await checkHealth();

      if (!online) {
        throw new Error("A API não está acessível.");
      }

      await refreshTasks(false);
      showNotification("Dados atualizados.", "success");
    } catch (error) {
      showNotification(error.message, "error");
    } finally {
      setBusy(false);
    }
  }

  elements.instructionForm.addEventListener("submit", createPlan);

  elements.approveButton.addEventListener("click", () => {
    decideTask("approve");
  });

  elements.rejectButton.addEventListener("click", () => {
    decideTask("reject");
  });

  elements.refreshButton.addEventListener("click", refreshAll);

  async function initialize() {
    const online = await checkHealth();

    if (!online) {
      elements.taskList.replaceChildren(
        element("p", "empty-state", "API indisponível. Inicie o servidor no Termux.")
      );
      return;
    }

    try {
      await refreshTasks(false);
    } catch (error) {
      showNotification(
        `Falha ao carregar histórico: ${error.message}`,
        "error"
      );
    }
  }

  initialize();
})();
