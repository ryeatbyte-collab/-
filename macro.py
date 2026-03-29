### macro.py — 응원단석 연속 3자리 자동 선택 매크로 (Mac)
from pynput import keyboard, mouse
import pyautogui
import numpy as np
from collections import defaultdict
import time
import threading
import subprocess

# ------------------- 설정 -------------------
# 좌석 색상 (RGB)
target_color = (68, 87, 101)   # 빈 좌석 (진한 파란/회색)
tolerance = 15

# 연속 좌석 수
seat_count = 3

# 좌석 크기 (픽셀)
min_seat_size = 6
max_seat_size = 25

# 고정 좌표 (구역 클릭 후 초기 상태 기준)
region = (273, 416, 188, 389)       # 좌석 지도 영역 (x, y, w, h)
next_button_pos = (839, 866)        # 다음단계 버튼

# ------------------- Retina 스케일 팩터 -------------------
def get_scale_factor():
    try:
        ss = pyautogui.screenshot(region=(0, 0, 1, 1))
        return ss.size[0]
    except Exception:
        return 2.0

SCALE = get_scale_factor()

# ------------------- 핵심 로직 -------------------
mouse_controller = mouse.Controller()

def click_at(x, y):
    mouse_controller.position = (x, y)
    time.sleep(0.05)
    mouse_controller.click(mouse.Button.left, 1)

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

                seats.append({
                    'cx': cx, 'cy': cy,
                    'w': sw, 'h': sh,
                    'pixels': len(pixels)
                })

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


def run_macro():
    """스캔 → 연속 3자리 클릭 → 다음단계"""
    print(f"\n스캔 중... region={region}")
    screenshot = pyautogui.screenshot(region=region)
    img = np.array(screenshot.convert("RGB"))

    seats = find_seats(img)
    print(f"발견된 좌석: {len(seats)}개")

    if not seats:
        print("빈 좌석을 찾지 못했습니다.")
        return

    consecutive = find_consecutive_seats(seats, seat_count)
    selected = False

    if consecutive:
        print(f"\n연속 {seat_count}자리 발견!")
        for i, seat in enumerate(consecutive):
            real_x = region[0] + seat['cx'] / SCALE
            real_y = region[1] + seat['cy'] / SCALE
            click_at(real_x, real_y)
            print(f"  좌석 {i+1} 클릭: ({real_x:.0f}, {real_y:.0f})")
            time.sleep(0.1)
        selected = True
    else:
        print(f"연속 {seat_count}자리를 찾지 못했습니다.")
        if len(seats) >= seat_count:
            print(f"대신 가장 가까운 {seat_count}자리 선택...")
            seats.sort(key=lambda s: (s['cy'], s['cx']))
            for i in range(seat_count):
                real_x = region[0] + seats[i]['cx'] / SCALE
                real_y = region[1] + seats[i]['cy'] / SCALE
                click_at(real_x, real_y)
                print(f"  좌석 {i+1} 클릭: ({real_x:.0f}, {real_y:.0f})")
                time.sleep(0.1)
            selected = True

    if selected:
        print("다음단계 클릭...")
        time.sleep(1.0)
        # AppleScript로 Chrome에서 JavaScript 실행 (다음단계 버튼 클릭)
        subprocess.run([
            "osascript", "-e",
            'tell application "Google Chrome" to execute front window\'s active tab javascript "document.querySelector(\'a.btn.btn_full.ng-binding\').click()"'
        ], capture_output=True)
        print("  다음단계 (JS 클릭)")


# ------------------- 단축키 -------------------
def on_press(key):
    try:
        if key == keyboard.Key.alt:
            print("\n=== option 키 → 매크로 실행 ===")
            t = threading.Thread(target=run_macro, daemon=True)
            t.start()
    except Exception as e:
        print("오류:", e)

print("=" * 45)
print("  응원단석 연속 3자리 자동 선택 매크로")
print("=" * 45)
print(f"  좌석 영역: {region}")
print(f"  다음단계: {next_button_pos}")
print(f"  스케일: {SCALE}x")
print()
print("  구역 클릭 후 지도 움직이지 말고")
print("  option 키 → 바로 실행!")
print()
print("  Ctrl+C로 종료")
print("=" * 45)

with keyboard.Listener(on_press=on_press) as listener:
    listener.join()
