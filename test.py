import cv2
import numpy as np
from PIL import Image
import pytesseract
import time
import pygetwindow as gw
import pyautogui
from PIL import Image

# find the coordinate of the window of maplestory 
# screen shot the rectangle part we need
try:
    window = gw.getWindowsWithTitle('MapleStory')[0]
except IndexError:
    print("MapleStory not found")
    exit()

def locate_potentail_redcube():
    x,y =window.left,window.top
    x1, y1 = x + 750, y + 570
    rect_width = 220
    rect_height = 60
    screenshot = pyautogui.screenshot(region=(x1, y1,rect_width, rect_height))
    screenshot.save('screenshot.png')

def image_processing():
# Load the image using OpenCV
    image = cv2.imread('screenshot.png')
# Convert the image to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    


    _, thresholded_image = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cv2.imwrite('gray.png',thresholded_image)
# Perform OCR on the image
    text = pytesseract.image_to_string(thresholded_image)
    text = text.replace(",", "").replace(".", "")
# Print the OCR result
    
    test_list = text.split("\n")
    while "" in test_list:
        test_list.remove("")
    
    print(test_list)
    return test_list
while True:
    locate_potentail_redcube()
    test_list = image_processing()
    

    found = False
    count = 0
    for i,potential_line in enumerate(test_list):
        if count == 2:
            break
            print("found 2 matt,break loop")
        if "Magic ATT" in potential_line:
            count +=1
            print("matt=",count)
            
    if found:
        break

    time.sleep(5) 
    
