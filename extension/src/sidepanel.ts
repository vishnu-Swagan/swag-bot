import "./sidepanel.css";
import {
  captureActivePage,
  hasHostPermission,
  requestHostPermission,
  runTabAction,
  type PageCapture,
  type TabOutcome,
} from "./tab.js";

const HOST_NAME = "com.swagbot.host";

type Autonomy = "ask-always" | "ask-risky" | "auto";

interface StepView {
  id: string;
  title: string;
  status: string;
}

interface ApprovalView {
  requestId: string;
  risk: string;
  summary: string;
  kind: string;
  url?: string;
  selector?: string;
  text?: string;
  target?: string;
}

interface HostEvent {
  kind?: string;
  text?: string;
  plan?: { steps?: StepView[] } | null;
}

const AUTONOMY_HINT: Record<Autonomy, string> = {
  "ask-risky": "Asks before anything that is not a pure read. This is the default.",
  "ask-always": "Asks before every action, including reads.",
  auto: "Does not ask. Actions are still logged. A hard deny still applies.",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "Pending",
  doing: "Doing",
  verifying: "Verifying",
  done: "Done",
  failed: "Failed",
  skipped: "Skipped",
};

const state = {
  port: null as chrome.runtime.Port | null,
  connected: false,
  runId: null as string | null,
  running: false,
  page: null as PageCapture | null,
  useTab: false,
  approval: null as ApprovalView | null,
};

const connection = document.querySelector<HTMLElement>("#connection");
const setup = document.querySelector<HTMLElement>("#setup");
const setupTitle = document.querySelector<HTMLElement>("#setup-title");
const setupDetail = document.querySelector<HTMLElement>("#setup-detail");
const extensionId = document.querySelector<HTMLElement>("#extension-id");
const installCommand = document.querySelector<HTMLElement>("#install-command");
const goal = document.querySelector<HTMLTextAreaElement>("#goal");
const autonomy = document.querySelector<HTMLSelectElement>("#autonomy");
const autonomyHint = document.querySelector<HTMLElement>("#autonomy-hint");
const tabHint = document.querySelector<HTMLElement>("#tab-hint");
const useTab = document.querySelector<HTMLInputElement>("#use-tab");
const pageChip = document.querySelector<HTMLElement>("#page-chip");
const pageTitle = document.querySelector<HTMLElement>("#page-title");
const pageUrl = document.querySelector<HTMLElement>("#page-url");
const banner = document.querySelector<HTMLElement>("#banner");
const runButton = document.querySelector<HTMLButtonElement>("#run");
const cancelButton = document.querySelector<HTMLButtonElement>("#cancel");
const progress = document.querySelector<HTMLElement>("#progress");
const steps = document.querySelector<HTMLOListElement>("#steps");
const logWrap = document.querySelector<HTMLElement>("#log-wrap");
const log = document.querySelector<HTMLElement>("#log");
const approval = document.querySelector<HTMLElement>("#approval");
const approvalSummary = document.querySelector<HTMLElement>("#approval-summary");
const approvalMeta = document.querySelector<HTMLElement>("#approval-meta");
const summary = document.querySelector<HTMLElement>("#summary");
const summaryBody = document.querySelector<HTMLElement>("#summary-body");
const composer = document.querySelector<HTMLFormElement>("#composer");

function requireElement<T extends Element>(element: T | null, name: string): T {
  if (!element) throw new Error(`missing ${name}`);
  return element;
}

const ui = {
  connection: requireElement(connection, "connection"),
  setup: requireElement(setup, "setup"),
  setupTitle: requireElement(setupTitle, "setup-title"),
  setupDetail: requireElement(setupDetail, "setup-detail"),
  extensionId: requireElement(extensionId, "extension-id"),
  installCommand: requireElement(installCommand, "install-command"),
  goal: requireElement(goal, "goal"),
  autonomy: requireElement(autonomy, "autonomy"),
  autonomyHint: requireElement(autonomyHint, "autonomy-hint"),
  tabHint: requireElement(tabHint, "tab-hint"),
  useTab: requireElement(useTab, "use-tab"),
  pageChip: requireElement(pageChip, "page-chip"),
  pageTitle: requireElement(pageTitle, "page-title"),
  pageUrl: requireElement(pageUrl, "page-url"),
  banner: requireElement(banner, "banner"),
  runButton: requireElement(runButton, "run"),
  cancelButton: requireElement(cancelButton, "cancel"),
  progress: requireElement(progress, "progress"),
  steps: requireElement(steps, "steps"),
  logWrap: requireElement(logWrap, "log-wrap"),
  log: requireElement(log, "log"),
  approval: requireElement(approval, "approval"),
  approvalSummary: requireElement(approvalSummary, "approval-summary"),
  approvalMeta: requireElement(approvalMeta, "approval-meta"),
  summary: requireElement(summary, "summary"),
  summaryBody: requireElement(summaryBody, "summary-body"),
  composer: requireElement(composer, "composer"),
};

function installLine(): string {
  return `swag extension install --extension-id ${chrome.runtime.id}`;
}

function setBanner(message: string): void {
  ui.banner.hidden = !message;
  ui.banner.textContent = message;
}

function showSetup(title: string, detail: string): void {
  state.connected = false;
  ui.connection.textContent = "Not connected";
  ui.setup.hidden = false;
  ui.setupTitle.textContent = title;
  ui.setupDetail.textContent = detail;
  ui.runButton.disabled = true;
}

function showReady(version: string): void {
  state.connected = true;
  ui.setup.hidden = true;
  ui.connection.textContent = version ? `Connected · swag-bot ${version}` : "Connected";
  ui.runButton.disabled = state.running || ui.goal.value.trim() === "";
}

function explainDisconnect(message: string): { title: string; detail: string } {
  const text = message.toLowerCase();
  if (text.includes("forbidden")) {
    return {
      title: "This extension is not allowed to talk to Swag Bot yet.",
      detail:
        "The host only accepts extension ids it was given. Register this id, then quit Chrome completely.",
    };
  }
  if (text.includes("not found") || text.includes("specified native messaging host")) {
    return {
      title: "Swag Bot's bridge is not registered.",
      detail: "The panel talks to a native messaging host on this computer. Install it with the command below.",
    };
  }
  if (text.includes("exited")) {
    return {
      title: "Swag Bot closed the connection.",
      detail: "If a task was running, it stopped. Check that `swag version` works, then try again.",
    };
  }
  return {
    title: "Swag Bot is not connected.",
    detail: message || "The native messaging host did not answer.",
  };
}

function renderAutonomy(): void {
  const value = ui.autonomy.value as Autonomy;
  ui.autonomyHint.textContent = AUTONOMY_HINT[value] ?? AUTONOMY_HINT["ask-risky"];
}

function renderPage(): void {
  const page = state.page;
  ui.pageChip.hidden = page === null;
  if (!page) return;
  ui.pageTitle.textContent = page.title || "Untitled page";
  ui.pageUrl.textContent = page.url;
}

function renderUseTab(): void {
  ui.useTab.checked = state.useTab;
  ui.tabHint.hidden = !state.useTab;
  ui.tabHint.textContent =
    "Swag Bot can read, click, type, and navigate in the attached tab. " +
    "Every action still goes through the permission policy. " +
    "Click, type, and navigation ask for approval at ask-risky.";
}

function setRunning(running: boolean): void {
  state.running = running;
  ui.goal.disabled = running;
  ui.autonomy.disabled = running;
  ui.useTab.disabled = running;
  ui.cancelButton.hidden = !running;
  ui.runButton.disabled = running || !state.connected || ui.goal.value.trim() === "";
  const usePage = document.querySelector<HTMLButtonElement>("#use-page");
  if (usePage) usePage.disabled = running;
}

function resetTaskView(): void {
  state.approval = null;
  ui.progress.hidden = true;
  ui.steps.replaceChildren();
  ui.logWrap.hidden = true;
  ui.log.replaceChildren();
  ui.approval.hidden = true;
  ui.summary.hidden = true;
  ui.summaryBody.textContent = "";
  setBanner("");
}

function renderSteps(items: StepView[]): void {
  ui.progress.hidden = false;
  ui.steps.replaceChildren();
  for (const step of items) {
    const row = document.createElement("li");
    row.className = "step";
    row.dataset.status = step.status;
    const pip = document.createElement("span");
    pip.className = "pip";
    const title = document.createElement("p");
    title.className = "step-title";
    title.textContent = step.title;
    const pill = document.createElement("span");
    pill.className = "pill";
    pill.textContent = STATUS_LABEL[step.status] ?? step.status;
    row.append(pip, title, pill);
    ui.steps.append(row);
  }
}

function appendLog(text: string): void {
  const cleaned = text.trim();
  if (!cleaned) return;
  ui.logWrap.hidden = false;
  const line = document.createElement("p");
  line.className = "log-line";
  line.textContent = cleaned;
  const nearBottom = ui.log.scrollHeight - ui.log.scrollTop - ui.log.clientHeight < 40;
  ui.log.append(line);
  if (nearBottom) ui.log.scrollTop = ui.log.scrollHeight;
}

function showApproval(view: ApprovalView): void {
  state.approval = view;
  ui.approval.hidden = false;
  ui.approvalSummary.textContent = view.summary;
  ui.approvalMeta.replaceChildren();
  const rows: Array<[string, string | undefined]> = [
    ["Risk", view.risk],
    ["Kind", view.kind],
    ["URL", view.url],
    ["Selector", view.selector],
    ["Text", view.text],
    ["Target", view.target],
  ];
  for (const [label, value] of rows) {
    if (!value) continue;
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    ui.approvalMeta.append(dt, dd);
  }
  document.querySelector<HTMLButtonElement>("#deny")?.focus();
}

function connect(): void {
  state.port?.disconnect();
  state.port = null;
  state.connected = false;
  ui.connection.textContent = "Connecting…";
  ui.setup.hidden = true;
  let port: chrome.runtime.Port;
  try {
    port = chrome.runtime.connectNative(HOST_NAME);
  } catch (error) {
    const message = error instanceof Error ? error.message : "native messaging failed";
    const explained = explainDisconnect(message);
    showSetup(explained.title, explained.detail);
    return;
  }
  state.port = port;
  const timer = window.setTimeout(() => {
    if (!state.connected) {
      showSetup(
        "Swag Bot did not answer.",
        "Quit Chrome completely after `swag extension install`, then open this panel again.",
      );
    }
  }, 4000);
  port.onMessage.addListener((message: unknown) => {
    window.clearTimeout(timer);
    onHostMessage(message);
  });
  port.onDisconnect.addListener(() => {
    window.clearTimeout(timer);
    const message = chrome.runtime.lastError?.message ?? "disconnected";
    state.port = null;
    state.running = false;
    setRunning(false);
    const explained = explainDisconnect(message);
    showSetup(explained.title, explained.detail);
  });
  port.postMessage({ type: "hello" });
}

function post(message: Record<string, unknown>): void {
  state.port?.postMessage(message);
}

function onHostMessage(message: unknown): void {
  if (!message || typeof message !== "object") return;
  const record = message as Record<string, unknown>;
  if (record.type === "hello") {
    const version = typeof record.version === "string" ? record.version : "";
    showReady(version);
    return;
  }
  if (record.type === "pong") return;
  if (record.type === "event") {
    onEvent(record.event);
    return;
  }
  if (record.type === "approval_request") {
    const action = record.action;
    if (!action || typeof action !== "object" || typeof record.request_id !== "string") return;
    const view = action as Record<string, unknown>;
    showApproval({
      requestId: record.request_id,
      risk: stringField(view, "risk"),
      summary: stringField(view, "summary") || "Allow this action?",
      kind: stringField(view, "kind"),
      url: optionalField(view, "url"),
      selector: optionalField(view, "selector"),
      text: optionalField(view, "text"),
      target: optionalField(view, "target"),
    });
    return;
  }
  if (record.type === "tab_action") {
    void answerTabAction(record);
    return;
  }
  if (record.type === "result") {
    state.running = false;
    state.approval = null;
    ui.approval.hidden = true;
    setRunning(false);
    ui.summary.hidden = false;
    ui.summaryBody.textContent = typeof record.summary === "string" ? record.summary : "";
    state.runId = null;
    return;
  }
  if (record.type === "error") {
    const text = typeof record.message === "string" ? record.message : "the task failed";
    setBanner(text);
    if (state.running) {
      state.running = false;
      setRunning(false);
    }
  }
}

function onEvent(event: unknown): void {
  if (!event || typeof event !== "object") return;
  const record = event as HostEvent;
  const planSteps = record.plan?.steps;
  if (Array.isArray(planSteps)) renderSteps(planSteps);
  if (record.kind === "plan" && Array.isArray(planSteps)) {
    appendLog(`Planned ${planSteps.length} ${planSteps.length === 1 ? "step" : "steps"}.`);
  } else if (typeof record.text === "string" && record.text.trim()) {
    appendLog(record.text);
  }
}

async function answerTabAction(record: Record<string, unknown>): Promise<void> {
  const requestId = typeof record.request_id === "string" ? record.request_id : "";
  const tool = typeof record.tool === "string" ? record.tool : "";
  const args = record.arguments;
  const tabId = state.page?.tabId;
  let outcome: TabOutcome;
  if (!requestId || !tool) {
    outcome = { ok: false, error: "incomplete tab action" };
  } else if (!state.useTab || tabId === undefined) {
    outcome = { ok: false, error: "Act in this tab is off for this task." };
  } else {
    const cleaned: Record<string, string> = {};
    if (args && typeof args === "object") {
      for (const [key, value] of Object.entries(args)) {
        if (typeof value === "string") cleaned[key] = value;
      }
    }
    outcome = await runTabAction(tabId, tool, cleaned);
  }
  post({
    type: "tab_result",
    request_id: requestId,
    ok: outcome.ok,
    error: outcome.error ?? "",
    title: outcome.title ?? "",
    url: outcome.url ?? "",
    content: outcome.content ?? "",
    detail: outcome.detail ?? "",
  });
}

function stringField(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === "string" ? value : "";
}

function optionalField(record: Record<string, unknown>, key: string): string | undefined {
  const value = stringField(record, key);
  return value || undefined;
}

function answerApproval(approved: boolean): void {
  const pending = state.approval;
  if (!pending) return;
  state.approval = null;
  ui.approval.hidden = true;
  post({ type: "approval", request_id: pending.requestId, approved });
}

ui.extensionId.textContent = chrome.runtime.id;
ui.installCommand.textContent = installLine();

const savedAutonomy = localStorage.getItem("swag.autonomy");
if (savedAutonomy === "ask-always" || savedAutonomy === "ask-risky" || savedAutonomy === "auto") {
  ui.autonomy.value = savedAutonomy;
}
renderAutonomy();
void hasHostPermission().then((granted) => {
  state.useTab = granted && localStorage.getItem("swag.useTab") === "1";
  renderUseTab();
});

ui.autonomy.addEventListener("change", () => {
  localStorage.setItem("swag.autonomy", ui.autonomy.value);
  renderAutonomy();
});

ui.goal.addEventListener("input", () => {
  ui.runButton.disabled = state.running || !state.connected || ui.goal.value.trim() === "";
});

ui.goal.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    ui.composer.requestSubmit();
  }
});

document.querySelector("#use-page")?.addEventListener("click", () => {
  setBanner("");
  void captureActivePage()
    .then((page) => {
      state.page = page;
      renderPage();
    })
    .catch((error: unknown) => {
      const message = error instanceof Error ? error.message : "Could not read this page.";
      setBanner(
        `${message} Click the Swag Bot icon on the tab, or turn on Act in this tab and allow site access.`,
      );
    });
});

document.querySelector("#clear-page")?.addEventListener("click", () => {
  state.page = null;
  renderPage();
});

ui.useTab.addEventListener("change", () => {
  if (!ui.useTab.checked) {
    state.useTab = false;
    localStorage.setItem("swag.useTab", "0");
    renderUseTab();
    return;
  }
  ui.useTab.checked = false;
  requestHostPermission((granted) => {
    state.useTab = granted;
    localStorage.setItem("swag.useTab", granted ? "1" : "0");
    renderUseTab();
    if (!granted) {
      setBanner("Site access was not granted. Swag Bot can still use page text you attach.");
    }
  });
});

ui.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  void startRun();
});

async function startRun(): Promise<void> {
  if (!state.connected || state.running) return;
  const text = ui.goal.value.trim();
  if (!text) return;
  if (state.useTab && state.page === null) {
    try {
      state.page = await captureActivePage();
      renderPage();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not read this page.";
      setBanner(`${message} Open the page, then run the task again.`);
      return;
    }
  }
  resetTaskView();
  const runId = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
  state.runId = runId;
  setRunning(true);
  const attached = state.page;
  post({
    type: "run",
    id: runId,
    goal: text,
    autonomy: ui.autonomy.value,
    use_tab: state.useTab && attached !== null,
    page: attached
      ? {
          url: attached.url,
          title: attached.title,
          selection: attached.selection,
          content: attached.content,
        }
      : undefined,
  });
}

ui.cancelButton.addEventListener("click", () => {
  post({ type: "cancel", id: state.runId });
});

document.querySelector("#approve")?.addEventListener("click", () => answerApproval(true));
document.querySelector("#deny")?.addEventListener("click", () => answerApproval(false));
document.querySelector("#again")?.addEventListener("click", () => {
  resetTaskView();
  setRunning(false);
  ui.goal.focus();
});
document.querySelector("#retry")?.addEventListener("click", () => connect());
document.querySelector("#copy-command")?.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(installLine());
    setBanner("Copied the install command.");
  } catch {
    setBanner("Select the command and copy it.");
  }
});

connect();
