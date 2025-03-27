import time
import numpy as np
import mss
from skimage import color, filters
import screen_brightness_control as sbc
import win32gui
import win32ui
import win32con

# ===== CONFIGURATION =====
MONITOR = {"top": 0, "left": 0, "width": 800, "height": 600}  # Adjust to your screen size
SAFE_BRIGHTNESS = 25
BLUR_STRENGTH = 8
FLICKER_THRESHOLD = 20  # Minimum brightness change to consider
FLICKER_FREQUENCY = 3   # Hz - minimum flicker rate to trigger protection
ANALYSIS_WINDOW = 0.5   # Seconds to analyze for flicker patterns
COOLDOWN_SEC = 1.0      # How long to maintain safety after last flicker
UPDATE_RATE = 1/60      # 60 FPS for better detection

# ===== FLICKER DETECTION IMPROVEMENTS =====
class FlickerDetector:
    def __init__(self):
        self.frame_history = []
        self.brightness_history = []
        self.last_flicker_time = 0
        self.safety_active = False
    
    def analyze_frame(self, frame):
        # Convert to grayscale and calculate average brightness
        grey = color.rgb2gray(frame)
        brightness = np.mean(grey) * 255
        
        # Maintain a rolling window of brightness values
        current_time = time.time()
        self.brightness_history.append((current_time, brightness))
        
        # Remove old entries
        self.brightness_history = [
            (t, b) for t, b in self.brightness_history 
            if current_time - t <= ANALYSIS_WINDOW
        ]
        
        # Need enough data to analyze
        if len(self.brightness_history) < 5:
            return False
        
        # Calculate brightness differences
        diffs = []
        timestamps = []
        for i in range(1, len(self.brightness_history)):
            t1, b1 = self.brightness_history[i-1]
            t2, b2 = self.brightness_history[i]
            diffs.append(abs(b2 - b1))
            timestamps.append(t1)
        
        # Count significant brightness changes
        significant_changes = sum(1 for d in diffs if d > FLICKER_THRESHOLD)
        
        # Calculate frequency if we have enough changes
        if significant_changes >= 3:
            time_span = timestamps[-1] - timestamps[0]
            frequency = significant_changes / time_span
            return frequency >= FLICKER_FREQUENCY
        
        return False

# ===== DIRECTX OVERLAY (unchanged) =====
class GreyFilterOverlay:
    def __init__(self):
        self.hwnd = win32gui.GetDesktopWindow()
        self.hdc = win32gui.GetWindowDC(self.hwnd)
        self.mfc = win32ui.CreateDCFromHandle(self.hdc)
        self.save_dc = self.mfc.CreateCompatibleDC()
        self.bitmap = win32ui.CreateBitmap()
        self.bitmap.CreateCompatibleBitmap(self.mfc, MONITOR['width'], MONITOR['height'])
        self.save_dc.SelectObject(self.bitmap)
        self.active = False
    
    def apply_filter(self, frame):
        if frame.shape[2] == 4:
            frame = frame[:, :, :3]
        grey = color.rgb2gray(frame) * 255
        blurred = filters.gaussian(grey, sigma=BLUR_STRENGTH)
        return np.dstack([blurred]*3).astype(np.uint8)
    
    def update(self, frame):
        try:
            processed = self.apply_filter(frame)
            temp_bitmap = win32ui.CreateBitmap()
            temp_bitmap.CreateCompatibleBitmap(self.mfc, MONITOR['width'], MONITOR['height'])
            bgr_frame = np.ascontiguousarray(processed[:, :, ::-1])
            temp_bitmap.SetBitmapBits(bgr_frame.tobytes())
            self.save_dc.SelectObject(temp_bitmap)
            self.mfc.BitBlt(
                (MONITOR['left'], MONITOR['top']),
                (MONITOR['width'], MONITOR['height']),
                self.save_dc,
                (0, 0),
                win32con.SRCCOPY
            )
            win32gui.DeleteObject(temp_bitmap.GetHandle())
            self.active = True
        except Exception as e:
            print(f"Overlay update error: {str(e)}")
            self.clear()
    
    def clear(self):
        if self.active:
            self.mfc.BitBlt(
                (MONITOR['left'], MONITOR['top']),
                (MONITOR['width'], MONITOR['height']),
                self.save_dc,
                (0, 0),
                win32con.BLACKNESS
            )
            self.active = False
    
    def __del__(self):
        self.clear()
        win32gui.DeleteObject(self.bitmap.GetHandle())
        self.save_dc.DeleteDC()
        self.mfc.DeleteDC()
        win32gui.ReleaseDC(self.hwnd, self.hdc)

# ===== MAIN APPLICATION =====
def main():
    overlay = GreyFilterOverlay()
    detector = FlickerDetector()
    sct = mss.mss()
    
    print("=== Improved Epilepsy Protection ===")
    print(f"Monitoring: {MONITOR['width']}x{MONITOR['height']} area")
    print("Press Ctrl+C to exit...")
    
    try:
        while True:
            frame = np.array(sct.grab(MONITOR))[:, :, :3]
            
            # Improved flicker detection
            flicker_detected = detector.analyze_frame(frame)
            
            # Manage safety state
            if flicker_detected:
                if not detector.safety_active:
                    sbc.set_brightness(SAFE_BRIGHTNESS)
                    print("⚠️ Flicker detected! Applying protective measures")
                detector.safety_active = True
                detector.last_flicker_time = time.time()
                overlay.update(frame)
            elif detector.safety_active and (time.time() - detector.last_flicker_time > COOLDOWN_SEC):
                sbc.set_brightness(100)
                detector.safety_active = False
                overlay.clear()
                print("✅ Normal display restored")
            
            time.sleep(UPDATE_RATE)
            
    except KeyboardInterrupt:
        overlay.clear()
        sbc.set_brightness(100)
        print("\nProtection disabled")

if __name__ == "__main__":
    main()