let netCount = 0;

// ==============================
// 탭 전환
// ==============================
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
  });
});

// ==============================
// 이벤트 로그
// ==============================
function logEvent(msg, level = 'info') {
  const el = document.getElementById('event-log');
  const div = document.createElement('div');
  div.className = `log-entry ${level}`;
  const time = new Date().toLocaleTimeString('ko-KR');
  div.innerHTML = `<span class="time">${time}</span>${escapeHtml(msg)}`;
  el.prepend(div);
  // 최대 200개
  while (el.children.length > 200) el.lastChild.remove();
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

document.getElementById('clearLogBtn').addEventListener('click', () => {
  document.getElementById('event-log').innerHTML = '';
  document.getElementById('network-log').innerHTML = '';
  netCount = 0;
  document.getElementById('net-count').textContent = '0';
});

// ==============================
// 네트워크 로그
// ==============================
function addNetEntry(data) {
  netCount++;
  document.getElementById('net-count').textContent = netCount;

  const el = document.getElementById('network-log');
  const div = document.createElement('div');
  div.className = 'net-entry';

  const urlShort = data.url.length > 80 ? data.url.substring(0, 80) + '...' : data.url;
  const statusClass = data.status >= 200 && data.status < 400 ? 'status-ok' : 'status-err';

  div.innerHTML = `
    <span class="method ${data.method}">${data.method}</span>
    <span class="url">${escapeHtml(urlShort)}</span>
    <div class="meta">
      <span class="${statusClass}">${data.status}</span> · ${data.elapsed}ms
    </div>
    <div class="preview">${escapeHtml(data.responsePreview || '(empty)')}\n\n--- Request Body ---\n${escapeHtml(data.requestBody || '(none)')}</div>
  `;

  div.addEventListener('click', () => div.classList.toggle('expanded'));
  el.prepend(div);

  while (el.children.length > 300) el.lastChild.remove();
}

// ==============================
// DOM 스냅샷
// ==============================
document.getElementById('snapshotBtn').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'REQUEST_SNAPSHOT' }, (response) => {
    if (!response) {
      logEvent('스냅샷 실패 - 페이지에 content script가 없습니다', 'error');
      return;
    }
    renderSnapshot(response);
    logEvent('DOM 스냅샷 완료', 'success');
  });
});

function renderSnapshot(snap) {
  const el = document.getElementById('dom-snapshot');
  let html = '';

  html += `<div class="dom-item"><span class="tag">URL</span> <span class="id">${escapeHtml(snap.url)}</span></div>`;
  html += `<div class="dom-item"><span class="tag">Title</span> ${escapeHtml(snap.title)}</div>`;

  if (snap.forms.length) {
    html += `<div class="dom-item"><span class="tag">Forms (${snap.forms.length})</span></div>`;
    snap.forms.forEach(f => {
      html += `<div class="dom-item" style="padding-left:16px">`;
      html += `<span class="id">#${f.id || '(no-id)'}</span> action=${escapeHtml(f.action)} method=${f.method}`;
      f.inputs.forEach(inp => {
        html += `<div class="detail" style="padding-left:8px">&lt;${inp.tag.toLowerCase()} type="${inp.type}" id="${inp.id}" name="${inp.name}"&gt; ${inp.visible ? '' : '[hidden]'} val="${escapeHtml(inp.value || '')}"</div>`;
      });
      html += `</div>`;
    });
  }

  if (snap.buttons.length) {
    html += `<div class="dom-item"><span class="tag">Buttons/Links (${snap.buttons.length})</span></div>`;
    snap.buttons.forEach(b => {
      const vis = b.visible ? '' : ' [hidden]';
      html += `<div class="dom-item" style="padding-left:16px">`;
      html += `<span class="id">${escapeHtml(b.text || '(empty)')}</span>${vis}`;
      if (b.onclick) html += `<div class="detail">onclick: ${escapeHtml(b.onclick)}</div>`;
      if (b.href) html += `<div class="detail">href: ${escapeHtml(b.href)}</div>`;
      html += `</div>`;
    });
  }

  if (snap.iframes.length) {
    html += `<div class="dom-item"><span class="tag">Iframes (${snap.iframes.length})</span></div>`;
    snap.iframes.forEach(f => {
      html += `<div class="dom-item" style="padding-left:16px"><span class="id">#${f.id}</span> <span class="detail">${escapeHtml(f.src)}</span></div>`;
    });
  }

  if (snap.imgs.length) {
    html += `<div class="dom-item"><span class="tag">Captcha Images (${snap.imgs.length})</span></div>`;
    snap.imgs.forEach(img => {
      html += `<div class="dom-item" style="padding-left:16px"><span class="id">#${img.id}</span> ${img.width}x${img.height}</div>`;
    });
  }

  if (snap.modals.length) {
    html += `<div class="dom-item"><span class="tag" style="color:#f9e2af">Visible Modals/Popups (${snap.modals.length})</span></div>`;
    snap.modals.forEach(m => {
      html += `<div class="dom-item" style="padding-left:16px">`;
      html += `<span class="id">#${m.id || ''}</span> .${escapeHtml(m.class || '')}`;
      html += `<div class="detail">${escapeHtml(m.text?.substring(0, 200) || '')}</div>`;
      html += `</div>`;
    });
  }

  if (snap.scripts.length) {
    html += `<div class="dom-item"><span class="tag">Scripts (${snap.scripts.length})</span></div>`;
    snap.scripts.forEach(s => {
      const short = s.length > 80 ? '...' + s.substring(s.length - 60) : s;
      html += `<div class="dom-item" style="padding-left:16px"><span class="detail">${escapeHtml(short)}</span></div>`;
    });
  }

  if (snap.bodyText) {
    html += `<div class="dom-item"><span class="tag">Page Text (first 1000 chars)</span></div>`;
    html += `<div class="dom-item"><span class="detail" style="white-space:pre-wrap">${escapeHtml(snap.bodyText)}</span></div>`;
  }

  el.innerHTML = html;
}

// ==============================
// 사이트 분석
// ==============================
let lastAnalysisData = null;

document.getElementById('analyzeBtn').addEventListener('click', () => {
  logEvent('사이트 분석 중...', 'info');
  chrome.runtime.sendMessage({ type: 'REQUEST_ANALYSIS' }, (response) => {
    if (!response) {
      logEvent('분석 실패 - content script 없음', 'error');
      return;
    }
    lastAnalysisData = response;
    renderAnalysis(response);
    document.getElementById('copyAnalysisBtn').style.display = 'inline-block';
    logEvent('사이트 분석 완료', 'success');
  });
});

document.getElementById('copyAnalysisBtn').addEventListener('click', () => {
  if (lastAnalysisData) {
    navigator.clipboard.writeText(JSON.stringify(lastAnalysisData, null, 2));
    logEvent('분석 결과 클립보드에 복사됨', 'success');
  }
});

function renderAnalysis(data) {
  const el = document.getElementById('analysis-result');
  let html = '';

  html += `<div class="dom-item"><span class="tag">URL</span> <span class="id">${escapeHtml(data.url)}</span></div>`;

  // SVG 맵
  if (data.svgMaps?.length) {
    data.svgMaps.forEach((svg, i) => {
      html += `<div class="dom-item"><span class="tag">SVG #${i}</span> ${svg.width}x${svg.height} viewBox=${svg.viewBox || 'none'} (${svg.totalElements} elements, ${svg.clickableCount} clickable)</div>`;
      html += `<div class="dom-item" style="padding-left:12px"><span class="detail">위치: x=${svg.boundingRect.x} y=${svg.boundingRect.y} ${svg.boundingRect.w}x${svg.boundingRect.h}</span></div>`;

      if (svg.clickableExamples?.length) {
        html += `<div class="dom-item" style="padding-left:12px"><span class="id">클릭 가능 요소 (${svg.clickableCount}):</span></div>`;
        svg.clickableExamples.forEach(c => {
          const info = [c.ngClick, c.onclick, c.dataSeat].filter(Boolean).join(' | ');
          html += `<div class="dom-item" style="padding-left:24px"><span class="detail">&lt;${c.tag}&gt; #${c.id || ''} .${c.class || ''} fill=${c.fill || ''}</span></div>`;
          if (info) html += `<div class="dom-item" style="padding-left:32px"><span class="id">${escapeHtml(info)}</span></div>`;
        });
      }

      if (svg.groups?.length) {
        html += `<div class="dom-item" style="padding-left:12px"><span class="id">그룹:</span></div>`;
        svg.groups.forEach(g => {
          html += `<div class="dom-item" style="padding-left:24px"><span class="detail">&lt;g&gt; #${g.id} .${g.class || ''} (${g.childCount} children)</span></div>`;
        });
      }

      if (svg.texts?.length) {
        html += `<div class="dom-item" style="padding-left:12px"><span class="id">텍스트: </span><span class="detail">${svg.texts.map(t => t.text).join(', ')}</span></div>`;
      }
    });
  } else {
    html += `<div class="dom-item"><span class="detail">SVG 없음</span></div>`;
  }

  // Canvas
  if (data.canvases?.length) {
    html += `<div class="dom-item"><span class="tag">Canvas (${data.canvases.length})</span></div>`;
    data.canvases.forEach(c => {
      html += `<div class="dom-item" style="padding-left:12px"><span class="detail">#${c.id} ${c.width}x${c.height} at (${c.boundingRect.x},${c.boundingRect.y})</span></div>`;
    });
  }

  // Angular
  if (data.angularData) {
    const ad = data.angularData;
    if (ad.appName) html += `<div class="dom-item"><span class="tag">Angular App</span> <span class="id">${escapeHtml(ad.appName)}</span></div>`;

    if (ad.controllers?.length) {
      html += `<div class="dom-item"><span class="tag">Controllers (${ad.controllers.length})</span></div>`;
      ad.controllers.forEach(c => {
        html += `<div class="dom-item" style="padding-left:12px"><span class="id">${escapeHtml(c.name)}</span> #${c.id} &lt;${c.tag}&gt;</div>`;
      });
    }

    if (ad.ngClicks?.length) {
      html += `<div class="dom-item"><span class="tag">ng-click (${ad.ngClicks.length})</span></div>`;
      ad.ngClicks.forEach(c => {
        const vis = c.visible ? '' : ' [hidden]';
        html += `<div class="dom-item" style="padding-left:12px"><span class="id">${escapeHtml(c.ngClick)}</span>${vis}</div>`;
        if (c.text) html += `<div class="dom-item" style="padding-left:20px"><span class="detail">"${escapeHtml(c.text)}" &lt;${c.tag}&gt;</span></div>`;
      });
    }

    if (ad.ngModels?.length) {
      html += `<div class="dom-item"><span class="tag">ng-model (${ad.ngModels.length})</span></div>`;
      ad.ngModels.forEach(m => {
        html += `<div class="dom-item" style="padding-left:12px"><span class="id">${escapeHtml(m.ngModel)}</span> = "${escapeHtml(m.value || '')}" &lt;${m.tag} type=${m.type}&gt;</div>`;
      });
    }

    if (ad.ngRepeats?.length) {
      html += `<div class="dom-item"><span class="tag">ng-repeat (${ad.ngRepeats.length})</span></div>`;
      ad.ngRepeats.forEach(r => {
        html += `<div class="dom-item" style="padding-left:12px"><span class="detail">${escapeHtml(r)}</span></div>`;
      });
    }

    // scope 변수들
    const scopeEntries = Object.entries(ad).filter(([k]) => k.startsWith('val_') || k.startsWith('obj_') || k.startsWith('fn_'));
    if (scopeEntries.length) {
      html += `<div class="dom-item"><span class="tag">Scope 변수</span></div>`;
      scopeEntries.forEach(([k, v]) => {
        const type = k.substring(0, k.indexOf('_'));
        const name = k.substring(k.indexOf('_') + 1);
        html += `<div class="dom-item" style="padding-left:12px"><span class="id">${type}:${name}</span> <span class="detail">${escapeHtml(String(v).substring(0, 200))}</span></div>`;
      });
    }
  }

  // 등급 UI
  if (data.gradeUI?.length) {
    html += `<div class="dom-item"><span class="tag">등급/좌석 UI (${data.gradeUI.length})</span></div>`;
    data.gradeUI.forEach(g => {
      html += `<div class="dom-item" style="padding-left:12px"><span class="id">${escapeHtml(g.ngClick || '')}</span></div>`;
      html += `<div class="dom-item" style="padding-left:20px"><span class="detail">"${escapeHtml(g.text || '')}"</span></div>`;
    });
  }

  // API 엔드포인트
  if (data.apiEndpoints?.length) {
    html += `<div class="dom-item"><span class="tag">API Endpoints (${data.apiEndpoints.length})</span></div>`;
    data.apiEndpoints.forEach(ep => {
      html += `<div class="dom-item" style="padding-left:12px"><span class="id">${escapeHtml(ep)}</span></div>`;
    });
  }

  // 글로벌 변수
  if (Object.keys(data.globalVars || {}).length) {
    html += `<div class="dom-item"><span class="tag">Global Vars</span></div>`;
    Object.entries(data.globalVars).forEach(([k, v]) => {
      html += `<div class="dom-item" style="padding-left:12px"><span class="id">${k}</span> <span class="detail">${escapeHtml(v)}</span></div>`;
    });
  }

  // 이미지맵
  if (data.imageMaps?.length) {
    data.imageMaps.forEach(m => {
      html += `<div class="dom-item"><span class="tag">ImageMap: ${m.name} (${m.areas.length} areas)</span></div>`;
      m.areas.forEach(a => {
        html += `<div class="dom-item" style="padding-left:12px"><span class="detail">${a.shape} ${a.alt || a.title || ''} ${escapeHtml(a.ngClick || a.onclick || a.href || '')}</span></div>`;
      });
    });
  }

  // 페이지 상태
  html += `<div class="dom-item"><span class="tag">페이지 상태</span></div>`;
  html += `<div class="dom-item" style="padding-left:12px"><span class="detail">현재 단계: ${escapeHtml(data.pageState?.step || '?')} | 선택 등급: ${escapeHtml(data.pageState?.selectedGrade || '없음')} | 선택 좌석: ${data.pageState?.seatCount || 0}</span></div>`;
  if (data.pageState?.visiblePopups?.length) {
    html += `<div class="dom-item" style="padding-left:12px"><span class="id">열린 팝업:</span></div>`;
    data.pageState.visiblePopups.forEach(p => {
      html += `<div class="dom-item" style="padding-left:20px"><span class="detail">#${p.id} .${p.class}</span></div>`;
    });
  }

  el.innerHTML = html;
}

// ==============================
// JS 실행
// ==============================
function runJS() {
  const input = document.getElementById('jsInput');
  const code = input.value.trim();
  if (!code) return;

  logEvent(`> ${code}`, 'info');
  input.value = '';

  chrome.runtime.sendMessage({ type: 'EXEC_JS', code }, (response) => {
    if (response?.ok) {
      logEvent(response.result, 'success');
    } else {
      logEvent(response?.error || 'No response', 'error');
    }
  });
}

document.getElementById('jsRunBtn').addEventListener('click', runJS);
document.getElementById('jsInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') runJS();
});

// ==============================
// 메시지 수신 (content script → sidepanel)
// ==============================
chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'SPY_XHR' || message.type === 'SPY_FETCH') {
    addNetEntry(message);
  }

  if (message.type === 'SPY_LOG') {
    logEvent(message.msg, message.level || 'info');
  }

  if (message.type === 'SPY_DOM_CHANGE') {
    logEvent(`DOM: ${message.action} #${message.id || ''} .${message.class || ''} — ${message.text?.substring(0, 100) || ''}`, 'warn');
  }

  if (message.type === 'CAPTCHA_HINT') {
    logEvent(`API 힌트: ${message.hint}`, 'success');
  }

  if (message.type === 'CAPTCHA_DETECTED') {
    logEvent('캡차 감지 — API 힌트 요청', 'warn');
    const badge = document.getElementById('status-badge');
    badge.textContent = '캡차!';
    badge.classList.add('active');
  }

  if (message.type === 'CAPTCHA_HINT_REQUEST') {
    callClaudeAPIForHint(message.imgSrc);
  }
});

// ==============================
// 캡차 API 힌트
// ==============================
async function callClaudeAPIForHint(imgSrc) {
  const startTime = performance.now();
  try {
    const result = await chrome.storage.local.get(['claudeApiKey']);
    const apiKey = result.claudeApiKey;
    if (!apiKey) {
      logEvent('API 키 없음 — 수동 입력만 가능', 'warn');
      return;
    }

    let base64Data = imgSrc;
    let mediaType = 'image/jpeg';
    if (base64Data.startsWith('data:')) {
      const match = base64Data.match(/^data:(image\/[a-z]+);base64,(.+)$/);
      if (match) { mediaType = match[1]; base64Data = match[2]; }
    }

    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'anthropic-dangerous-direct-browser-access': 'true'
      },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 100,
        messages: [{
          role: 'user',
          content: [
            { type: 'image', source: { type: 'base64', media_type: mediaType, data: base64Data } },
            { type: 'text', text: 'This image is a CAPTCHA. Read the distorted text characters exactly. Reply with ONLY the characters (uppercase). No spaces, no explanation.' }
          ]
        }]
      })
    });

    if (!response.ok) throw new Error(`API ${response.status}`);
    const data = await response.json();
    const text = data.content[0].text.trim().toUpperCase().replace(/[^A-Z0-9]/g, '');
    const elapsed = Math.round(performance.now() - startTime);
    logEvent(`API 응답: "${text}" (${elapsed}ms)`, 'success');

    const badge = document.getElementById('status-badge');
    badge.textContent = '완료';

    // 힌트를 content script에 전달 (페이지에 표시)
    chrome.runtime.sendMessage({ type: 'CAPTCHA_HINT', hint: text });
  } catch (err) {
    logEvent(`API 오류: ${err.message}`, 'error');
  }
}

// ==============================
// 설정
// ==============================
document.addEventListener('DOMContentLoaded', () => {
  const apiKeyInput = document.getElementById('apiKeyInput');
  const saveKeyBtn = document.getElementById('saveKeyBtn');
  const apiKeyStatus = document.getElementById('apiKeyStatus');
  chrome.storage.local.get(['claudeApiKey'], (result) => {
    if (result.claudeApiKey) {
      apiKeyInput.value = result.claudeApiKey;
      apiKeyStatus.textContent = 'API 키 설정됨';
      apiKeyStatus.className = 'api-status ok';
    } else {
      apiKeyStatus.textContent = 'API 키를 입력하세요';
      apiKeyStatus.className = 'api-status no';
    }
  });

  saveKeyBtn.addEventListener('click', () => {
    const key = apiKeyInput.value.trim();
    if (!key) return;
    chrome.storage.local.set({ claudeApiKey: key }, () => {
      apiKeyStatus.textContent = 'API 키 저장됨';
      apiKeyStatus.className = 'api-status ok';
      logEvent('API 키 저장', 'success');
    });
  });

  const autoCloseToggle = document.getElementById('autoCloseToggle');
  chrome.storage.local.get(['autoClosePopup'], (result) => {
    autoCloseToggle.checked = result.autoClosePopup !== false;
  });
  autoCloseToggle.addEventListener('change', () => {
    chrome.storage.local.set({ autoClosePopup: autoCloseToggle.checked });
    logEvent(`예매안내 자동닫기: ${autoCloseToggle.checked ? 'ON' : 'OFF'}`, 'info');
  });
});
