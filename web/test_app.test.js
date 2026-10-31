"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const APP_PATH = path.join(__dirname, "app.js");
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

  append(...nodes) {
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
}

const ELEMENT_IDS = [
  "health-indicator",
  "health-label",
  "api-status",
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

  const requests = [];
  const pendingTaskRequests = new Map();

  const document = {
    getElementById(id) {
      return elements[id] || null;
    },
    createElement(tagName) {
      return new FakeElement(tagName);
    },
  };

  async function fetchMock(url, options = {}) {
    requests.push({ url, options });

    let data;

    if (url === "/health") {
      data = { status: "ok" };
    } else if (url === "/tasks") {
      data = { tasks: [...tasks] };
    } else if (url.startsWith("/tasks/")) {
      const id = decodeURIComponent(url.slice("/tasks/".length));

      if (harnessOptions.deferTaskRequests) {
        return await new Promise((resolve) => {
          const queue = pendingTaskRequests.get(id) || [];

          queue.push(() => {
            const task = tasks.find(
              (item) => item.approval_id === id
            ) || {};

            const failure = harnessOptions.taskRequestFailures?.[id];

            if (failure) {
              resolve({
                ok: false,
                status: failure.status || 500,
                async text() {
                  return JSON.stringify({ error: failure.message });
                },
              });
              return;
            }

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
    renderTaskList,
    refreshTasks,
    selectTask,
    initialize,
    state,
    elements
  };
})();`
  );

  const context = vm.createContext({
    document,
    fetch: fetchMock,
    window: {
      confirm: () => true,
      setTimeout: () => 1,
      clearTimeout: () => {},
    },
    console,
  });

  vm.runInContext(instrumentedSource, context, {
    filename: APP_PATH,
  });

  return {
    api: context.__devagentTest,
    elements,
    requests,
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
