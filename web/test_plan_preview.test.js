"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../devagent_studio/app.js"), "utf8");

class Node {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {};
    this.style = {}; this.attributes = {}; this.textContent = "";
    this.classList = { add() {} }; this.scrollTop = 0;
  }
  get firstChild() { return this.children[0] || null; }
  append(...nodes) { for (const n of nodes) { n.parent = this; this.children.push(n); } }
  removeChild(node) { this.children.splice(this.children.indexOf(node), 1); }
  remove() { this.parent?.removeChild(this); }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(key, fn) { this.listeners[key] = fn; }
  focus() {} select() {} setSelectionRange() {}
}
function harness(options = {}) {
  const elements = new Map();
  const copied = [];
  const document = {
    body: new Node("body"), activeElement: new Node(),
    hidden: false, listeners: {},
    addEventListener(name, listener) { this.listeners[name] = listener; },
    getElementById(id) { if (!elements.has(id)) elements.set(id, new Node()); return elements.get(id); },
    createElement(tag) { return new Node(tag); },
    execCommand(command) {
      assert.equal(command, "copy");
      if (options.fallbackFails) return false;
      copied.push(document.body.children.at(-1).value); return true;
    },
  };
  const context = vm.createContext({
    fetch: async (url) => {
      const currentTask = options.currentTask || task();
      let data;
      if (url === "/health") data = { status: "ok", ai_provider: "Codex" };
      else if (url === "/tasks") data = { tasks: [currentTask] };
      else if (url === `/tasks/${encodeURIComponent(currentTask.approval_id)}`) data = currentTask;
      else throw new Error(`Rota inesperada: ${url}`);
      return { ok: true, status: 200, async text() { return JSON.stringify(data); } };
    },
    document, navigator: { clipboard: { async writeText(content) {
      if (options.clipboardFails) throw new Error("denied");
      copied.push(content);
    } } },
    window: {
      location: { host: "127.0.0.1:35319" },
      setTimeout() { return 1; }, clearTimeout() {},
    }, console,
  });
  const marker = "  initialize();\n})();";
  assert.equal(source.split(marker).length, 2);
  vm.runInContext(source.replace(marker, "  globalThis.api = { renderPlanPanel, elements, state, pollTasks };\n})();"), context);
  return { ...context.api, document, copied };
}
function task(id = "158", content = 'print("Olá")\n') {
  return { approval_id: id, status: "pending", plan: { objective: "Revisar", changes: [
    { path: "example.py", change_type: "create", content },
  ], tests: [], risks: [] } };
}
function find(node, tag) {
  if (node.tagName === tag) return node;
  for (const child of node.children) { const found = find(child, tag); if (found) return found; }
}
test("atualizar a mesma tarefa preserva o painel aberto e o elemento de texto", () => {
  const h = harness(); const t = task(); h.renderPlanPanel(t);
  const details = find(h.elements.planContent, "DETAILS");
  const pre = find(details, "PRE"); details.open = true; pre.scrollTop = 63;
  h.renderPlanPanel(JSON.parse(JSON.stringify(t)));
  assert.equal(find(h.elements.planContent, "DETAILS"), details);
  assert.equal(details.open, true); assert.equal(find(details, "PRE"), pre);
  assert.equal(pre.scrollTop, 63);
});
test("polling real da tarefa selecionada preserva o painel aberto", async () => {
  const t = task(); const h = harness({ currentTask: t });
  h.state.selectedTaskId = t.approval_id;
  h.state.selectedTask = t; h.state.pollingStarted = true;
  h.renderPlanPanel(t);
  const details = find(h.elements.planContent, "DETAILS"); details.open = true;
  const pre = find(details, "PRE");
  await h.pollTasks();
  assert.equal(find(h.elements.planContent, "DETAILS"), details);
  assert.equal(details.open, true); assert.equal(find(details, "PRE"), pre);
});
test("mudança de estado atualiza controles sem recriar o conteúdo", () => {
  const h = harness(); const t = task(); h.renderPlanPanel(t);
  const details = find(h.elements.planContent, "DETAILS"); details.open = true;
  t.status = "rolled_back"; h.renderPlanPanel(t);
  assert.equal(h.elements.planStatus.textContent, "REVERTIDA");
  assert.equal(h.elements.approvalActions.hidden, true);
  assert.equal(find(h.elements.planContent, "DETAILS"), details);
});
test("plano alterado substitui o texto e exige nova abertura", () => {
  const h = harness(); h.renderPlanPanel(task());
  const before = find(h.elements.planContent, "DETAILS"); before.open = true;
  h.renderPlanPanel(task("158", "NOVO\n"));
  const after = find(h.elements.planContent, "DETAILS");
  assert.notEqual(after, before); assert.notEqual(after.open, true);
  assert.equal(find(after, "PRE").textContent, "NOVO\n");
});
test("outra tarefa com plano igual recebe novos elementos", () => {
  const h = harness(); h.renderPlanPanel(task());
  const before = find(h.elements.planContent, "DETAILS");
  h.renderPlanPanel(task("159"));
  assert.notEqual(find(h.elements.planContent, "DETAILS"), before);
});
test("copiar preserva exatamente acentos e quebras de linha", async () => {
  const h = harness(); const content = 'Olá\n\n  print("ação")\n';
  h.renderPlanPanel(task("158", content));
  await find(find(h.elements.planContent, "DETAILS"), "BUTTON").listeners.click();
  assert.deepEqual(h.copied, [content]);
  assert.equal(h.elements.notification.textContent, "Conteúdo copiado.");
});
test("cópia alternativa funciona quando navegador nega clipboard", async () => {
  const h = harness({ clipboardFails: true }); h.renderPlanPanel(task());
  await find(find(h.elements.planContent, "DETAILS"), "BUTTON").listeners.click();
  assert.deepEqual(h.copied, ['print("Olá")\n']);
  assert.equal(h.document.body.children.length, 0);
});
test("falha de cópia é informada sem apagar o conteúdo", async () => {
  const h = harness({ clipboardFails: true, fallbackFails: true }); h.renderPlanPanel(task());
  const pre = find(h.elements.planContent, "PRE");
  await find(find(h.elements.planContent, "DETAILS"), "BUTTON").listeners.click();
  assert.equal(h.copied.length, 0); assert.equal(h.document.body.children.length, 0);
  assert.match(h.elements.notification.textContent, /Não foi possível copiar/);
  assert.equal(find(h.elements.planContent, "PRE"), pre);
});
