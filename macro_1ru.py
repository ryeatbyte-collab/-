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
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import requests
from pynput import mouse, keyboard as kb
import pyautogui
import numpy as np
from collections import defaultdict
import ddddocr

# ==================== 타이밍 로그 ====================
_log_entries = []
_log_t0 = None  # run_full 시작 시점 (perf_counter)
_log_t0_wall = None  # run_full 시작 시점 (wall clock)

def tlog(event, **kwargs):
    """타이밍 로그 기록. 콘솔 출력은 안 함, 파일에만 저장."""
    now_pc = time.perf_counter()
    now_wall = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    elapsed = (now_pc - _log_t0) * 1000 if _log_t0 else 0
    entry = {
        'time': now_wall,
        'elapsed_ms': round(elapsed, 1),
        'event': event,
    }
    entry.update(kwargs)
    _log_entries.append(entry)

def save_log():
    """로그를 파일로 저장"""
    if not _log_entries:
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"log_{ts}.json"
    filepath = os.path.join(os.path.dirname(__file__) or '.', filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(_log_entries, f, ensure_ascii=False, indent=2)
    print(f"\n  로그 저장: {filepath} ({len(_log_entries)}건)")

    # 요약도 텍스트로 저장
    summary_path = filepath.replace('.json', '.txt')
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(f"=== 티켓 매크로 실행 로그 ({ts}) ===\n\n")
        phases = {}
        for e in _log_entries:
            f.write(f"[{e['time']}] +{e['elapsed_ms']:>8.1f}ms  {e['event']}")
            extras = {k: v for k, v in e.items() if k not in ('time', 'elapsed_ms', 'event')}
            if extras:
                f.write(f"  {extras}")
            f.write("\n")
            # phase별 시간 집계
            ev = e['event']
            if ev.startswith('phase') and ev.endswith('_start'):
                phases[ev.replace('_start', '')] = e['elapsed_ms']
            elif ev.startswith('phase') and ev.endswith('_end'):
                phase = ev.replace('_end', '')
                if phase in phases:
                    duration = e['elapsed_ms'] - phases[phase]
                    f.write(f"  >>> {phase} 소요: {duration:.0f}ms\n")
        f.write(f"\n총 소요: {_log_entries[-1]['elapsed_ms']:.0f}ms\n")
    print(f"  요약 저장: {summary_path}")

# ==================== 설정 ====================
TARGET_DATE = "04.10"           # 예매할 경기 날짜 (페이지에 표시되는 형식)
GRADE_NAME = "1루 응원단석"      # 등급 이름
TARGET_SECTION = "106"           # 우선 선택할 구역
SEAT_COUNT = 3                   # 연속 좌석 수
OPEN_TIME = "11:00:00"           # 판매 오픈 시간
NEXT_BTN_POS = (908, 920)        # 다음단계 버튼 고정 좌표
ASSIST_MODE = "--assist" in sys.argv  # 어시스트 모드: 사용자 1클릭 → 옆자리 자동

# 좌석 색상 (RGB) — JS 스캔용
SEAT_COLOR = (68, 87, 101)
SEAT_TOLERANCE = 15
MIN_SEAT_PIXELS = 18   # min_seat_size² * 0.5
MAX_SEAT_SPAN = 50     # max_seat_size * 2

# 좌석 색상 — pyautogui 스캔용 (하위호환)
target_color = SEAT_COLOR
tolerance = SEAT_TOLERANCE
min_seat_size = 6
max_seat_size = 25
region = (20, 340, 680, 604)

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
from scipy.ndimage import label as _ndlabel, find_objects as _nd_find_objects

def find_seats(img):
    diff = np.abs(img.astype(int) - np.array(target_color, dtype=int))
    mask = np.all(diff <= tolerance, axis=2)
    if not mask.any():
        return []
    labeled, num = _ndlabel(mask)
    if num == 0:
        return []
    seats = []
    slices = _nd_find_objects(labeled)
    for i, sl in enumerate(slices):
        if sl is None:
            continue
        region = labeled[sl] == (i + 1)
        px_count = region.sum()
        if px_count < min_seat_size * min_seat_size * 0.5:
            continue
        y_sl, x_sl = sl
        sw = x_sl.stop - x_sl.start
        sh = y_sl.stop - y_sl.start
        if sw > max_seat_size * 2 or sh > max_seat_size * 2:
            continue
        ys, xs = np.where(region)
        cx_val = x_sl.start + (xs.min() + xs.max()) // 2
        cy_val = y_sl.start + (ys.min() + ys.max()) // 2
        seats.append({'cx': cx_val, 'cy': cy_val, 'w': sw, 'h': sh, 'pixels': int(px_count)})
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
    # 사람처럼 미세하게 접근 후 클릭 (~15-25ms)
    ox = random.randint(-6, -3)
    oy = random.randint(-3, 3)
    mouse_controller.position = (x + ox, y + oy)
    time.sleep(random.uniform(0.004, 0.008))
    mouse_controller.position = (x + ox // 2, y + oy // 2)
    time.sleep(random.uniform(0.003, 0.006))
    mouse_controller.position = (x, y)
    time.sleep(random.uniform(0.002, 0.005))
    mouse_controller.press(mouse.Button.left)
    time.sleep(random.uniform(0.001, 0.003))
    mouse_controller.release(mouse.Button.left)


# ==================== 티켓링크 창 찾기 ====================
# ==================== 탭 캐시 (AppleScript 호출 최소화) ====================
_tab_cache = {
    'tabs': [],       # [(window, tab, url), ...]
    'timestamp': 0,   # 마지막 갱신 시각 (time.time)
    'ttl': 0.5,       # 캐시 유효 시간 (초)
}


def _refresh_tab_cache(force=False):
    """모든 Chrome 탭 URL을 한 번에 가져와 캐싱. AppleScript 1회."""
    now = time.time()
    if not force and _tab_cache['tabs'] and (now - _tab_cache['timestamp']) < _tab_cache['ttl']:
        return _tab_cache['tabs']

    applescript = '''
tell application "Google Chrome"
    set r to ""
    set winCount to count of windows
    repeat with w from 1 to winCount
        repeat with i from 1 to count of tabs of window w
            set u to URL of tab i of window w
            set r to r & w & "," & i & "," & u & linefeed
        end repeat
    end repeat
    return r
end tell'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.applescript', delete=False) as f:
        f.write(applescript)
        f.flush()
        result = subprocess.run(["osascript", f.name], capture_output=True, text=True, timeout=10)
        os.unlink(f.name)

    tabs = []
    for line in result.stdout.strip().split('\n'):
        parts = line.strip().split(',', 2)
        if len(parts) == 3:
            try:
                tabs.append((int(parts[0]), int(parts[1]), parts[2]))
            except ValueError:
                continue

    _tab_cache['tabs'] = tabs
    _tab_cache['timestamp'] = time.time()
    return tabs


def find_ticketlink_window():
    """티켓링크 예매 창(reserve/plan/schedule) 찾기 → (window, tab) 반환"""
    for w, t, url in _refresh_tab_cache():
        if "ticketlink.co.kr/reserve/plan/schedule" in url:
            return w, t
    return 0, 0


def find_schedule_window():
    """티켓링크 스케줄 페이지 찾기"""
    for w, t, url in _refresh_tab_cache():
        if "ticketlink.co.kr" in url and "schedule" in url and "reserve/plan" not in url:
            return w, t
    return 0, 0


def find_any_ticketlink():
    """ticketlink.co.kr이 열린 아무 탭 찾기"""
    for w, t, url in _refresh_tab_cache():
        if "ticketlink.co.kr" in url:
            return w, t
    return 0, 0


# ==================== 캡차 (보안문자) 자동 풀기 ====================
def _find_captcha_tab():
    """캡차가 있는 탭 찾기"""
    rw, rt = find_ticketlink_window()
    if rw == 0:
        rw, rt = find_any_ticketlink()
    return rw, rt


_DIGIT_TO_ALPHA = {'0': 'O', '1': 'I', '2': 'Z', '3': 'E', '4': 'A', '5': 'S', '6': 'G', '7': 'T', '8': 'B', '9': 'G'}

def _ascii_only(text):
    """ASCII 영문만 남기고 대문자. 숫자는 가장 비슷한 알파벳으로 치환."""
    out = []
    for c in text:
        if c.isascii() and c.isalpha():
            out.append(c.upper())
        elif c.isdigit():
            out.append(_DIGIT_TO_ALPHA[c])
    return ''.join(out)[:5]

def ocr_captcha(img_bytes):
    """캡차 이미지 OCR (ddddocr) — 여러 전처리 시도, 5글자 우선"""
    from PIL import Image, ImageEnhance, ImageFilter
    import io

    results = []

    # 1차: 원본
    t1 = _ascii_only(_ocr.classification(img_bytes))
    results.append(t1)
    if len(t1) == 5:
        return t1

    img_orig = Image.open(io.BytesIO(img_bytes))

    # 2차: 그레이스케일 + 대비 1.5x
    img = img_orig.convert('L')
    img = ImageEnhance.Contrast(img).enhance(1.5)
    buf = io.BytesIO(); img.save(buf, format='PNG')
    t2 = _ascii_only(_ocr.classification(buf.getvalue()))
    results.append(t2)
    if len(t2) == 5:
        return t2

    # 3차: 그레이스케일 + 대비 2.0x + 샤프닝
    img = img_orig.convert('L')
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = ImageEnhance.Sharpness(img).enhance(2.0)
    buf = io.BytesIO(); img.save(buf, format='PNG')
    t3 = _ascii_only(_ocr.classification(buf.getvalue()))
    results.append(t3)
    if len(t3) == 5:
        return t3

    # 4차: 이진화 (threshold 100, 더 관대)
    img = img_orig.convert('L')
    img = img.point(lambda x: 0 if x < 100 else 255)
    buf = io.BytesIO(); img.save(buf, format='PNG')
    t4 = _ascii_only(_ocr.classification(buf.getvalue()))
    results.append(t4)
    if len(t4) == 5:
        return t4

    # 5글자 없으면 가장 긴 결과 반환
    return max(results, key=len)


def _captcha_get_image_and_key(rw, rt):
    """캡차 이미지(canvas JPEG) + captchaKey 한 번에"""
    js = '''
    try {
        var r = {};
        var c = document.getElementById('captcha_canvas');
        if (c && c.width > 0) r.img = c.toDataURL('image/png');
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
            time.sleep(0.3)  # 새 이미지 로딩 대기
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

        # 2. OCR (5글자 아니면 바로 새로고침)
        text = ocr_captcha(img_bytes)
        if not text or len(text) != 5:
            print(f"  OCR 불완전: '{text}' ({len(text) if text else 0}자) → 새로고침")
            continue

        print(f"  OCR: {text} ({(time.time()-t0)*1000:.0f}ms)")

        # 3. 답 입력 + 입력완료 버튼 클릭 (execCommand + pynput)
        if not _type_captcha_fallback(text, rw, rt, t0):
            continue

        # 4. 제출 결과 확인 — polling으로 빠르게 감지
        for _ in range(10):
            time.sleep(0.1)
            if _is_captcha_done(rw, rt):
                break
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
        time.sleep(0.03)
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
        time.sleep(0.05)
        click_at(data['sx'], data['sy'])
        print(f"  예매하기 더블클릭: {data.get('text','')}")
        return 'clicked'
    elif data.get('status') == 'not_open_yet':
        return 'not_open_yet'
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
        for attempt in range(60):
            url = _run_js("location.href;", sw, st)
            if "reserve/plan/schedule" in url:
                print(f"  좌석 선택 페이지 전환 확인: window {sw}, tab {st}")
                rw, rt = sw, st
                break
            time.sleep(0.05)
        else:
            # 혹시 새 창으로 열렸을 수도 있으니 확인
            _refresh_tab_cache(force=True)
            rw, rt = find_ticketlink_window()
            if rw == 0:
                print("  좌석 선택 페이지를 찾을 수 없습니다!")
                return False
            print(f"  좌석 선택 페이지 (새 창): window {rw}, tab {rt}")
    else:
        # 스케줄 탭이 사라졌으면 이미 전환된 것 → 예매 페이지 찾기
        for attempt in range(60):
            _refresh_tab_cache(force=True)
            rw, rt = find_ticketlink_window()
            if rw > 0:
                print(f"  좌석 선택 페이지 발견: window {rw}, tab {rt}")
                break
            time.sleep(0.05)
        else:
            print("  좌석 선택 페이지를 찾을 수 없습니다!")
            return False

    # 등급 → 구역 선택 fallback 체인
    # 우선 구역 리스트: 순서대로 시도, 전부 실패 시 좌석 수 가장 많은 구역
    GRADE_CHAIN = [
        ("1루 응원단석", ["106", "103"], 3),
        ("중앙탁자석", ["100B", "100C", "100A"], 3),
        ("중앙지정석", ["100B"], 3),
        ("1루 내야지정석", ["110", "102"], 3),
    ]

    def _try_grade_and_section(grade_name, pref_sections, min_seats, rw, rt):
        """등급 클릭 → 구역 선택. 성공 시 True"""
        js_grade = f'''
        (function() {{
            var grades = document.querySelectorAll('[ng-click*="select.select"]');
            for (var i = 0; i < grades.length; i++) {{
                if (grades[i].innerText.indexOf('{grade_name}') > -1) {{
                    grades[i].click();
                    return 'grade_clicked:' + grades[i].innerText.substring(0,30).replace(/\\n/g,' ');
                }}
            }}
            return 'grade_not_found';
        }})();
        '''
        for _ in range(60):
            result = run_direct_js(js_grade, rw, rt)
            if result.startswith("grade_clicked"):
                break
            time.sleep(0.05)
        else:
            return False
        print(f"  등급 선택: {result}")

        prefs_js = json.dumps(pref_sections)
        # 첫 번째 우선 구역으로 등급 전환 확인 (이전 등급 구역이 남아있는지 판별)
        first_pref = pref_sections[0] if pref_sections else ""
        js_section = f'''
        (function() {{
            // 현재 선택된 등급 확인 (active/selected 클래스)
            var activeGrade = document.querySelector('[ng-click*="select.select"].active, [ng-click*="select.select"].on');
            if (activeGrade && activeGrade.innerText.indexOf('{grade_name}') === -1) return 'not_ready';
            var zones = document.querySelectorAll('[ng-click*="grade.select"]');
            if (zones.length === 0) return 'not_ready';
            var prefs = {prefs_js};
            var bestFallback = null;
            var bestCount = 0;
            var zoneMap = {{}};
            var totalZones = 0;
            for (var i = 0; i < zones.length; i++) {{
                var text = zones[i].innerText;
                if (text.indexOf('구역') > -1) totalZones++;
                var match = text.match(/(\\d+)\\s*석/);
                if (!match || parseInt(match[1]) < {min_seats}) continue;
                var cnt = parseInt(match[1]);
                for (var p = 0; p < prefs.length; p++) {{
                    if (text.indexOf(prefs[p] + '구역') > -1) {{
                        zoneMap[prefs[p]] = zones[i];
                    }}
                }}
                if (cnt > bestCount) {{ bestCount = cnt; bestFallback = zones[i]; }}
            }}
            var clicked = null;
            for (var p = 0; p < prefs.length; p++) {{
                if (zoneMap[prefs[p]]) {{
                    zoneMap[prefs[p]].click();
                    clicked = 'section_clicked:' + zoneMap[prefs[p]].innerText.trim().replace(/\\n/g, ' ');
                    break;
                }}
            }}
            if (!clicked && bestFallback) {{
                bestFallback.click();
                clicked = 'section_clicked(best):' + bestFallback.innerText.trim().replace(/\\n/g, ' ').substring(0,50);
            }}
            return clicked || (totalZones > 0 ? 'no_seats' : 'not_ready');
        }})();
        '''
        for _ in range(20):
            result = run_direct_js(js_section, rw, rt)
            if result.startswith("section_clicked"):
                print(f"  구역 선택: {result}")
                return True
            if result == 'no_seats':
                print(f"  → {grade_name}: 좌석 부족 (< {min_seats}석)")
                return False
            time.sleep(0.05)
        return False

    for grade_name, pref_sections, min_s in GRADE_CHAIN:
        print(f"  시도: {grade_name} (우선: {pref_sections})")
        if _try_grade_and_section(grade_name, pref_sections, min_s, rw, rt):
            break
    else:
        print("  모든 등급에서 좌석을 찾을 수 없습니다!")
        return False

    return True


# ==================== Phase 3: 좌석 스캔 + 클릭 ====================
def _bring_chrome_front(window=1):
    """Chrome 창을 최앞으로 가져오기"""
    bring_as = f'''
tell application "Google Chrome"
    set index of window {window} to 1
    activate
end tell'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.applescript', delete=False) as f:
        f.write(bring_as)
        f.flush()
        subprocess.run(["osascript", f.name], capture_output=True, timeout=5)
        os.unlink(f.name)
    time.sleep(0.15)


def _get_canvas_region(rw=0, rt=0):
    """캔버스의 화면 좌표를 JS로 동적으로 가져오기"""
    if rw == 0:
        rw, rt = find_ticketlink_window()
    if rw == 0:
        rw, rt = find_any_ticketlink()
    if rw == 0:
        return None
    result = run_direct_js('''
    (function() {
        var canvases = document.querySelectorAll('#main_view canvas');
        for (var i = canvases.length - 1; i >= 0; i--) {
            var c = canvases[i];
            if (c.style.display !== 'none' && c.width > 100) {
                var r = c.getBoundingClientRect();
                var tb = window.outerHeight - window.innerHeight;
                return JSON.stringify({
                    x: Math.round(window.screenX + r.left),
                    y: Math.round(window.screenY + tb + r.top),
                    w: Math.round(r.width),
                    h: Math.round(r.height)
                });
            }
        }
        return 'not_found';
    })();
    ''', rw, rt)
    if not result or result == 'not_found':
        return None
    r = json.loads(result)
    return (r['x'], r['y'], r['w'], r['h'])


def phase3_scan_and_click(cached_region=None):
    """자동 모드: pyautogui 스크린샷 + 좌석 스캔"""
    t0 = time.time()
    canvas_region = cached_region or region

    screenshot = pyautogui.screenshot(region=canvas_region)
    img = np.array(screenshot.convert("RGB"))
    t1 = time.time()

    seats = find_seats(img)
    t2 = time.time()
    print(f"  좌석 {len(seats)}개 (캡처:{(t1-t0)*1000:.0f}ms 스캔:{(t2-t1)*1000:.0f}ms)")

    if not seats:
        return False

    consecutive = find_consecutive_seats(seats, SEAT_COUNT)
    to_click = None
    if consecutive:
        print(f"  연속 {SEAT_COUNT}자리 발견!")
        to_click = consecutive
    elif len(seats) >= SEAT_COUNT:
        seats.sort(key=lambda s: (s['cy'], s['cx']))
        to_click = seats[:SEAT_COUNT]

    if not to_click:
        return False

    for i, seat in enumerate(to_click):
        real_x = canvas_region[0] + seat['cx']
        real_y = canvas_region[1] + seat['cy']
        click_at(real_x, real_y)
        print(f"  좌석 {i+1}: ({real_x}, {real_y})")
        time.sleep(0.25)

    # 다음단계
    time.sleep(0.35)
    click_at(NEXT_BTN_POS[0], NEXT_BTN_POS[1])
    print(f"  다음단계 클릭! {NEXT_BTN_POS}")
    return True


def phase3_assist_mode():
    """어시스트 모드: 사용자가 1석 클릭 → 옆 2석 자동 클릭 → 즉시 다음단계
    JS polling 없이 순수 마우스 클릭 감지만 사용"""
    import threading

    click_pos = [None]
    click_event = threading.Event()

    def on_click(x, y, button, pressed):
        if pressed and button == mouse.Button.left:
            click_pos[0] = (x, y)
            click_event.set()

    listener = mouse.Listener(on_click=on_click)
    listener.start()

    print("  좌석 1개를 클릭하세요... (캔버스 영역 감지 중)")
    t0 = time.time()

    # 사용자 클릭 대기 (최대 60초)
    if not click_event.wait(timeout=60):
        listener.stop()
        print("  타임아웃 (60초)")
        return False

    user_x, user_y = int(click_pos[0][0]), int(click_pos[0][1])
    listener.stop()
    print(f"  클릭 감지! ({user_x},{user_y}) {(time.time()-t0)*1000:.0f}ms")

    # 클릭 위치 오른쪽으로 미니 스캔 (사용자 좌석은 이미 선택됨)
    scan_w, scan_h = 400, 50
    mini_x = max(0, user_x + 15)  # 사용자 좌석 오른쪽부터
    mini_y = max(0, user_y - scan_h // 2)

    screenshot = pyautogui.screenshot(region=(mini_x, mini_y, scan_w, scan_h))
    img = np.array(screenshot.convert("RGB"))
    seats = find_seats(img)

    user_local_y = user_y - mini_y

    # 같은 행에서 오른쪽 좌석들
    right = [s for s in seats if abs(s['cy'] - user_local_y) <= 8]
    right.sort(key=lambda s: s['cx'])

    to_click = right[:SEAT_COUNT - 1]
    if len(to_click) < SEAT_COUNT - 1:
        print(f"  오른쪽 좌석 부족 ({len(to_click)}석만 발견, 행 필터 전 {len(seats)}개)")
        return False

    for i, s in enumerate(to_click):
        rx = mini_x + s['cx']
        ry = mini_y + s['cy']
        click_at(rx, ry)
        print(f"  자동 좌석 {i+2}: ({rx},{ry})")

    print(f"  {SEAT_COUNT}석 완료! {(time.time()-t0)*1000:.0f}ms")

    # 바로 다음단계 클릭
    time.sleep(0.35)
    click_at(NEXT_BTN_POS[0], NEXT_BTN_POS[1])
    print(f"  다음단계 클릭! {NEXT_BTN_POS}")
    return True


def _verify_seat_selection(rw=0, rt=0):
    """좌석이 실제로 선택되었는지 확인 (tk.state.select.getTotalCnt)"""
    if rw == 0:
        rw, rt = find_ticketlink_window()
    if rw == 0:
        rw, rt = find_any_ticketlink()
    if rw == 0:
        return 0

    js = '''
    try {
        var count = 0;
        if (typeof tk !== 'undefined' && tk.state && tk.state.select) {
            if (typeof tk.state.select.getTotalCnt === 'function') {
                count = tk.state.select.getTotalCnt();
            }
        }
        document.getElementById('__mr').setAttribute('data-r', String(count));
    } catch(e) {
        document.getElementById('__mr').setAttribute('data-r', '0');
    }
    '''
    result = run_page_js(js, rw, rt)
    try:
        return int(result)
    except:
        return 0


# ==================== Phase 4: 다음단계 ====================
def phase4_next_step():
    """좌석 선택 확인 후 다음단계 버튼 클릭"""
    # 선택 확인
    count = _verify_seat_selection()
    print(f"  선택된 좌석 수: {count}")

    if count < SEAT_COUNT:
        print(f"  좌석이 {SEAT_COUNT}석 선택되지 않았습니다! 다음단계 건너뜀.")
        print("  수동으로 좌석을 선택한 후 다음단계를 눌러주세요.")
        return False

    rw, rt = find_ticketlink_window()
    if rw == 0:
        rw, rt = find_any_ticketlink()
        if rw == 0:
            print("  예매 창을 찾을 수 없습니다.")
            return False

    # 다음단계 버튼 위치 찾아서 실제 클릭 (JS 호출은 "요청 데이터 오류" 발생)
    js_btn = '''
    (function() {
        var btns = document.querySelectorAll('button, a, input[type="button"]');
        for (var i = 0; i < btns.length; i++) {
            var t = (btns[i].innerText || btns[i].value || '').trim();
            if (t === '다음단계' || t === '다음 단계') {
                var rect = btns[i].getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    var tb = window.outerHeight - window.innerHeight;
                    return JSON.stringify({
                        sx: Math.round(window.screenX + rect.left + rect.width/2),
                        sy: Math.round(window.screenY + tb + rect.top + rect.height/2)
                    });
                }
            }
        }
        return 'not_found';
    })();
    '''
    result = run_direct_js(js_btn, rw, rt)
    if result == 'not_found':
        print("  다음단계 버튼을 찾을 수 없습니다.")
        return False

    pos = json.loads(result)
    _bring_chrome_front(rw)
    click_at(pos['sx'], pos['sy'])
    print(f"  다음단계 클릭! ({pos['sx']}, {pos['sy']})")
    return True


# ==================== 서버 시간 동기화 ====================
_sync_session = requests.Session()  # keep-alive로 RTT 안정화

def get_server_time_offset_rough():
    """1단계: 대략적 동기화 (±500ms) — Date 헤더 기반"""
    offsets = []
    for i in range(5):
        try:
            t_before = time.time()
            resp = _sync_session.head("https://www.ticketlink.co.kr", timeout=3)
            t_after = time.time()
            rtt = t_after - t_before
            local_at_server = t_before + rtt / 2

            server_dt = parsedate_to_datetime(resp.headers['Date'])
            server_ts = server_dt.timestamp()

            offset = server_ts - local_at_server
            offsets.append(offset)
        except Exception as e:
            print(f"  시간 동기화 시도 {i+1} 실패: {e}")
    if not offsets:
        return 0.0
    offsets.sort()
    return offsets[len(offsets) // 2]


def get_server_time_offset_precise(num_boundaries=7):
    """2~3단계: 초 경계 감지로 정밀 동기화 (±5-10ms)

    Date 헤더가 N초 → N+1초로 바뀌는 순간을 포착하여
    서버의 정확한 초 경계를 로컬 시각으로 매핑한다.
    """
    offsets = []
    median_rtt = None

    # 먼저 RTT 기준선 측정 (5회)
    rtts = []
    for _ in range(5):
        try:
            t0 = time.perf_counter()
            resp = _sync_session.head("https://www.ticketlink.co.kr", timeout=3)
            t1 = time.perf_counter()
            rtts.append(t1 - t0)
        except:
            pass
        time.sleep(0.01)
    if rtts:
        rtts.sort()
        median_rtt = rtts[len(rtts) // 2]
        print(f"  RTT 기준선: {median_rtt*1000:.1f}ms (min={min(rtts)*1000:.1f}, max={max(rtts)*1000:.1f})")
    else:
        print("  RTT 측정 실패! 대략적 동기화로 폴백")
        return get_server_time_offset_rough()

    rtt_threshold = median_rtt * 2.0  # 이 이상이면 버림

    boundaries_found = 0
    attempts = 0
    max_attempts = num_boundaries * 3  # 최대 시도 횟수

    while boundaries_found < num_boundaries and attempts < max_attempts:
        attempts += 1
        try:
            # 현재 초 값 확인
            resp = _sync_session.head("https://www.ticketlink.co.kr", timeout=3)
            prev_date = resp.headers.get('Date', '')
            prev_second = prev_date.split(':')[-1].split(' ')[0] if ':' in prev_date else ''

            # 초가 바뀔 때까지 빠르게 polling (35ms 간격)
            last_t = time.perf_counter()
            last_rtt = 0
            boundary_detected = False

            for _ in range(60):  # 최대 ~2초
                t_send = time.perf_counter()
                resp = _sync_session.head("https://www.ticketlink.co.kr", timeout=3)
                t_recv = time.perf_counter()
                rtt = t_recv - t_send

                cur_date = resp.headers.get('Date', '')
                cur_second = cur_date.split(':')[-1].split(' ')[0] if ':' in cur_date else ''

                if cur_second != prev_second and prev_second:
                    # 초 경계 감지!
                    if rtt < rtt_threshold and last_rtt < rtt_threshold:
                        # 서버의 XX:YY.000 = 로컬 어디?
                        # last_t: 마지막 이전 초 요청 전송 시각
                        # t_send: 첫 다음 초 요청 전송 시각
                        boundary_local = (last_t + t_send) / 2 + (last_rtt + rtt) / 4

                        # 서버 시각 (정수 초)
                        server_dt = parsedate_to_datetime(cur_date)
                        server_boundary = server_dt.timestamp()  # XX:YY:SS.000

                        # perf_counter → time.time 변환
                        pc_now = time.perf_counter()
                        tt_now = time.time()
                        boundary_time_time = tt_now - (pc_now - boundary_local)

                        offset = server_boundary - boundary_time_time
                        offsets.append(offset)
                        boundaries_found += 1

                        gap_ms = (t_send - last_t) * 1000
                        print(f"  경계 #{boundaries_found}: offset={offset:+.4f}s "
                              f"(gap={gap_ms:.0f}ms rtt={rtt*1000:.0f}/{last_rtt*1000:.0f}ms)")

                    boundary_detected = True
                    break

                last_t = t_send
                last_rtt = rtt
                prev_second = cur_second

                # 다음 요청까지 대기 (35ms 간격 목표)
                elapsed = time.perf_counter() - t_send
                wait = 0.035 - elapsed
                if wait > 0:
                    time.sleep(wait)

            if not boundary_detected:
                # 2초 안에 경계 못 찾음 — 잠시 ��기 후 재시도
                time.sleep(0.1)

        except Exception as e:
            print(f"  경계 감지 오류: {e}")
            time.sleep(0.1)

    if not offsets:
        print("  정밀 동기화 실패! 대략적 동기화로 폴백")
        return get_server_time_offset_rough()

    offsets.sort()
    median_offset = offsets[len(offsets) // 2]
    spread = offsets[-1] - offsets[0]
    print(f"  정밀 동기화 완료: offset={median_offset:+.4f}s "
          f"(���위={spread*1000:.1f}ms, {len(offsets)}개 경계)")
    return median_offset


def server_now(offset):
    """서버 시간 기준 현재 시각"""
    return datetime.fromtimestamp(time.time() + offset)


# ==================== 메인 ====================
def wait_for_open_time():
    """오픈 시간까지 대기 (정밀 서버 시간 동기화)"""
    # 1단계: 대략적 동기화 (빠르게)
    print("  1단계: 대략적 시간 동기��...")
    rough_offset = get_server_time_offset_rough()
    print(f"  대략적 offset: {rough_offset:+.3f}초")

    today = server_now(rough_offset).strftime("%Y-%m-%d")
    target_dt = datetime.strptime(f"{today} {OPEN_TIME}", "%Y-%m-%d %H:%M:%S")
    target_ts = target_dt.timestamp()

    now = server_now(rough_offset)
    if now >= target_dt:
        print("  이미 오픈 시간이 지났습니다. 바로 시작합니다.")
        return

    wait_seconds = (target_dt - now).total_seconds()
    print(f"  {OPEN_TIME} 까지 {wait_seconds:.0f}초 대기")
    print(f"  (Ctrl+C로 대기 취소 후 바로 시작 가능)")

    try:
        # 30초 전까지 느긋하게 대기
        while (target_dt - server_now(rough_offset)).total_seconds() > 30:
            remaining = (target_dt - server_now(rough_offset)).total_seconds()
            print(f"\r  남은 시간: {remaining:.0f}초  ", end="", flush=True)
            time.sleep(1)
        print()

        # 2~3단계: 정밀 동기화 (오픈 25~15초 전)
        print("\n  2단계: 정밀 시간 동기화 (초 경계 감지)...")
        precise_offset = get_server_time_offset_precise(num_boundaries=7)
        improvement = abs(precise_offset - rough_offset) * 1000
        print(f"  대략→정밀 차이: {improvement:.1f}ms")

        # 정밀 offset으로 타겟 시각 재계산
        # AppleScript 오버헤드(~150ms)를 감안하여 일찍 시작
        # reload() 후 HTTP 요청이 서버에 도착하는 시점이 11:00:00 + 30ms가 되도록
        APPLESCRIPT_OVERHEAD = 0.150  # ~150ms
        SAFETY_MARGIN = 0.030        # +30ms (서버 처리 시간 마진)
        early_start = APPLESCRIPT_OVERHEAD - SAFETY_MARGIN  # 120ms 일찍

        target_perf = time.perf_counter() + (target_ts - (time.time() + precise_offset))
        reload_perf = target_perf - early_start  # 새로고침 발사 시점
        remaining = target_perf - time.perf_counter()
        print(f"\n  오픈까지 {remaining:.2f}초 (정밀 기준)")
        print(f"  새로고침 예정: 오픈 {early_start*1000:.0f}ms 전 발사 → 서버 도착 ~오픈+{SAFETY_MARGIN*1000:.0f}ms")

        # 스케줄 창 미리 찾아두기 (AppleScript 1회 절약)
        _pre_sw, _pre_st = find_schedule_window()
        if _pre_sw > 0:
            print(f"  스케줄 페이지 미리 확인: window {_pre_sw}, tab {_pre_st}")

        # 50ms 전까지 sleep
        while True:
            remaining = reload_perf - time.perf_counter()
            if remaining <= 0.05:
                break
            if remaining > 1:
                print(f"\r  남은 시간: {remaining:.1f}초  ", end="", flush=True)
                time.sleep(min(0.5, remaining - 0.05))
            else:
                time.sleep(0.001)
        print()

        # 마지막 50ms: spin-wait (perf_counter 기반)
        print("  spin-wait 진입...")
        while time.perf_counter() < reload_perf:
            pass

        overshoot = (time.perf_counter() - reload_perf) * 1000
        print(f"  새로고침 발사! (overshoot: {overshoot:.2f}ms)")

        # 즉시 새로고침 (스케줄 창을 미리 찾아뒀으므로 find 생략)
        if _pre_sw > 0:
            run_direct_js("location.reload();", _pre_sw, _pre_st)
            print(f"  reload 완료 → 서버 11:00:00 +{SAFETY_MARGIN*1000:.0f}ms 부근 도착 예상")

    except KeyboardInterrupt:
        print("\n  대기 취소! 바로 시작합니다.")


def run_full(skip_wait=False):
    """전체 플로우 실행"""
    global _log_t0, _log_t0_wall

    # ── Phase 0: 버튼 상태 확인 → 필요 시에만 대기+새로고침 ──
    print("\n" + "=" * 50)
    print("  Phase 0: 버튼 상태 확인")
    print("=" * 50)

    pre_check = phase1_click_reserve(do_reload=False)

    if pre_check == 'clicked':
        # 이미 "예매하기"(검정) → 대기/새로고침 불필요, 바로 진행
        print("  이미 오픈됨! 바로 예매 진행")
        t_start = time.time()
        _log_t0 = time.perf_counter()
        _log_t0_wall = datetime.now()
        tlog('run_start', mode='already_open')
        tlog('phase1_button_found', attempt=0)
        tlog('phase1_end')

    elif pre_check == 'not_open_yet':
        # "판매예정"(회색) → 오픈 시간 대기 + 새로고침
        print("  판매예정 상태 → 오픈 시간에 새로고침 필요")
        if not skip_wait:
            print("\n" + "=" * 50)
            print("  Phase 0: 오픈 시간 대기")
            print("=" * 50)
            wait_for_open_time()

        t_start = time.time()
        _log_t0 = time.perf_counter()
        _log_t0_wall = datetime.now()
        tlog('run_start', mode='after_wait')

        print("\n" + "=" * 50)
        print("  Phase 1: 예매하기 클릭 (새로고침)")
        print("=" * 50)
        tlog('phase1_start')

        for attempt in range(60):
            r = phase1_click_reserve(do_reload=True)
            if r == 'clicked':
                tlog('phase1_button_found', attempt=attempt, after_reload=True)
                break
            time.sleep(0.5)
        else:
            tlog('phase1_fail')
            print("  예매하기 버튼을 찾을 수 없습니다. 종료.")
            save_log()
            return
        tlog('phase1_end')

    else:
        # 버튼 자체를 못 찾음 (페이지 로딩 중이거나 날짜 불일치)
        if not skip_wait:
            print("  버튼 못 찾음. 오픈 시간 대기 후 재시도")
            print("\n" + "=" * 50)
            print("  Phase 0: 오픈 시간 대기")
            print("=" * 50)
            wait_for_open_time()

        t_start = time.time()
        _log_t0 = time.perf_counter()
        _log_t0_wall = datetime.now()
        tlog('run_start', mode='not_found_retry')

        print("\n" + "=" * 50)
        print("  Phase 1: 예매하기 클릭")
        print("=" * 50)
        tlog('phase1_start')

        for attempt in range(60):
            r = phase1_click_reserve(do_reload=(attempt == 0))
            if r == 'clicked':
                tlog('phase1_button_found', attempt=attempt)
                break
            time.sleep(0.05)
        else:
            tlog('phase1_fail')
            print("  예매하기 버튼을 찾을 수 없습니다. 종료.")
            save_log()
            return
        tlog('phase1_end')

    # ── Phase 1.5: 보안문자 ──
    print("\n" + "=" * 50)
    print("  Phase 1.5: 보안문자 확인")
    print("=" * 50)
    tlog('phase1_5_start')

    captcha_found = False
    for i in range(20):
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
                captcha_found = True
                break
        time.sleep(0.1)
        if not captcha_found and i >= 5:
            break

    tlog('phase1_5_captcha_detected', found=captcha_found)

    if captcha_found:
        print("  보안문자 발견! 자동 풀기 시도...")
        for cap_attempt in range(3):
            tlog('captcha_attempt', attempt=cap_attempt + 1)
            if solve_captcha():
                tlog('captcha_pass', attempt=cap_attempt + 1)
                break
            print(f"  캡차 재시도 {cap_attempt+1}...")
            time.sleep(1)
        else:
            tlog('captcha_fail')
            print("  캡차 자동 풀기 실패. 수동으로 입력하세요.")
            input("  입력 후 Enter...")
    else:
        print("  보안문자 없음, 계속 진행")
    tlog('phase1_5_end')

    # ── Phase 2: 등급/구역 선택 ──
    print("\n" + "=" * 50)
    print("  Phase 2: 등급/구역 선택")
    print("=" * 50)
    tlog('phase2_start')

    if not phase2_select_grade_and_section():
        tlog('phase2_fail')
        print("  등급/구역 선택 실패. 종료.")
        save_log()
        return
    tlog('phase2_grade_section_done')

    # 좌석 지도 로딩 대기
    print("  좌석 지도 로딩 대기...")
    tlog('phase2_canvas_wait_start')
    rw2, rt2 = find_ticketlink_window()
    if rw2 == 0:
        rw2, rt2 = find_any_ticketlink()
    for _ in range(40):
        has = _run_js("document.querySelectorAll('#main_view canvas').length;", rw2, rt2)
        if has and int(has) > 0:
            break
        time.sleep(0.05)
    time.sleep(0.1)
    tlog('phase2_canvas_loaded')

    cached_canvas = _get_canvas_region(rw2, rt2) or region
    print(f"  캔버스 위치: {cached_canvas}")
    tlog('phase2_canvas_region', region=cached_canvas)

    # 다음단계 버튼 좌표 미리 캐싱 (rw2, rt2 재사용)
    next_btn_pos = None
    if rw2 > 0:
        js_btn = '''
        (function() {
            var btns = document.querySelectorAll('button, a, input[type="button"]');
            for (var i = 0; i < btns.length; i++) {
                var t = (btns[i].innerText || btns[i].value || '').trim();
                if (t === '다음단계' || t === '다음 단계') {
                    var rect = btns[i].getBoundingClientRect();
                    if (rect.width > 0) {
                        var tb = window.outerHeight - window.innerHeight;
                        return JSON.stringify({
                            sx: Math.round(window.screenX + rect.left + rect.width/2),
                            sy: Math.round(window.screenY + tb + rect.top + rect.height/2)
                        });
                    }
                }
            }
            return 'not_found';
        })();
        '''
        result = run_direct_js(js_btn, rw2, rt2)
        if result and result != 'not_found':
            next_btn_pos = json.loads(result)
            print(f"  다음단계 버튼 위치 캐싱: ({next_btn_pos['sx']},{next_btn_pos['sy']})")
    tlog('phase2_end', next_btn_cached=next_btn_pos is not None)

    # ── Phase 3: 좌석 스캔 + 클릭 ──
    if ASSIST_MODE:
        print("\n" + "=" * 50)
        print("  Phase 3+4: 어시스트 모드 (좌석 1개 클릭하세요)")
        print("=" * 50)
        tlog('phase3_start', mode='assist')
        if not phase3_assist_mode():
            tlog('phase3_fail')
            print("  어시스트 실패. 수동으로 진행하세요.")
            save_log()
            return
    else:
        print("\n" + "=" * 50)
        print("  Phase 3: 좌석 스캔 + 클릭")
        print("=" * 50)
        tlog('phase3_start', mode='auto')
        for attempt in range(5):
            if phase3_scan_and_click(cached_region=cached_canvas):
                tlog('phase3_seats_clicked', attempt=attempt + 1)
                break
            print(f"  재스캔 {attempt+1}...")
            time.sleep(0.3)
        else:
            tlog('phase3_fail')
            print("  좌석을 찾을 수 없습니다. 수동으로 선택하세요.")
            save_log()
            return

    tlog('phase3_end')

    elapsed = time.time() - t_start
    tlog('run_end', total_sec=round(elapsed, 1))
    print(f"\n{'=' * 50}")
    print(f"  완료! 총 {elapsed:.1f}초")
    print(f"{'=' * 50}")
    save_log()


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
    print(f"  모드: {'어시스트 (1클릭→자동)' if ASSIST_MODE else '전자동'}")
    print()
    print("  사용법:")
    print("    python3 macro_full.py          # 오픈 시간 대기 → 전자동")
    print("    python3 macro_full.py --now     # 대기 없이 바로 시작")
    print("    python3 macro_full.py --cancel  # 취소표 자동 잡기")
    print("    python3 macro_full.py --sync    # 정밀 시간 동기화 테스트")
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

    if len(sys.argv) > 1 and sys.argv[1] == "--sync":
        print("=" * 50)
        print("  정밀 시간 동기화 테스트")
        print("=" * 50)
        print()
        print("  1단계: 대략적 동기화...")
        rough = get_server_time_offset_rough()
        print(f"  대략적 offset: {rough:+.4f}초")
        print()
        print("  2단계: 정밀 동기화 (초 경계 감지)...")
        precise = get_server_time_offset_precise(num_boundaries=7)
        print()
        print(f"  대략적 offset: {rough:+.4f}초 (±500ms)")
        print(f"  정밀 offset:   {precise:+.4f}초 (±5-10ms)")
        print(f"  차이:          {abs(precise - rough)*1000:.1f}ms")
        print()
        server_time = datetime.fromtimestamp(time.time() + precise)
        local_time = datetime.now()
        print(f"  로컬 시각:  {local_time.strftime('%H:%M:%S.%f')[:-3]}")
        print(f"  서버 시각:  {server_time.strftime('%H:%M:%S.%f')[:-3]}")
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "--cancel":
        print("=" * 50)
        print("  취소표 자동 잡기 모드")
        print("=" * 50)
        print(f"  대상: {GRADE_NAME} {TARGET_SECTION}구역")
        print(f"  필요 좌석: {SEAT_COUNT}자리")
        print()
        print("  1) 스케줄 페이지에서 예매하기 → 캡차 통과까지 자동 진행")
        print("  2) 등급 선택 후 타겟 구역 잔여석 polling")
        print(f"  3) {SEAT_COUNT}석 이상 풀리면 자동 진입")
        print()
        input("  Enter를 누르면 시작...")

        t_start = time.time()

        # Phase 1: 예매하기 클릭
        print("\n── Phase 1: 예매하기 클릭 ──")
        if phase1_click_reserve() != 'clicked':
            print("  예매하기 실패!")
            sys.exit(1)
        time.sleep(0.3)

        # Phase 1.5: 캡차
        print("\n── Phase 1.5: 보안문자 ──")
        captcha_found = False
        for i in range(20):
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
                    captcha_found = True
                    break
            time.sleep(0.1)
            if not captcha_found and i >= 5:
                break
        if captcha_found:
            print("  보안문자 발견! 풀기 시도...")
            for cap_attempt in range(3):
                if solve_captcha():
                    break
                print(f"  재시도 {cap_attempt+1}...")
                time.sleep(1)
            else:
                print("  캡차 실패. 수동으로 입력하세요.")
                input("  입력 후 Enter...")
        else:
            print("  보안문자 없음")

        # Phase 2: 등급 선택까지만
        print("\n── Phase 2: 등급 선택 ──")
        rw, rt = 0, 0
        sw, st = find_schedule_window()
        if sw > 0:
            for attempt in range(60):
                url = _run_js("location.href;", sw, st)
                if "reserve/plan/schedule" in url:
                    rw, rt = sw, st
                    break
                time.sleep(0.05)
        if rw == 0:
            for attempt in range(60):
                _refresh_tab_cache(force=True)
                rw, rt = find_ticketlink_window()
                if rw > 0:
                    break
                time.sleep(0.05)
        if rw == 0:
            print("  좌석 선택 페이지를 찾을 수 없습니다!")
            sys.exit(1)
        print(f"  좌석 선택 페이지: window {rw}, tab {rt}")

        # 등급 로딩 + 클릭
        js_grade = f'''
        (function() {{
            var grades = document.querySelectorAll('[ng-click*="select.select"]');
            for (var i = 0; i < grades.length; i++) {{
                if (grades[i].innerText.indexOf('{GRADE_NAME}') > -1) {{
                    grades[i].click();
                    return 'grade_clicked:' + grades[i].innerText.substring(0,30).replace(/\\n/g,' ');
                }}
            }}
            return 'grade_not_found:count=' + grades.length;
        }})();
        '''
        for _ in range(60):
            result = run_direct_js(js_grade, rw, rt)
            if result.startswith("grade_clicked"):
                break
            time.sleep(0.05)
        else:
            print("  등급 선택 실패!")
            sys.exit(1)
        print(f"  {result}")

        # 취소표 polling 시작
        print(f"\n── 취소표 대기 중 ({TARGET_SECTION}구역, {SEAT_COUNT}석 이상) ──")
        print("  Ctrl+C로 중단")
        js_check = f'''
        (function() {{
            var zones = document.querySelectorAll('[ng-click*="grade.select"]');
            for (var i = 0; i < zones.length; i++) {{
                var text = zones[i].innerText;
                if (text.indexOf('{TARGET_SECTION}구역') > -1) {{
                    var match = text.match(/(\\d+)\\s*석/);
                    return match ? match[1] : '0';
                }}
            }}
            return '0';
        }})();
        '''
        poll_count = 0
        try:
            while True:
                seats_str = run_direct_js(js_check, rw, rt)
                try:
                    seats = int(seats_str)
                except:
                    seats = 0
                poll_count += 1
                now_str = datetime.now().strftime("%H:%M:%S")
                print(f"\r  [{now_str}] {TARGET_SECTION}구역: {seats}석 (polling #{poll_count})  ", end="", flush=True)

                if seats >= SEAT_COUNT:
                    print(f"\n\n  취소표 발견! {seats}석!")
                    # 구역 클릭 + 좌석 스캔 + 다음단계
                    js_section = f'''
                    (function() {{
                        var zones = document.querySelectorAll('[ng-click*="grade.select"]');
                        for (var i = 0; i < zones.length; i++) {{
                            var text = zones[i].innerText;
                            if (text.indexOf('{TARGET_SECTION}구역') > -1) {{
                                zones[i].click();
                                return 'section_clicked:' + text.trim().replace(/\\n/g, ' ');
                            }}
                        }}
                        return 'not_found';
                    }})();
                    '''
                    sec_result = run_direct_js(js_section, rw, rt)
                    print(f"  구역 선택: {sec_result}")

                    # 좌석 지도 로딩 대기
                    print("  좌석 지도 로딩 대기...")
                    for _ in range(40):
                        has = _run_js("document.querySelectorAll('#main_view canvas').length;", rw, rt)
                        if has and int(has) > 0:
                            break
                        time.sleep(0.05)
                    time.sleep(0.3)

                    cached_canvas = _get_canvas_region(rw, rt) or region
                    print(f"  캔버스 위치: {cached_canvas}")

                    # 좌석 스캔 + 클릭
                    print("\n── 좌석 스캔 + 클릭 ──")
                    for attempt in range(5):
                        if phase3_scan_and_click(cached_region=cached_canvas):
                            break
                        print(f"  재스캔 {attempt+1}...")
                        time.sleep(0.3)
                    else:
                        print("  좌석을 찾을 수 없습니다.")

                    elapsed = time.time() - t_start
                    print(f"\n  완료! 총 {elapsed:.1f}초 (polling {poll_count}회)")
                    break

                time.sleep(2)  # 2초 간격 polling (너무 빠르면 차단 위험)
        except KeyboardInterrupt:
            print(f"\n\n  중단됨 (polling {poll_count}회)")
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "--captcha":
        print("  --captcha: 보안문자 풀기만 실행")
        print("  캡차가 표시된 티켓링크 페이지를 Chrome에 열어두세요.")
        print()
        input("  Enter를 누르면 캡차 풀기 시작...")
        solve_captcha()
        sys.exit(0)

    if "--now" in sys.argv:
        print("  --now: 대기 없이 바로 시작!")
        run_full(skip_wait=True)
    else:
        input("  Enter를 누르면 오픈 시간 대기 시작...")
        run_full()
