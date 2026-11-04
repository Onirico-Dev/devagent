const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(
  path.join(root, "devagent_studio/index.html"),
  "utf8"
);
const js = fs.readFileSync(
  path.join(root, "devagent_studio/app.js"),
  "utf8"
);

test("HTML possui identificador de endereco dinamico", () => {
  assert.match(
    html,
    /<strong\s+id="server-address">/
  );
});

test("HTML nao possui endereco fixo", () => {
  assert.doesNotMatch(html, /127\.0\.0\.1:8765/);
});

test("JavaScript utiliza a origem atual", () => {
  assert.match(
    js,
    /serverAddress\.textContent\s*=\s*window\.location\.host/
  );
});

test("endereco acompanha a porta do navegador", () => {
  const match = js.match(
    /const serverAddress = document\.getElementById\("server-address"\);\s*if \(serverAddress\) \{\s*serverAddress\.textContent = window\.location\.host;\s*\}/
  );

  assert.ok(match, "Bloco de atualizacao nao encontrado");

  for (const port of [8765, 8766, 9000]) {
    const element = { textContent: "" };

    const context = {
      document: {
        getElementById(id) {
          assert.equal(id, "server-address");
          return element;
        },
      },
      window: {
        location: {
          host: `127.0.0.1:${port}`,
        },
      },
    };

    vm.runInNewContext(match[0], context);

    assert.equal(
      element.textContent,
      `127.0.0.1:${port}`
    );
  }
});

test("JavaScript possui sintaxe valida", () => {
  assert.doesNotThrow(() => new vm.Script(js));
});
