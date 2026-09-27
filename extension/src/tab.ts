export interface PageCapture {
  tabId: number;
  url: string;
  title: string;
  selection: string;
  content: string;
}

export interface TabOutcome {
  ok: boolean;
  error?: string;
  title?: string;
  url?: string;
  content?: string;
  detail?: string;
}

export interface PageRequest {
  tool: string;
  selector?: string;
  url?: string;
  text?: string;
  value?: string;
  attribute?: string;
}

const HOST_ORIGINS = ["http://*/*", "https://*/*"] as const;

export function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (url.protocol === "http:" || url.protocol === "https:") && url.username === "" && url.password === "";
  } catch {
    return false;
  }
}

export async function hasHostPermission(): Promise<boolean> {
  return chrome.permissions.contains({ origins: [...HOST_ORIGINS] });
}

export function requestHostPermission(callback: (granted: boolean) => void): void {
  chrome.permissions.request({ origins: [...HOST_ORIGINS] }, callback);
}

export async function captureActivePage(): Promise<PageCapture> {
  const tab = await activeTab();
  const [injected] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => {
      const selection = window.getSelection()?.toString() ?? "";
      const root =
        document.querySelector("article") || document.querySelector("main") || document.body;
      const raw = root?.innerText ?? "";
      const content = raw.replace(/\n{3,}/g, "\n\n").trim().slice(0, 80000);
      return {
        url: location.href,
        title: document.title,
        selection: selection.slice(0, 8000),
        content,
      };
    },
  });
  const result = injected?.result;
  if (!result || typeof result.url !== "string") {
    throw new Error("Chrome did not return the page text.");
  }
  return { tabId: tab.id, ...result };
}

export async function runTabAction(
  tabId: number,
  tool: string,
  args: Record<string, string>,
): Promise<TabOutcome> {
  try {
    if (tool === "browser__navigate") {
      return await navigate(tabId, args.url ?? "");
    }
    const request: PageRequest = {
      tool,
      selector: args.selector,
      url: args.url,
      text: args.text,
      value: args.value,
      attribute: args.attribute,
    };
    const [injected] = await chrome.scripting.executeScript({
      target: { tabId },
      func: performInPage,
      args: [request],
    });
    return injected?.result ?? { ok: false, error: "Chrome did not return a result." };
  } catch (error) {
    const message = error instanceof Error ? error.message : "the tab action failed";
    return { ok: false, error: message };
  }
}

async function activeTab(): Promise<chrome.tabs.Tab & { id: number }> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id === undefined) {
    throw new Error("No active tab. Click the Swag Bot icon on the page you want to use.");
  }
  if (tab.url?.startsWith("chrome://") || tab.url?.startsWith("chrome-extension://")) {
    throw new Error("Swag Bot cannot read a Chrome internal page. Open a normal web page.");
  }
  return tab as chrome.tabs.Tab & { id: number };
}

async function navigate(tabId: number, url: string): Promise<TabOutcome> {
  if (!isHttpUrl(url)) {
    return { ok: false, error: "url must be an http or https URL" };
  }
  await new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(onUpdated);
      reject(new Error("navigation timed out"));
    }, 15000);
    const onUpdated = (id: number, info: { status?: string }) => {
      if (id === tabId && info.status === "complete") {
        window.clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(onUpdated);
        resolve();
      }
    };
    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.update(tabId, { url }, () => {
      const message = chrome.runtime.lastError?.message;
      if (message) {
        window.clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(onUpdated);
        reject(new Error(message));
      }
    });
  });
  const [injected] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => ({ title: document.title, url: location.href }),
  });
  const landed = injected?.result;
  return {
    ok: true,
    url: landed?.url || url,
    title: landed?.title || "",
    detail: url,
  };
}

function performInPage(request: PageRequest): TabOutcome {
  const refusedClick =
    "This control submits a form or leaves the site. Use browser__submit or browser__navigate so it can be approved on its own.";

  function snapshot(): TabOutcome {
    const root =
      document.querySelector("article") || document.querySelector("main") || document.body;
    const raw = root?.innerText ?? "";
    return {
      ok: true,
      title: document.title,
      url: location.href,
      content: raw.replace(/\n{3,}/g, "\n\n").trim().slice(0, 12000),
    };
  }

  function find(selector: string | undefined): Element | null {
    if (!selector) return null;
    try {
      return document.querySelector(selector);
    } catch {
      return null;
    }
  }

  function isSubmit(el: Element): boolean {
    if (el instanceof HTMLButtonElement) {
      return (el.getAttribute("type") || "submit").toLowerCase() === "submit";
    }
    if (el instanceof HTMLInputElement) {
      return el.type === "submit" || el.type === "image";
    }
    return false;
  }

  function leavesSite(el: Element): boolean {
    if (!(el instanceof HTMLAnchorElement) || !el.href) return false;
    let next: URL;
    try {
      next = new URL(el.href, location.href);
    } catch {
      return true;
    }
    if (next.protocol !== "http:" && next.protocol !== "https:") return true;
    return next.host !== location.host;
  }

  if (request.tool === "browser__snapshot") return snapshot();

  const selector = request.selector ?? "";
  const el = find(selector);
  if (!el) return { ok: false, error: `No element matches ${selector}` };

  if (request.tool === "browser__click") {
    if (isSubmit(el) || leavesSite(el)) return { ok: false, error: refusedClick };
    if (el instanceof HTMLElement) el.click();
    return { ok: true, url: location.href, title: document.title, detail: selector };
  }

  if (request.tool === "browser__type_text" || request.tool === "browser__fill") {
    const value = request.tool === "browser__fill" ? (request.value ?? "") : (request.text ?? "");
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      el.focus();
      el.value = request.tool === "browser__fill" ? value : el.value + value;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return {
        ok: true,
        detail: request.tool === "browser__fill" ? `filled ${selector}` : `typed into ${selector}`,
        url: location.href,
      };
    }
    if (el instanceof HTMLElement && el.isContentEditable) {
      el.focus();
      el.textContent = request.tool === "browser__fill" ? value : (el.textContent ?? "") + value;
      return { ok: true, detail: `updated ${selector}`, url: location.href };
    }
    return { ok: false, error: "That element is not an input." };
  }

  if (request.tool === "browser__submit") {
    const form = el instanceof HTMLFormElement ? el : el.closest("form");
    if (!form) return { ok: false, error: "No form found for that selector." };
    let approved: URL;
    try {
      approved = new URL(request.url ?? "", location.href);
    } catch {
      return { ok: false, error: "url must be an http or https URL" };
    }
    const action = form.getAttribute("action") || "";
    let target: URL;
    try {
      target = !action || action.startsWith("?") ? new URL(location.href) : new URL(action, location.href);
    } catch {
      return { ok: false, error: "The form action is not a URL Swag Bot can check." };
    }
    if (target.host !== approved.host) {
      return {
        ok: false,
        error: "The form posts to a different site than the URL you approved.",
      };
    }
    if (typeof form.requestSubmit === "function") form.requestSubmit();
    else form.submit();
    return { ok: true, url: location.href, detail: selector };
  }

  if (request.tool === "browser__extract") {
    let nodes: NodeListOf<Element>;
    try {
      nodes = document.querySelectorAll(selector);
    } catch {
      return { ok: false, error: "selector is not valid CSS" };
    }
    const parts: string[] = [];
    const attribute = request.attribute ?? "";
    nodes.forEach((node, index) => {
      if (index >= 20) return;
      const value = attribute ? (node.getAttribute(attribute) ?? "") : (node.textContent ?? "").trim();
      if (value) parts.push(value.slice(0, 500));
    });
    return {
      ok: true,
      title: document.title,
      url: location.href,
      content: parts.join("\n").slice(0, 12000),
    };
  }

  return { ok: false, error: `unknown tab tool: ${request.tool}` };
}
