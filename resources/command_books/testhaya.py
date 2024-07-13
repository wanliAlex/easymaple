import cv2
import pytesseract
import pyautogui
import pygetwindow as gw

class GameImageProcessor:
    def __init__(self, window_title="MapleStory"):
        self.window = self.locate_window(window_title)
    
    def locate_window(self, window_title):
        try:
            window = gw.getWindowsWithTitle(window_title)[0]
            return window
        except IndexError:
            print(f"Window titled '{window_title}' not found")
            exit()

    def find_hayato_se(self):
        x, y, w, h = self.window.left, self.window.top, self.window.width, self.window.height
        screenshot = pyautogui.screenshot(region=(x, y, w, h))
        screenshot.save("maplewindow.png")
        
        game_screenshot = cv2.imread("maplewindow.png")
        template_tl = cv2.imread('tl_hayato.png', 0)
        template_br = cv2.imread('br_hayato.png', 0)

        game_gray = cv2.cvtColor(game_screenshot, cv2.COLOR_BGR2GRAY)

        res_tl = cv2.matchTemplate(game_gray, template_tl, cv2.TM_CCOEFF_NORMED)
        res_br = cv2.matchTemplate(game_gray, template_br, cv2.TM_CCOEFF_NORMED)
        
        _, _, _, max_loc_tl = cv2.minMaxLoc(res_tl)
        _, _, _, max_loc_br = cv2.minMaxLoc(res_br)
        top_left = max_loc_tl
        bottom_right = (max_loc_br[0] + template_br.shape[1], max_loc_br[1] + template_br.shape[0])
        
        top_left1 = (top_left[0] + 38, top_left[1] + 56)
        bottom_right1 = (bottom_right[0] - 80, bottom_right[1] - 10)
        
        matched_region = game_screenshot[top_left1[1]:bottom_right1[1], top_left1[0]:bottom_right1[0]]
        
        # Resize and threshold the image to enhance OCR accuracy
        scale_factor = 4
        enlarged_image = cv2.resize(matched_region, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_LINEAR)
        gray = cv2.cvtColor(enlarged_image, cv2.COLOR_BGR2GRAY)
        _, processed_image = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Use Tesseract to extract text, with configuration for OCR processing
        text = pytesseract.image_to_string(processed_image, config='--psm 6')

        cv2.imwrite('hayato_SE.png', processed_image)
        return int(text)

# Example usage
processor = GameImageProcessor()
hayato_se_value = processor.find_hayato_se()
print(hayato_se_value)
