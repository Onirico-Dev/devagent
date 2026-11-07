"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const APP_PATH = path.join(__dirname, "..", "devagent_studio", "app.js");
const APP_SOURCE = fs.readFileSync(APP_PATH, "utf8");

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.className = "";
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.type = "";
    this.style = {};
    this.parentElement = null;
    this.classList = {
      add: (...names) => {
        const current = new Set(this.className.split(/\s+/).filter(Boolean));
        names.forEach((name) => current.add(name));
        this.className = [...current].join(" ");
      },
      contains: (name) => this.className.split(/\s+/).includes(name),
    };
  }

  get firstChild() {
    return this.children[0] || null;
  }

  get nextSibling() {
    if (!this.parentElement) return null;
    return this.parentElement.children[this.parentElement.children.indexOf(this) + 1] || null;
  }

  insertBefore(node, reference) {
    if (reference === null) { this.append(node); return node; }
    const index = this.children.indexOf(reference);
    assert.ok(index >= 0, "O nó de referência deve pertencer ao pai.");
    node.parentElement = this;
    this.children.splice(index, 0, node);
    return node;
  }

  append(...nodes) {
    nodes.forEach((node) => { node.parentElement = this; });
    this.children.push(...nodes);
  }

  removeChild(node) {
    const index = this.children.indexOf(node);
    if (index >= 0) this.children.splice(index, 1);
    return node;
  }

  replaceChildren(...nodes) {
    this.children = [...nodes];
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return this.attributes[name] ?? null;
  }

  addEventListener(name, callback) {
    this.listeners[name] = callback;
  }

  remove() { this.parentElement?.removeChild(this); }
  focus() {}
  select() {}
  setSelectionRange() {}
}

const ELEMENT_IDS = [
  "health-indicator",
  "health-label",
  "api-status",
  "ai-provider",
  "refresh-button",
  "instruction-form",
  "instruction",
  "plan-button",
  "plan-panel",
  "plan-status",
  "plan-content",
  "approval-actions",
  "approve-button",
  "reject-button",
  "operation-details",
  "task-count",
  "task-list",
  "notification",
  "chat-form", "chat-input", "chat-send", "chat-clear", "chat-log", "chat-status",
];

function makeTask(id, updatedAt, extra = {}) {
  return {
    approval_id: String(id),
    status: "pending",
    instruction: `Operação ${id}`,
    created_at: updatedAt,
    updated_at: updatedAt,
    plan: {
      objective: `Plano ${id}`,
      changes: [],
      tests: [],
      risks: [],
    },
    ...extra,
  };
}

function createHarness(tasks, harnessOptions = {}) {
  const elements = Object.fromEntries(
    ELEMENT_IDS.map((id) => [id, new FakeElement()])
  );
  elements.instruction.value = harnessOptions.initialInstruction || "";
  elements["chat-input"].value = "";
  elements["instruction-form"].append(new FakeElement("label"), elements.instruction, new FakeElement("div"));

  const requests = [];
  const copied = [];
  const timers = new Map();
  let nextTimerId = 1;

  function fakeSetTimeout(callback, delay) {
    const id = nextTimerId++;
    timers.set(id, { callback, delay });
    return id;
  }

  function fakeClearTimeout(id) {
    timers.delete(id);
  }

  const pendingTaskRequests = new Map();
  const pendingPostRequests = new Map();
  let taskListFailureArmed = false;
  let taskRequestFailureArmed = false;
  const taskListFailures = [...(harnessOptions.taskListFailures || [])];

  function postResponse(url, request) {
    const configured = harnessOptions.postResponses?.[url] || {};
    const status = configured.status ?? 200;
    const data = configured.data ?? (
      url === "/plan"
        ? {
            approval_id: "created-1",
            status: "pending",
            plan: {
              objective: "Plano criado",
              changes: [],
              tests: [],
              risks: [],
            },
          }
        : {
            status: url.startsWith("/reject/") ? "rejected" : "executing",
          }
    );

    if (
      status >= 200 &&
      status < 300 &&
      url === "/plan" &&
      data.approval_id &&
      !Object.hasOwn(configured, "rawBody")
    ) {
      const body = JSON.parse(request.options.body);
      const created = {
        ...data,
        approval_id: String(data.approval_id),
        instruction: body.instruction,
        created_at: "2026-10-31T12:00:00Z",
        updated_at: "2026-10-31T12:00:00Z",
      };
      const index = tasks.findIndex(
        (task) => task.approval_id === created.approval_id
      );
      if (index >= 0) tasks[index] = created;
      else tasks.push(created);
    }

    if (
      status >= 200 &&
      status < 300 &&
      (url.startsWith("/approve/") || url.startsWith("/reject/"))
    ) {
      taskListFailureArmed = true;
      taskRequestFailureArmed = true;
      const id = decodeURIComponent(url.slice(url.lastIndexOf("/") + 1));
      const task = tasks.find((item) => item.approval_id === id);
      if (task) {
        task.status = data.status || (
          url.startsWith("/reject/") ? "rejected" : "executing"
        );
        task.updated_at = "2026-10-31T12:01:00Z";
      }
    }

    return {
      ok: status >= 200 && status < 300,
      status,
      async text() {
        return Object.hasOwn(configured, "rawBody")
          ? configured.rawBody
          : JSON.stringify(data);
      },
    };
  }

  const document = {
    body: new FakeElement("body"),
    activeElement: new FakeElement("button"),
    hidden: false,
    listeners: {},
    getElementById(id) {
      return elements[id] || null;
    },
    createElement(tagName) {
      return new FakeElement(tagName);
    },
    addEventListener(name, callback) {
      this.listeners[name] = callback;
    },
    execCommand(command) {
      assert.equal(command, "copy");
      if (harnessOptions.fallbackFails) return false;
      copied.push(document.body.children.at(-1).value);
      return true;
    },
  };

  async function fetchMock(url, options = {}) {
    const request = { url, options };
    requests.push(request);

    if (url === "/chat" || url.startsWith("/chat/")) {
      if (harnessOptions.chatResponse) return await harnessOptions.chatResponse(url, options);
      return reportResponse(harnessOptions.chatData);
    }

    if (url === "/consultations" || url.startsWith("/consultations/")) {
      if (harnessOptions.consultationResponse) return await harnessOptions.consultationResponse(url, options);
      return reportResponse(harnessOptions.consultationData);
    }

    if (url.startsWith("/tasks/") && url.includes("/investigation")) {
      if (harnessOptions.investigationResponse) return await harnessOptions.investigationResponse(url, options);
      return reportResponse(harnessOptions.investigationData);
    }

    let data;

    if (options.method === "POST") {
      const transportError = harnessOptions.postErrors?.[url];
      if (transportError) {
        throw new TypeError(transportError);
      }

      if (harnessOptions.deferPostRequests) {
        return await new Promise((resolve) => {
          const queue = pendingPostRequests.get(url) || [];
          queue.push(() => resolve(postResponse(url, request)));
          pendingPostRequests.set(url, queue);
        });
      }
      const response = postResponse(url, request);
      const postCommitError =
        harnessOptions.postCommitTransportErrors?.[url];

      if (postCommitError) {
        throw new TypeError(postCommitError);
      }

      return response;
    }

    if (url === "/health") {
      if (harnessOptions.healthError) throw new TypeError(harnessOptions.healthError);
      data = harnessOptions.healthData || { status: "ok", ai_provider: "Mock" };
    } else if (url === "/tasks") {
      const failure = taskListFailureArmed ? taskListFailures.shift() : null;
      if (failure) {
        return {
          ok: false,
          status: failure.status || 503,
          async text() {
            return JSON.stringify({
              error: failure.message || "Falha simulada ao atualizar tarefas.",
            });
          },
        };
      }
      data = { tasks: [...tasks] };
    } else if (url.startsWith("/tasks/") && url.endsWith("/diagnostic")) {
      if (harnessOptions.diagnosticResponse) return await harnessOptions.diagnosticResponse(url);
      data = harnessOptions.diagnosticData;
    } else if (url.startsWith("/tasks/")) {
      const id = decodeURIComponent(url.slice("/tasks/".length));
      const shouldInjectTaskFailure = taskRequestFailureArmed;
      taskRequestFailureArmed = false;
      const failure = shouldInjectTaskFailure
        ? harnessOptions.taskRequestFailures?.[id]
        : null;
      if (failure) {
        return {
          ok: false,
          status: failure.status || 500,
          async text() {
            return JSON.stringify({ error: failure.message || "Falha simulada ao carregar tarefa." });
          },
        };
      }

      if (harnessOptions.deferTaskRequests) {
        return await new Promise((resolve) => {
          const queue = pendingTaskRequests.get(id) || [];

          queue.push(() => {
            const task = tasks.find(
              (item) => item.approval_id === id
            ) || {};

            resolve({
              ok: true,
              status: 200,
              async text() {
                return JSON.stringify(task);
              },
            });
          });

          pendingTaskRequests.set(id, queue);
        });
      }

      data = tasks.find((task) => task.approval_id === id) || {};
    } else {
      throw new Error(`Rota inesperada no teste: ${url}`);
    }

    return {
      ok: true,
      status: 200,
      async text() {
        return JSON.stringify(data);
      },
    };
  }

  const sourceMarker = "  initialize();\n})();";

  assert.equal(
    APP_SOURCE.split(sourceMarker).length - 1,
    1,
    "O ponto de inicialização do app.js mudou; revise o harness."
  );

  const instrumentedSource = APP_SOURCE.replace(
    sourceMarker,
    `  globalThis.__devagentTest = {
    sortTasksByUpdatedAt,
    showNotification,
    decideTask,
    renderTaskList,
    renderOperation,
    renderPlanPanel,
    checkHealth,
    refreshTasks,
    selectTask,
    initialize,
    startPolling,
    pollTasks,
    schedulePolling,
    handleVisibilityChange,
    state,
    elements
  };
})();`
  );

  const context = vm.createContext({
    navigator: harnessOptions.noClipboard ? {} : { clipboard: {
      async writeText(content) {
        if (harnessOptions.clipboardFails) throw new Error("denied");
        if (harnessOptions.clipboardWrite) await harnessOptions.clipboardWrite(content);
        copied.push(content);
      },
    } },
    document,
    fetch: harnessOptions.fetchImpl || fetchMock,
    window: {
      confirm: () => harnessOptions.confirmResult ?? true,
      setTimeout: fakeSetTimeout,
      clearTimeout: fakeClearTimeout,
    },
    console,
  });

  vm.runInContext(instrumentedSource, context, {
    filename: APP_PATH,
  });

  const api = context.__devagentTest;

  return {
    api,
    elements,
    requests,
    copied,
    document,
    pendingNotificationTimer() {
      return timers.get(api.state.notificationTimer) || null;
    },
    runNotificationTimer() {
      const id = api.state.notificationTimer;
      const timer = timers.get(id);
      assert.ok(timer, "Deve existir temporizador de notificação.");
      timers.delete(id);
      timer.callback();
    },
    async runPollingTimer() {
      const id = api.state.pollingTimer;
      if (id === null || !timers.has(id)) {
        throw new Error("Não existe temporizador de polling pendente.");
      }

      const timer = timers.get(id);
      timers.delete(id);
      await timer.callback();
    },
    pendingPollingTimers() {
      const id = api.state.pollingTimer;
      return id !== null && timers.has(id) ? 1 : 0;
    },
    setDocumentHidden(hidden) {
      document.hidden = Boolean(hidden);
      const listener = document.listeners.visibilitychange;
      if (listener) {
        listener();
      }
    },
    resolvePostRequest(url) {
      const queue = pendingPostRequests.get(url) || [];
      const resolve = queue.shift();
      if (!resolve) {
        throw new Error(`Não existe POST pendente para ${url}.`);
      }
      if (queue.length === 0) pendingPostRequests.delete(url);
      resolve();
    },
    resolveTaskRequest(id) {
      const key = String(id);
      const queue = pendingTaskRequests.get(key) || [];
      const resolve = queue.shift();

      if (!resolve) {
        throw new Error(`Não existe requisição pendente para ${key}.`);
      }

      if (queue.length === 0) {
        pendingTaskRequests.delete(key);
      }

      resolve();
    },
  };
}


function listedTaskIds(taskList) {
  return taskList.children
    .filter((node) => node.tagName === "BUTTON")
    .map((node) => node.getAttribute("data-task-id"));
}

test("ordena tarefas por updated_at, da mais recente para a mais antiga", () => {
  const harness = createHarness([]);
  const tasks = [
    makeTask("148", "2026-10-30T19:52:32.023Z"),
    makeTask("147", "2026-10-30T19:49:37.799Z"),
    makeTask("149", "2026-10-30T20:29:51.368Z"),
  ];

  const ordered = harness.api.sortTasksByUpdatedAt(tasks);

  assert.deepEqual(
    Array.from(ordered, (task) => task.approval_id),
    ["149", "148", "147"]
  );

  assert.deepEqual(
    tasks.map((task) => task.approval_id),
    ["148", "147", "149"],
    "A ordenação não deve modificar o array original."
  );
});

test("usa created_at quando updated_at está ausente ou inválido", () => {
  const harness = createHarness([]);
  const tasks = [
    {
      approval_id: "antiga",
      created_at: "2026-10-01T10:00:00Z",
      updated_at: "data-invalida",
    },
    {
      approval_id: "recente",
      created_at: "2026-10-20T10:00:00Z",
    },
    {
      approval_id: "intermediaria",
      created_at: "2026-10-10T10:00:00Z",
      updated_at: null,
    },
  ];

  const ordered = harness.api.sortTasksByUpdatedAt(tasks);

  assert.deepEqual(
    Array.from(ordered, (task) => task.approval_id),
    ["recente", "intermediaria", "antiga"]
  );
});

test("renderTaskList mantém a ordenação mesmo recebendo dados fora de ordem", () => {
  const harness = createHarness([]);
  const tasks = [
    makeTask("148", "2026-10-30T19:52:32Z"),
    makeTask("149", "2026-10-30T20:29:51Z"),
    makeTask("147", "2026-10-30T19:49:37Z"),
  ];

  harness.api.renderTaskList(tasks);

  assert.deepEqual(
    listedTaskIds(harness.elements["task-list"]),
    ["149", "148", "147"]
  );

  assert.equal(harness.elements["task-count"].textContent, "3");
});

test("renderTaskList não utiliza task_id como substituto de approval_id", () => {
  const harness = createHarness([]);

  harness.api.renderTaskList([
    {
      task_id: "999",
      status: "pending",
      instruction: "Tarefa sem approval_id",
    },
  ]);

  assert.deepEqual(
    listedTaskIds(harness.elements["task-list"]),
    []
  );

  assert.equal(harness.elements["task-count"].textContent, "1");
});


test("polling inicia, consulta tarefas e reagenda após sucesso", async () => {
  const harness = createHarness([
    makeTask("poll-1", "2026-10-31T10:00:00Z"),
  ]);

  harness.api.startPolling();

  assert.equal(harness.pendingPollingTimers(), 1);

  await harness.runPollingTimer();

  assert.ok(
    harness.requests.some((request) => request.url === "/tasks")
  );
  assert.equal(harness.pendingPollingTimers(), 1);
  assert.equal(harness.api.state.pollingInFlight, false);
});

test("polling pausa com a página oculta e sincroniza ao retornar", async () => {
  const harness = createHarness([
    makeTask("visible-1", "2026-10-31T10:00:00Z"),
  ]);

  harness.api.startPolling();
  harness.setDocumentHidden(true);

  assert.equal(harness.pendingPollingTimers(), 0);

  const before = harness.requests.filter(
    (request) => request.url === "/tasks"
  ).length;

  harness.setDocumentHidden(false);
  await new Promise((resolve) => setImmediate(resolve));

  const after = harness.requests.filter(
    (request) => request.url === "/tasks"
  ).length;

  assert.ok(after > before);
  assert.equal(harness.pendingPollingTimers(), 1);
});

test("polling não consulta enquanto uma operação estiver ocupada", async () => {
  const harness = createHarness([
    makeTask("busy-1", "2026-10-31T10:00:00Z"),
  ]);

  harness.api.startPolling();
  harness.api.state.busy = true;

  const before = harness.requests.filter(
    (request) => request.url === "/tasks"
  ).length;

  await harness.runPollingTimer();

  const after = harness.requests.filter(
    (request) => request.url === "/tasks"
  ).length;

  assert.equal(after, before);
  assert.equal(harness.pendingPollingTimers(), 1);

  harness.api.state.busy = false;
  await harness.runPollingTimer();

  assert.ok(
    harness.requests.some((request) => request.url === "/tasks")
  );
});

test("polling recupera aprovação incerta antes da seleção anterior", async () => {
  const harness = createHarness([
    makeTask("target", "2026-10-31T10:00:00Z", {
      status: "executing",
    }),
    makeTask("other", "2026-10-31T11:00:00Z"),
  ]);

  harness.api.state.selectedTaskId = "other";
  harness.api.state.uncertainApprovalId = "target";

  harness.api.startPolling();
  await harness.runPollingTimer();

  assert.equal(harness.api.state.selectedTaskId, "target");
  assert.equal(harness.api.state.uncertainApprovalId, null);

  assert.ok(
    harness.requests.some(
      (request) => request.url === "/tasks/target"
    )
  );

  assert.equal(
    harness.requests.filter(
      (request) => request.options.method === "POST"
    ).length,
    0
  );
});

test("polling não inicia ciclos concorrentes", async () => {
  const harness = createHarness([
    makeTask("concurrent-1", "2026-10-31T10:00:00Z"),
  ]);

  harness.api.startPolling();
  harness.api.state.pollingInFlight = true;

  const before = harness.requests.filter(
    (request) => request.url === "/tasks"
  ).length;

  await harness.runPollingTimer();

  const after = harness.requests.filter(
    (request) => request.url === "/tasks"
  ).length;

  assert.equal(after, before);
  assert.equal(harness.pendingPollingTimers(), 1);

  harness.api.state.pollingInFlight = false;
});

test("inicialização seleciona automaticamente a tarefa mais recente", async () => {
  const tasks = [
    makeTask("148", "2026-10-30T19:52:32Z"),
    makeTask("147", "2026-10-30T19:49:37Z"),
    makeTask("149", "2026-10-30T20:29:51Z", {
      status: "committed",
    }),
  ];

  const harness = createHarness(tasks);

  await harness.api.initialize();

  assert.equal(harness.api.state.selectedTaskId, "149");
  assert.equal(harness.api.state.selectedTask.approval_id, "149");

  assert.deepEqual(
    listedTaskIds(harness.elements["task-list"]),
    ["149", "148", "147"]
  );

  assert.ok(
    harness.requests.some((request) => request.url === "/tasks/149"),
    "A inicialização deve buscar os detalhes da tarefa mais recente."
  );
});

test("refreshTasks preserva uma seleção válida quando solicitado", async () => {
  const tasks = [
    makeTask("148", "2026-10-30T19:52:32Z"),
    makeTask("149", "2026-10-30T20:29:51Z"),
  ];

  const harness = createHarness(tasks);
  harness.api.state.selectedTaskId = "148";

  await harness.api.refreshTasks(true);

  assert.equal(harness.api.state.selectedTaskId, "148");
  assert.equal(harness.api.state.selectedTask.approval_id, "148");

  assert.deepEqual(
    listedTaskIds(harness.elements["task-list"]),
    ["149", "148"]
  );

  assert.ok(
    harness.requests.some((request) => request.url === "/tasks/148")
  );
});

test("refreshTasks seleciona a mais recente quando não deve preservar seleção", async () => {
  const tasks = [
    makeTask("148", "2026-10-30T19:52:32Z"),
    makeTask("149", "2026-10-30T20:29:51Z"),
  ];

  const harness = createHarness(tasks);
  harness.api.state.selectedTaskId = "148";

  await harness.api.refreshTasks(false);

  assert.equal(harness.api.state.selectedTaskId, "149");
  assert.equal(harness.api.state.selectedTask.approval_id, "149");
});

test("refreshTasks limpa a seleção quando não existem tarefas", async () => {
  const harness = createHarness([]);

  harness.api.state.selectedTaskId = "148";
  harness.api.state.selectedTask = makeTask(
    "148",
    "2026-10-30T19:52:32Z"
  );

  await harness.api.refreshTasks(false);

  assert.equal(harness.api.state.selectedTaskId, null);
  assert.equal(harness.api.state.selectedTask, null);
  assert.equal(harness.api.state.pendingApprovalId, null);
  assert.equal(harness.elements["plan-panel"].hidden, true);
  assert.deepEqual(
    listedTaskIds(harness.elements["task-list"]),
    []
  );
});

test("selectTask rejeita resposta cujo approval_id não corresponde ao solicitado", async () => {
  const harness = createHarness([
    makeTask("149", "2026-10-30T20:29:51Z"),
  ]);

  await harness.api.selectTask("148", false);

  assert.equal(harness.api.state.selectedTaskId, null);
  assert.match(
    harness.elements.notification.textContent,
    /approval_id solicitado/
  );
});

test("seleção visual acompanha o approval_id selecionado", async () => {
  const tasks = [
    makeTask("148", "2026-10-30T19:52:32Z"),
    makeTask("149", "2026-10-30T20:29:51Z"),
  ];

  const harness = createHarness(tasks);

  await harness.api.selectTask("148");

  const selected = harness.elements["task-list"].children.filter(
    (node) => node.classList.contains("selected")
  );

  assert.equal(selected.length, 1);
  assert.equal(selected[0].getAttribute("data-task-id"), "148");
  assert.equal(selected[0].getAttribute("aria-current"), "true");
});


test("selectTask ignora resposta antiga quando seleções terminam fora de ordem", async () => {
  const tasks = [
    makeTask("A", "2026-10-31T10:00:00Z", {
      instruction: "Tarefa A antiga",
      plan: { objective: "Plano A", changes: [], tests: [], risks: [] },
    }),
    makeTask("B", "2026-10-31T10:01:00Z", {
      instruction: "Tarefa B mais recente",
      plan: { objective: "Plano B", changes: [], tests: [], risks: [] },
    }),
  ];

  const harness = createHarness(tasks, { deferTaskRequests: true });

  // Aguarda a inicialização automática, que usa respostas imediatas
  // para health e listagem, antes de iniciar as seleções concorrentes.
  await new Promise((resolve) => setImmediate(resolve));

  const selectionA = harness.api.selectTask("A", false);
  const selectionB = harness.api.selectTask("B", false);

  // A seleção mais recente responde primeiro.
  harness.resolveTaskRequest("B");
  await selectionB;

  // A seleção antiga responde por último.
  harness.resolveTaskRequest("A");
  await selectionA;

  assert.equal(
    harness.api.state.selectedTaskId,
    "B",
    "A seleção antiga não pode sobrescrever a seleção mais recente."
  );

  assert.equal(harness.api.state.selectedTask.approval_id, "B");
  const renderedPlanText = [];

  function collectText(node) {
    if (node.textContent) {
      renderedPlanText.push(node.textContent);
    }

    for (const child of node.children || []) {
      collectText(child);
    }
  }

  collectText(harness.elements["plan-content"]);

  assert.ok(
    renderedPlanText.includes("Plano B"),
    "O conteúdo renderizado deve continuar correspondendo à seleção B."
  );
});


test("selectTask ignora erro de uma seleção antiga", async () => {
  const tasks = [
    makeTask("A", "2026-10-31T10:00:00Z", {
      plan: { objective: "Plano A", changes: [], tests: [], risks: [] },
    }),
    makeTask("B", "2026-10-31T10:01:00Z", {
      plan: { objective: "Plano B", changes: [], tests: [], risks: [] },
    }),
  ];

  const harness = createHarness(tasks, {
    deferTaskRequests: true,
    taskRequestFailures: {
      A: { status: 500, message: "Falha antiga simulada." },
    },
  });

  await new Promise((resolve) => setImmediate(resolve));

  const selectionA = harness.api.selectTask("A", false);
  const selectionB = harness.api.selectTask("B", false);

  harness.resolveTaskRequest("B");
  await selectionB;

  const notificationBeforeOldFailure =
    harness.elements.notification.textContent;

  harness.resolveTaskRequest("A");
  await selectionA;

  assert.equal(harness.api.state.selectedTaskId, "B");
  assert.equal(harness.api.state.selectedTask.approval_id, "B");

  assert.equal(
    harness.elements.notification.textContent,
    notificationBeforeOldFailure,
    "Uma falha obsoleta não pode substituir a notificação atual."
  );

  assert.doesNotMatch(
    harness.elements.notification.textContent,
    /Falha antiga simulada/
  );
});

test("criação envia instrução e apresenta o plano retornado pela API", async () => {
  const harness = createHarness([]);
  harness.elements.instruction.value = "Crie um módulo de teste.";

  await harness.elements["instruction-form"].listeners.submit({
    preventDefault() {},
  });

  const request = harness.requests.find((item) => item.url === "/plan");
  assert.ok(request);
  assert.equal(request.options.method, "POST");
  assert.deepEqual(JSON.parse(request.options.body), {
    instruction: "Crie um módulo de teste.",
  });
  assert.equal(harness.api.state.selectedTaskId, "created-1");
  assert.equal(harness.api.state.pendingApprovalId, "created-1");
  assert.equal(harness.elements["plan-panel"].hidden, false);
  assert.match(harness.elements.notification.textContent, /Plano recebido/);
  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.elements["plan-button"].disabled, false);
});

test("criações sequenciais preservam a instrução de cada requisição", async () => {
  const harness = createHarness([]);

  harness.elements.instruction.value = "Primeira instrução.";
  await harness.elements["instruction-form"].listeners.submit({
    preventDefault() {},
  });

  assert.equal(harness.api.state.selectedTask.instruction, "Primeira instrução.");

  harness.elements.instruction.value = "Segunda instrução.";
  await harness.elements["instruction-form"].listeners.submit({
    preventDefault() {},
  });

  const planRequests = harness.requests.filter(
    (request) => request.url === "/plan"
  );

  assert.equal(planRequests.length, 2);
  assert.deepEqual(
    planRequests.map((request) => JSON.parse(request.options.body).instruction),
    ["Primeira instrução.", "Segunda instrução."]
  );
  assert.equal(harness.api.state.selectedTaskId, "created-1");
  assert.equal(harness.api.state.selectedTask.instruction, "Segunda instrução.");
  assert.equal(harness.api.state.pendingApprovalId, "created-1");
  assert.equal(harness.api.state.busy, false);
});


for (const invalidCase of [
  {
    name: "ausente",
    data: {
      status: "pending",
      plan: { objective: "Plano sem identificador" },
    },
  },
  {
    name: "vazio",
    data: {
      approval_id: "",
      status: "pending",
      plan: { objective: "Plano com identificador vazio" },
    },
  },
  {
    name: "nulo",
    data: {
      approval_id: null,
      status: "pending",
      plan: { objective: "Plano com identificador nulo" },
    },
  },
]) {
  test(`criação rejeita resposta com approval_id ${invalidCase.name}`, async () => {
    const harness = createHarness([], {
      postResponses: {
        "/plan": {
          status: 200,
          data: invalidCase.data,
        },
      },
    });
    harness.elements.instruction.value = "Criar arquivo.";

    await harness.elements["instruction-form"].listeners.submit({
      preventDefault() {},
    });

    assert.match(
      harness.elements.notification.textContent,
      /Falha ao gerar plano: A API não retornou approval_id\./
    );
    assert.equal(harness.api.state.selectedTaskId, null);
    assert.equal(harness.api.state.selectedTask, null);
    assert.equal(harness.api.state.pendingApprovalId, null);
    assert.equal(harness.api.state.busy, false);
    assert.equal(harness.elements["plan-button"].disabled, false);
    assert.equal(
      harness.requests.filter((item) => item.url === "/plan").length,
      1
    );
  });
}


for (const invalidResponse of [
  {
    name: "JSON malformado",
    configured: {
      status: 200,
      data: {},
      rawBody: "{json inválido",
    },
    expected: /A API retornou uma resposta inválida\./,
  },
  {
    name: "corpo vazio",
    configured: {
      status: 200,
      data: {},
      rawBody: "",
    },
    expected: /A API não retornou approval_id\./,
  },
  {
    name: "array JSON",
    configured: {
      status: 200,
      data: [],
    },
    expected: /A API não retornou approval_id\./,
  },
]) {
  test(`criação trata ${invalidResponse.name} da API`, async () => {
    const harness = createHarness([], {
      postResponses: {
        "/plan": invalidResponse.configured,
      },
    });
    harness.elements.instruction.value = "Criar arquivo.";

    await harness.elements["instruction-form"].listeners.submit({
      preventDefault() {},
    });

    assert.match(
      harness.elements.notification.textContent,
      invalidResponse.expected
    );
    assert.equal(harness.api.state.selectedTaskId, null);
    assert.equal(harness.api.state.selectedTask, null);
    assert.equal(harness.api.state.pendingApprovalId, null);
    assert.equal(harness.api.state.busy, false);
    assert.equal(harness.elements["plan-button"].disabled, false);
    assert.equal(
      harness.requests.filter((item) => item.url === "/plan").length,
      1
    );
    assert.equal(
      harness.requests.some((item) => item.url.startsWith("/tasks/")),
      false
    );
  });
}

test("falha na criação apresenta erro e restaura controles", async () => {
  const harness = createHarness([], {
    postResponses: {
      "/plan": {
        status: 500,
        data: { error: "Falha simulada na criação." },
      },
    },
  });
  harness.elements.instruction.value = "Criar arquivo.";

  await harness.elements["instruction-form"].listeners.submit({
    preventDefault() {},
  });

  assert.match(harness.elements.notification.textContent, /Falha simulada/);
  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.elements["plan-button"].disabled, false);
});

test("aprovação envia POST após confirmação", async () => {
  const harness = createHarness([makeTask("A", "2026-10-31T10:00:00Z")]);
  await harness.api.selectTask("A");

  await harness.api.decideTask("approve");

  assert.ok(harness.requests.some((item) => item.url === "/approve/A"));
  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.api.state.pendingApprovalId, null);
  assert.match(harness.elements.notification.textContent, /estado não reconhecido: Executando/i);
});

test("rejeição envia POST após confirmação", async () => {
  const harness = createHarness([makeTask("R", "2026-10-31T10:00:00Z")]);
  await harness.api.selectTask("R");

  await harness.api.decideTask("reject");

  assert.ok(harness.requests.some((item) => item.url === "/reject/R"));
  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.api.state.pendingApprovalId, null);
  assert.match(harness.elements.notification.textContent, /Plano rejeitado/);
});

test("cancelamento da confirmação não envia POST", async () => {
  const harness = createHarness(
    [makeTask("C", "2026-10-31T10:00:00Z")],
    { confirmResult: false }
  );
  await harness.api.selectTask("C");
  const requestCount = harness.requests.length;

  await harness.elements["approve-button"].listeners.click();

  assert.equal(harness.requests.length, requestCount);
  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.api.state.pendingApprovalId, "C");
});

test("cliques repetidos durante aprovação pendente geram apenas um POST", async () => {
  const harness = createHarness(
    [makeTask("D", "2026-10-31T10:00:00Z")],
    { deferPostRequests: true }
  );
  await harness.api.selectTask("D");

  const first = harness.api.decideTask("approve");

  assert.equal(harness.api.state.busy, true);
  assert.equal(harness.elements["approve-button"].disabled, true);

  await harness.elements["approve-button"].listeners.click();
  await harness.elements["reject-button"].listeners.click();

  assert.equal(
    harness.requests.filter((item) =>
      item.url === "/approve/D" || item.url === "/reject/D"
    ).length,
    1
  );

  harness.resolvePostRequest("/approve/D");
  await first;

  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.elements["approve-button"].disabled, false);
  assert.equal(harness.elements["reject-button"].disabled, false);
});

test("cancelamento da rejeição não envia POST", async () => {
  const harness = createHarness(
    [makeTask("CR", "2026-10-31T10:00:00Z")],
    { confirmResult: false }
  );
  await harness.api.selectTask("CR");
  const requestCount = harness.requests.length;

  await harness.elements["reject-button"].listeners.click();

  assert.equal(harness.requests.length, requestCount);
  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.api.state.pendingApprovalId, "CR");
});

test("rejeição duplicada durante requisição pendente gera apenas um POST", async () => {
  const harness = createHarness(
    [makeTask("RD", "2026-10-31T10:00:00Z")],
    { deferPostRequests: true }
  );
  await harness.api.selectTask("RD");

  const first = harness.api.decideTask("reject");

  assert.equal(harness.elements["reject-button"].disabled, true);

  await harness.elements["reject-button"].listeners.click();
  await harness.elements["approve-button"].listeners.click();

  assert.equal(
    harness.requests.filter((item) =>
      item.url === "/approve/RD" || item.url === "/reject/RD"
    ).length,
    1
  );

  harness.resolvePostRequest("/reject/RD");
  await first;

  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.elements["approve-button"].disabled, false);
  assert.equal(harness.elements["reject-button"].disabled, false);
});

test("falha HTTP na aprovação restaura os controles", async () => {
  const harness = createHarness(
    [makeTask("AF", "2026-10-31T10:00:00Z")],
    {
      postResponses: {
        "/approve/AF": {
          status: 409,
          data: { error: "Solicitação não está pendente." },
        },
      },
    }
  );
  await harness.api.selectTask("AF");

  await harness.api.decideTask("approve");

  assert.ok(harness.requests.some(
    (item) => item.url === "/approve/AF" && item.options.method === "POST"
  ));
  assert.match(
    harness.elements.notification.textContent,
    /não foi possível aprovar/i
  );
  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.elements["approve-button"].disabled, false);
  assert.equal(harness.elements["reject-button"].disabled, false);
  assert.equal(harness.api.state.selectedTaskId, "AF");
  assert.equal(harness.api.state.selectedTask.approval_id, "AF");
  assert.equal(harness.api.state.pendingApprovalId, "AF");
});

test("falha HTTP na rejeição restaura os controles", async () => {
  const harness = createHarness(
    [makeTask("RF", "2026-10-31T10:00:00Z")],
    {
      postResponses: {
        "/reject/RF": {
          status: 409,
          data: { error: "Solicitação não está pendente." },
        },
      },
    }
  );
  await harness.api.selectTask("RF");

  await harness.api.decideTask("reject");

  assert.ok(harness.requests.some(
    (item) => item.url === "/reject/RF" && item.options.method === "POST"
  ));
  assert.match(
    harness.elements.notification.textContent,
    /não foi possível rejeitar/i
  );
  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.elements["approve-button"].disabled, false);
  assert.equal(harness.elements["reject-button"].disabled, false);
  assert.equal(harness.api.state.selectedTaskId, "RF");
  assert.equal(harness.api.state.selectedTask.approval_id, "RF");
  assert.equal(harness.api.state.pendingApprovalId, "RF");
});


test("falha de transporte na criação apresenta erro e restaura controles", async () => {
  const harness = createHarness([], {
    postErrors: {
      "/plan": "Falha de conexão simulada.",
    },
  });
  harness.elements.instruction.value = "Criar arquivo.";

  await harness.elements["instruction-form"].listeners.submit({
    preventDefault() {},
  });

  assert.ok(harness.requests.some(
    (item) => item.url === "/plan" && item.options.method === "POST"
  ));
  assert.match(
    harness.elements.notification.textContent,
    /Falha ao gerar plano: Falha de conexão simulada\./
  );
  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.elements["plan-button"].disabled, false);
  assert.equal(harness.api.state.selectedTask, null);
  assert.equal(harness.api.state.pendingApprovalId, null);
});

test("falha de transporte na aprovação preserva tarefa e restaura controles", async () => {
  const harness = createHarness(
    [makeTask("AT", "2026-10-31T10:00:00Z")],
    {
      postErrors: {
        "/approve/AT": "Conexão interrompida.",
      },
    }
  );
  await harness.api.selectTask("AT");

  await harness.api.decideTask("approve");

  assert.ok(harness.requests.some(
    (item) => item.url === "/approve/AT" && item.options.method === "POST"
  ));
  assert.match(
    harness.elements.notification.textContent,
    /não foi possível aprovar: Conexão interrompida\./i
  );
  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.elements["approve-button"].disabled, false);
  assert.equal(harness.elements["reject-button"].disabled, false);
  assert.equal(harness.api.state.selectedTaskId, "AT");
  assert.equal(harness.api.state.selectedTask.approval_id, "AT");
  assert.equal(harness.api.state.pendingApprovalId, "AT");
});

test("falha de transporte na rejeição preserva tarefa e restaura controles", async () => {
  const harness = createHarness(
    [makeTask("RT", "2026-10-31T10:00:00Z")],
    {
      postErrors: {
        "/reject/RT": "Conexão interrompida.",
      },
    }
  );
  await harness.api.selectTask("RT");

  await harness.api.decideTask("reject");

  assert.ok(harness.requests.some(
    (item) => item.url === "/reject/RT" && item.options.method === "POST"
  ));
  assert.match(
    harness.elements.notification.textContent,
    /não foi possível rejeitar: Conexão interrompida\./i
  );
  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.elements["approve-button"].disabled, false);
  assert.equal(harness.elements["reject-button"].disabled, false);
  assert.equal(harness.api.state.selectedTaskId, "RT");
  assert.equal(harness.api.state.selectedTask.approval_id, "RT");
  assert.equal(harness.api.state.pendingApprovalId, "RT");
});


test("resposta perdida após aprovação concluída e falha de reconciliação bloqueiam repetição", async () => {
  const id = "AMBIGUOUS-POST";
  const harness = createHarness(
    [makeTask(id, "2026-10-31T10:00:00Z")],
    {
      postCommitTransportErrors: {
        [`/approve/${id}`]: "Resposta perdida após processamento.",
      },
      taskListFailures: [
        {
          status: 503,
          message: "Reconciliação indisponível.",
        },
      ],
    }
  );

  await harness.api.selectTask(id);
  await harness.api.decideTask("approve");

  assert.equal(harness.api.state.selectedTask.status, "unknown");
  assert.equal(harness.api.state.pendingApprovalId, null);
  assert.equal(harness.elements["approval-actions"].hidden, true);

  const postCount = harness.requests.filter(
    (request) => request.url === `/approve/${id}`
  ).length;

  await harness.api.decideTask("approve");

  assert.equal(
    harness.requests.filter(
      (request) => request.url === `/approve/${id}`
    ).length,
    postCount
  );
});

test("resposta perdida após rejeição concluída e falha de reconciliação bloqueiam repetição", async () => {
  const id = "AMBIGUOUS-REJECT";
  const harness = createHarness(
    [makeTask(id, "2026-10-31T10:00:00Z")],
    {
      postCommitTransportErrors: {
        [`/reject/${id}`]: "Resposta perdida após processamento.",
      },
      taskListFailures: [
        {
          status: 503,
          message: "Reconciliação indisponível.",
        },
      ],
    }
  );

  await harness.api.selectTask(id);
  await harness.api.decideTask("reject");

  assert.equal(harness.api.state.selectedTask.status, "unknown");
  assert.equal(harness.api.state.pendingApprovalId, null);
  assert.equal(harness.elements["approval-actions"].hidden, true);

  const postCount = harness.requests.filter(
    (request) => request.url === `/reject/${id}`
  ).length;

  await harness.api.decideTask("reject");

  assert.equal(
    harness.requests.filter(
      (request) => request.url === `/reject/${id}`
    ).length,
    postCount,
    "Uma rejeição de resultado incerto não pode ser repetida."
  );
});


test("atualização posterior recupera a tarefa com operação ambígua, mesmo quando outra é mais recente", async () => {
  const targetId = "AMBIGUOUS-RECOVERY";
  const newerId = "NEWER-TASK";

  const harness = createHarness(
    [
      makeTask(targetId, "2026-10-31T10:00:00Z"),
      makeTask(newerId, "2026-10-31T12:02:00Z"),
    ],
    {
      postCommitTransportErrors: {
        [`/approve/${targetId}`]: "Resposta perdida após processamento.",
      },
      taskRequestFailures: {
        [targetId]: {
          status: 503,
          message: "Primeira reconciliação individual indisponível.",
        },
      },
    }
  );

  await harness.api.selectTask(targetId);
  await harness.api.decideTask("approve");

  assert.match(
    harness.elements.notification.textContent,
    /reconciliação também falhou/i,
    "A falha do GET individual deve ser identificada como falha de reconciliação."
  );

  assert.equal(harness.api.state.uncertainApprovalId, targetId);
  assert.equal(harness.api.state.selectedTaskId, targetId);
  assert.equal(harness.api.state.selectedTask.status, "unknown");
  assert.equal(harness.api.state.pendingApprovalId, null);

  const targetRequestsBefore = harness.requests.filter(
    (request) => request.url === `/tasks/${targetId}`
  ).length;

  await harness.api.refreshTasks(false);

  const targetRequestsAfter = harness.requests.filter(
    (request) => request.url === `/tasks/${targetId}`
  ).length;

  assert.ok(
    targetRequestsAfter > targetRequestsBefore,
    "A atualização posterior deve consultar novamente a tarefa cuja operação ficou ambígua."
  );

  assert.equal(harness.api.state.selectedTaskId, targetId);
  assert.equal(harness.api.state.selectedTask.status, "executing");
  assert.equal(harness.api.state.uncertainApprovalId, null);
  assert.equal(harness.api.state.pendingApprovalId, null);
  assert.equal(harness.elements["approval-actions"].hidden, true);
});

for (const scenario of [
  {
    status: "committed",
    notification: /Aprovação concluída\. As alterações foram aplicadas e o commit foi realizado\./i,
  },
  {
    status: "rolled_back",
    notification: /A execução não foi concluída\. As alterações foram revertidas\./i,
  },
  {
    status: "failed",
    notification: /A aprovação falhou\. A transação terminou em estado de falha\./i,
  },
]) {
  test(`aprovação trata corretamente o resultado ${scenario.status}`, async () => {
    const id = `RESULT-${scenario.status}`;
    const harness = createHarness(
      [makeTask(id, "2026-10-31T10:00:00Z")],
      {
        postResponses: {
          [`/approve/${id}`]: {
            data: { status: scenario.status },
          },
        },
      }
    );

    await harness.api.selectTask(id);
    await harness.api.decideTask("approve");

    assert.equal(harness.api.state.busy, false);
    assert.equal(harness.api.state.selectedTask.status, scenario.status);
    assert.equal(harness.api.state.pendingApprovalId, null);
    assert.equal(harness.elements["approval-actions"].hidden, true);
    assert.match(harness.elements.notification.textContent, scenario.notification);

    const postCount = harness.requests.filter(
      (request) => request.url === `/approve/${id}`
    ).length;

    await harness.api.decideTask("approve");

    assert.equal(
      harness.requests.filter((request) => request.url === `/approve/${id}`).length,
      postCount,
      "Um resultado final não pode gerar uma segunda aprovação."
    );
  });
}

test("aprovação concluída com falha no GET individual mantém estado local e bloqueia repetição", async () => {
  const id = "INDIVIDUAL-FAIL";
  const harness = createHarness(
    [makeTask(id, "2026-10-31T10:00:00Z")],
    {
      taskRequestFailures: {
        [id]: {
          status: 503,
          message: "Detalhes temporariamente indisponíveis.",
        },
      },
    }
  );

  await harness.api.selectTask(id);
  await harness.api.decideTask("approve");

  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.api.state.selectedTaskId, id);
  assert.equal(harness.api.state.selectedTask.status, "executing");
  assert.equal(harness.api.state.pendingApprovalId, null);
  assert.equal(harness.elements["approval-actions"].hidden, true);

  assert.match(
    harness.elements.notification.textContent,
    /Não foi possível carregar a tarefa: Detalhes temporariamente indisponíveis\./i
  );

  const postCount = harness.requests.filter(
    (request) => request.url === `/approve/${id}`
  ).length;

  await harness.api.decideTask("approve");

  assert.equal(
    harness.requests.filter((request) => request.url === `/approve/${id}`).length,
    postCount,
    "A falha de sincronização não pode permitir repetir a aprovação."
  );
});

test("aprovação concluída no servidor com falha na sincronização informa resultado e bloqueia repetição", async () => {
  const harness = createHarness(
    [makeTask("REC", "2026-10-31T10:00:00Z")],
    {
      taskListFailures: [
        { status: 503, message: "Lista temporariamente indisponível." },
      ],
    }
  );
  await harness.api.selectTask("REC");

  await harness.api.decideTask("approve");

  assert.ok(harness.requests.some(
    (item) => item.url === "/approve/REC" && item.options.method === "POST"
  ));
  assert.equal(
    harness.requests.filter((item) => item.url === "/tasks").length,
    2,
    "Esperava a carga inicial e uma atualização posterior à aprovação."
  );
  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.api.state.selectedTaskId, "REC");
  assert.equal(harness.api.state.selectedTask.status, "executing");
  assert.equal(harness.api.state.pendingApprovalId, null);
  assert.equal(harness.elements["approval-actions"].hidden, true);
  assert.match(
    harness.elements.notification.textContent,
    /aprovação foi concluída, mas não foi possível sincronizar a interface: Lista temporariamente indisponível\./i
  );

  const postCount = harness.requests.filter(
    (item) => item.url === "/approve/REC"
  ).length;
  await harness.api.decideTask("approve");
  assert.equal(
    harness.requests.filter((item) => item.url === "/approve/REC").length,
    postCount,
    "Uma aprovação já concluída não pode ser repetida pela interface."
  );
});

test("rejeição concluída no servidor com falha na sincronização bloqueia repetição", async () => {
  const harness = createHarness(
    [makeTask("REJ", "2026-10-31T10:00:00Z")],
    {
      taskListFailures: [
        { status: 503, message: "Lista temporariamente indisponível." },
      ],
    }
  );
  await harness.api.selectTask("REJ");

  await harness.api.decideTask("reject");

  assert.ok(harness.requests.some(
    (item) => item.url === "/reject/REJ" && item.options.method === "POST"
  ));
  assert.equal(harness.api.state.busy, false);
  assert.equal(harness.api.state.pendingApprovalId, null);
  assert.equal(harness.elements["approval-actions"].hidden, true);
  assert.match(
    harness.elements.notification.textContent,
    /rejeição foi concluída, mas não foi possível sincronizar a interface: Lista temporariamente indisponível\./i
  );

  const postCount = harness.requests.filter(
    (item) => item.url === "/reject/REJ"
  ).length;
  await harness.api.decideTask("reject");
  assert.equal(
    harness.requests.filter((item) => item.url === "/reject/REJ").length,
    postCount,
    "Uma rejeição já concluída não pode ser repetida pela interface."
  );
});

test("integração HTTP real: criação, aprovação e rejeição", { timeout: 120000 }, async () => {
  const { spawn, execFileSync } = require("node:child_process");
  const os = require("node:os");

  const repoRoot = path.resolve(__dirname, "..");
  const projectRoot = fs.mkdtempSync(
    path.join(os.tmpdir(), "devagent-http-integration-")
  );

  let server = null;
  let stderr = "";

  try {
    execFileSync("git", ["init"], {
      cwd: projectRoot,
      stdio: "pipe",
    });
    execFileSync("git", ["config", "user.email", "test@devagent.local"], {
      cwd: projectRoot,
      stdio: "pipe",
    });
    execFileSync("git", ["config", "user.name", "DevAgent Integration Test"], {
      cwd: projectRoot,
      stdio: "pipe",
    });

    const python = process.env.PYTHON || "python";
    const pythonEnv = {
      ...process.env,
      DEVAGENT_AI: "mock",
      PYTHONPATH: [
        repoRoot,
        process.env.PYTHONPATH,
      ].filter(Boolean).join(path.delimiter),
    };

    server = spawn(
      python,
      [path.join(repoRoot, "tests/http_integration_server.py"), projectRoot],
      {
        cwd: projectRoot,
        env: pythonEnv,
        stdio: ["ignore", "pipe", "pipe"],
      }
    );

    let baseUrl;

    try {
      baseUrl = await new Promise((resolve, reject) => {
        let stdout = "";
        let settled = false;

        const timeout = setTimeout(() => {
          if (settled) return;
          settled = true;
          reject(new Error(
            `Timeout aguardando servidor HTTP. stderr: ${stderr}`
          ));
        }, 20000);

        const finish = (error, value) => {
          if (settled) return;
          settled = true;
          clearTimeout(timeout);
          if (error) reject(error);
          else resolve(value);
        };

        server.stdout.on("data", (chunk) => {
          stdout += chunk.toString();
          const newline = stdout.indexOf("\n");
          if (newline < 0) return;

          try {
            const ready = JSON.parse(stdout.slice(0, newline));
            assert.ok(
              Number.isInteger(ready.port) && ready.port > 0,
              "O servidor informou uma porta inválida."
            );
            finish(null, `http://127.0.0.1:${ready.port}`);
          } catch (error) {
            finish(new Error(
              `Resposta inicial inválida do servidor: ${stdout}\n${stderr}\n${error.message}`
            ));
          }
        });

        server.stderr.on("data", (chunk) => {
          stderr += chunk.toString();
        });

        server.once("error", (error) => {
          finish(new Error(`Falha ao iniciar servidor auxiliar: ${error.message}`));
        });

        server.once("exit", (code, signal) => {
          finish(new Error(
            `Servidor encerrou antes de ficar pronto. code=${code}, signal=${signal}. stderr: ${stderr}`
          ));
        });
      });
    } catch (error) {
      if (server && server.exitCode === null && server.signalCode === null) {
        server.kill("SIGTERM");
      }
      throw error;
    }

    const realRequests = [];
    const harness = createHarness([], {
      fetchImpl: async (url, options = {}) => {
        realRequests.push({
          url,
          method: options.method || "GET",
        });
        return fetch(`${baseUrl}${url}`, options);
      },
    });

    await harness.api.initialize();

    assert.ok(
      realRequests.some((request) => request.url === "/health"),
      "O frontend não consultou /health."
    );
    assert.ok(
      realRequests.some((request) => request.url === "/tasks"),
      "O frontend não consultou /tasks durante a inicialização."
    );

    // Criação real de uma tarefa pela submissão do formulário.
    harness.elements.instruction.value =
      'Crie arquivo integration_created.py contendo print("INTEGRATION")';

    const submit = harness.elements["instruction-form"].listeners.submit;
    assert.equal(typeof submit, "function");

    await submit({ preventDefault() {} });

    const createdId = harness.api.state.selectedTask?.approval_id;
    assert.ok(createdId, "A API não criou uma tarefa selecionável.");
    assert.equal(harness.api.state.selectedTask.status, "pending");

    assert.ok(
      realRequests.some(
        (request) => request.url === "/plan" && request.method === "POST"
      ),
      "O frontend não enviou POST /plan."
    );

    // Aprovação real: execução, testes e commit no projeto temporário.
    await harness.api.decideTask("approve");

    assert.equal(
      harness.api.state.selectedTask?.status,
      "committed",
      `A aprovação não terminou em committed. Notificação: ${harness.elements.notification.textContent}. stderr: ${stderr}`
    );

    const diagnosticResponse = await fetch(`${baseUrl}/tasks/${encodeURIComponent(createdId)}/diagnostic`);
    assert.equal(diagnosticResponse.status, 200);
    assert.equal((await diagnosticResponse.json()).category, "completed");

    const createdFile = path.join(projectRoot, "integration_created.py");
    assert.ok(
      fs.existsSync(createdFile),
      "O arquivo aprovado não foi criado no projeto temporário."
    );
    assert.match(
      fs.readFileSync(createdFile, "utf8"),
      /INTEGRATION/
    );

    execFileSync("git", ["ls-files", "--error-unmatch", "integration_created.py"], {
      cwd: projectRoot,
      stdio: "pipe",
    });

    assert.ok(
      realRequests.some(
        (request) => request.url === `/approve/${encodeURIComponent(createdId)}`
          && request.method === "POST"
      ),
      "O frontend não enviou a aprovação à API real."
    );

    // Segunda tarefa: rejeição real, sem criar o arquivo solicitado.
    harness.elements.instruction.value =
      'Crie arquivo integration_rejected.py contendo print("REJECTED")';

    await submit({ preventDefault() {} });

    const rejectedId = harness.api.state.selectedTask?.approval_id;
    assert.ok(rejectedId, "A segunda tarefa não foi criada.");
    assert.notEqual(rejectedId, createdId);

    await harness.api.decideTask("reject");

    assert.equal(
      harness.api.state.selectedTask?.status,
      "rejected"
    );
    assert.equal(
      fs.existsSync(path.join(projectRoot, "integration_rejected.py")),
      false,
      "A rejeição não deveria criar o arquivo."
    );

    assert.ok(
      realRequests.some(
        (request) => request.url === `/reject/${encodeURIComponent(rejectedId)}`
          && request.method === "POST"
      ),
      "O frontend não enviou a rejeição à API real."
    );

    const rejectedResponse = await fetch(
      `${baseUrl}/tasks/${encodeURIComponent(rejectedId)}`
    );
    assert.equal(rejectedResponse.status, 200);

    const rejectedTask = await rejectedResponse.json();
    assert.equal(rejectedTask.status, "rejected");

    console.log("Integração HTTP real validada: criação, commit e rejeição.");
  } finally {
    if (server && server.exitCode === null && server.signalCode === null) {
      const exited = new Promise((resolve) => {
        server.once("exit", resolve);
      });

      server.kill("SIGTERM");

      await Promise.race([
        exited,
        new Promise((resolve) => {
          const timer = setTimeout(() => {
            if (server.exitCode === null && server.signalCode === null) {
              server.kill("SIGKILL");
            }
            resolve();
          }, 5000);
          timer.unref();
        }),
      ]);
    }

    fs.rmSync(projectRoot, {
      recursive: true,
      force: true,
    });
  }
});

test("erro permanece visível durante polling e fecha por botão acessível", async () => {
  const h = createHarness([]);
  h.api.showNotification("Erro persistente.", "error");
  const notification = h.elements.notification;
  const close = notification.children.find((node) => node.tagName === "BUTTON");
  assert.ok(close);
  assert.equal(close.textContent, "Fechar");
  assert.equal(close.type, "button");
  assert.equal(close.disabled, false);
  assert.equal(h.api.state.notificationTimer, null);
  assert.equal(h.pendingNotificationTimer(), null);
  h.api.startPolling();
  await h.runPollingTimer();
  await h.runPollingTimer();
  assert.equal(notification.hidden, false);
  assert.equal(h.pendingPollingTimers(), 1);
  close.listeners.click();
  assert.equal(notification.hidden, true);
  assert.equal(h.pendingPollingTimers(), 1);
});

for (const type of ["success", "info"]) {
  test(`${type} desaparece após cinco segundos`, () => {
    const h = createHarness([]);
    h.api.showNotification("Mensagem temporária.", type);
    assert.equal(h.elements.notification.hidden, false);
    assert.equal(h.pendingNotificationTimer().delay, 5000);
    assert.equal(h.elements.notification.children.length, 0);
    h.runNotificationTimer();
    assert.equal(h.elements.notification.hidden, true);
    assert.equal(h.api.state.notificationTimer, null);
  });

  test(`erro cancela temporizador anterior de ${type}`, () => {
    const h = createHarness([]);
    h.api.showNotification("Mensagem temporária.", type);
    const previousTimerId = h.api.state.notificationTimer;
    h.api.showNotification("Erro persistente.", "error");
    assert.equal(h.pendingNotificationTimer(), null);
    assert.equal(h.api.state.notificationTimer, null);
    h.api.state.notificationTimer = previousTimerId;
    assert.equal(h.pendingNotificationTimer(), null);
    h.api.state.notificationTimer = null;
    assert.equal(h.elements.notification.hidden, false);
  });
}

test("fechar erro permite apresentar nova notificação temporária", () => {
  const h = createHarness([]);
  h.api.showNotification("Erro persistente.", "error");
  h.elements.notification.children[0].listeners.click();
  assert.equal(h.elements.notification.hidden, true);
  h.api.showNotification("Operação concluída.", "success");
  assert.equal(h.elements.notification.hidden, false);
  assert.equal(h.pendingNotificationTimer().delay, 5000);
  h.runNotificationTimer();
  assert.equal(h.elements.notification.hidden, true);
});

// Regressões do painel de conteúdo proposto.
require("./test_plan_preview.test.js");

for (const [provider, expected] of [
  ['Codex', 'Codex'], ['Mock', 'Mock'], ['Groq', 'Groq'],
  [undefined, 'Desconhecido'], [null, 'Desconhecido'],
  ['Outro', 'Desconhecido'], ['<img src=x onerror=alert(1)>', 'Desconhecido'],
]) {
  test(`health mostra o provedor ${String(provider)} como ${expected}`, async () => {
    const harness = createHarness([], { healthData: { status: 'ok', ai_provider: provider } });
    assert.equal(await harness.api.checkHealth(), true);
    assert.equal(harness.elements['ai-provider'].textContent, expected);
    assert.equal(harness.elements['api-status'].textContent, 'Online');
  });
}

test('falha de health limpa o provedor anterior e a recuperação atualiza o valor', async () => {
  const options = { healthData: { status: 'ok', ai_provider: 'Codex' } };
  const harness = createHarness([], options);
  await harness.api.checkHealth();
  assert.equal(harness.elements['ai-provider'].textContent, 'Codex');
  options.healthError = 'Failed to fetch';
  assert.equal(await harness.api.checkHealth(), false);
  assert.equal(harness.elements['api-status'].textContent, 'Offline');
  assert.equal(harness.elements['ai-provider'].textContent, 'Indisponível');
  options.healthError = null;
  options.healthData = { status: 'ok', ai_provider: 'Groq' };
  assert.equal(await harness.api.checkHealth(), true);
  assert.equal(harness.elements['ai-provider'].textContent, 'Groq');
});

test('polling consulta health e atualiza o provedor sem depender de reload', async () => {
  const options = { healthData: { status: 'ok', ai_provider: 'Codex' } };
  const harness = createHarness([], options);
  harness.api.startPolling();
  await harness.runPollingTimer();
  assert.equal(harness.elements['ai-provider'].textContent, 'Codex');
  options.healthData = { status: 'ok', ai_provider: 'Mock' };
  await harness.runPollingTimer();
  assert.equal(harness.elements['ai-provider'].textContent, 'Mock');
  assert.equal(harness.requests.filter(request => request.url === '/health').length, 2);
  assert.equal(harness.pendingPollingTimers(), 1);
});

test('estado inválido em health não mantém identificação de IA online', async () => {
  const harness = createHarness([], { healthData: { status: 'failed', ai_provider: 'Codex' } });
  assert.equal(await harness.api.checkHealth(), false);
  assert.equal(harness.elements['api-status'].textContent, 'Offline');
  assert.equal(harness.elements['ai-provider'].textContent, 'Indisponível');
});

function findSummaryNode(node, predicate) {
  if (predicate(node)) return node;
  for (const child of node.children) {
    const found = findSummaryNode(child, predicate);
    if (found) return found;
  }
  return null;
}

function summaryButton(harness) {
  return findSummaryNode(harness.elements["operation-details"],
    (node) => node.tagName === "BUTTON" && node.textContent === "Copiar resumo");
}

function summaryTask(extra = {}) {
  return makeTask("163", "2026-11-06T14:11:43Z", {
    status: "committed", transaction_id: "transaction-163",
    tests: { success: true, returncode: 0, stdout: "PRIVATE_OUTPUT", stderr: "PRIVATE_ERROR" },
    repair_attempts: 0, git: { commit_hash: "05f357c", message: "PRIVATE_MESSAGE" },
    instruction: "PRIVATE_INSTRUCTION", metadata: { secret: "PRIVATE_METADATA" },
    ...extra,
  });
}

const EXPECTED_SUMMARY = [
  "Identificador: 163", "Estado: Concluída", "Transação: transaction-163",
  "Sucesso dos testes: Sim", "Código de saída: 0", "Tentativas de reparo: 0",
  "Commit: 05f357c",
].join("\n");

test("copiar resumo contém somente os sete campos públicos solicitados", async () => {
  const h = createHarness([]);
  h.api.renderOperation(summaryTask());
  const button = summaryButton(h);
  assert.equal(button.type, "button");
  await button.listeners.click();
  assert.deepEqual(h.copied, [EXPECTED_SUMMARY]);
  assert.equal(h.elements.notification.textContent, "Resumo copiado.");
  assert.equal(h.elements.notification.className, "notification success");
  assert.equal(h.requests.length, 0);
});

test("copiar resumo informa campos ausentes sem usar task_id como approval_id", async () => {
  const h = createHarness([]);
  h.api.renderOperation({ task_id: "INTERNAL_ID" });
  await summaryButton(h).listeners.click();
  assert.equal(h.copied[0], ["Identificador", "Estado", "Transação", "Sucesso dos testes",
    "Código de saída", "Tentativas de reparo", "Commit"]
    .map((label) => `${label}: Não informado`).join("\n"));
});

test("copiar resumo preserva resultado falso e valores numéricos zero", async () => {
  const h = createHarness([]);
  h.api.renderOperation(summaryTask({ status: "rolled_back", tests: { success: false, returncode: 1 } }));
  await summaryButton(h).listeners.click();
  assert.equal(h.copied[0], EXPECTED_SUMMARY.replace("Concluída", "Revertida")
    .replace("testes: Sim", "testes: Não").replace("saída: 0", "saída: 1"));
});

test("copiar resumo não serializa objetos inesperados nos campos permitidos", async () => {
  const h = createHarness([]);
  h.api.renderOperation({ approval_id: {}, status: null, transaction_id: {},
    tests: { success: "false", returncode: {} }, repair_attempts: {}, git: { commit_hash: {} } });
  await summaryButton(h).listeners.click();
  assert.equal(h.copied[0].split("Não informado").length - 1, 7);
  assert.equal(h.copied[0].includes("[object Object]"), false);
});

test("copiar resumo acompanha a tarefa selecionada sem enviar POST", async () => {
  const tasks = [summaryTask(), summaryTask({ approval_id: "164", status: "pending", tests: null, git: null })];
  const h = createHarness(tasks);
  await h.api.selectTask("163");
  await summaryButton(h).listeners.click();
  await h.api.selectTask("164");
  await summaryButton(h).listeners.click();
  assert.equal(h.copied[0], EXPECTED_SUMMARY);
  assert.match(h.copied[1], /^Identificador: 164\nEstado: Pendente\n/);
  assert.equal(h.api.state.selectedTaskId, "164");
  assert.equal(h.requests.some((request) => request.options.method === "POST"), false);
});

test("polling atualiza resumo e preserva prévia aberta e aprovação pendente", async () => {
  const task = summaryTask({ status: "pending", tests: null, git: null,
    plan: { objective: "Plano", changes: [{ change_type: "create", path: "example.py", content: "VALUE = 1\n" }], tests: [], risks: [] } });
  const tasks = [task];
  const h = createHarness(tasks);
  await h.api.selectTask("163");
  const details = findSummaryNode(h.elements["plan-content"], (node) => node.tagName === "DETAILS");
  details.open = true;
  const pre = findSummaryNode(details, (node) => node.tagName === "PRE");
  task.repair_attempts = 1;
  h.api.startPolling();
  await h.runPollingTimer();
  await summaryButton(h).listeners.click();
  assert.match(h.copied[0], /Tentativas de reparo: 1/);
  assert.equal(findSummaryNode(h.elements["plan-content"], (node) => node.tagName === "DETAILS"), details);
  assert.equal(details.open, true);
  assert.equal(findSummaryNode(details, (node) => node.tagName === "PRE"), pre);
  assert.equal(h.api.state.pendingApprovalId, "163");
  assert.equal(h.elements["approval-actions"].hidden, false);
  assert.equal(h.pendingPollingTimers(), 1);
});

test("nenhuma operação selecionada não apresenta botão copiar resumo", () => {
  const h = createHarness([]);
  h.api.renderOperation(summaryTask());
  assert.ok(summaryButton(h));
  h.api.renderOperation(null);
  assert.equal(summaryButton(h), null);
  assert.equal(h.elements["operation-details"].textContent, "Nenhuma operação selecionada.");
});

for (const options of [{ clipboardFails: true }, { noClipboard: true }]) {
  test(`copiar resumo usa alternativa quando clipboard ${options.noClipboard ? "está ausente" : "é negado"}`, async () => {
    const h = createHarness([], options);
    let focusRestored = false;
    h.document.activeElement.focus = () => { focusRestored = true; };
    h.api.renderOperation(summaryTask());
    await summaryButton(h).listeners.click();
    assert.deepEqual(h.copied, [EXPECTED_SUMMARY]);
    assert.equal(h.document.body.children.length, 0);
    assert.equal(focusRestored, true);
    assert.equal(h.elements.notification.textContent, "Resumo copiado.");
  });
}

test("falha ao copiar resumo preserva operação e permite nova tentativa", async () => {
  const options = { clipboardFails: true, fallbackFails: true };
  const h = createHarness([summaryTask()], options);
  await h.api.selectTask("163");
  const button = summaryButton(h);
  await button.listeners.click();
  assert.deepEqual(h.copied, []);
  assert.equal(h.elements.notification.className, "notification error");
  assert.equal(h.elements.notification.textContent, "Não foi possível copiar o resumo. Tente novamente.");
  assert.equal(h.api.state.selectedTaskId, "163");
  assert.equal(h.api.state.selectedTask.status, "committed");
  assert.equal(h.document.body.children.length, 0);
  assert.equal(button.disabled, false);
  options.clipboardFails = false;
  await button.listeners.click();
  assert.deepEqual(h.copied, [EXPECTED_SUMMARY]);
});

test("cópia pendente ignora clique repetido sem ocupar o fluxo de aprovação", async () => {
  let finish;
  const h = createHarness([], { clipboardWrite: () => new Promise((resolve) => { finish = resolve; }) });
  h.api.renderOperation(summaryTask());
  const button = summaryButton(h);
  const copying = button.listeners.click();
  assert.equal(button.disabled, true);
  assert.equal(h.api.state.busy, false);
  await button.listeners.click();
  assert.equal(h.copied.length, 0);
  finish();
  await copying;
  assert.deepEqual(h.copied, [EXPECTED_SUMMARY]);
  assert.equal(button.disabled, false);
});

function diagnosticButton(h) {
  return findSummaryNode(h.elements['operation-details'],
    node => node.tagName === 'BUTTON' && ['Diagnóstico', 'Analisando…'].includes(node.textContent));
}
function diagnosticPanel(h) {
  return findSummaryNode(h.elements['operation-details'], node => node.className === 'diagnostic-panel');
}
function publicReport(id = '163') {
  return { approval_id: id, summary: 'Operação concluída.', evidence: ['Testes aprovados.'],
    next_steps: ['Confira o resultado.'], limitations: 'Consulta somente de leitura.' };
}
function reportResponse(report, status = 200) {
  return { ok: status === 200, status, async text() { return JSON.stringify(report); } };
}
function allText(node) {
  return [node.textContent, ...node.children.map(allText)].join('\n');
}

test('diagnóstico usa apenas GET e mantém seleção, aprovação, prévia e cópia', async () => {
  const task = summaryTask({ status: 'pending', plan: { objective: 'Plano',
    changes: [{ path: 'example.py', change_type: 'create', content: 'VALUE = 1\n' }], tests: [], risks: [] } });
  const h = createHarness([task], { diagnosticData: publicReport() });
  await h.api.selectTask('163');
  const preview = findSummaryNode(h.elements['plan-content'], node => node.tagName === 'DETAILS');
  preview.open = true;
  const copy = summaryButton(h);
  const button = diagnosticButton(h);
  assert.equal(button.type, 'button');
  await button.listeners.click();
  assert.equal(h.api.state.busy, false);
  assert.equal(h.api.state.pendingApprovalId, '163');
  assert.equal(h.api.state.selectedTaskId, '163');
  assert.equal(h.elements['approval-actions'].hidden, false);
  assert.equal(preview.open, true);
  assert.equal(diagnosticPanel(h).hidden, false);
  assert.match(allText(diagnosticPanel(h)), /Operação concluída/);
  assert.equal(diagnosticPanel(h).attributes['aria-live'], 'polite');
  assert.equal(h.requests.at(-1).url, '/tasks/163/diagnostic');
  assert.equal(h.requests.some(r => r.options.method === 'POST'), false);
  assert.equal(summaryButton(h), copy);
  await copy.listeners.click();
  assert.match(h.copied[0], /^Identificador: 163/);
  h.api.startPolling();
  await h.runPollingTimer();
  assert.match(allText(diagnosticPanel(h)), /Operação concluída/);
  assert.equal(h.pendingPollingTimers(), 1);
  assert.equal(findSummaryNode(h.elements['plan-content'], node => node.tagName === 'DETAILS'), preview);
});

test('diagnóstico pendente evita duplicação e aceita resposta após polling dos mesmos dados', async () => {
  let finish;
  const task = summaryTask();
  const h = createHarness([task], { diagnosticResponse: () => new Promise(resolve => { finish = resolve; }) });
  await h.api.selectTask('163');
  const first = diagnosticButton(h).listeners.click();
  assert.equal(diagnosticButton(h).disabled, true);
  assert.equal(h.api.state.busy, false);
  h.api.startPolling();
  await h.runPollingTimer();
  assert.equal(diagnosticButton(h).disabled, true);
  await diagnosticButton(h).listeners.click();
  assert.equal(h.requests.filter(r => r.url.endsWith('/diagnostic')).length, 1);
  finish(reportResponse(publicReport()));
  await first;
  assert.equal(diagnosticButton(h).disabled, false);
  assert.equal(diagnosticPanel(h).hidden, false);
});

for (const staleError of [false, true]) {
  test(`troca de seleção ignora ${staleError ? 'erro' : 'resposta'} antiga do diagnóstico`, async () => {
    let finish;
    const h = createHarness([summaryTask(), summaryTask({ approval_id: '164' })], {
      diagnosticResponse: () => new Promise(resolve => { finish = resolve; }),
    });
    await h.api.selectTask('163');
    const first = diagnosticButton(h).listeners.click();
    await h.api.selectTask('164');
    const before = h.elements.notification.textContent;
    finish(reportResponse(staleError ? { error: 'erro antigo' } : publicReport(), staleError ? 503 : 200));
    await first;
    assert.equal(h.api.state.selectedTaskId, '164');
    assert.equal(diagnosticPanel(h).hidden, true);
    assert.equal(diagnosticButton(h).disabled, false);
    assert.equal(h.elements.notification.textContent, before);
  });
}

test('mudança nos dados invalida relatório e resposta pendente, mesmo na mesma tarefa', async () => {
  let finish;
  const options = { diagnosticData: publicReport() };
  const task = summaryTask();
  const h = createHarness([task], options);
  await h.api.selectTask('163');
  await diagnosticButton(h).listeners.click();
  options.diagnosticResponse = () => new Promise(resolve => { finish = resolve; });
  const second = diagnosticButton(h).listeners.click();
  task.tests.returncode = -15;
  h.api.startPolling();
  await h.runPollingTimer();
  assert.equal(diagnosticPanel(h).hidden, true);
  finish(reportResponse(publicReport()));
  await second;
  assert.equal(diagnosticPanel(h).hidden, true);
});

for (const report of [null, publicReport('other'), { ...publicReport(), evidence: [{}] },
  { ...publicReport(), summary: 'x'.repeat(1001) }, { ...publicReport(), next_steps: [] }]) {
  test(`resposta inválida do diagnóstico é recusada: ${JSON.stringify(report).slice(0, 60)}`, async () => {
    const h = createHarness([summaryTask()], { diagnosticData: report });
    await h.api.selectTask('163');
    await diagnosticButton(h).listeners.click();
    assert.equal(diagnosticPanel(h).hidden, true);
    assert.equal(h.elements.notification.className, 'notification error');
    assert.equal(h.api.state.notificationTimer, null);
    assert.equal(diagnosticButton(h).disabled, false);
  });
}

test('falha de rede no diagnóstico permite nova tentativa sem bloquear aprovação', async () => {
  const options = { diagnosticResponse: async () => { throw new TypeError('Sem conexão.'); } };
  const h = createHarness([summaryTask({ status: 'pending' })], options);
  await h.api.selectTask('163');
  await diagnosticButton(h).listeners.click();
  assert.match(h.elements.notification.textContent, /Sem conexão/);
  assert.equal(h.api.state.pendingApprovalId, '163');
  assert.equal(h.elements['approve-button'].disabled, false);
  options.diagnosticResponse = async () => reportResponse(publicReport());
  await diagnosticButton(h).listeners.click();
  assert.equal(diagnosticPanel(h).hidden, false);
});

test('diagnóstico renderiza texto literal e limpa o relatório quando não há seleção', async () => {
  const report = { ...publicReport(), summary: '<img src=x onerror=alert(1)>' };
  const h = createHarness([summaryTask()], { diagnosticData: report });
  await h.api.selectTask('163');
  await diagnosticButton(h).listeners.click();
  assert.match(allText(diagnosticPanel(h)), /<img src=x/);
  assert.equal(findSummaryNode(diagnosticPanel(h), node => node.tagName === 'IMG'), null);
  h.api.renderOperation(null);
  assert.equal(diagnosticButton(h), null);
  assert.equal(h.api.state.diagnosticContext, null);
});

function investigationButton(h) {
  return findSummaryNode(h.elements['operation-details'],
    node => node.tagName === 'BUTTON' && ['Investigar com IA', 'Investigando…'].includes(node.textContent));
}
function investigationPanel(h) {
  return findSummaryNode(h.elements['operation-details'], node => node.className === 'diagnostic-panel investigation-panel');
}
function investigationJob(id = '163', status = 'completed') {
  return { approval_id: id, job_id: 'a'.repeat(32), status, provider: 'Codex', error: null,
    report: status === 'completed' ? { summary: 'Há dados insuficientes para comprovar a causa.',
      hypotheses: [{ cause: 'Pode ter ocorrido interrupção externa.', confidence: 'baixa', evidence: ['diagnostic'] }],
      next_steps: ['Confira os registros antes de propor correção.'] } : null };
}
function investigationCopy(h) {
  return findSummaryNode(investigationPanel(h), node => node.tagName === 'BUTTON' && node.textContent === 'Copiar investigação');
}

const PUBLIC_INVESTIGATION_ERRORS = [
  'timeout: O tempo de espera da investigação foi excedido. Tente novamente.',
  'transport_error: A comunicação com o Codex falhou. Tente novamente.',
  'invalid_response: A IA retornou uma resposta inválida. Tente novamente.',
];
const PRIVATE_INVESTIGATION_ERROR = 'PRIVATE_EXCEPTION /private/project token=PRIVATE_CREDENTIAL prompt=PRIVATE_PROMPT raw=PRIVATE_RESPONSE';
const INVESTIGATION_FAILURE_CASES = [
  ...PUBLIC_INVESTIGATION_ERRORS.map(error => ({ name: error.split(':')[0], error, expected: error })),
  { name: 'ausente', absent: true },
  { name: 'null', error: null },
  { name: 'objeto', error: { message: PRIVATE_INVESTIGATION_ERROR } },
  { name: 'número', error: 176 },
  { name: 'booleano', error: true },
  { name: 'array', error: [PUBLIC_INVESTIGATION_ERRORS[0]] },
  { name: 'texto arbitrário', error: PRIVATE_INVESTIGATION_ERROR },
  { name: 'categoria isolada', error: 'timeout' },
  { name: 'espaço adicional', error: PUBLIC_INVESTIGATION_ERRORS[0] + ' ' },
  { name: 'prefixo adicional', error: 'PRIVATE_PREFIX ' + PUBLIC_INVESTIGATION_ERRORS[1] },
  { name: 'conteúdo privado anexado', error: PUBLIC_INVESTIGATION_ERRORS[2] + PRIVATE_INVESTIGATION_ERROR },
];

for (const phase of ['POST', 'GET']) {
  for (const scenario of INVESTIGATION_FAILURE_CASES) {
    test(`falha de investigação ${phase}: ${scenario.name}`, async () => {
      const task = summaryTask({ instruction: 'Operação pública', tests: { success: false, returncode: 1 }, git: null, status: 'pending' });
      let current = investigationJob('163', phase === 'POST' ? 'failed' : 'running');
      const h = createHarness([task], { investigationResponse: async () => reportResponse(current) });
      await h.api.selectTask('163');
      const context = h.api.state.investigationContext;
      const failed = { ...investigationJob('163', 'failed'), error: scenario.error };
      if (scenario.absent) delete failed.error;
      if (phase === 'POST') current = failed;
      h.api.startPolling();
      await investigationButton(h).listeners.click();
      if (phase === 'GET') {
        assert.equal(context.running, true);
        assert.equal(investigationButton(h).disabled, true);
        current = failed;
        await h.runPollingTimer();
      }
      const prefix = phase === 'POST'
        ? 'Não foi possível investigar com IA: '
        : 'Não foi possível atualizar a investigação: ';
      assert.equal(h.elements.notification.textContent, prefix + (scenario.expected || 'A investigação não foi concluída. Tente novamente.'));
      assert.equal(h.elements.notification.className, 'notification error');
      assert.equal(h.api.state.notificationTimer, null);
      assert.equal(h.api.state.investigationContext, context);
      assert.equal(context.running, false);
      assert.equal(context.jobId, null);
      assert.equal(investigationButton(h).disabled, false);
      assert.equal(investigationButton(h).textContent, 'Investigar com IA');
      assert.equal(investigationPanel(h).hidden, true);
      assert.equal(h.api.state.selectedTaskId, '163');
      assert.equal(h.api.state.pendingApprovalId, '163');
      assert.equal(h.api.state.busy, false);
      assert.equal(h.elements['approve-button'].disabled, false);
      assert.doesNotMatch(allText(h.elements.notification) + allText(h.elements['operation-details']), /PRIVATE_|\/private\/project/);
      assert.deepEqual(h.copied, []);
      const before = h.requests.filter(r => r.url.includes('/investigation')).length;
      const notification = h.elements.notification.textContent;
      await h.runPollingTimer();
      await h.runPollingTimer();
      assert.equal(h.requests.filter(r => r.url.includes('/investigation')).length, before);
      assert.equal(h.elements.notification.textContent, notification);
      assert.equal(h.api.state.investigationContext, context);
      assert.equal(h.pendingPollingTimers(), 1);
      current = { ...investigationJob(), job_id: 'b'.repeat(32) };
      await investigationButton(h).listeners.click();
      assert.equal(h.requests.filter(r => r.options.method === 'POST' && r.url.endsWith('/investigation')).length, 2);
      assert.equal(h.api.state.investigationContext, context);
      assert.equal(context.jobId, 'b'.repeat(32));
      assert.equal(investigationPanel(h).hidden, false);
      assert.equal(investigationButton(h).disabled, false);
      await investigationCopy(h).listeners.click();
      assert.equal(h.copied.length, 1);
      assert.doesNotMatch(h.copied[0], /PRIVATE_/);
    });
  }
}

for (const phase of ['POST', 'GET']) {
  for (const change of ['seleção', 'evidência']) {
    test(`falha antiga de investigação ${phase} é ignorada após mudar ${change}`, async () => {
      let finish;
      const task = summaryTask();
      const options = { investigationData: investigationJob('163', 'running') };
      const h = createHarness([task, summaryTask({ approval_id: '164' })], options);
      await h.api.selectTask('163');
      const oldContext = h.api.state.investigationContext;
      if (phase === 'GET') await investigationButton(h).listeners.click();
      options.investigationResponse = () => new Promise(resolve => { finish = resolve; });
      h.api.startPolling();
      const pending = phase === 'POST'
        ? investigationButton(h).listeners.click()
        : h.runPollingTimer();
      if (phase === 'GET') await new Promise(resolve => setImmediate(resolve));
      assert.equal(typeof finish, 'function');
      if (change === 'seleção') await h.api.selectTask('164');
      else {
        task.tests.stderr = 'Evidência atualizada';
        await h.api.selectTask('163');
      }
      const currentContext = h.api.state.investigationContext;
      assert.notEqual(currentContext, oldContext);
      options.investigationResponse = async () => reportResponse({ ...investigationJob(currentContext.task.approval_id, 'running'), job_id: 'b'.repeat(32) });
      await investigationButton(h).listeners.click();
      const notification = h.elements.notification.textContent;
      finish(reportResponse({ ...investigationJob('163', 'failed'), error: PUBLIC_INVESTIGATION_ERRORS[0] }));
      await pending;
      assert.equal(h.api.state.investigationContext, currentContext);
      assert.equal(h.api.state.selectedTaskId, change === 'seleção' ? '164' : '163');
      assert.equal(currentContext.running, true);
      assert.equal(currentContext.jobId, 'b'.repeat(32));
      assert.equal(investigationButton(h).disabled, true);
      assert.equal(investigationPanel(h).hidden, true);
      assert.equal(h.elements.notification.textContent, notification);
      assert.equal(h.pendingPollingTimers(), 1);
    });
  }
}

test('GET de investigação pendente mantém identidade e impede consultas simultâneas', async () => {
  let finish;
  const options = { investigationData: investigationJob('163', 'running') };
  const h = createHarness([summaryTask()], options);
  await h.api.selectTask('163');
  await investigationButton(h).listeners.click();
  const context = h.api.state.investigationContext;
  options.investigationResponse = () => new Promise(resolve => { finish = resolve; });
  h.api.startPolling();
  const pending = h.runPollingTimer();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(typeof finish, 'function');
  assert.equal(h.api.state.investigationContext, context);
  assert.equal(context.polling, true);
  await h.api.pollTasks();
  await investigationButton(h).listeners.click();
  assert.equal(h.requests.filter(r => r.url.includes('/investigation/')).length, 1);
  assert.equal(h.requests.filter(r => r.options.method === 'POST').length, 1);
  finish(reportResponse({ ...investigationJob('163', 'failed'), error: PUBLIC_INVESTIGATION_ERRORS[1] }));
  await pending;
  assert.equal(h.api.state.investigationContext, context);
  assert.equal(context.polling, false);
  assert.equal(context.running, false);
  assert.equal(context.jobId, null);
  assert.equal(investigationButton(h).disabled, false);
  assert.equal(h.pendingPollingTimers(), 1);
});

test('investigação usa POST explícito e preserva aprovação, seleção, prévia e cópias', async () => {
  const task = summaryTask({ status: 'pending', plan: { objective: 'Plano', changes: [
    { path: 'example.py', change_type: 'create', content: 'VALUE = 1\n' }], tests: [], risks: [] } });
  const h = createHarness([task], { investigationData: investigationJob() });
  await h.api.selectTask('163');
  const preview = findSummaryNode(h.elements['plan-content'], n => n.tagName === 'DETAILS');
  preview.open = true;
  const copy = summaryButton(h);
  const diagnostic = diagnosticButton(h);
  assert.equal(investigationButton(h).type, 'button');
  assert.match(allText(h.elements['operation-details']), /envia à IA/);
  await investigationButton(h).listeners.click();
  const requests = h.requests.filter(r => r.options.method === 'POST');
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/tasks/163/investigation');
  assert.equal(requests[0].options.body, '{}');
  assert.equal(requests[0].options.headers['Content-Type'], 'application/json');
  assert.equal(h.api.state.busy, false);
  assert.equal(h.api.state.pendingApprovalId, '163');
  assert.equal(h.elements['approval-actions'].hidden, false);
  assert.equal(h.elements['approve-button'].disabled, false);
  assert.equal(h.api.state.selectedTaskId, '163');
  assert.equal(preview.open, true);
  assert.equal(summaryButton(h), copy);
  assert.equal(diagnosticButton(h), diagnostic);
  assert.equal(investigationPanel(h).hidden, false);
  assert.equal(investigationPanel(h).attributes['aria-live'], 'polite');
  assert.match(allText(investigationPanel(h)), /Hipóteses da IA/);
  await investigationCopy(h).listeners.click();
  assert.equal(h.copied.length, 1);
  assert.match(h.copied[0], /hipóteses para revisão humana/);
  assert.doesNotMatch(h.copied[0], /PRIVATE/);
  assert.equal(h.elements.notification.textContent, 'Investigação copiada.');
});

test('investigação em segundo plano acompanha polling sem duplicar POST ou temporizador', async () => {
  let current = investigationJob('163', 'running');
  const h = createHarness([summaryTask()], { investigationResponse: async () => reportResponse(current) });
  await h.api.selectTask('163');
  h.api.startPolling();
  await investigationButton(h).listeners.click();
  assert.equal(investigationButton(h).disabled, true);
  await investigationButton(h).listeners.click();
  await h.runPollingTimer();
  assert.equal(h.requests.filter(r => r.options.method === 'POST').length, 1);
  assert.equal(investigationButton(h).disabled, true);
  assert.equal(h.pendingPollingTimers(), 1);
  assert.equal(h.api.state.busy, false);
  current = investigationJob();
  await h.runPollingTimer();
  assert.equal(investigationButton(h).disabled, false);
  assert.equal(investigationPanel(h).hidden, false);
  assert.equal(h.pendingPollingTimers(), 1);
  assert.ok(h.requests.some(r => r.url === '/tasks/163/investigation/' + 'a'.repeat(32)));
  const before = h.requests.filter(r => r.url.includes('/investigation/')).length;
  await h.runPollingTimer();
  assert.equal(h.requests.filter(r => r.url.includes('/investigation/')).length, before);
  assert.equal(investigationPanel(h).hidden, false);
});

for (const staleError of [false, true]) {
  test(`troca de seleção ignora ${staleError ? 'erro' : 'resposta'} antiga da investigação`, async () => {
    let finish;
    const h = createHarness([summaryTask(), summaryTask({ approval_id: '164' })], {
      investigationResponse: () => new Promise(resolve => { finish = resolve; }),
    });
    await h.api.selectTask('163');
    const first = investigationButton(h).listeners.click();
    await h.api.selectTask('164');
    const before = h.elements.notification.textContent;
    finish(reportResponse(staleError ? { error: 'erro antigo' } : investigationJob(), staleError ? 503 : 200));
    await first;
    assert.equal(h.api.state.selectedTaskId, '164');
    assert.equal(investigationPanel(h).hidden, true);
    assert.equal(investigationButton(h).disabled, false);
    assert.equal(h.elements.notification.textContent, before);
  });
}

test('resposta pendente da consulta de investigação é ignorada após mudar a seleção', async () => {
  let finish;
  const options = { investigationData: investigationJob('163', 'running') };
  const h = createHarness([summaryTask(), summaryTask({ approval_id: '164' })], options);
  await h.api.selectTask('163');
  await investigationButton(h).listeners.click();
  options.investigationResponse = () => new Promise(resolve => { finish = resolve; });
  h.api.startPolling();
  const polling = h.runPollingTimer();
  await new Promise(resolve => setImmediate(resolve));
  await h.api.selectTask('164');
  finish(reportResponse(investigationJob()));
  await polling;
  assert.equal(investigationPanel(h).hidden, true);
  assert.equal(h.api.state.selectedTaskId, '164');
});

test('mudança nos trechos públicos invalida investigação sem alterar diagnóstico por regras', async () => {
  const task = summaryTask();
  const h = createHarness([task], { investigationData: investigationJob(), diagnosticData: publicReport() });
  await h.api.selectTask('163');
  await diagnosticButton(h).listeners.click();
  await investigationButton(h).listeners.click();
  task.tests.stderr = 'Nova evidência';
  h.api.startPolling();
  await h.runPollingTimer();
  assert.equal(investigationPanel(h).hidden, true);
  assert.equal(diagnosticPanel(h).hidden, false);
});

for (const job of [null, investigationJob('other'), { ...investigationJob(), job_id: '../wrong' },
  { ...investigationJob(), status: 'unknown' }, { ...investigationJob(), provider: 'Mock' },
  { ...investigationJob(), report: null },
  { ...investigationJob(), report: { ...investigationJob().report, hypotheses: [{}] } },
  { ...investigationJob(), report: { ...investigationJob().report, next_steps: ['x'.repeat(601)] } },
  investigationJob('163', 'failed')]) {
  test(`investigação recusa resposta inválida: ${JSON.stringify(job).slice(0, 65)}`, async () => {
    const h = createHarness([summaryTask()], { investigationData: job });
    await h.api.selectTask('163');
    await investigationButton(h).listeners.click();
    assert.equal(investigationPanel(h).hidden, true);
    assert.equal(investigationButton(h).disabled, false);
    assert.equal(h.elements.notification.className, 'notification error');
    assert.equal(h.api.state.notificationTimer, null);
    assert.equal(h.api.state.busy, false);
  });
}

test('falha de consulta libera nova tentativa e não marca o serviço offline', async () => {
  const options = { investigationData: investigationJob('163', 'running') };
  const h = createHarness([summaryTask()], options);
  await h.api.selectTask('163');
  await investigationButton(h).listeners.click();
  options.investigationResponse = async () => { throw new TypeError('Falha simulada.'); };
  h.api.startPolling();
  await h.runPollingTimer();
  assert.equal(investigationButton(h).disabled, false);
  assert.equal(h.elements['api-status'].textContent, 'Online');
  assert.match(h.elements.notification.textContent, /Falha simulada/);
  options.investigationResponse = async () => reportResponse(investigationJob());
  await investigationButton(h).listeners.click();
  assert.equal(investigationPanel(h).hidden, false);
});

test('investigação rejeita identificador de consulta diferente do solicitado', async () => {
  let current = investigationJob('163', 'running');
  const h = createHarness([summaryTask()], { investigationResponse: async () => reportResponse(current) });
  await h.api.selectTask('163');
  await investigationButton(h).listeners.click();
  current = { ...investigationJob(), job_id: 'b'.repeat(32) };
  h.api.startPolling();
  await h.runPollingTimer();
  assert.equal(investigationPanel(h).hidden, true);
  assert.equal(investigationButton(h).disabled, false);
  assert.match(h.elements.notification.textContent, /Resposta de investigação inválida/);
});

test('relatório da IA usa texto literal e cópia reaproveita alternativa com foco restaurado', async () => {
  const job = investigationJob();
  job.report.summary = '<img src=x onerror=alert(1)>';
  const options = { investigationData: job, noClipboard: true };
  const h = createHarness([summaryTask()], options);
  let restored = false;
  h.document.activeElement.focus = () => { restored = true; };
  await h.api.selectTask('163');
  await investigationButton(h).listeners.click();
  assert.equal(findSummaryNode(investigationPanel(h), n => n.tagName === 'IMG'), null);
  assert.match(allText(investigationPanel(h)), /<img/);
  await investigationCopy(h).listeners.click();
  assert.equal(restored, true);
  assert.equal(h.document.body.children.length, 0);
  assert.match(h.copied[0], /<img/);
  options.fallbackFails = true;
  await investigationCopy(h).listeners.click();
  assert.equal(h.elements.notification.className, 'notification error');
  assert.equal(investigationCopy(h).disabled, false);
  h.api.renderOperation(null);
  assert.equal(h.api.state.investigationContext, null);
  assert.equal(investigationButton(h), null);
});

function consultationJob(status = 'completed', extra = {}) {
  return { kind: 'consultation', job_id: 'c'.repeat(32), status, provider: 'Codex', error: null,
    report: status === 'completed' ? {
      summary: 'A fonte atual não comprova quem enviou o sinal histórico.',
      findings: [{ text: 'O relato informa -15.', evidence: ['request'] }],
      hypotheses: [{ cause: 'Uma interrupção é possível.', confidence: 'baixa', evidence: ['request'] }],
      next_steps: ['Obtenha o registro histórico.'], missing_information: ['Emissor do sinal.'],
      correction_proposal: null, operation_id: '163',
      sources: [{ path: 'core/executor/test_runner.py', sha256: 'd'.repeat(64) }],
    } : null, ...extra };
}
function consultationCopy(h) {
  return findSummaryNode(h.api.elements.consultationPanel, n => n.tagName === 'BUTTON' && n.textContent === 'Copiar consulta');
}

function sourceSelection(records = [], truncated = false) {
  return { version: 1, records, truncated };
}

test('consulta apresenta e copia diagnóstico local com origens e motivos de omissão', async () => {
  const job = consultationJob();
  job.report.source_selection = sourceSelection([
    { path: 'core/executor/test_runner.py', origin: 'explicit', reason: 'included' },
    { path: 'tests/missing.py', origin: 'explicit', reason: 'not_found' },
    { path: 'core/gateway.py', origin: 'concept', reason: 'file_size' },
    { path: 'other.py', origin: 'relevance', reason: 'context_budget' },
    { path: '[caminho bloqueado]', origin: 'explicit', reason: 'protected' },
    { path: 'image.png', origin: 'explicit', reason: 'extension' },
    { path: 'binary.py', origin: 'explicit', reason: 'binary' },
    { path: 'last.py', origin: 'explicit', reason: 'file_limit' },
    { path: 'unavailable.py', origin: 'explicit', reason: 'unavailable' },
  ], true);
  const h = createHarness([summaryTask({ status: 'pending' })], { consultationData: job });
  await h.api.selectTask('163');
  const preview = h.elements['plan-content'].firstChild;
  h.elements.instruction.value = 'Examine as fontes sem alterar.';
  await h.api.elements.consultButton.listeners.click();
  const text = allText(h.api.elements.consultationPanel);
  assert.match(text, /Cobertura da seleção de fontes/);
  assert.match(text, /Diagnóstico gerado pelo coletor local/);
  for (const expected of ['Solicitado', 'Por conceito', 'Por relevância', 'Incluído', 'Arquivo não encontrado',
    'Limite de tamanho', 'contexto agregado', 'Caminho bloqueado', 'Extensão não permitida',
    'Conteúdo binário', 'quantidade de fontes', 'Arquivo indisponível', 'Diagnóstico abreviado']) {
    assert.ok(text.includes(expected), expected);
  }
  await consultationCopy(h).listeners.click();
  assert.ok(h.copied[0].includes('tests/missing.py — Arquivo não encontrado'));
  assert.ok(h.copied[0].includes('Diagnóstico abreviado'));
  assert.equal(h.elements['plan-content'].firstChild, preview);
  assert.equal(h.api.state.pendingApprovalId, '163');
  assert.equal(h.requests.filter(r => r.options.method === 'POST').length, 1);
});

test('relatório antigo sem diagnóstico de seleção permanece utilizável e copiável', async () => {
  const h = createHarness([], { consultationData: consultationJob() });
  h.elements.instruction.value = 'Examine sem alterar.';
  await h.api.elements.consultButton.listeners.click();
  assert.doesNotMatch(allText(h.api.elements.consultationPanel), /Cobertura da seleção/);
  await consultationCopy(h).listeners.click();
  assert.match(h.copied[0], /SHA256/);
});

const selectionRecord = { path: 'app.py', origin: 'explicit', reason: 'included' };
for (const selection of [null, {}, [], 'arbitrary', sourceSelection([], 'true'),
  { ...sourceSelection(), version: 2 }, { ...sourceSelection(), extra: 'PRIVATE_SENTINEL' },
  sourceSelection(Array(49).fill(selectionRecord)), sourceSelection([null]),
  sourceSelection([{ ...selectionRecord, path: '' }]),
  sourceSelection([{ ...selectionRecord, path: 'x'.repeat(241) }]),
  sourceSelection([{ ...selectionRecord, path: '/private/absolute.py' }]),
  sourceSelection([{ ...selectionRecord, path: '../private.py' }]),
  sourceSelection([{ ...selectionRecord, path: 'private\\file.py' }]),
  sourceSelection([{ ...selectionRecord, reason: 'toString' }]),
  sourceSelection([{ ...selectionRecord, reason: ['included'] }]),
  sourceSelection([{ ...selectionRecord, origin: 'ai' }]),
  sourceSelection([{ ...selectionRecord, origin: ['explicit'] }]),
  sourceSelection([{ ...selectionRecord, secret: 'PRIVATE_SENTINEL' }]),
  sourceSelection(Array(48).fill({ ...selectionRecord, path: '𠀀'.repeat(235), reason: 'context_budget' })),
]) {
  test(`consulta rejeita diagnóstico de seleção inválido: ${JSON.stringify(selection).slice(0, 90)}`, async () => {
    const job = consultationJob();
    job.report.source_selection = selection;
    const h = createHarness([], { consultationData: job });
    h.elements.instruction.value = 'Examine sem alterar.';
    await h.api.elements.consultButton.listeners.click();
    assert.equal(h.elements.notification.className, 'notification error');
    assert.equal(h.api.state.consultationContext.report, null);
    assert.doesNotMatch(allText(h.api.elements.consultationPanel), /PRIVATE_SENTINEL/);
    assert.equal(h.api.elements.consultButton.disabled, false);
  });
}

test('diagnóstico recebido no acompanhamento GET é exibido como texto literal', async () => {
  let job = consultationJob('running');
  const h = createHarness([], { consultationResponse: async () => reportResponse(job) });
  h.api.startPolling();
  h.elements.instruction.value = 'Examine sem alterar.';
  await h.api.elements.consultButton.listeners.click();
  job = consultationJob();
  job.report.source_selection = sourceSelection([{ ...selectionRecord, path: '<img src=x>.py' }]);
  await h.runPollingTimer();
  assert.match(allText(h.api.elements.consultationPanel), /<img src=x>.py/);
  assert.equal(findSummaryNode(h.api.elements.consultationPanel, n => n.tagName === 'IMG'), null);
  assert.equal(h.api.state.consultationContext.running, false);
});

test('consulta explícita usa fontes e contexto selecionado sem criar plano ou mudar aprovação', async () => {
  const task = summaryTask({ status: 'pending', plan: { objective: 'Plano', changes: [
    { path: 'example.py', change_type: 'create', content: 'VALUE = 1\n' }], tests: [], risks: [] } });
  const h = createHarness([task], { consultationData: consultationJob() });
  await h.api.selectTask('163');
  const preview = findSummaryNode(h.elements['plan-content'], n => n.tagName === 'DETAILS');
  preview.open = true;
  h.elements.instruction.value = 'Investigue. Não modificar arquivos. Não criar commits.';
  const submittedInstruction = h.elements.instruction.value;
  assert.equal(h.api.elements.consultButton.type, 'button');
  await h.api.elements.consultButton.listeners.click();
  const posts = h.requests.filter(r => r.options.method === 'POST');
  assert.equal(posts.length, 1);
  assert.equal(posts[0].url, '/consultations');
  assert.deepEqual(JSON.parse(posts[0].options.body), { instruction: submittedInstruction, context_task_id: '163' });
  assert.equal(h.api.state.busy, false);
  assert.equal(h.api.state.pendingApprovalId, '163');
  assert.equal(h.api.state.selectedTaskId, '163');
  assert.equal(h.elements['approval-actions'].hidden, false);
  assert.equal(preview.open, true);
  assert.equal(h.api.elements.consultationPanel.hidden, false);
  assert.match(allText(h.api.elements.consultationPanel), /Informações adicionais necessárias/);
  await consultationCopy(h).listeners.click();
  assert.match(h.copied[0], /Emissor do sinal/);
  assert.match(h.copied[0], /Operação de contexto: 163/);
  assert.match(h.copied[0], /SHA256/);
  assert.equal(h.elements.notification.textContent, 'Consulta copiada.');
});

test('Gerar plano encaminha resultado de leitura sem exigir approval_id ou substituir plano aberto', async () => {
  const h = createHarness([summaryTask({ status: 'pending' })], {
    postResponses: { '/plan': { data: consultationJob() } },
  });
  await h.api.selectTask('163');
  const plan = h.elements['plan-content'].firstChild;
  h.elements.instruction.value = 'Investigue; não modificar arquivos.';
  await h.elements['instruction-form'].listeners.submit({ preventDefault() {} });
  assert.equal(h.api.state.selectedTaskId, '163');
  assert.equal(h.api.state.pendingApprovalId, '163');
  assert.equal(h.elements['plan-content'].firstChild, plan);
  assert.equal(h.api.elements.consultationPanel.hidden, false);
  assert.match(h.elements.notification.textContent, /encaminhado à consulta/);
  assert.equal(h.api.state.busy, false);
});

test('consulta pendente usa polling existente e preserva o contexto original ao trocar seleção', async () => {
  let current = consultationJob('running');
  const h = createHarness([summaryTask(), summaryTask({ approval_id: '164' })], {
    consultationResponse: async () => reportResponse(current),
  });
  await h.api.selectTask('163');
  h.elements.instruction.value = 'Pergunta original';
  h.api.startPolling();
  await h.api.elements.consultButton.listeners.click();
  assert.equal(h.api.elements.consultButton.disabled, true);
  await h.api.elements.consultButton.listeners.click();
  assert.equal(h.requests.filter(r => r.url === '/consultations').length, 1);
  h.elements.instruction.value = 'Rascunho novo';
  await h.api.selectTask('164');
  current = consultationJob();
  await h.runPollingTimer();
  assert.equal(h.api.elements.consultButton.disabled, false);
  assert.equal(h.pendingPollingTimers(), 1);
  assert.equal(h.api.state.selectedTaskId, '164');
  assert.equal(h.elements.instruction.value, 'Rascunho novo');
  assert.match(allText(h.api.elements.consultationPanel), /Pergunta original/);
  assert.match(allText(h.api.elements.consultationPanel), /Operação de contexto: 163/);
  const before = h.requests.filter(r => r.url.startsWith('/consultations/')).length;
  await h.runPollingTimer();
  assert.equal(h.requests.filter(r => r.url.startsWith('/consultations/')).length, before);
});

test('consulta vazia informa erro persistente sem chamar API', async () => {
  const h = createHarness([]);
  h.elements.instruction.value = '  ';
  await h.api.elements.consultButton.listeners.click();
  assert.equal(h.requests.length, 0);
  assert.equal(h.elements.notification.textContent, 'Informe uma consulta.');
  assert.equal(h.api.state.notificationTimer, null);
});

for (const job of [null, consultationJob('failed'), consultationJob('unknown'),
  consultationJob('completed', { job_id: '../wrong' }),
  consultationJob('completed', { report: {} }),
  consultationJob('completed', { report: { ...consultationJob().report, findings: [{ text: 'x', evidence: ['private.py'] }] } }),
  consultationJob('completed', { report: { ...consultationJob().report, hypotheses: [] } }),
  consultationJob('completed', { report: { ...consultationJob().report, correction_proposal: {} } })]) {
  test(`consulta recusa resposta inválida: ${JSON.stringify(job).slice(0, 60)}`, async () => {
    const h = createHarness([], { consultationData: job });
    h.elements.instruction.value = 'Analise somente de leitura.';
    await h.api.elements.consultButton.listeners.click();
    assert.equal(h.elements.notification.className, 'notification error');
    assert.equal(h.api.elements.consultButton.disabled, false);
    assert.equal(h.api.state.busy, false);
  });
}

test('falha na atualização de consulta mantém polling e libera nova tentativa', async () => {
  const options = { consultationData: consultationJob('running') };
  const h = createHarness([], options);
  h.elements.instruction.value = 'Consulta de teste';
  await h.api.elements.consultButton.listeners.click();
  options.consultationResponse = async () => { throw new TypeError('Conexão interrompida.'); };
  h.api.startPolling();
  await h.runPollingTimer();
  assert.equal(h.api.elements.consultButton.disabled, false);
  assert.equal(h.pendingPollingTimers(), 1);
  assert.equal(h.elements['api-status'].textContent, 'Online');
  assert.match(h.elements.notification.textContent, /atualizar a consulta/);
  options.consultationResponse = async () => reportResponse(consultationJob());
  await h.api.elements.consultButton.listeners.click();
  assert.equal(h.api.state.consultationContext.report.summary, consultationJob().report.summary);
});

test('falha ao iniciar consulta não desabilita os controles existentes', async () => {
  const h = createHarness([], { consultationResponse: async () => { throw new TypeError('Sem conexão.'); } });
  h.elements.instruction.value = 'Consulta';
  await h.api.elements.consultButton.listeners.click();
  assert.equal(h.api.elements.consultButton.disabled, false);
  assert.equal(h.elements['plan-button'].disabled, false);
  assert.equal(h.elements['approve-button'].disabled, false);
  assert.match(h.elements.notification.textContent, /Não foi possível consultar/);
});

test('consulta exibe texto literal e copia com alternativa e recuperação de foco', async () => {
  const job = consultationJob();
  job.report.summary = '<img src=x onerror=alert(1)>';
  job.report.correction_proposal = 'Revisar a hipótese antes de propor mudança.';
  const options = { noClipboard: true, consultationData: job };
  const h = createHarness([], options);
  let focused = false;
  h.document.activeElement.focus = () => { focused = true; };
  h.elements.instruction.value = 'Consulta';
  await h.api.elements.consultButton.listeners.click();
  assert.equal(findSummaryNode(h.api.elements.consultationPanel, n => n.tagName === 'IMG'), null);
  await consultationCopy(h).listeners.click();
  assert.equal(focused, true);
  assert.equal(h.document.body.children.length, 0);
  assert.match(h.copied[0], /<img/);
  options.fallbackFails = true;
  await consultationCopy(h).listeners.click();
  assert.equal(h.elements.notification.className, 'notification error');
  assert.equal(consultationCopy(h).disabled, false);
});

function editInstruction(h, value) {
  h.elements.instruction.value = value;
  h.elements.instruction.listeners.input();
}
function submitPlan(h) {
  return h.elements['instruction-form'].listeners.submit({ preventDefault() {} });
}

test('plano aceito limpa a caixa e mantém a instrução na tarefa apresentada', async () => {
  const h = createHarness([]);
  editInstruction(h, '  Crie exemplo.py.  ');
  await submitPlan(h);
  assert.equal(h.elements.instruction.value, '');
  assert.equal(h.api.state.selectedTask.instruction, 'Crie exemplo.py.');
  assert.equal(h.api.state.pendingApprovalId, 'created-1');
  assert.equal(h.elements['plan-button'].disabled, false);
});

for (const options of [
  { postErrors: { '/plan': 'Sem conexão.' } },
  { postResponses: { '/plan': { status: 500, data: { error: 'Falha de planejamento.' } } } },
  { postResponses: { '/plan': { data: { status: 'pending' } } } },
]) {
  test(`erro no plano preserva a instrução: ${JSON.stringify(options)}`, async () => {
    const h = createHarness([], options);
    editInstruction(h, '  Minha instrução original.  ');
    await submitPlan(h);
    assert.equal(h.elements.instruction.value, '  Minha instrução original.  ');
    assert.equal(h.elements.notification.className, 'notification error');
  });
}

test('resposta de plano não apaga um rascunho substituído durante a espera', async () => {
  const h = createHarness([], { deferPostRequests: true });
  editInstruction(h, 'Primeiro pedido.');
  const creating = submitPlan(h);
  editInstruction(h, 'Novo rascunho.');
  h.resolvePostRequest('/plan');
  await creating;
  assert.equal(h.elements.instruction.value, 'Novo rascunho.');
  assert.equal(h.api.state.selectedTask.instruction, 'Primeiro pedido.');
});

test('consulta aceita limpa a caixa e conserva a pergunta no relatório e na cópia', async () => {
  const h = createHarness([], { consultationData: consultationJob() });
  editInstruction(h, '  Minha pergunta de leitura.  ');
  await h.api.elements.consultButton.listeners.click();
  assert.equal(h.elements.instruction.value, '');
  assert.match(allText(h.api.elements.consultationPanel), /Minha pergunta de leitura/);
  await consultationCopy(h).listeners.click();
  assert.match(h.copied[0], /Minha pergunta de leitura/);
});

test('consulta encaminhada por Gerar plano também limpa a caixa', async () => {
  const h = createHarness([], { postResponses: { '/plan': { data: consultationJob('running') } } });
  editInstruction(h, 'Analise sem modificar arquivos.');
  await submitPlan(h);
  assert.equal(h.elements.instruction.value, '');
  assert.equal(h.api.state.consultationContext.instruction, 'Analise sem modificar arquivos.');
  assert.equal(h.api.state.consultationContext.running, true);
});

for (const current of [consultationJob('failed'), consultationJob('completed', { report: {} })]) {
  test(`falha inicial de consulta mantém texto: ${current.status}`, async () => {
    const h = createHarness([], { consultationData: current });
    editInstruction(h, '  Pergunta preservada.  ');
    await h.api.elements.consultButton.listeners.click();
    assert.equal(h.elements.instruction.value, '  Pergunta preservada.  ');
    assert.equal(h.api.elements.consultButton.disabled, false);
  });
}

test('falha posterior restaura a pergunta enviada quando a caixa continua vazia', async () => {
  let current = consultationJob('running');
  const h = createHarness([], { consultationResponse: async () => reportResponse(current) });
  editInstruction(h, '  Pergunta para tentar novamente.  ');
  await h.api.elements.consultButton.listeners.click();
  assert.equal(h.elements.instruction.value, '');
  current = consultationJob('failed');
  h.api.startPolling();
  await h.runPollingTimer();
  assert.equal(h.elements.instruction.value, '  Pergunta para tentar novamente.  ');
  assert.equal(h.api.elements.consultButton.disabled, false);
});

for (const newDraft of ['Rascunho novo.', '']) {
  test(`falha posterior preserva edição posterior, inclusive exclusão intencional: ${JSON.stringify(newDraft)}`, async () => {
    let current = consultationJob('running');
    const h = createHarness([], { consultationResponse: async () => reportResponse(current) });
    editInstruction(h, 'Pergunta enviada.');
    await h.api.elements.consultButton.listeners.click();
    editInstruction(h, 'Texto digitado depois.');
    editInstruction(h, newDraft);
    current = consultationJob('failed');
    h.api.startPolling();
    await h.runPollingTimer();
    assert.equal(h.elements.instruction.value, newDraft);
  });
}

test('aceite de consulta atrasado preserva rascunho novo mesmo se o texto final for igual', async () => {
  let finish;
  const h = createHarness([], { consultationResponse: () => new Promise(resolve => { finish = resolve; }) });
  editInstruction(h, 'Texto original.');
  const starting = h.api.elements.consultButton.listeners.click();
  editInstruction(h, 'Outro texto.');
  editInstruction(h, 'Texto original.');
  finish(reportResponse(consultationJob('running')));
  await starting;
  assert.equal(h.elements.instruction.value, 'Texto original.');
});

test('nova operação aceita impede restauração de uma consulta anterior que falhar', async () => {
  let current = consultationJob('running');
  const h = createHarness([], { consultationResponse: async () => reportResponse(current) });
  editInstruction(h, 'Consulta antiga.');
  await h.api.elements.consultButton.listeners.click();
  editInstruction(h, 'Crie exemplo.py.');
  await submitPlan(h);
  assert.equal(h.elements.instruction.value, '');
  current = consultationJob('failed');
  h.api.startPolling();
  await h.runPollingTimer();
  assert.equal(h.elements.instruction.value, '');
  assert.equal(h.api.state.pendingApprovalId, 'created-1');
});

test('contexto visível acompanha seleção e identifica a operação enviada durante a consulta', async () => {
  const h = createHarness([summaryTask(), summaryTask({ approval_id: '164' })], { consultationData: consultationJob('running') });
  assert.match(h.api.elements.consultationContextLabel.textContent, /nenhuma operação selecionada/);
  await h.api.selectTask('163');
  assert.equal(h.api.elements.consultationContextLabel.textContent, 'Contexto da próxima consulta: operação 163.');
  editInstruction(h, 'Consulta.');
  await h.api.elements.consultButton.listeners.click();
  await h.api.selectTask('164');
  assert.equal(h.api.elements.consultationContextLabel.textContent, 'Contexto da próxima consulta: operação 164.');
  assert.match(allText(h.api.elements.consultationPanel), /Operação enviada como contexto: 163/);
  assert.equal(JSON.parse(h.requests.find(r => r.url === '/consultations').options.body).context_task_id, '163');
  await h.api.refreshTasks(true);
  assert.equal(h.api.elements.consultationContextLabel.textContent, 'Contexto da próxima consulta: operação 164.');
});

function preparationButton(h) {
  return findSummaryNode(h.api.elements.consultationPanel, n => n.tagName === 'BUTTON' && n.textContent === 'Preparar instrução');
}
function preparationEditor(h) {
  return findSummaryNode(h.api.elements.consultationPanel, n => n.className === 'instruction-preparation');
}
function preparationControl(h, name) {
  return findSummaryNode(preparationEditor(h), n => n.tagName === 'BUTTON' && n.textContent === name);
}
function preparationObjective(h) {
  return findSummaryNode(preparationEditor(h), n => n.tagName === 'TEXTAREA');
}
async function completedConsultation(options = {}) {
  if (!Object.hasOwn(options, 'consultationData')) options.consultationData = consultationJob();
  const h = createHarness([summaryTask({ status: 'pending' })], options);
  await h.api.selectTask('163');
  editInstruction(h, 'Analise a operação, sem escrita ou commits.');
  await h.api.elements.consultButton.listeners.click();
  assert.equal(h.elements.instruction.value, '');
  return h;
}

test('Preparar instrução exige objetivo e monta rascunho sem enviar pedido ou alterar seleção e aprovação', async () => {
  const h = await completedConsultation();
  const before = h.requests.length;
  const prepare = preparationButton(h);
  assert.equal(prepare.type, 'button');
  assert.equal(preparationEditor(h).hidden, true);
  prepare.listeners.click();
  assert.equal(preparationEditor(h).hidden, false);
  const objective = preparationObjective(h);
  const label = findSummaryNode(preparationEditor(h), n => n.tagName === 'LABEL');
  assert.equal(label.getAttribute('for'), objective.getAttribute('id'));
  assert.equal(objective.getAttribute('maxlength'), '1000');
  objective.value = 'Adicione horários de início e fim ao relatório.';
  preparationControl(h, 'Usar no campo Instrução').listeners.click();
  assert.match(h.elements.instruction.value, /^Crie um plano de alterações/);
  assert.match(h.elements.instruction.value, /Adicione horários de início e fim ao relatório/);
  assert.match(h.elements.instruction.value, /HIPÓTESES NÃO CONFIRMADAS/);
  assert.match(h.elements.instruction.value, /Confiança: baixa/);
  assert.match(h.elements.instruction.value, /core\/executor\/test_runner.py/);
  assert.match(h.elements.instruction.value, /SHA256/);
  assert.match(h.elements.instruction.value, /Operação de contexto: 163/);
  assert.doesNotMatch(h.elements.instruction.value, /Analise a operação, sem escrita ou commits/);
  assert.equal(h.requests.length, before);
  assert.equal(h.api.state.selectedTaskId, '163');
  assert.equal(h.api.state.pendingApprovalId, '163');
  assert.equal(h.api.state.busy, false);
  assert.equal(h.elements['approval-actions'].hidden, false);
  assert.equal(preparationEditor(h).hidden, true);
  assert.equal(h.elements.notification.textContent, 'Instrução preparada. Revise antes de gerar o plano.');
});

for (const value of ['', '  ', 'x'.repeat(1001)]) {
  test(`objetivo vazio ou acima do limite não preenche a instrução: ${value.length}`, async () => {
    const h = await completedConsultation();
    const before = h.requests.length;
    preparationButton(h).listeners.click();
    preparationObjective(h).value = value;
    preparationControl(h, 'Usar no campo Instrução').listeners.click();
    assert.equal(h.elements.instruction.value, '');
    assert.equal(h.requests.length, before);
    assert.equal(h.elements.notification.className, 'notification error');
    assert.match(h.elements.notification.textContent, /até 1000 caracteres/);
  });
}

test('rascunho existente é preservado e instrução preparada pode ser copiada', async () => {
  const h = await completedConsultation();
  editInstruction(h, 'Rascunho que já estava sendo escrito.');
  preparationButton(h).listeners.click();
  preparationObjective(h).value = 'Adicione identificação da etapa aos registros.';
  const before = h.requests.length;
  preparationControl(h, 'Usar no campo Instrução').listeners.click();
  assert.equal(h.elements.instruction.value, 'Rascunho que já estava sendo escrito.');
  assert.match(h.elements.notification.textContent, /rascunho.*preservado/);
  await preparationControl(h, 'Copiar instrução preparada').listeners.click();
  assert.match(h.copied[0], /Adicione identificação da etapa/);
  assert.equal(h.elements.instruction.value, 'Rascunho que já estava sendo escrito.');
  assert.equal(h.requests.length, before);
});

test('cancelar fecha o editor sem mudar a instrução ou perder o objetivo digitado', async () => {
  const h = await completedConsultation();
  preparationButton(h).listeners.click();
  preparationObjective(h).value = 'Melhorar a apresentação do relatório.';
  preparationControl(h, 'Cancelar').listeners.click();
  assert.equal(preparationEditor(h).hidden, true);
  assert.equal(h.elements.instruction.value, '');
  preparationButton(h).listeners.click();
  assert.equal(preparationObjective(h).value, 'Melhorar a apresentação do relatório.');
});

for (const status of ['running', 'failed']) {
  test(`consulta ${status} não oferece preparação de instrução`, async () => {
    const h = createHarness([], { consultationData: consultationJob(status) });
    editInstruction(h, 'Consulta de teste');
    await h.api.elements.consultButton.listeners.click();
    assert.equal(preparationButton(h), null);
  });
}

test('preparação não altera o rascunho enquanto uma operação está ocupada', async () => {
  const h = await completedConsultation();
  preparationButton(h).listeners.click();
  preparationObjective(h).value = 'Adicione um campo ao relatório.';
  h.api.state.busy = true;
  const before = h.requests.length;
  preparationControl(h, 'Usar no campo Instrução').listeners.click();
  assert.equal(h.elements.instruction.value, '');
  assert.equal(h.requests.length, before);
  assert.match(h.elements.notification.textContent, /Aguarde a operação/);
});

test('botões antigos são ignorados quando outra consulta substitui o relatório', async () => {
  const h = await completedConsultation();
  preparationButton(h).listeners.click();
  preparationObjective(h).value = 'Adicione um campo ao relatório.';
  const oldUse = preparationControl(h, 'Usar no campo Instrução');
  const oldCopy = preparationControl(h, 'Copiar instrução preparada');
  const oldPrepare = preparationButton(h);
  const oldCancel = preparationControl(h, 'Cancelar');
  editInstruction(h, 'Nova consulta sem escrita.');
  await h.api.elements.consultButton.listeners.click();
  const before = h.requests.length;
  const notification = h.elements.notification.textContent;
  oldUse.listeners.click();
  oldPrepare.listeners.click();
  oldCancel.listeners.click();
  await oldCopy.listeners.click();
  assert.equal(h.elements.instruction.value, '');
  assert.equal(h.copied.length, 0);
  assert.equal(h.requests.length, before);
  assert.equal(h.elements.notification.textContent, notification);
});

test('rascunho preparado respeita 12000 caracteres e conserva objetivo e orientação de planejamento', async () => {
  const job = consultationJob();
  job.report.findings = Array.from({ length: 8 }, () => ({ text: '😀'.repeat(500), evidence: ['request'] }));
  job.report.hypotheses = Array.from({ length: 4 }, () => ({ cause: 'h'.repeat(800), confidence: 'baixa', evidence: ['request'] }));
  job.report.missing_information = Array.from({ length: 8 }, () => 'm'.repeat(600));
  const h = await completedConsultation({ consultationData: job });
  preparationButton(h).listeners.click();
  const objective = 'Adicione um campo ao relatório. ' + 'o'.repeat(950);
  preparationObjective(h).value = objective;
  preparationControl(h, 'Usar no campo Instrução').listeners.click();
  const draft = h.elements.instruction.value;
  assert.ok(draft.length <= 12000);
  assert.ok(draft.includes(objective));
  assert.match(draft, /Contexto abreviado/);
  assert.match(draft, /ORIENTAÇÃO PARA O PLANEJAMENTO/);
  assert.match(draft, /testes direcionados/);
  assert.equal(draft.isWellFormed(), true);
  assert.match(h.elements.notification.textContent, /contexto abreviado/);
});

test('objetivo e texto da IA são tratados como texto literal', async () => {
  const job = consultationJob();
  job.report.summary = '<img src=x onerror=alert(1)>';
  const h = await completedConsultation({ consultationData: job });
  preparationButton(h).listeners.click();
  preparationObjective(h).value = '<script>alert(1)</script> Adicione um campo.';
  preparationControl(h, 'Usar no campo Instrução').listeners.click();
  assert.match(h.elements.instruction.value, /<script>/);
  assert.match(h.elements.instruction.value, /<img/);
  assert.equal(findSummaryNode(h.api.elements.consultationPanel, n => n.tagName === 'SCRIPT' || n.tagName === 'IMG'), null);
});

test('instrução preparada só é enviada após submissão explícita do usuário', async () => {
  const h = await completedConsultation();
  preparationButton(h).listeners.click();
  preparationObjective(h).value = 'Adicione o nome da etapa ao relatório.';
  preparationControl(h, 'Usar no campo Instrução').listeners.click();
  const prepared = h.elements.instruction.value;
  assert.equal(h.requests.filter(r => r.url === '/plan').length, 0);
  await submitPlan(h);
  const plan = h.requests.find(r => r.url === '/plan');
  assert.equal(JSON.parse(plan.options.body).instruction, prepared);
  assert.equal(h.elements.instruction.value, '');
  assert.equal(h.api.state.pendingApprovalId, 'created-1');
});

test('preparar rascunho preserva prévia aberta e operação de origem do relatório', async () => {
  const task = summaryTask({ status: 'pending', plan: { objective: 'Plano existente', changes: [
    { path: 'example.py', change_type: 'create', content: 'VALUE = 1\n' }], tests: [], risks: [] } });
  const h = createHarness([task, { ...task, approval_id: '164' }], { consultationData: consultationJob() });
  await h.api.selectTask('163');
  editInstruction(h, 'Consulta sem escrita');
  await h.api.elements.consultButton.listeners.click();
  await h.api.selectTask('164');
  const preview = findSummaryNode(h.elements['plan-content'], n => n.tagName === 'DETAILS');
  preview.open = true;
  preparationButton(h).listeners.click();
  preparationObjective(h).value = 'Adicione uma identificação ao relatório.';
  preparationControl(h, 'Usar no campo Instrução').listeners.click();
  assert.match(h.elements.instruction.value, /Operação de contexto: 163/);
  assert.equal(h.api.state.selectedTaskId, '164');
  assert.equal(findSummaryNode(h.elements['plan-content'], n => n.tagName === 'DETAILS'), preview);
  assert.equal(preview.open, true);
});

test('contador inicia abaixo da caixa e fica associado à descrição acessível', () => {
  const h = createHarness([]);
  const counter = h.api.elements.instructionCounter;
  assert.equal(counter.textContent, '0 / 12000 caracteres');
  assert.equal(counter.getAttribute('id'), 'instruction-count');
  assert.equal(h.elements.instruction.getAttribute('aria-describedby'), 'instruction-count');
  assert.equal(h.elements.instruction.nextSibling, counter);
  assert.equal(counter.parentElement, h.elements['instruction-form']);
  assert.equal(h.requests.length, 0);
});

test('contador considera texto existente ao carregar e acompanha digitação, colagem e exclusão', () => {
  const h = createHarness([], { initialInstruction: 'Olá' });
  const counter = h.api.elements.instructionCounter;
  assert.equal(counter.textContent, '3 / 12000 caracteres');
  for (const value of ['Texto colado\ncom espaços. ', 'ação 🧠', 'x'.repeat(12000), '']) {
    editInstruction(h, value);
    assert.equal(counter.textContent, `${value.length} / 12000 caracteres`);
    assert.equal(h.elements.instruction.value, value);
  }
  assert.equal(h.api.state.instructionRevision, 4);
  assert.equal(h.requests.length, 0);
});

test('plano aceito atualiza contador para zero sem mudar o texto enviado', async () => {
  const h = createHarness([]);
  editInstruction(h, '  Crie exemplo.py.  ');
  await submitPlan(h);
  assert.equal(h.api.elements.instructionCounter.textContent, '0 / 12000 caracteres');
  const request = h.requests.find(r => r.url === '/plan');
  assert.equal(JSON.parse(request.options.body).instruction, 'Crie exemplo.py.');
  assert.equal(h.api.state.pendingApprovalId, 'created-1');
});

test('erro de planejamento conserva o contador e o rascunho', async () => {
  const h = createHarness([], { postErrors: { '/plan': 'Codex excedeu o tempo limite.' } });
  const value = '  Adicione o contador.  ';
  editInstruction(h, value);
  await submitPlan(h);
  assert.equal(h.elements.instruction.value, value);
  assert.equal(h.api.elements.instructionCounter.textContent, `${value.length} / 12000 caracteres`);
  assert.equal(h.elements.notification.className, 'notification error');
});

test('plano atrasado preserva contador do novo rascunho', async () => {
  const h = createHarness([], { deferPostRequests: true });
  editInstruction(h, 'Primeiro pedido.');
  const pending = submitPlan(h);
  editInstruction(h, 'Novo.');
  h.resolvePostRequest('/plan');
  await pending;
  assert.equal(h.elements.instruction.value, 'Novo.');
  assert.equal(h.api.elements.instructionCounter.textContent, '5 / 12000 caracteres');
});

for (const forwarded of [false, true]) {
  test(`consulta aceita limpa o contador, encaminhada: ${forwarded}`, async () => {
    const h = createHarness([], forwarded
      ? { postResponses: { '/plan': { data: consultationJob('running') } } }
      : { consultationData: consultationJob('running') });
    editInstruction(h, 'Analise sem alterar arquivos.');
    if (forwarded) await submitPlan(h);
    else await h.api.elements.consultButton.listeners.click();
    assert.equal(h.elements.instruction.value, '');
    assert.equal(h.api.elements.instructionCounter.textContent, '0 / 12000 caracteres');
  });
}

for (const newDraft of [null, 'Texto novo.', '']) {
  test(`falha posterior de consulta mantém contador coerente com o rascunho: ${JSON.stringify(newDraft)}`, async () => {
    let current = consultationJob('running');
    const h = createHarness([], { consultationResponse: async () => reportResponse(current) });
    const original = '  Consulta original.  ';
    editInstruction(h, original);
    await h.api.elements.consultButton.listeners.click();
    if (newDraft !== null) {
      editInstruction(h, 'Edição posterior.');
      editInstruction(h, newDraft);
    }
    current = consultationJob('failed');
    h.api.startPolling();
    await h.runPollingTimer();
    const expected = newDraft === null ? original : newDraft;
    assert.equal(h.elements.instruction.value, expected);
    assert.equal(h.api.elements.instructionCounter.textContent, `${expected.length} / 12000 caracteres`);
  });
}

test('Preparar instrução atualiza contador ao inserir e preserva contador de rascunho existente', async () => {
  const h = await completedConsultation();
  assert.equal(h.api.elements.instructionCounter.textContent, '0 / 12000 caracteres');
  preparationButton(h).listeners.click();
  preparationObjective(h).value = 'Adicione um contador de caracteres.';
  const before = h.requests.length;
  preparationControl(h, 'Usar no campo Instrução').listeners.click();
  const prepared = h.elements.instruction.value;
  assert.ok(prepared.length > 0 && prepared.length <= 12000);
  assert.equal(h.api.elements.instructionCounter.textContent, `${prepared.length} / 12000 caracteres`);
  preparationButton(h).listeners.click();
  editInstruction(h, 'Rascunho preservado.');
  preparationControl(h, 'Usar no campo Instrução').listeners.click();
  assert.equal(h.elements.instruction.value, 'Rascunho preservado.');
  assert.equal(h.api.elements.instructionCounter.textContent, '20 / 12000 caracteres');
  await preparationControl(h, 'Copiar instrução preparada').listeners.click();
  assert.equal(h.api.elements.instructionCounter.textContent, '20 / 12000 caracteres');
  assert.equal(h.requests.length, before);
  assert.equal(h.api.state.pendingApprovalId, '163');
});

test('polling preserva contador, seleção e prévia aberta durante rascunho', async () => {
  const task = summaryTask({ status: 'pending', plan: { objective: 'Plano',
    changes: [{ change_type: 'modify', path: 'example.py', content: 'VALUE = 1\n' }], tests: [], risks: [] } });
  const h = createHarness([task]);
  await h.api.selectTask('163');
  const details = findSummaryNode(h.elements['plan-content'], n => n.tagName === 'DETAILS');
  details.open = true;
  editInstruction(h, 'Novo pedido.');
  const counter = h.api.elements.instructionCounter;
  h.api.startPolling();
  await h.runPollingTimer();
  assert.equal(h.api.elements.instructionCounter, counter);
  assert.equal(counter.textContent, '12 / 12000 caracteres');
  assert.equal(details.open, true);
  assert.equal(h.api.state.selectedTaskId, '163');
  assert.equal(h.api.state.pendingApprovalId, '163');
  assert.equal(h.pendingPollingTimers(), 1);
});

test('cópia da instrução preparada usa alternativa e permite repetir após falha', async () => {
  const options = { noClipboard: true, consultationData: consultationJob() };
  const h = await completedConsultation(options);
  let restored = false;
  h.document.activeElement.focus = () => { restored = true; };
  preparationButton(h).listeners.click();
  preparationObjective(h).value = 'Adicione o nome da etapa ao relatório.';
  await preparationControl(h, 'Copiar instrução preparada').listeners.click();
  assert.equal(restored, true);
  assert.equal(h.document.body.children.length, 0);
  assert.equal(h.elements.instruction.value, '');
  options.fallbackFails = true;
  await preparationControl(h, 'Copiar instrução preparada').listeners.click();
  assert.equal(h.elements.notification.className, 'notification error');
  assert.equal(preparationControl(h, 'Copiar instrução preparada').disabled, false);
});


function chatJob(status = 'completed', extra = {}) {
  return { kind: 'chat', job_id: 'e'.repeat(32), provider: 'Codex', status, error: null,
    report: status === 'completed' ? {
      reply: 'A função retorna OK.', references: ['request', 'app.py'],
      sources: [{ path: 'app.py', sha256: 'd'.repeat(64) }],
      source_selection: sourceSelection([{ path: 'app.py', origin: 'explicit', reason: 'included' }]),
    } : null, ...extra };
}
async function sendChat(h, message) {
  h.api.elements.chatInput.value = message;
  h.api.elements.chatInput.listeners.input();
  await h.api.elements.chatForm.listeners.submit({ preventDefault() {} });
}
function chatCopy(h) {
  return findSummaryNode(h.api.elements.chatLog, node => node.tagName === 'BUTTON' && node.textContent === 'Copiar resposta');
}

test('chat responde e copia fontes sem mudar plano, aprovação, seleção ou rascunho principal', async () => {
  const h = createHarness([summaryTask({ status: 'pending' })], { chatData: chatJob() });
  await h.api.selectTask('163');
  const preview = h.elements['plan-content'].firstChild;
  preview.open = true;
  h.elements.instruction.value = 'Rascunho de implementação';
  await sendChat(h, 'Explique app.py');
  const posts = h.requests.filter(r => r.options.method === 'POST');
  assert.equal(posts.length, 1);
  assert.equal(posts[0].url, '/chat');
  assert.deepEqual(JSON.parse(posts[0].options.body), { message: 'Explique app.py', history: [] });
  assert.equal(h.api.elements.chatInput.value, '');
  assert.equal(h.elements.instruction.value, 'Rascunho de implementação');
  assert.equal(h.api.state.pendingApprovalId, '163');
  assert.equal(h.api.state.selectedTaskId, '163');
  assert.equal(h.elements['plan-content'].firstChild, preview);
  assert.equal(preview.open, true);
  await chatCopy(h).listeners.click();
  assert.match(h.copied[0], /A função retorna OK/);
  assert.match(h.copied[0], /SHA256/);
  assert.match(h.copied[0], /Solicitado: app.py — Incluído/);
  assert.equal(h.api.elements.chatSend.disabled, false);
});

test('segunda pergunta envia a troca anterior como histórico sem dados da operação selecionada', async () => {
  const h = createHarness([summaryTask()], { chatData: chatJob() });
  await h.api.selectTask('163');
  await sendChat(h, 'Explique app.py');
  await sendChat(h, 'E qual é o retorno?');
  const sent = JSON.parse(h.requests.filter(r => r.url === '/chat').at(-1).options.body);
  assert.deepEqual(sent.history, [
    { role: 'user', content: 'Explique app.py' }, { role: 'assistant', content: 'A função retorna OK.' },
  ]);
  assert.equal(Object.hasOwn(sent, 'context_task_id'), false);
  assert.equal(h.api.state.chatTurns.length, 2);
});

test('histórico visível fica em quatro trocas e o enviado fica em três trocas anteriores', async () => {
  const h = createHarness([], { chatData: chatJob() });
  for (let i = 0; i < 5; i++) await sendChat(h, 'Pergunta ' + i);
  assert.equal(h.api.state.chatTurns.length, 4);
  assert.equal(h.api.state.chatTurns[0].question, 'Pergunta 1');
  const sent = JSON.parse(h.requests.filter(r => r.url === '/chat').at(-1).options.body);
  assert.equal(sent.history.length, 6);
  assert.equal(sent.history[0].content, 'Pergunta 1');
});

test('histórico enviado elimina pares antigos inteiros para respeitar 12000 caracteres', async () => {
  const job = chatJob();
  job.report.reply = 'r'.repeat(4000);
  const h = createHarness([], { chatData: job });
  for (let i = 0; i < 3; i++) await sendChat(h, String(i) + 'q'.repeat(3999));
  const sent = JSON.parse(h.requests.filter(r => r.url === '/chat').at(-1).options.body);
  assert.equal(sent.history.length, 2);
  assert.ok(sent.history.reduce((sum, item) => sum + item.content.length, 0) <= 12000);
  assert.ok(sent.history[0].content.startsWith('1'));
});

test('Nova conversa limpa histórico exibido, preserva rascunho e não envia requisição', async () => {
  const h = createHarness([], { chatData: chatJob() });
  await sendChat(h, 'Primeira pergunta');
  h.api.elements.chatInput.value = 'Próxima pergunta ainda não enviada';
  const before = h.requests.length;
  await h.api.elements.chatClear.listeners.click();
  assert.equal(h.requests.length, before);
  assert.equal(h.api.state.chatTurns.length, 0);
  assert.equal(h.api.state.chatContext, null);
  assert.equal(h.api.elements.chatInput.value, 'Próxima pergunta ainda não enviada');
  assert.match(allText(h.api.elements.chatLog), /iniciar a conversa/);
});

test('chat pendente bloqueia envios duplicados e limpeza, preservando edição durante o POST', async () => {
  let finish;
  const h = createHarness([], { chatResponse: () => new Promise(resolve => { finish = resolve; }) });
  const pending = sendChat(h, 'Pergunta inicial');
  assert.equal(h.api.elements.chatSend.disabled, true);
  await h.api.elements.chatForm.listeners.submit({ preventDefault() {} });
  await h.api.elements.chatClear.listeners.click();
  assert.equal(h.requests.filter(r => r.url === '/chat').length, 1);
  assert.equal(h.api.state.chatTurns.length, 1);
  h.api.elements.chatInput.value = 'Rascunho novo';
  h.api.elements.chatInput.listeners.input();
  finish(reportResponse(chatJob('running')));
  await pending;
  assert.equal(h.api.elements.chatInput.value, 'Rascunho novo');
  assert.equal(h.api.elements.chatSend.disabled, true);
});

test('chat acompanha GET pelo polling existente e encerra acompanhamento após conclusão', async () => {
  let current = chatJob('running');
  const h = createHarness([], { chatResponse: async () => reportResponse(current) });
  h.api.startPolling();
  await sendChat(h, 'Pergunta');
  assert.equal(h.api.elements.chatInput.value, '');
  current = chatJob();
  await h.runPollingTimer();
  assert.match(allText(h.api.elements.chatLog), /A função retorna OK/);
  assert.equal(h.api.elements.chatSend.disabled, false);
  const before = h.requests.filter(r => r.url.startsWith('/chat/')).length;
  await h.runPollingTimer();
  assert.equal(h.requests.filter(r => r.url.startsWith('/chat/')).length, before);
});

for (const draft of [null, 'Rascunho novo', '']) {
  test('falha posterior restaura apenas rascunho intocado: ' + JSON.stringify(draft), async () => {
    let current = chatJob('running');
    const h = createHarness([], { chatResponse: async () => reportResponse(current) });
    h.api.startPolling();
    await sendChat(h, 'Pergunta original');
    if (draft !== null) {
      h.api.elements.chatInput.value = draft;
      h.api.elements.chatInput.listeners.input();
    }
    current = chatJob('failed', { error: 'PRIVATE_SENTINEL' });
    await h.runPollingTimer();
    assert.equal(h.api.elements.chatInput.value, draft === null ? 'Pergunta original' : draft);
    assert.equal(h.api.state.chatContext.running, false);
    assert.equal(h.api.elements.chatSend.disabled, false);
    assert.doesNotMatch(allText(h.api.elements.chatLog), /PRIVATE_SENTINEL/);
    const before = h.requests.length;
    await h.runPollingTimer();
    assert.equal(h.requests.slice(before).some(r => r.url.startsWith('/chat/')), false);
  });
}

for (const message of ['', '  ', 'x'.repeat(4001)]) {
  test('mensagem inválida não chama API: ' + message.length, async () => {
    const h = createHarness([]);
    await sendChat(h, message);
    assert.equal(h.requests.length, 0);
    assert.equal(h.api.state.chatTurns.length, 0);
    assert.equal(h.elements.notification.className, 'notification error');
  });
}

for (const job of [null, chatJob('unknown'), chatJob('completed', { kind: 'consultation' }),
  chatJob('completed', { job_id: ['e'.repeat(32)] }),
  chatJob('completed', { provider: 'Mock' }), chatJob('completed', { job_id: '../wrong' }),
  chatJob('completed', { report: {} }),
  chatJob('completed', { report: { ...chatJob().report, reply: '' } }),
  chatJob('completed', { report: { ...chatJob().report, actions: [] } }),
  chatJob('completed', { report: { ...chatJob().report, references: ['conversation'] } }),
  chatJob('completed', { report: { ...chatJob().report, references: ['private.py'] } }),
  chatJob('completed', { report: { ...chatJob().report, references: ['request', 'request'] } }),
  chatJob('completed', { report: { ...chatJob().report, source_selection: null } }),
  chatJob('completed', { report: { ...chatJob().report, sources: [{ path: 'app.py', sha256: 'bad' }] } }),
  chatJob('completed', { report: { ...chatJob().report, sources: [{ path: 'app.py', sha256: ['d'.repeat(64)] }] } }),
]) {
  test('chat recusa resposta inválida sem alterar a operação: ' + JSON.stringify(job).slice(0, 100), async () => {
    const h = createHarness([summaryTask()], { chatData: job });
    await sendChat(h, 'Pergunta original');
    assert.equal(h.api.elements.chatInput.value, 'Pergunta original');
    assert.equal(h.api.state.chatTurns[0].report, null);
    assert.equal(h.api.state.chatContext.running, false);
    assert.equal(h.api.elements.chatSend.disabled, false);
    assert.equal(h.elements.notification.className, 'notification error');
    assert.equal(h.requests.filter(r => r.options.method === 'POST' && r.url !== '/chat').length, 0);
  });
}

for (const error of ['timeout: O tempo de espera da investigação foi excedido. Tente novamente.',
  'transport_error: A comunicação com o Codex falhou. Tente novamente.',
  'invalid_response: A IA retornou uma resposta inválida. Tente novamente.', null, { private: 'PRIVATE_SENTINEL' }]) {
  test('falha de chat usa somente mensagens públicas: ' + JSON.stringify(error), async () => {
    const options = { chatData: chatJob('failed', { error }) };
    const h = createHarness([], options);
    await sendChat(h, 'Pergunta original');
    assert.doesNotMatch(allText(h.api.elements.chatLog), /PRIVATE_SENTINEL/);
    assert.equal(h.api.state.chatContext.running, false);
    options.chatData = chatJob();
    await sendChat(h, 'Pergunta original');
    assert.equal(h.api.state.chatTurns.at(-1).report.reply, chatJob().report.reply);
    const sent = JSON.parse(h.requests.filter(r => r.url === '/chat').at(-1).options.body);
    assert.deepEqual(sent.history, []);
  });
}

test('falhas de transporte não expõem mensagens arbitrárias nem provocam reenvio automático', async () => {
  const h = createHarness([], { chatResponse: async () => { throw new TypeError('PRIVATE_SENTINEL'); } });
  await sendChat(h, 'Pergunta');
  assert.doesNotMatch(allText(h.api.elements.chatLog), /PRIVATE_SENTINEL/);
  assert.equal(h.api.elements.chatInput.value, 'Pergunta');
  assert.equal(h.requests.length, 1);
});

test('chat trata HTML como texto, copia por alternativa e informa falha de cópia', async () => {
  const job = chatJob();
  job.report.reply = '<img src=x onerror=alert(1)>';
  job.report.references = [];
  job.report.source_selection.truncated = true;
  const options = { chatData: job, noClipboard: true };
  const h = createHarness([], options);
  await sendChat(h, 'Pergunta');
  assert.equal(findSummaryNode(h.api.elements.chatLog, n => n.tagName === 'IMG'), null);
  await chatCopy(h).listeners.click();
  assert.match(h.copied[0], /<img/);
  assert.match(h.copied[0], /abreviado/);
  options.fallbackFails = true;
  await chatCopy(h).listeners.click();
  assert.equal(h.elements.notification.className, 'notification error');
  assert.equal(chatCopy(h).disabled, false);
});

test('resposta antiga de chat é ignorada quando o contexto deixa de ser o ativo', async () => {
  let finish;
  const h = createHarness([], { chatResponse: () => new Promise(resolve => { finish = resolve; }) });
  const pending = sendChat(h, 'Pergunta antiga');
  h.api.state.chatContext = null;
  h.api.state.chatTurns = [];
  h.api.elements.chatInput.value = 'Rascunho novo';
  finish(reportResponse(chatJob()));
  await pending;
  assert.equal(h.api.elements.chatInput.value, 'Rascunho novo');
  assert.equal(h.api.state.chatTurns.length, 0);
});

test('chat respeita operação ocupada e consulta de IA já em andamento', async () => {
  const h = createHarness([], { chatData: chatJob() });
  h.api.state.busy = true;
  await sendChat(h, 'Pergunta');
  h.api.state.busy = false;
  h.api.state.consultationContext = { running: true };
  await sendChat(h, 'Pergunta');
  assert.equal(h.requests.length, 0);
});

test('falha de transporte no acompanhamento do chat restaura a pergunta e exige nova ação manual', async () => {
  const h = createHarness([], { chatResponse: async url => {
    if (url === '/chat') return reportResponse(chatJob('running'));
    throw new TypeError('PRIVATE_SENTINEL');
  } });
  h.api.startPolling();
  await sendChat(h, 'Pergunta original');
  await h.runPollingTimer();
  assert.equal(h.api.elements.chatInput.value, 'Pergunta original');
  assert.equal(h.api.state.chatContext.inFlight, false);
  assert.equal(h.api.state.chatContext.running, false);
  assert.doesNotMatch(allText(h.api.elements.chatLog), /PRIVATE_SENTINEL/);
});

test('acompanhamento antigo do chat não preenche uma conversa substituta', async () => {
  let finish;
  const h = createHarness([], { chatResponse: async url => url === '/chat'
    ? reportResponse(chatJob('running')) : new Promise(resolve => { finish = resolve; }) });
  h.api.startPolling();
  await sendChat(h, 'Pergunta antiga');
  const pending = h.runPollingTimer();
  for (let i = 0; !finish && i < 20; i++) await Promise.resolve();
  assert.equal(typeof finish, 'function');
  h.api.state.chatContext = null;
  h.api.state.chatTurns = [];
  h.api.elements.chatInput.value = 'Rascunho da conversa nova';
  finish(reportResponse(chatJob()));
  await pending;
  assert.equal(h.api.state.chatTurns.length, 0);
  assert.equal(h.api.elements.chatInput.value, 'Rascunho da conversa nova');
});
