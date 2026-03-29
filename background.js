// 확장 프로그램 아이콘 클릭 시 사이드 패널 열기
chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ tabId: tab.id });
});

// 메시지 라우팅: content script <-> side panel
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // content → sidepanel (spy 데이터)
  if (message.type.startsWith('SPY_') || message.type === 'CAPTCHA_DETECTED') {
    chrome.runtime.sendMessage(message).catch(() => {});
  }

  // content → sidepanel (캡차 API 힌트 요청)
  if (message.type === 'CAPTCHA_HINT_REQUEST') {
    chrome.runtime.sendMessage(message).catch(() => {});
  }

  // sidepanel → content (캡차 API 힌트 결과)
  if (message.type === 'CAPTCHA_HINT') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) {
        chrome.tabs.sendMessage(tabs[0].id, message);
      }
    });
  }

  // 캡차 감지 시 페이지 탭에 포커스 유지 (사이드 패널이 포커스를 뺏지 않도록)
  if (message.type === 'CAPTCHA_DETECTED' && sender.tab) {
    chrome.tabs.update(sender.tab.id, { active: true });
  }

  // sidepanel → content (캡차 입력)
  if (message.type === 'FILL_CAPTCHA_TO_TAB') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) {
        chrome.tabs.sendMessage(tabs[0].id, {
          type: 'DO_FILL_CAPTCHA',
          text: message.text,
          autoSubmit: message.autoSubmit
        });
      }
    });
  }

  // sidepanel → content (분석/스냅샷 요청)
  if (message.type === 'REQUEST_ANALYSIS') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) {
        chrome.tabs.sendMessage(tabs[0].id, { type: 'REQUEST_ANALYSIS' }, (response) => {
          sendResponse(response);
        });
      }
    });
    return true;
  }

  if (message.type === 'REQUEST_SNAPSHOT') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) {
        chrome.tabs.sendMessage(tabs[0].id, { type: 'REQUEST_SNAPSHOT' }, (response) => {
          sendResponse(response);
        });
      }
    });
    return true;
  }

  // sidepanel → JS 실행 (chrome.scripting.executeScript 사용, CSP 우회)
  if (message.type === 'EXEC_JS') {
    chrome.tabs.query({ active: true, currentWindow: true }, async (tabs) => {
      if (!tabs[0]) {
        sendResponse({ ok: false, error: 'No active tab' });
        return;
      }
      try {
        const results = await chrome.scripting.executeScript({
          target: { tabId: tabs[0].id },
          func: (code) => {
            try {
              const result = Function('"use strict"; return (' + code + ')')();
              return { ok: true, result: String(result)?.substring(0, 2000) };
            } catch (e) {
              return { ok: false, error: e.message };
            }
          },
          args: [message.code],
          world: 'MAIN' // 페이지의 JS 컨텍스트에서 실행
        });
        sendResponse(results[0]?.result || { ok: false, error: 'No result' });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    });
    return true;
  }
});
