// Chrome remembers openPanelOnActionClick. While that is on, the toolbar
// click opens the panel and never reaches this listener, so activeTab is
// not granted and "Use this page" cannot read the tab. Turn it off, then
// open the panel from the action click, which does grant activeTab.
void chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: false })
  .catch(() => undefined);

chrome.action.onClicked.addListener((tab) => {
  if (tab.id === undefined) return;
  void chrome.sidePanel.open({ tabId: tab.id }).catch(() => undefined);
});
