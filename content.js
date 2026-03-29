(() => {
  const MSG = (type, data = {}) => chrome.runtime.sendMessage({ type, ...data }).catch(() => {});

  // ==============================
  // 1. 페이지 분석 (스파이)
  // ==============================

  // XHR 인터셉트
  const origXHROpen = XMLHttpRequest.prototype.open;
  const origXHRSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url, ...args) {
    this._spy = { method, url, startTime: 0 };
    return origXHROpen.call(this, method, url, ...args);
  };

  XMLHttpRequest.prototype.send = function (body) {
    if (this._spy) {
      this._spy.startTime = performance.now();
      this._spy.body = body;

      this.addEventListener('load', function () {
        const elapsed = performance.now() - this._spy.startTime;
        let responsePreview = '';
        try { responsePreview = this.responseText?.substring(0, 500) || ''; } catch (e) {}

        MSG('SPY_XHR', {
          method: this._spy.method, url: this._spy.url,
          status: this.status, elapsed: Math.round(elapsed),
          requestBody: typeof this._spy.body === 'string' ? this._spy.body?.substring(0, 300) : null,
          responsePreview
        });
      });

      this.addEventListener('error', function () {
        MSG('SPY_XHR', {
          method: this._spy.method, url: this._spy.url,
          status: 'ERROR', elapsed: Math.round(performance.now() - this._spy.startTime),
          requestBody: null, responsePreview: ''
        });
      });
    }
    return origXHRSend.call(this, body);
  };

  // Fetch 인터셉트
  const origFetch = window.fetch;
  window.fetch = async function (...args) {
    const startTime = performance.now();
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '?';
    const method = args[1]?.method || 'GET';
    let reqBody = null;
    if (args[1]?.body && typeof args[1].body === 'string') {
      reqBody = args[1].body.substring(0, 300);
    }
    try {
      const response = await origFetch.apply(this, args);
      const elapsed = Math.round(performance.now() - startTime);
      let responsePreview = '';
      try { const clone = response.clone(); responsePreview = (await clone.text()).substring(0, 500); } catch (e) {}
      MSG('SPY_FETCH', { method, url, status: response.status, elapsed, requestBody: reqBody, responsePreview });
      return response;
    } catch (err) {
      MSG('SPY_FETCH', { method, url, status: 'ERROR', elapsed: Math.round(performance.now() - startTime), requestBody: reqBody, responsePreview: err.message });
      throw err;
    }
  };

  // debugger 트랩 차단
  const origSetInterval = window.setInterval;
  window.setInterval = function (fn, delay, ...args) {
    const fnStr = typeof fn === 'function' ? fn.toString() : String(fn);
    if (fnStr.includes('debugger')) {
      MSG('SPY_LOG', { msg: `[BLOCKED] debugger 트랩 setInterval 차단 (${delay}ms)`, level: 'warn' });
      return -1;
    }
    return origSetInterval.call(this, fn, delay, ...args);
  };

  const origSetTimeout = window.setTimeout;
  window.setTimeout = function (fn, delay, ...args) {
    const fnStr = typeof fn === 'function' ? fn.toString() : String(fn);
    if (fnStr.includes('debugger')) {
      MSG('SPY_LOG', { msg: `[BLOCKED] debugger 트랩 setTimeout 차단`, level: 'warn' });
      return -1;
    }
    return origSetTimeout.call(this, fn, delay, ...args);
  };

  // ==============================
  // 2. DOM 스냅샷
  // ==============================
  function domSnapshot() {
    const forms = [...document.querySelectorAll('form')].map(f => ({
      id: f.id, action: f.action, method: f.method,
      inputs: [...f.querySelectorAll('input, select, textarea, button')].map(el => ({
        tag: el.tagName, type: el.type, id: el.id, name: el.name,
        value: el.type === 'password' ? '***' : el.value?.substring(0, 50),
        visible: el.offsetParent !== null
      }))
    }));

    const buttons = [...document.querySelectorAll('button, a[onclick], input[type="button"], input[type="submit"]')]
      .slice(0, 50)
      .map(el => ({
        tag: el.tagName, text: el.textContent?.trim().substring(0, 50),
        id: el.id, class: el.className?.substring?.(0, 60),
        onclick: el.getAttribute('onclick')?.substring(0, 100),
        href: el.tagName === 'A' ? el.href?.substring(0, 100) : undefined,
        visible: el.offsetParent !== null
      }));

    const iframes = [...document.querySelectorAll('iframe')].map(f => ({
      id: f.id, src: f.src?.substring(0, 200), width: f.width, height: f.height
    }));

    // 캡차 이미지: 더 넓은 범위로 검색
    const imgs = [...document.querySelectorAll('img')]
      .filter(img => {
        const id = (img.id || '').toLowerCase();
        const src = (img.src || '').toLowerCase();
        const cls = (img.className || '').toLowerCase();
        const parentCls = (img.parentElement?.className || '').toLowerCase();
        return id.includes('captcha') || id.includes('capcha') ||
               src.includes('captcha') || src.includes('capcha') ||
               cls.includes('captcha') || cls.includes('capcha') ||
               parentCls.includes('captcha') || parentCls.includes('capcha') ||
               (src.startsWith('data:image') && img.closest('.ly_captcha, .capchaLayer, [class*="captcha"]'));
      })
      .map(img => ({
        id: img.id, src: img.src?.substring(0, 200),
        width: img.naturalWidth, height: img.naturalHeight,
        parentClass: img.parentElement?.className?.substring(0, 60)
      }));

    const modals = [...document.querySelectorAll('[class*="modal"], [class*="popup"], [class*="overlay"], [class*="dialog"], [class*="layer"], [class*="capcha"], [class*="captcha"], [class*="ly_pop"]')]
      .slice(0, 30)
      .map(el => {
        const style = window.getComputedStyle(el);
        return {
          tag: el.tagName, id: el.id,
          class: el.className?.toString?.()?.substring(0, 100),
          visible: style.display !== 'none' && style.visibility !== 'hidden' && !el.classList.contains('ng-hide'),
          text: el.textContent?.trim().substring(0, 200),
          innerHTML: el.innerHTML?.substring(0, 500)
        };
      });

    const scripts = [...document.querySelectorAll('script[src]')].map(s => s.src).filter(s => s);

    return {
      url: location.href, title: document.title,
      forms, buttons, iframes, imgs, modals, scripts,
      bodyClasses: document.body?.className,
      bodyText: document.body?.innerText?.substring(0, 1000)
    };
  }

  // ==============================
  // 2-1. 사이트 심층 분석
  // ==============================
  function siteAnalysis() {
    const result = { url: location.href, timestamp: new Date().toISOString() };

    // 1. SVG 좌석맵 분석
    const svgs = document.querySelectorAll('svg');
    result.svgMaps = [...svgs].map((svg, i) => {
      const rect = svg.getBoundingClientRect();
      const clickableEls = svg.querySelectorAll('[ng-click], [onclick], [data-seat], [class*="seat"], [class*="block"], [class*="section"]');
      const allGroups = svg.querySelectorAll('g[id], g[class]');
      const texts = [...svg.querySelectorAll('text')].slice(0, 50).map(t => ({
        text: t.textContent?.trim(), x: t.getAttribute('x'), y: t.getAttribute('y'),
        parentId: t.closest('g')?.id || ''
      }));
      return {
        index: i, width: svg.getAttribute('width'), height: svg.getAttribute('height'),
        viewBox: svg.getAttribute('viewBox'),
        boundingRect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
        totalElements: svg.querySelectorAll('*').length,
        clickableCount: clickableEls.length,
        clickableExamples: [...clickableEls].slice(0, 20).map(el => ({
          tag: el.tagName, id: el.id,
          class: el.getAttribute('class')?.substring(0, 80),
          ngClick: el.getAttribute('ng-click')?.substring(0, 100),
          onclick: el.getAttribute('onclick')?.substring(0, 100),
          fill: el.getAttribute('fill'),
          style: el.getAttribute('style')?.substring(0, 80),
          dataSeat: el.dataset?.seat || el.dataset?.seatNo || el.dataset?.blockCode || '',
        })),
        groups: [...allGroups].slice(0, 30).map(g => ({
          id: g.id, class: g.getAttribute('class')?.substring(0, 60),
          childCount: g.children.length,
        })),
        texts: texts,
      };
    });

    // 2. Canvas 분석
    const canvases = document.querySelectorAll('canvas');
    result.canvases = [...canvases].map((c, i) => {
      const rect = c.getBoundingClientRect();
      return {
        index: i, id: c.id, class: c.className,
        width: c.width, height: c.height,
        boundingRect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
        hasClickListener: !!c.onclick,
      };
    });

    // 3. AngularJS scope 데이터 (가능한 경우)
    result.angularData = {};
    try {
      const ngApp = document.querySelector('[ng-app], [data-ng-app]');
      if (ngApp) result.angularData.appName = ngApp.getAttribute('ng-app') || ngApp.getAttribute('data-ng-app');

      // ng-controller 목록
      const controllers = document.querySelectorAll('[ng-controller]');
      result.angularData.controllers = [...controllers].map(c => ({
        name: c.getAttribute('ng-controller'),
        id: c.id, tag: c.tagName,
      }));

      // ng-click 이벤트 전체 수집
      const ngClicks = document.querySelectorAll('[ng-click]');
      result.angularData.ngClicks = [...ngClicks].slice(0, 80).map(el => ({
        tag: el.tagName, id: el.id,
        text: el.textContent?.trim().substring(0, 40),
        ngClick: el.getAttribute('ng-click'),
        class: el.getAttribute('class')?.substring(0, 60),
        visible: el.offsetParent !== null || el.closest('.ng-hide') === null,
      }));

      // ng-model 입력 필드
      const ngModels = document.querySelectorAll('[ng-model]');
      result.angularData.ngModels = [...ngModels].map(el => ({
        tag: el.tagName, type: el.type, id: el.id,
        ngModel: el.getAttribute('ng-model'),
        value: el.type === 'password' ? '***' : el.value?.substring(0, 50),
      }));

      // ng-repeat
      const ngRepeats = document.querySelectorAll('[ng-repeat]');
      result.angularData.ngRepeats = [...new Set([...ngRepeats].map(el => el.getAttribute('ng-repeat')))];

      // Angular scope 변수 접근 시도
      if (typeof angular !== 'undefined') {
        const scopeEl = document.querySelector('[ng-controller]') || document.querySelector('[ng-app]');
        if (scopeEl) {
          const scope = angular.element(scopeEl).scope();
          if (scope) {
            const keys = Object.keys(scope).filter(k => !k.startsWith('$') && !k.startsWith('_'));
            result.angularData.scopeKeys = keys;
            // 주요 데이터 추출
            keys.forEach(k => {
              try {
                const val = scope[k];
                if (val === null || val === undefined) return;
                if (typeof val === 'function') {
                  result.angularData['fn_' + k] = `function(${val.length} args)`;
                } else if (typeof val === 'object') {
                  result.angularData['obj_' + k] = JSON.stringify(val).substring(0, 300);
                } else {
                  result.angularData['val_' + k] = String(val).substring(0, 100);
                }
              } catch (e) {}
            });
          }
        }
      }
    } catch (e) {
      result.angularData.error = e.message;
    }

    // 4. 등급/좌석 선택 UI
    const gradeItems = document.querySelectorAll('[ng-click*="grade"], [ng-click*="Grade"], [ng-click*="block"], [ng-click*="Block"], [ng-click*="seat"], [ng-click*="Seat"], [ng-click*="section"]');
    result.gradeUI = [...gradeItems].slice(0, 30).map(el => ({
      tag: el.tagName, text: el.textContent?.trim().substring(0, 60),
      ngClick: el.getAttribute('ng-click'),
      class: el.getAttribute('class')?.substring(0, 60),
    }));

    // 5. 주요 API 엔드포인트 (script 태그에서 추출)
    const allScriptContent = [...document.querySelectorAll('script:not([src])')].map(s => s.textContent).join('\n');
    const apiPatterns = allScriptContent.match(/['"`](\/api\/[^'"`\s]+|\/reserve\/[^'"`\s]+|\/product\/[^'"`\s]+|https?:\/\/[^'"`\s]*api[^'"`\s]*)/gi) || [];
    result.apiEndpoints = [...new Set(apiPatterns)].slice(0, 30);

    // 6. 글로벌 JS 변수/함수 (예매 관련)
    const ticketVars = {};
    const interestingKeys = ['seatMap', 'seatInfo', 'blockInfo', 'gradeInfo', 'schedule', 'product', 'reserve',
      'ticketData', 'priceInfo', 'areaInfo', 'config', 'SEAT', 'BLOCK', 'GRADE', 'AREA'];
    interestingKeys.forEach(key => {
      try {
        if (window[key] !== undefined) {
          ticketVars[key] = JSON.stringify(window[key]).substring(0, 500);
        }
      } catch (e) {}
    });
    result.globalVars = ticketVars;

    // 7. 이미지맵 (좌석맵이 이미지+맵인 경우)
    const maps = document.querySelectorAll('map');
    result.imageMaps = [...maps].map(m => ({
      name: m.name,
      areas: [...m.querySelectorAll('area')].slice(0, 30).map(a => ({
        shape: a.shape, coords: a.coords?.substring(0, 80),
        href: a.href?.substring(0, 80),
        onclick: a.getAttribute('onclick')?.substring(0, 100),
        ngClick: a.getAttribute('ng-click')?.substring(0, 100),
        alt: a.alt, title: a.title,
      }))
    }));

    // 8. 현재 페이지 상태 요약
    result.pageState = {
      step: document.querySelector('.tab_step .on, .step .active, [class*="step"][class*="on"]')?.textContent?.trim(),
      selectedGrade: document.querySelector('.grade_item.on, .grade.active, [class*="grade"][class*="selected"]')?.textContent?.trim(),
      seatCount: document.querySelectorAll('[class*="seat"][class*="select"], [class*="seat"][class*="on"]').length,
      visiblePopups: [...document.querySelectorAll('[class*="layer"]:not(.ng-hide), [class*="popup"]:not(.ng-hide)')].map(p => ({
        id: p.id, class: p.className?.toString?.()?.substring(0, 60),
      })),
    };

    return result;
  }

  // ==============================
  // 3. 캡차 감지 (티켓링크 + 인터파크 통합)
  // ==============================
  let lastCaptchaSrc = null;

  // 캡차 컨테이너 찾기
  function findCaptchaContainer() {
    // 티켓링크: .ly_captcha (ng-hide 없을 때만)
    const tlCaptcha = document.querySelector('.ly_captcha');
    if (tlCaptcha && !tlCaptcha.classList.contains('ng-hide')) {
      return tlCaptcha;
    }

    // 인터파크: #divRecaptcha
    const ipCaptcha = document.getElementById('divRecaptcha');
    if (ipCaptcha && ipCaptcha.style.display !== 'none') {
      return ipCaptcha;
    }

    // 일반적인 캡차 컨테이너
    const generic = document.querySelector('[class*="captcha"]:not(.ng-hide), [class*="capcha"]:not(.ng-hide)');
    if (generic) {
      const style = window.getComputedStyle(generic);
      if (style.display !== 'none' && style.visibility !== 'hidden') {
        return generic;
      }
    }

    return null;
  }

  // 캡차 이미지 찾기
  function findCaptchaImage(container) {
    if (!container) return null;

    // 1. 티켓링크: canvas 기반 캡차 (#captcha_canvas)
    const captchaCanvas = container.querySelector('#captcha_canvas') || container.querySelector('canvas');
    if (captchaCanvas) {
      try {
        const dataUrl = captchaCanvas.toDataURL('image/png');
        if (dataUrl && dataUrl !== 'data:,') {
          return { src: dataUrl, _isCanvas: true };
        }
      } catch (e) {
        MSG('SPY_LOG', { msg: `Canvas toDataURL 실패: ${e.message}`, level: 'error' });
      }
    }

    // 2. data:image base64 이미지
    const dataImg = container.querySelector('img[src^="data:image"]');
    if (dataImg) return dataImg;

    // 3. captcha 관련 id/src를 가진 이미지
    const namedImg = container.querySelector('img[id*="captcha"], img[id*="Captcha"], img[src*="captcha"]');
    if (namedImg) return namedImg;

    // 4. 컨테이너 안의 아무 이미지
    const anyImg = container.querySelector('img[src]');
    if (anyImg && anyImg.src) return anyImg;

    return null;
  }

  // 캡차 입력란 찾기
  function findCaptchaInput(container) {
    if (!container) return null;

    // 티켓링크: #ipt_captcha
    return document.getElementById('ipt_captcha') ||
      container.querySelector('input[type="text"]') ||
      document.getElementById('txtCaptcha') ||
      document.querySelector('input[name*="captcha"], input[id*="captcha"]');
  }

  // 비프음 재생
  function playBeep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 880; // A5
      gain.gain.value = 0.3;
      osc.start();
      osc.stop(ctx.currentTime + 0.15);
      // 두 번째 비프 (긴급한 느낌)
      const osc2 = ctx.createOscillator();
      osc2.connect(gain);
      osc2.frequency.value = 1100;
      osc2.start(ctx.currentTime + 0.2);
      osc2.stop(ctx.currentTime + 0.35);
    } catch (e) {}
  }

  // API 힌트: 사이드 패널에 요청을 보내고, 결과를 받아서 캡차 팝업에 표시
  function requestApiHint(imgSrc) {
    MSG('CAPTCHA_HINT_REQUEST', { imgSrc });
  }

  // API 힌트 결과를 캡차 팝업에 표시
  function displayHint(hint) {
    const container = findCaptchaContainer();
    if (!container) return;

    const existing = container.querySelector('#captcha-api-hint');
    if (existing) existing.remove();

    const hintEl = document.createElement('div');
    hintEl.id = 'captcha-api-hint';
    hintEl.style.cssText = 'text-align:center; margin:4px 0; padding:4px 8px; background:#e8f5e9; border-radius:4px; font-size:18px; font-weight:bold; letter-spacing:6px; color:#2e7d32; font-family:monospace;';
    hintEl.textContent = hint;

    const imgContainer = container.querySelector('.bx_img') || container.querySelector('.captcha_info');
    if (imgContainer) {
      imgContainer.after(hintEl);
    }
  }

  function checkCaptcha() {
    const container = findCaptchaContainer();
    if (!container) return;

    const img = findCaptchaImage(container);
    if (!img || !img.src) return;

    if (img.src !== lastCaptchaSrc) {
      lastCaptchaSrc = img.src;

      MSG('SPY_LOG', { msg: `캡차 감지!`, level: 'success' });
      MSG('CAPTCHA_DETECTED', { imgSrc: img.src });

      // 1. 비프음 — 즉시 인지
      playBeep();

      // 2. 입력란 자동 포커스 — 사이드 패널이 포커스를 뺏으므로 반복 시도
      const input = findCaptchaInput(container);
      if (input) {
        const forceFocus = () => {
          input.value = '';
          window.focus(); // 페이지 윈도우에 포커스
          input.focus();  // 입력란에 포커스
          input.click();  // 클릭도 시뮬레이션
        };
        // 사이드 패널 업데이트 후에도 포커스를 되찾도록 여러 번 시도
        setTimeout(forceFocus, 100);
        setTimeout(forceFocus, 300);
        setTimeout(forceFocus, 600);
        setTimeout(forceFocus, 1000);
        MSG('SPY_LOG', { msg: `입력란 자동 포커스 시도`, level: 'info' });
      }

      // 4. API 힌트 (사이드 패널에서 API 호출, 결과 나오면 페이지에 표시)
      requestApiHint(img.src);
    }
  }

  // ==============================
  // 4. DOM 변화 감시
  // ==============================
  function startObserver() {
    const observer = new MutationObserver((mutations) => {
      // 캡차 체크 (매 DOM 변경마다)
      checkCaptcha();

      for (const mut of mutations) {
        for (const node of mut.addedNodes) {
          if (node.nodeType !== 1) continue;

          const classes = node.className?.toString?.() || '';
          if (classes.match(/modal|popup|overlay|dialog|layer|capcha|captcha|ly_pop/i)) {
            const isHidden = node.classList.contains('ng-hide');
            MSG('SPY_DOM_CHANGE', {
              action: 'POPUP_APPEARED',
              id: node.id,
              class: classes.substring(0, 80),
              hidden: isHidden,
              text: node.textContent?.trim().substring(0, 300)
            });

            // 예매안내 팝업 자동 닫기 (캡차 제외)
            if (!classes.includes('ly_captcha') && !classes.includes('captcha')) {
              setTimeout(() => autoCloseNoticePopup(node), 200);
            }
          }
        }

        // ng-hide 제거 감지 (AngularJS 요소 표시)
        if (mut.type === 'attributes' && mut.attributeName === 'class') {
          const target = mut.target;
          const classes = target.className?.toString?.() || '';
          const isNowVisible = !target.classList.contains('ng-hide');

          // 캡차 레이어
          if (isNowVisible && (classes.includes('captcha') || classes.includes('capcha') || classes.includes('ly_captcha'))) {
            MSG('SPY_LOG', { msg: `캡차 레이어 표시됨 (ng-hide 제거)`, level: 'warn' });
            setTimeout(() => checkCaptcha(), 300);
            setTimeout(() => checkCaptcha(), 800);
            setTimeout(() => checkCaptcha(), 1500);
          }

          // 예매안내 팝업 (캡차 제외)
          if (isNowVisible && !classes.includes('ly_captcha') && !classes.includes('captcha') &&
              (classes.match(/modal|popup|layer|ly_pop|guide|notice/i) || target.id === 'noticeModalDiv')) {
            setTimeout(() => autoCloseNoticePopup(target), 200);
          }
        }
      }
    });

    observer.observe(document.body || document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['style', 'class', 'src']
    });

    // 주기적 캡차 체크 + 팝업 자동닫기 (Angular 동적 렌더링 대비, 500ms 간격)
    origSetInterval.call(window, () => {
      checkCaptcha();
      autoCloseNoticePopup();
    }, 500);
  }

  // ==============================
  // 5. 메시지 수신 (사이드 패널에서 요청)
  // ==============================
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'REQUEST_SNAPSHOT') {
      sendResponse(domSnapshot());
      return true;
    }

    if (message.type === 'REQUEST_ANALYSIS') {
      sendResponse(siteAnalysis());
      return true;
    }

    if (message.type === 'DO_FILL_CAPTCHA') {
      const container = findCaptchaContainer();
      const input = findCaptchaInput(container);

      if (input) {
        MSG('SPY_LOG', { msg: `입력란 발견: #${input.id}`, level: 'info' });

        // 1. 포커스
        input.focus();

        // 2. 기존 값 비우기
        input.value = '';

        // 3. execCommand insertText — 브라우저의 네이티브 텍스트 삽입
        //    Angular/jQuery/vanilla JS 모두 이 방식으로 value가 설정됨
        input.select();
        document.execCommand('insertText', false, message.text);

        // 4. 값 확인 — execCommand가 실패했을 경우 직접 설정
        if (input.value !== message.text) {
          MSG('SPY_LOG', { msg: `execCommand 후 value="${input.value}", 직접 설정 시도`, level: 'warn' });
          input.value = message.text;
          // input 이벤트 발생 (Angular $watch 트리거)
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }

        MSG('SPY_LOG', { msg: `캡차 입력: "${input.value}"`, level: 'success' });
      } else {
        MSG('SPY_LOG', { msg: `캡차 입력란을 찾지 못했습니다`, level: 'error' });
      }
    }

    if (message.type === 'CAPTCHA_HINT') {
      displayHint(message.hint);
    }

    if (message.type === 'EXEC_JS') {
      // eval 대신 Function 생성자도 CSP에 걸리므로
      // background에서 chrome.scripting.executeScript로 처리
      sendResponse({ ok: false, error: 'JS 실행은 background를 통해 처리됩니다' });
      return true;
    }
  });

  // ==============================
  // 6. 예매안내 팝업 자동 닫기
  // ==============================
  async function autoCloseNoticePopup(target) {
    // 설정 확인
    const settings = await chrome.storage.local.get(['autoClosePopup']);
    if (settings.autoClosePopup === false) return; // 기본값은 true

    // 특정 타겟이 주어졌으면 그걸 사용, 아니면 여러 셀렉터로 찾기
    const popups = target ? [target] : [
      document.getElementById('noticeModalDiv'),
      document.querySelector('.ly_reserve_guide:not(.ng-hide)'),
      document.querySelector('.ly_pop:not(.ng-hide):not(.ly_captcha)'),
      document.querySelector('[class*="notice"]:not(.ng-hide)[class*="modal"]'),
      document.querySelector('[class*="guide"]:not(.ng-hide)[class*="layer"]'),
    ].filter(Boolean);

    for (const popup of popups) {
      if (popup.classList.contains('ng-hide') || popup.style.display === 'none') continue;
      // 캡차 팝업은 건너뛰기
      if (popup.classList.contains('ly_captcha') || popup.querySelector('#captcha_canvas, #ipt_captcha')) continue;

      const btns = popup.querySelectorAll('button, a.btn, a[ng-click], input[type="button"]');
      for (const btn of btns) {
        const text = btn.textContent?.trim();
        if (text && (text === '확인' || text === '닫기' || text === '동의' || text === '예매하기' || text === '예매 계속하기' || text === 'OK')) {
          MSG('SPY_LOG', { msg: `팝업 자동 클릭: "${text}" (${popup.id || popup.className?.substring(0, 40)})`, level: 'success' });
          btn.click();
          return;
        }
      }
    }
  }

  // ==============================
  // 7. 초기화
  // ==============================
  function init() {
    MSG('SPY_LOG', { msg: `페이지 로드: ${location.href}`, level: 'info' });
    startObserver();
    // 초기 캡차 체크 (딜레이 포함)
    checkCaptcha();
    setTimeout(() => checkCaptcha(), 1000);
    setTimeout(() => checkCaptcha(), 3000);
  }

  if (document.body) {
    init();
  } else {
    document.addEventListener('DOMContentLoaded', init);
  }
})();
