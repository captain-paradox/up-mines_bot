import pyautogui
import time

# Coordinates offset for movement (in pixels)
move_offset = 50

# Loop to move cursor every 2 seconds
try:
    while True:
        # Get current position
        x, y = pyautogui.position()
        
        # Move to a new position
        pyautogui.moveTo(x + move_offset, y + move_offset, duration=0.2)
        time.sleep(2)

        pyautogui.moveTo(x, y, duration=0.2)
        time.sleep(2)

except KeyboardInterrupt:
    print("Stopped by user.")
