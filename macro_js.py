### macro_js.py — 티켓링크 예매 매크로 (Chrome JS 제어 방식)
### 기존 macro.py(픽셀 기반)과 별개. 좌석 선택은 canvas 클릭, 나머지는 JS로 처리.
import subprocess
import time
import json
from pynput import keyboard, mouse
import pyautogui
import numpy as np
from collections import defaultdict
import threading

# ------------------- 설정 -------------------
target_color = (68, 87, 101)
tolerance = 15
seat_count = 3
min_seat_size = 6
max_seat_size = 25
region = (273, 416, 188, 389)

# ------------------- Retina 스케일 팩터 -------------------
def get_scale_factor():
    try:
        ss = pyautogui.screenshot(region=(0, 0, 1, 1))
        return ss.size[0]
    except Exception:
        return 2.0

SCALE = get_scale_factor()  # pyautogui가 논리좌표 반환하면 1, Retina면 2

# ------------------- Chrome JS 실행 -------------------
import tempfile
import base64

def _run_applescript_js(browser_js):
    """AppleScript를 임시 파일로 작성해서 실행 (따옴표 문제 완전 회피)"""
    # browser_js 안의 따옴표를 AppleScript 이스케이핑
    escaped_js = browser_js.replace('\\', '\\\\').replace('"', '\\"')
    applescript = f'''
tell application "Google Chrome"
    execute tab 1 of window 2 javascript "{escaped_js}"
end tell
'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.scpt', delete=False) as f:
        f.write(applescript)
        f.flush()
        result = subprocess.run(
            ["osascript", f.name],
            capture_output=True, text=True, timeout=10
        )
        import os
        os.unlink(f.name)
    return result.stdout.strip() if result.stdout.strip() else result.stderr.strip()


def run_js_in_page(js_code):
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
    return _run_applescript_js(browser_js)


def run_js_simple(js_code):
    """페이지 컨텍스트에서 JS 실행 (결과 반환 필요 없음)"""
    b64 = base64.b64encode(js_code.encode()).decode()
    browser_js = (
        "var s=document.createElement('script');"
        "s.textContent=atob('" + b64 + "');"
        "document.body.appendChild(s);"
        "document.body.removeChild(s);"
        "'ok';"
    )
    return _run_applescript_js(browser_js)


# ------------------- 좌석 탐색 (기존 픽셀 방식 유지) -------------------
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
                cx = (min(xs) + max(xs)) // 2
                cy = (min(ys) + max(ys)) // 2
                sw = max(xs) - min(xs) + 1
                sh = max(ys) - min(ys) + 1
                if sw > max_seat_size * 2 or sh > max_seat_size * 2:
                    continue
                seats.append({'cx': cx, 'cy': cy, 'w': sw, 'h': sh, 'pixels': len(pixels)})
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


# ------------------- 클릭 -------------------
mouse_controller = mouse.Controller()

def click_at(x, y):
    mouse_controller.position = (x - 5, y)  # 살짝 옆에서
    time.sleep(0.02)
    mouse_controller.position = (x, y)       # 정확한 위치로 이동
    time.sleep(0.08)
    mouse_controller.press(mouse.Button.left)
    time.sleep(0.02)
    mouse_controller.release(mouse.Button.left)


# ------------------- 상태 확인 -------------------
def check_seat_state():
    """선택된 좌석 수 확인"""
    js = '''try {
        var d = JSON.stringify({hasSeats: tk.state.select.hasSelectedSeats, count: tk.state.select.selectedSeats ? tk.state.select.selectedSeats.length : 0});
        document.getElementById("__mr").setAttribute("data-r", d);
    } catch(e) {
        document.getElementById("__mr").setAttribute("data-r", JSON.stringify({error: e.message}));
    }'''
    result = run_js_in_page(js)
    try:
        return json.loads(result)
    except:
        return {"hasSeats": False, "count": 0, "raw": result}


def click_next_step():
    """다음단계 (JS로 실행)"""
    run_js_simple("tk.state.view.nextStep();")


# ------------------- 메인 매크로 -------------------
def run_macro():
    print(f"\n스캔 중... region={region}")
    screenshot = pyautogui.screenshot(region=region)
    img = np.array(screenshot.convert("RGB"))

    seats = find_seats(img)
    print(f"발견된 좌석: {len(seats)}개")

    if not seats:
        print("빈 좌석을 찾지 못했습니다.")
        return

    consecutive = find_consecutive_seats(seats, seat_count)
    to_click = None

    if consecutive:
        print(f"\n연속 {seat_count}자리 발견!")
        to_click = consecutive
    elif len(seats) >= seat_count:
        print(f"연속 좌석 없음. 가장 가까운 {seat_count}자리 선택...")
        seats.sort(key=lambda s: (s['cy'], s['cx']))
        to_click = seats[:seat_count]

    if to_click:
        for i, seat in enumerate(to_click):
            real_x = region[0] + seat['cx'] / SCALE
            real_y = region[1] + seat['cy'] / SCALE
            click_at(real_x, real_y)
            print(f"  좌석 {i+1} 클릭: ({real_x:.0f}, {real_y:.0f})")
            time.sleep(0.2)

        print("\n좌석 선택 완료! 다음단계를 클릭하세요.")


# ------------------- 단축키 -------------------
def on_press(key):
    try:
        if key == keyboard.Key.alt:
            print("\n=== option 키 → 매크로 실행 ===")
            t = threading.Thread(target=run_macro, daemon=True)
            t.start()
    except Exception as e:
        print("오류:", e)

print("=" * 50)
print("  티켓링크 예매 매크로 (JS 제어 방식)")
print("=" * 50)
print(f"  좌석 영역: {region}")
print(f"  스케일: {SCALE}x")
print(f"  연속 좌석: {seat_count}자리")
print()
print("  구역 클릭 후 지도 안 움직이고")
print("  option 키 → 좌석 선택 → 다음단계 자동!")
print()
print("  Ctrl+C로 종료")
print("=" * 50)

with keyboard.Listener(on_press=on_press) as listener:
    listener.join()
