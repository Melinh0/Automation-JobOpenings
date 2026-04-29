import pyautogui
import time

print("Posicione o mouse. A posição será capturada em 3 segundos...")
time.sleep(3)
x, y = pyautogui.position()
print(f"Posição: ({x}, {y})")