### macro_full.py — 티켓링크 1루 응원단석 전체 자동 예매 매크로
### 11:00 오픈 → 예매하기 → 등급/구역 선택 → 좌석 3자리 클릭 → 다음단계
import subprocess
import time
import json
import base64
import tempfile
import os
import sys
import random
from datetime import datetime
from pynput import mouse, keyboard as kb
import pyautogui
import numpy as np
from collections import defaultdict
import ddddocr

# ==================== 설정 ====================
TARGET_DATE = "04.02"           # 예매할 경기 날짜 (페이지에 표시되는 형식)
GRADE_NAME = "1루 응원단석"      # 등급 이름
SEAT_COUNT = 3                   # 연속 좌석 수
OPEN_TIME = "11:00:00"           # 판매 오픈 시간

# 좌석 색상 (RGB)
target_color = (68, 87, 101)
tolerance = 15
min_seat_size = 6
max_seat_size = 25

# 좌석 지도 영역 (구역 클릭 후 초기 위치 기준 — 필요시 coord_picker.py로 재측정)
region = (273, 416, 188, 389)

# OCR 엔진 미리 로딩 (캡차 인식용)
print("OCR 엔진 로딩 중...")
_ocr = ddddocr.DdddOcr(show_ad=False)
print("OCR 준비 완료")

# ==================== Chrome JS 실행 ====================
def _run_js(browser_js, window=1, tab=1):
    """AppleScript로 Chrome 탭에서 JS 실행"""
    escaped_js = browser_js.replace('\\', '\\\\').replace('"', '\\"')
    applescript = f'''tell application "Google Chrome"
    execute tab {tab} of window {window} javascript "{escaped_js}"
end tell'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.applescript', delete=False) as f:
        f.write(applescript)
        f.flush()
        result = subprocess.run(["osascript", f.name], capture_output=True, text=True, timeout=15)
        os.unlink(f.name)
    out = result.stdout.strip()
    return out if out and out != "missing value" else ""


def run_page_js(js_code, window=1, tab=1):
    """페이지 컨텍스트에서 JS 실행 후 결과 반환 (script 태그 주입)"""
    b64 = base64.b64encode(js_code.encode()).decode()
    browser_js = (
        "var s=document.createElement('script');"
        "s.id='__mr';"
        "s.textContent=atob('" + b64 + "');"
        "document.body.appendChild(s);"
        "var r=document.getElementById('__mr').getAttribute('data-r');"
        "document.body.removeChild(s);"
        "r;"
    )
    return _run_js(browser_js, window, tab)


def run_page_js_fire(js_code, window=1, tab=1):
    """페이지 컨텍스트에서 JS 실행 (결과 불필요)"""
    b64 = base64.b64encode(js_code.encode()).decode()
    browser_js = (
        "var s=document.createElement('script');"
        "s.textContent=atob('" + b64 + "');"
        "document.body.appendChild(s);"
        "document.body.removeChild(s);"
        "'ok';"
    )
    return _run_js(browser_js, window, tab)


def run_direct_js(js_code, window=1, tab=1):
    """브라우저 컨텍스트에서 직접 JS 실행 (DOM 조작용)"""
    return _run_js(js_code, window, tab)


# ==================== 좌석 탐색 (픽셀 기반) ====================
def find_seats(img):
    h, w = img.shape[:2]
    diff = np.abs(img.astype(int) - np.array(target_color, dtype=int))
    mask = np.all(diff <= tolerance, axis=2)
    if not mask.any():
        return []
    visited = np.zeros_like(mask)
    seats = []
    for y in range(h):
        for x in range(w):
            if mask[y, x] and not visited[y, x]:
                stack = [(y, x)]
                pixels = []
                while stack:
                    cy, cx = stack.pop()
                    if cy < 0 or cy >= h or cx < 0 or cx >= w:
                        continue
                    if visited[cy, cx] or not mask[cy, cx]:
                        continue
                    visited[cy, cx] = True
                    pixels.append((cx, cy))
                    stack.extend([(cy+1, cx), (cy-1, cx), (cy, cx+1), (cy, cx-1)])
                if len(pixels) < min_seat_size * min_seat_size * 0.5:
                    continue
                xs = [p[0] for p in pixels]
                ys = [p[1] for p in pixels]
                cx_val = (min(xs) + max(xs)) // 2
                cy_val = (min(ys) + max(ys)) // 2
                sw = max(xs) - min(xs) + 1
                sh = max(ys) - min(ys) + 1
                if sw > max_seat_size * 2 or sh > max_seat_size * 2:
                    continue
                seats.append({'cx': cx_val, 'cy': cy_val, 'w': sw, 'h': sh, 'pixels': len(pixels)})
    return seats


def find_consecutive_seats(seats, count):
    if len(seats) < count:
        return None
    rows = defaultdict(list)
    for seat in seats:
        assigned = False
        for row_y in rows:
            if abs(seat['cy'] - row_y) <= 5:
                rows[row_y].append(seat)
                assigned = True
                break
        if not assigned:
            rows[seat['cy']].append(seat)
    for row_y in sorted(rows.keys()):
        row = sorted(rows[row_y], key=lambda s: s['cx'])
        if len(row) < count:
            continue
        for i in range(len(row) - count + 1):
            gaps = []
            for j in range(i, i + count - 1):
                gaps.append(row[j+1]['cx'] - row[j]['cx'])
            avg_gap = sum(gaps) / len(gaps)
            if avg_gap < min_seat_size or avg_gap > max_seat_size * 3:
                continue
            max_dev = max(abs(g - avg_gap) for g in gaps)
            if max_dev <= avg_gap * 0.35:
                return row[i:i + count]
    return None


# ==================== 마우스 클릭 ====================
mouse_controller = mouse.Controller()

def click_at(x, y):
    mouse_controller.position = (x - 5, y)
    time.sleep(0.02)
    mouse_controller.position = (x, y)
    time.sleep(0.08)
    mouse_controller.press(mouse.Button.left)
    time.sleep(0.02)
    mouse_controller.release(mouse.Button.left)


# ==================== 티켓링크 창 찾기 ====================
def find_ticketlink_window():
    """티켓링크 예매 창(reserve/plan/schedule) 찾기 → (window, tab) 반환"""
    applescript = '''
tell application "Google Chrome"
    set winCount to count of windows
    repeat with w from 1 to winCount
        repeat with i from 1 to count of tabs of window w
            set u to URL of tab i of window w
            if u contains "ticketlink.co.kr/reserve/plan/schedule" then
                return (w as text) & "," & (i as text)
            end if
        end repeat
    end repeat
    return "0,0"
end tell'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.applescript', delete=False) as f:
        f.write(applescript)
        f.flush()
        result = subprocess.run(["osascript", f.name], capture_output=True, text=True, timeout=10)
        os.unlink(f.name)
    parts = result.stdout.strip().split(",")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return 0, 0


def find_schedule_window():
    """티켓링크 스케줄 페이지 찾기"""
    applescript = '''
tell application "Google Chrome"
    set winCount to count of windows
    repeat with w from 1 to winCount
        repeat with i from 1 to count of tabs of window w
            set u to URL of tab i of window w
            if u contains "ticketlink.co.kr" and u contains "schedule" and u does not contain "reserve/plan" then
                return (w as text) & "," & (i as text)
            end if
        end repeat
    end repeat
    return "0,0"
end tell'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.applescript', delete=False) as f:
        f.write(applescript)
        f.flush()
        result = subprocess.run(["osascript", f.name], capture_output=True, text=True, timeout=10)
        os.unlink(f.name)
    parts = result.stdout.strip().split(",")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return 0, 0


# ==================== 티켓링크 아무 탭 찾기 ====================
def find_any_ticketlink():
    """ticketlink.co.kr이 열린 아무 탭 찾기"""
    applescript = '''
tell application "Google Chrome"
    set winCount to count of windows
    repeat with w from 1 to winCount
        repeat with i from 1 to count of tabs of window w
            set u to URL of tab i of window w
            if u contains "ticketlink.co.kr" then
                return (w as text) & "," & (i as text)
            end if
        end repeat
    end repeat
    return "0,0"
end tell'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.applescript', delete=False) as f:
        f.write(applescript)
        f.flush()
        result = subprocess.run(["osascript", f.name], capture_output=True, text=True, timeout=10)
        os.unlink(f.name)
    parts = result.stdout.strip().split(",")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return 0, 0


# ==================== 캡차 (보안문자) 자동 풀기 ====================
def _find_captcha_tab():
    """캡차가 있는 탭 찾기"""
    rw, rt = find_ticketlink_window()
    if rw == 0:
        rw, rt = find_any_ticketlink()
    return rw, rt


def ocr_captcha(img_bytes):
    """캡차 이미지 OCR (ddddocr — 즉시 인식)"""
    text = _ocr.classification(img_bytes)
    text = ''.join(c for c in text if c.isalpha()).upper()[:5]
    return text


def _captcha_get_image_and_key(rw, rt):
    """캡차 이미지(canvas JPEG) + captchaKey 한 번에"""
    js = '''
    try {
        var r = {};
        var c = document.getElementById('captcha_canvas');
        if (c && c.width > 0) r.img = c.toDataURL('image/jpeg', 0.3);
        try { r.key = angular.element(document.body).injector().get('captcha').captchaKey; } catch(e) {}
        document.getElementById('__mr').setAttribute('data-r', JSON.stringify(r));
    } catch(e) {
        document.getElementById('__mr').setAttribute('data-r', '{"error":"'+e.message+'"}');
    }
    '''
    raw = run_page_js(js, rw, rt)
    try:
        data = json.loads(raw)
    except:
        return None, None
    if 'img' not in data:
        return None, None
    return base64.b64decode(data['img'].split(',', 1)[1]), data.get('key')


def _captcha_click_refresh(rw, rt):
    """새로고침 버튼을 pynput으로 실제 클릭"""
    js = '''
    try {
        var btn = document.querySelector('[ng-click*="popupCaptcha.refresh"]');
        if (!btn) {
            var all = document.querySelectorAll('button, a, span');
            for (var i = 0; i < all.length; i++) {
                if (all[i].innerText.trim() === '새로고침') { btn = all[i]; break; }
            }
        }
        if (btn) {
            var rect = btn.getBoundingClientRect();
            var tb = window.outerHeight - window.innerHeight;
            document.getElementById('__mr').setAttribute('data-r', JSON.stringify({
                sx: Math.round(window.screenX + rect.left + rect.width/2),
                sy: Math.round(window.screenY + tb + rect.top + rect.height/2)
            }));
        } else {
            document.getElementById('__mr').setAttribute('data-r', 'no_btn');
        }
    } catch(e) {
        document.getElementById('__mr').setAttribute('data-r', 'error');
    }
    '''
    raw = run_page_js(js, rw, rt)
    try:
        pos = json.loads(raw)
        if 'sx' in pos:
            click_at(pos['sx'], pos['sy'])
            time.sleep(0.8)  # 새 이미지 로딩 대기
            print("  새로고침 클릭")
            return True
    except:
        pass
    print(f"  새로고침 버튼 못 찾음: {raw}")
    return False


def _captcha_try_auth(text, captcha_key, rw, rt):
    """API로 캡차 인증 시도. 성공=True, 실패=False"""
    js_auth = f'''
    try {{
        var sess = sessionStorage.getItem('TKL_MK_CAP_SESS');
        if (!sess) {{
            sess = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {{
                var r = Math.random() * 16 | 0;
                return (c == 'x' ? r : (r & 0x3 | 0x8)).toString(16);
            }});
            sessionStorage.setItem('TKL_MK_CAP_SESS', sess);
        }}
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/captcha/auth/{captcha_key}', false);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.send(JSON.stringify({{answer: '{text}', checkValue: sess}}));
        var res = JSON.parse(xhr.responseText);
        if (res.result.code === 0) {{
            try {{ angular.element(document.body).scope().$root.$broadcast('onCaptchaAuth'); }} catch(e) {{}}
            document.getElementById('__mr').setAttribute('data-r', 'ok');
        }} else {{
            document.getElementById('__mr').setAttribute('data-r', 'fail:' + res.result.code);
        }}
    }} catch(e) {{
        document.getElementById('__mr').setAttribute('data-r', 'error:' + e.message);
    }}
    '''
    return run_page_js(js_auth, rw, rt)


def _is_captcha_done(rw, rt):
    """캡차 팝업이 사라졌는지 확인 (사라짐=통과)"""
    js = '''
    try {
        var c = document.getElementById('captcha_canvas');
        if (!c) { document.getElementById('__mr').setAttribute('data-r','ok'); }
        else {
            var rect = c.getBoundingClientRect();
            document.getElementById('__mr').setAttribute('data-r',
                (rect.width > 0 && rect.height > 0) ? 'no' : 'ok');
        }
    } catch(e) { document.getElementById('__mr').setAttribute('data-r','ok'); }
    '''
    return run_page_js(js, rw, rt) == 'ok'


def solve_captcha():
    """캡차 자동 풀기 — 답 입력→제출→틀리면 새로고침 (최대 5회)"""
    rw, rt = _find_captcha_tab()
    if rw == 0:
        print("  티켓링크 탭을 찾을 수 없습니다!")
        return False

    t0 = time.time()

    for attempt in range(5):
        if attempt > 0:
            print(f"  ── 재시도 {attempt}/5 ──")
            _captcha_click_refresh(rw, rt)

        # 1. canvas에서 이미지
        img_bytes, _ = _captcha_get_image_and_key(rw, rt)
        if not img_bytes:
            print("  이미지 가져오기 실패")
            continue

        # 2. OCR
        text = ocr_captcha(img_bytes)
        if not text or len(text) < 3:
            print(f"  OCR 실패: '{text}'")
            continue

        print(f"  OCR: {text} ({(time.time()-t0)*1000:.0f}ms)")

        # 3. 답 입력 + 입력완료 버튼 클릭 (execCommand + pynput)
        if not _type_captcha_fallback(text, rw, rt, t0):
            continue

        # 4. 제출 결과 확인 — 팝업 사라지면 성공, 남아있으면 틀린 답
        time.sleep(1.0)
        if _is_captcha_done(rw, rt):
            print(f"  캡차 통과! {(time.time()-t0)*1000:.0f}ms")
            return True
        print("  틀린 답 — 새로고침 후 재시도")

    print("  5회 시도 실패")
    return False


def _type_captcha_fallback(answer, rw, rt, t0):
    """execCommand로 텍스트 입력 + pynput으로 버튼 클릭
    execCommand('insertText')는 브라우저가 trusted 이벤트로 처리 → 한글 입력기 무관
    """
    # 입력필드 포커스 + execCommand로 텍스트 삽입 + 버튼 위치 — 한 번의 JS 호출
    js_input = f'''
    try {{
        var el = document.getElementById('ipt_captcha');
        el.value = '';
        el.focus();
        document.execCommand('insertText', false, '{answer.upper()}');

        var btn = document.querySelector('[ng-click*="popupCaptcha.auth"]');
        if (!btn) {{
            var all = document.querySelectorAll('button, a');
            for (var i = 0; i < all.length; i++) {{
                if (all[i].innerText.indexOf('입력 완료') > -1) {{ btn = all[i]; break; }}
            }}
        }}
        var r = {{typed: el.value}};
        if (btn) {{
            var rect = btn.getBoundingClientRect();
            var tb = window.outerHeight - window.innerHeight;
            r.sx = Math.round(window.screenX + rect.left + rect.width/2);
            r.sy = Math.round(window.screenY + tb + rect.top + rect.height/2);
        }}
        document.getElementById('__mr').setAttribute('data-r', JSON.stringify(r));
    }} catch(e) {{
        document.getElementById('__mr').setAttribute('data-r', '{{"error":"' + e.message + '"}}');
    }}
    '''
    raw = run_page_js(js_input, rw, rt)
    try:
        data = json.loads(raw)
    except:
        print(f"  입력 실패: {raw}")
        return False

    print(f"  입력값: {data.get('typed','')}")

    if 'sx' in data:
        # Chrome 앞으로 가져오기
        bring_as = f'''
tell application "Google Chrome"
    set index of window {rw} to 1
    activate
end tell'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.applescript', delete=False) as f:
            f.write(bring_as)
            f.flush()
            subprocess.run(["osascript", f.name], capture_output=True, timeout=5)
            os.unlink(f.name)
        time.sleep(0.1)
        click_at(data['sx'], data['sy'])
        print(f"  입력 완료 클릭! {(time.time()-t0)*1000:.0f}ms")
        return True

    print("  버튼 못 찾음")
    return False


# ==================== Phase 1: 예매하기 클릭 ====================
def phase1_click_reserve(do_reload=False):
    """스케줄 페이지에서 타겟 날짜의 예매하기 버튼 클릭

    do_reload: True면 새로고침 (대기열 위험!), False면 DOM만 체크
    """
    sw, st = find_schedule_window()
    if sw == 0:
        print("  스케줄 페이지를 찾을 수 없습니다!")
        return False

    print(f"  스케줄 페이지: window {sw}, tab {st}")

    if do_reload:
        run_direct_js("location.reload();", sw, st)
        print("  페이지 새로고침... (대기열 주의)")
        time.sleep(2)

    # 예매하기 버튼 위치 찾기 (JS .click() 쓰면 차단됨! 위치만 가져옴)
    js = f'''
    var found = false;
    var allBtns = document.querySelectorAll('a.btn');
    for (var i = 0; i < allBtns.length; i++) {{
        var btn = allBtns[i];
        var row = btn.closest('li') || btn.closest('tr') || btn.parentElement.parentElement;
        var rowText = row ? row.innerText : '';
        if (rowText.indexOf('{TARGET_DATE}') > -1) {{
            if (btn.classList.contains('btn_reserve')) {{
                var rect = btn.getBoundingClientRect();
                var tb = window.outerHeight - window.innerHeight;
                document.getElementById('__mr').setAttribute('data-r', JSON.stringify({{
                    status: 'found',
                    sx: Math.round(window.screenX + rect.left + rect.width/2),
                    sy: Math.round(window.screenY + tb + rect.top + rect.height/2),
                    text: rowText.substring(0, 50)
                }}));
                found = true;
                break;
            }} else if (btn.classList.contains('btn_reserve_scdl')) {{
                document.getElementById('__mr').setAttribute('data-r', JSON.stringify({{status: 'not_open_yet'}}));
                found = true;
                break;
            }}
        }}
    }}
    if (!found) {{
        document.getElementById('__mr').setAttribute('data-r', JSON.stringify({{status: 'not_found'}}));
    }}
    '''
    result = run_page_js(js, sw, st)
    try:
        data = json.loads(result)
    except:
        print(f"  파싱 실패: {result}")
        return False

    if data.get('status') == 'found':
        # Chrome 앞으로 + pynput 실제 마우스 클릭
        bring_as = f'''
tell application "Google Chrome"
    set index of window {sw} to 1
    activate
end tell'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.applescript', delete=False) as f2:
            f2.write(bring_as)
            f2.flush()
            subprocess.run(["osascript", f2.name], capture_output=True, timeout=5)
            os.unlink(f2.name)
        time.sleep(0.1)
        click_at(data['sx'], data['sy'])
        print(f"  예매하기 클릭: {data.get('text','')}")
        return True
    elif data.get('status') == 'not_open_yet':
        return False
    else:
        print("  해당 날짜 경기를 찾을 수 없습니다.")
        return False


# ==================== Phase 2: 좌석 선택 페이지 ====================
def phase2_select_grade_and_section():
    """좌석 선택 페이지에서 1루 응원단석 > 빈 구역 클릭"""
    # 같은 탭에서 페이지가 전환되므로, 스케줄 탭의 URL이 바뀌는지 확인
    sw, st = find_schedule_window()
    if sw > 0:
        # 예매하기 클릭 후 같은 탭에서 reserve/plan/schedule로 전환됨
        # URL 변경 감지
        for attempt in range(20):
            url = _run_js("location.href;", sw, st)
            if "reserve/plan/schedule" in url:
                print(f"  좌석 선택 페이지 전환 확인: window {sw}, tab {st}")
                rw, rt = sw, st
                break
            time.sleep(0.5)
        else:
            # 혹시 새 창으로 열렸을 수도 있으니 확인
            rw, rt = find_ticketlink_window()
            if rw == 0:
                print("  좌석 선택 페이지를 찾을 수 없습니다!")
                return False
            print(f"  좌석 선택 페이지 (새 창): window {rw}, tab {rt}")
    else:
        # 스케줄 탭이 사라졌으면 이미 전환된 것 → 예매 페이지 찾기
        for attempt in range(20):
            rw, rt = find_ticketlink_window()
            if rw > 0:
                print(f"  좌석 선택 페이지 발견: window {rw}, tab {rt}")
                break
            time.sleep(0.5)
        else:
            print("  좌석 선택 페이지를 찾을 수 없습니다!")
            return False

    # 페이지 로딩 대기
    time.sleep(2)

    # 1루 응원단석 클릭
    js_grade = f'''
    var grades = document.querySelectorAll('[ng-click*="select.select"]');
    var clicked = false;
    for (var i = 0; i < grades.length; i++) {{
        if (grades[i].innerText.indexOf('{GRADE_NAME}') > -1) {{
            grades[i].click();
            clicked = true;
            break;
        }}
    }}
    document.getElementById('__mr').setAttribute('data-r', clicked ? 'grade_clicked' : 'grade_not_found');
    '''
    result = run_page_js(js_grade, rw, rt)
    print(f"  등급 선택: {result}")
    if result != "grade_clicked":
        return False

    time.sleep(1)

    # 빈 구역 찾아서 클릭 (남은석 > 0인 구역)
    js_section = '''
    var sections = document.querySelectorAll('[ng-click*="select.select"]');
    var clicked = false;
    for (var i = 0; i < sections.length; i++) {
        var text = sections[i].innerText;
        // "카스존 10X구역" 또는 "10X구역" 패턴이면서 0석이 아닌 것
        if ((text.indexOf('구역') > -1) && text.indexOf('0 석') === -1) {
            var match = text.match(/(\\d+)\\s*석/);
            if (match && parseInt(match[1]) > 0) {
                sections[i].click();
                document.getElementById('__mr').setAttribute('data-r', 'section_clicked:' + text.trim().replace(/\\n/g, ' '));
                clicked = true;
                break;
            }
        }
    }
    if (!clicked) {
        document.getElementById('__mr').setAttribute('data-r', 'no_available_section');
    }
    '''
    result = run_page_js(js_section, rw, rt)
    print(f"  구역 선택: {result}")

    if not result.startswith("section_clicked"):
        print("  빈 구역이 없습니다!")
        return False

    time.sleep(0.5)

    # 직접선택 팝업이 뜨면 클릭
    js_direct = '''
    var popup = document.querySelector('[ng-click*="btnClick"][ng-click*="SELF"]');
    if (!popup) {
        // 다른 방식으로 직접선택 버튼 찾기
        var btns = document.querySelectorAll('[ng-click*="btnClick"]');
        for (var i = 0; i < btns.length; i++) {
            if (btns[i].innerText.indexOf('직접선택') > -1 || btns[i].innerText.indexOf('직접') > -1) {
                popup = btns[i];
                break;
            }
        }
    }
    if (popup) {
        popup.click();
        document.getElementById('__mr').setAttribute('data-r', 'direct_clicked');
    } else {
        // 팝업 없이 바로 좌석 선택 가능한 경우
        document.getElementById('__mr').setAttribute('data-r', 'no_popup');
    }
    '''
    result = run_page_js(js_direct, rw, rt)
    print(f"  직접선택: {result}")

    return True


# ==================== Phase 3: 좌석 스캔 + 클릭 ====================
def phase3_scan_and_click():
    """좌석 스캔 → 연속 3자리 클릭"""
    print(f"\n  스캔 중... region={region}")
    screenshot = pyautogui.screenshot(region=region)
    img = np.array(screenshot.convert("RGB"))

    seats = find_seats(img)
    print(f"  발견된 좌석: {len(seats)}개")

    if not seats:
        return False

    consecutive = find_consecutive_seats(seats, SEAT_COUNT)
    to_click = None

    if consecutive:
        print(f"  연속 {SEAT_COUNT}자리 발견!")
        to_click = consecutive
    elif len(seats) >= SEAT_COUNT:
        print(f"  연속 없음, 가장 가까운 {SEAT_COUNT}자리...")
        seats.sort(key=lambda s: (s['cy'], s['cx']))
        to_click = seats[:SEAT_COUNT]

    if to_click:
        for i, seat in enumerate(to_click):
            real_x = region[0] + seat['cx']
            real_y = region[1] + seat['cy']
            click_at(real_x, real_y)
            print(f"  좌석 {i+1}: ({real_x}, {real_y})")
            time.sleep(0.2)
        return True
    return False


# ==================== Phase 4: 다음단계 ====================
def phase4_next_step():
    """다음단계 버튼 클릭"""
    # 같은 탭에서 계속 진행되므로 reserve/plan/schedule URL이 있는 탭 찾기
    rw, rt = find_ticketlink_window()
    if rw == 0:
        # 스케줄 탭이 전환됐을 수 있으므로 schedule URL도 확인
        rw, rt = find_schedule_window()
        if rw == 0:
            print("  예매 창을 찾을 수 없습니다.")
            return

    # JS로 다음단계 실행
    run_page_js_fire("tk.state.view.nextStep();", rw, rt)
    print("  다음단계 (JS)")


# ==================== 메인 ====================
def wait_for_open_time():
    """오픈 시간까지 대기"""
    today = datetime.now().strftime("%Y-%m-%d")
    target = datetime.strptime(f"{today} {OPEN_TIME}", "%Y-%m-%d %H:%M:%S")

    now = datetime.now()
    if now >= target:
        print("  이미 오픈 시간이 지났습니다. 바로 시작합니다.")
        return

    wait_seconds = (target - now).total_seconds()
    print(f"  {OPEN_TIME} 까지 {wait_seconds:.0f}초 대기...")
    print(f"  (Ctrl+C로 대기 취소 후 바로 시작 가능)")

    try:
        # 10초 전까지 대기
        while (target - datetime.now()).total_seconds() > 10:
            remaining = (target - datetime.now()).total_seconds()
            print(f"\r  남은 시간: {remaining:.0f}초  ", end="", flush=True)
            time.sleep(1)
        print()

        # 마지막 10초는 정밀 대기
        print("  10초 전! 준비 중...")
        while datetime.now() < target:
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n  대기 취소! 바로 시작합니다.")


def run_full():
    """전체 플로우 실행"""
    print("\n" + "=" * 50)
    print("  Phase 0: 오픈 시간 대기")
    print("=" * 50)
    wait_for_open_time()

    t_start = time.time()

    print("\n" + "=" * 50)
    print("  Phase 1: 예매하기 클릭")
    print("=" * 50)

    # 새로고침 없이 DOM polling으로 예매하기 버튼 감지 (대기열 회피)
    # 11시 되면 서버에서 버튼 상태가 바뀌므로, 페이지 내 JS로 반복 체크
    for attempt in range(30):
        if phase1_click_reserve(do_reload=False):
            break
        if attempt == 15:
            # 15회 실패 시 한 번만 새로고침 시도
            print("  DOM에서 못 찾음, 새로고침 1회 시도...")
            if phase1_click_reserve(do_reload=True):
                break
        print(f"  대기 {attempt+1}... (새로고침 없이 DOM 체크)")
        time.sleep(0.3)
    else:
        print("  예매하기 버튼을 찾을 수 없습니다. 종료.")
        return

    # 캡차 확인 (보안문자가 있으면 풀기)
    print("\n" + "=" * 50)
    print("  Phase 1.5: 보안문자 확인")
    print("=" * 50)
    rw, rt = _find_captcha_tab()
    if rw > 0:
        check_js = '''
        try {
            var canvas = document.getElementById('captcha_canvas');
            var popup = document.querySelector('[ng-click*="popupCaptcha.auth"]');
            document.getElementById('__mr').setAttribute('data-r',
                (canvas && canvas.width > 0) || popup ? 'captcha_found' : 'no_captcha');
        } catch(e) {
            document.getElementById('__mr').setAttribute('data-r', 'no_captcha');
        }
        '''
        has_captcha = run_page_js(check_js, rw, rt)
        if has_captcha == 'captcha_found':
            print("  보안문자 발견! 자동 풀기 시도...")
            for cap_attempt in range(3):
                if solve_captcha():
                    break
                print(f"  캡차 재시도 {cap_attempt+1}...")
                time.sleep(1)
            else:
                print("  캡차 자동 풀기 실패. 수동으로 입력하세요.")
                input("  입력 후 Enter...")
        else:
            print("  보안문자 없음, 계속 진행")

    print("\n" + "=" * 50)
    print("  Phase 2: 등급/구역 선택")
    print("=" * 50)

    if not phase2_select_grade_and_section():
        print("  등급/구역 선택 실패. 종료.")
        return

    # 좌석 지도 로딩 대기
    print("  좌석 지도 로딩 대기...")
    time.sleep(2)

    print("\n" + "=" * 50)
    print("  Phase 3: 좌석 스캔 + 클릭")
    print("=" * 50)

    # 좌석을 찾을 때까지 재스캔
    for attempt in range(5):
        if phase3_scan_and_click():
            break
        print(f"  재스캔 {attempt+1}...")
        time.sleep(1)
    else:
        print("  좌석을 찾을 수 없습니다. 수동으로 선택하세요.")
        elapsed = time.time() - t_start
        print(f"\n  경과 시간: {elapsed:.1f}초")
        return

    print("\n" + "=" * 50)
    print("  Phase 4: 다음단계")
    print("=" * 50)
    time.sleep(0.5)
    phase4_next_step()

    elapsed = time.time() - t_start
    print(f"\n{'=' * 50}")
    print(f"  완료! 총 {elapsed:.1f}초")
    print(f"{'=' * 50}")


# ==================== 시작 ====================
if __name__ == "__main__":
    print("=" * 50)
    print("  티켓링크 1루 응원단석 전체 자동 예매")
    print("=" * 50)
    print(f"  대상 경기: {TARGET_DATE}")
    print(f"  등급: {GRADE_NAME}")
    print(f"  좌석 수: {SEAT_COUNT}자리")
    print(f"  오픈: {OPEN_TIME}")
    print(f"  좌석 영역: {region}")
    print()
    print("  스케줄 페이지를 Chrome에 열어두세요:")
    print("  https://facility.ticketlink.co.kr/reserve/product/62162/schedule/sports")
    print()

    # 커맨드라인 인자
    if len(sys.argv) > 1 and sys.argv[1] == "--reserve":
        print("  --reserve: 예매하기 → 보안문자 자동 풀기")
        print("  스케줄 페이지가 Chrome에 열려있어야 합니다.")
        print()
        input("  Enter를 누르면 시작...")
        t_start = time.time()

        # 1) 예매하기 클릭 (열려있는 아무거나)
        print("\n── 예매하기 클릭 ──")
        sw, st = find_schedule_window()
        if sw == 0:
            sw, st = find_any_ticketlink()
        if sw == 0:
            print("  스케줄 페이지를 찾을 수 없습니다!")
            sys.exit(1)

        # TARGET_DATE의 예매하기 버튼 위치 + 좌표 디버깅
        js_find = f'''
        try {{
            var found = null;
            var allBtns = document.querySelectorAll('a.btn');
            for (var i = 0; i < allBtns.length; i++) {{
                var btn = allBtns[i];
                var row = btn.closest('li') || btn.closest('tr') || btn.parentElement.parentElement;
                var rowText = row ? row.innerText : '';
                if (rowText.indexOf('{TARGET_DATE}') > -1 && btn.classList.contains('btn_reserve')) {{
                    found = btn;
                    break;
                }}
            }}
            if (!found) {{
                // 날짜 못 찾으면 아무 예매하기나
                found = document.querySelector('a.btn_reserve');
            }}
            if (found) {{
                var rect = found.getBoundingClientRect();
                var row = found.closest('li,tr,div');
                var txt = row ? row.innerText.substring(0,40).replace(/\\n/g,' ') : '';
                document.getElementById('__mr').setAttribute('data-r', JSON.stringify({{
                    rx: Math.round(rect.left + rect.width/2),
                    ry: Math.round(rect.top + rect.height/2),
                    winX: window.screenX,
                    winY: window.screenY,
                    outerH: window.outerHeight,
                    innerH: window.innerHeight,
                    t: txt
                }}));
            }} else {{
                document.getElementById('__mr').setAttribute('data-r', 'no_btn');
            }}
        }} catch(e) {{
            document.getElementById('__mr').setAttribute('data-r', 'error:' + e.message);
        }}
        '''
        result = run_page_js(js_find, sw, st)
        if not result or result in ('no_btn',) or result.startswith('error'):
            print(f"  예매하기 버튼을 찾을 수 없습니다! ({result})")
            sys.exit(1)

        btn = json.loads(result)
        toolbar = btn['outerH'] - btn['innerH']
        sx = btn['winX'] + btn['rx']
        sy = btn['winY'] + toolbar + btn['ry']
        print(f"  발견: {btn.get('t','')}")
        print(f"  디버그: rect=({btn['rx']},{btn['ry']}) win=({btn['winX']},{btn['winY']}) toolbar={toolbar}")
        print(f"  스크린 좌표: ({sx}, {sy})")

        # Chrome 앞으로 + pynput 클릭
        bring_as = f'''
tell application "Google Chrome"
    set index of window {sw} to 1
    activate
end tell'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.applescript', delete=False) as f:
            f.write(bring_as)
            f.flush()
            subprocess.run(["osascript", f.name], capture_output=True, timeout=5)
            os.unlink(f.name)
        time.sleep(0.2)
        click_at(sx, sy)
        print(f"  클릭: ({sx}, {sy})")

        # 2) 페이지 전환 대기 (같은 탭에서 reserve/plan/schedule로 전환)
        print("\n── 페이지 로딩 대기 ──")
        for i in range(30):
            url = _run_js("location.href;", sw, st)
            if "reserve/plan" in url:
                print(f"  좌석선택 페이지 전환 확인 ({(time.time()-t_start)*1000:.0f}ms)")
                break
            time.sleep(0.2)
        else:
            print("  페이지 전환 시간 초과!")
            sys.exit(1)

        # 3) 캡차 로딩 대기 (canvas 생성까지)
        print("\n── 보안문자 대기 ──")
        for i in range(30):
            check = run_page_js('''
            try {
                var c = document.getElementById('captcha_canvas');
                document.getElementById('__mr').setAttribute('data-r', (c && c.width > 0) ? 'ready' : 'waiting');
            } catch(e) {
                document.getElementById('__mr').setAttribute('data-r', 'waiting');
            }
            ''', sw, st)
            if check == 'ready':
                print(f"  캡차 로딩 완료 ({(time.time()-t_start)*1000:.0f}ms)")
                break
            time.sleep(0.2)
        else:
            print("  캡차가 나타나지 않음 (없는 경기일 수 있음)")
            sys.exit(0)

        # 4) 캡차 풀기
        print("\n── 보안문자 풀기 ──")
        for attempt in range(3):
            if solve_captcha():
                break
            print(f"  재시도 {attempt+1}...")
            time.sleep(0.5)

        print(f"\n  총 {(time.time()-t_start)*1000:.0f}ms")
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "--captcha":
        print("  --captcha: 보안문자 풀기만 실행")
        print("  캡차가 표시된 티켓링크 페이지를 Chrome에 열어두세요.")
        print()
        input("  Enter를 누르면 캡차 풀기 시작...")
        solve_captcha()
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "--now":
        print("  --now: 대기 없이 바로 시작!")
        t_start = time.time()
        print("\n  Phase 1: 예매하기 클릭")
        for attempt in range(30):
            if phase1_click_reserve(do_reload=False):
                break
            if attempt == 15:
                print("  DOM에서 못 찾음, 새로고침 1회...")
                if phase1_click_reserve(do_reload=True):
                    break
            time.sleep(0.3)
        else:
            print("  실패")
            sys.exit(1)
        print("\n  Phase 2: 등급/구역 선택")
        if phase2_select_grade_and_section():
            time.sleep(2)
            print("\n  Phase 3: 좌석 스캔 + 클릭")
            for attempt in range(5):
                if phase3_scan_and_click():
                    break
                time.sleep(1)
            time.sleep(0.5)
            print("\n  Phase 4: 다음단계")
            phase4_next_step()
        elapsed = time.time() - t_start
        print(f"\n  완료! {elapsed:.1f}초")
    else:
        input("  Enter를 누르면 오픈 시간 대기 시작...")
        run_full()
