### coord_picker.py — 좌표 측정 도구
from pynput import mouse

saved_points = []

def on_click(x, y, button, pressed):
    if pressed:
        saved_points.append((x, y))
        print(f"클릭 위치: ({x}, {y})")

        if len(saved_points) == 2:
            x1, y1 = saved_points[0]
            x2, y2 = saved_points[1]
            region = (x1, y1, x2 - x1, y2 - y1)
            print(f"\nregion = {region}")
            print("이 값을 macro.py의 region에 넣으세요.")

        if len(saved_points) == 3:
            x3, y3 = saved_points[2]
            print(f"\nconfirm_button = ({x3}, {y3})")
            print("이 값을 macro.py의 confirm_button에 넣으세요.")

print("1번째 클릭: 좌석 영역 좌상단")
print("2번째 클릭: 좌석 영역 우하단")
print("3번째 클릭: 좌석선택완료 버튼")
print("Ctrl+C로 종료\n")

with mouse.Listener(on_click=on_click) as listener:
    listener.join()
