"use strict";
const byId = id => document.getElementById(id);
const panels = Array.from(document.querySelectorAll("main section"));
let settings, state, page = "main", waiting = false;
const tiles = new Map();

function show(name) {
  page = name;
  panels.forEach(panel => { panel.hidden = panel.id !== (state && state.boot ? "boot" : page); });
  document.querySelectorAll("header [data-page]").forEach(button => {
    if (button.dataset.page === (page === "main" ? "main" : "settings")) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });
}

document.querySelectorAll("[data-page]").forEach(button => {
  button.addEventListener("click", () => show(button.dataset.page));
});

function options(id, entries, current) {
  const select = byId(id);
  select.textContent = "";
  entries.forEach(([value, label]) => select.add(new Option(label, value)));
  if (current !== undefined) select.value = current;
}

function controlFields() {
  const name = byId("control-choice").value;
  const led = state.buttons.find(button => button.name === name);
  const mode = led && settings.led_modes[led.led] || "toggle";
  options("led-mode", Array.from(new Set(["toggle", "latched", "momentary", "flash", mode])).map(value => [value, value]), mode);
  const mapping = settings.button_macros[name];
  byId("action").value = typeof mapping === "string" ? mapping : (mapping && mapping.action || "");
  byId("hold-ms").value = led && settings.confirm_ms[led.led] || 0;
}

async function loadSettings() {
  settings = await (await fetch("/settings")).json();
  const themes = Object.entries(settings.themes);
  options("theme-choice", themes, settings.theme);
  options("template-choice", themes);
  options("profile-choice", settings.profiles.map(name => [name, name]), settings.profile);
  const names = Object.keys(settings.macros);
  options("macro-choice", [["", "New macro"], ...names.map(name => [name, name])]);
  const list = byId("macro-names");
  list.textContent = "";
  names.forEach(name => list.appendChild(new Option(name, name)));
  if (state && state.buttons) {
    const current = byId("control-choice").value;
    options("control-choice", state.buttons.filter(button => button.led).map(button => [button.name, button.name]));
    if (current) byId("control-choice").value = current;
    controlFields();
  }
}

async function save(update) {
  if (!settings || waiting) return;
  waiting = true;
  try {
    const reply = await fetch("/settings", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-MFD-Token": settings.token},
      body: JSON.stringify(update)
    });
    if (!reply.ok) throw new Error("Settings request failed (" + reply.status + ")");
    await new Promise(resolve => setTimeout(resolve, 200));
    await loadSettings();
  } catch (error) {
    byId("status").textContent = error.message;
  } finally {
    waiting = false;
  }
}

function bind(id, payload) {
  byId(id).addEventListener("submit", event => {
    event.preventDefault();
    try {
      save(payload());
    } catch (error) {
      byId("status").textContent = error.message;
    }
  });
}
bind("theme-form", () => ({kind: "theme", theme: byId("theme-choice").value}));
bind("profile-form", () => ({kind: "profile", name: byId("profile-choice").value}));
bind("template-form", () => ({kind: "template", theme: byId("template-choice").value}));
bind("control-form", () => ({
  kind: "button", name: byId("control-choice").value, mode: byId("led-mode").value,
  action: byId("action").value.trim(), hold_ms: Number(byId("hold-ms").value)
}));
bind("macro-form", () => ({
  kind: "macro", name: byId("macro-name").value, macro: JSON.parse(byId("macro-definition").value)
}));
byId("control-choice").addEventListener("change", controlFields);
byId("macro-choice").addEventListener("change", event => {
  const name = event.target.value;
  byId("macro-name").value = name;
  byId("macro-definition").value = JSON.stringify(
    settings.macros[name] || {keys: ["KEY_F16"], press_ms: 40, release_ms: 40}, null, 2
  );
});

function present(sample) {
  document.documentElement.dataset.theme = sample.theme;
  byId("profile").textContent = sample.profile;
  byId("status").textContent = sample.status;
  if (sample.boot) {
    byId("boot-stage").textContent = sample.boot.stage;
    byId("boot-message").textContent = sample.boot.message;
    return;
  }
  byId("gear").textContent = sample.gear === -2 ? "R" : sample.gear === -1 ? "N" : sample.gear;
  byId("tuner").textContent = sample.tuner;
  byId("layer").textContent = sample.layer;
  byId("diagnostic-values").textContent = sample.diagnostics.lines.join("\n");
  byId("pressed").textContent = sample.diagnostics.pressed.join(", ") || "None";
  sample.buttons.forEach(button => {
    if (!tiles.has(button.name)) {
      const tile = document.createElement("div");
      tile.append(document.createElement("i"), document.createTextNode(button.name), document.createElement("small"));
      byId("buttons").appendChild(tile);
      tiles.set(button.name, tile);
    }
    const tile = tiles.get(button.name);
    tile.dataset.held = String(button.held);
    const level = button.led ? button.level : (button.held ? 15 : 0);
    tile.firstChild.style.background = level ? "var(--accent)" : "transparent";
    tile.firstChild.style.opacity = level ? String(level / 15) : "1";
    const phase = button.phase && button.phase !== "idle" ? button.phase : "";
    tile.lastChild.textContent = phase ? {holding:"Hold", pending:"Queued", confirmed:"Done", aborted:"Abort"}[phase] : "";
    tile.title = phase || (button.held ? "Held" : level ? "On" : "Off");
  });
}

async function refresh() {
  try {
    const sample = await (await fetch("/state")).json();
    if (sample.buttons) {
      const first = !state;
      state = sample;
      present(state);
      show(page);
      if (first || !settings) await loadSettings();
    }
  } catch (error) {
    byId("status").textContent = "Waiting for controller";
  }
  setTimeout(refresh, 40);
}
refresh();
