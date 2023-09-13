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


image_count = 0
def image_processing():
    global image_count
    image =cv2.imread('screenshot.png')
# Enlarge the image by a factor of 2 (for example)
    scale_factor = 2.0
    enlarged_image = cv2.resize(image, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_LINEAR)
    
    # Convert the enlarged image to grayscale
    gray = cv2.cvtColor(enlarged_image, cv2.COLOR_BGR2GRAY)
    
    _, thresholded_image = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    filename = f'grayscale_image/gray{image_count}.png'
    
    cv2.imwrite(filename,gray)
    image_count+=1
# Perform OCR on the image
    text = pytesseract.image_to_string(gray)
    text = text.replace(",", "").replace(".", "")
# Print the OCR result
    
    test_list = text.split("\n")
    while "" in test_list:
        test_list.remove("")
    
    print(test_list)
    return test_list

def STR(test_list):
    count = 0
    found = False
    for i, potential_line in enumerate(test_list):
        # Test for temporary
        if count == 2:
            found = True
            print("found, break loop")
            break
        if "STR" in potential_line:
            count +=1
            print("STR=", count)  
    return found

def DEX(test_list):
    # Similar to STR function but for "DEX"
    pass
    
def switch(potential, test_list):
    if potential == "STR":
        return STR(test_list)
    elif potential == "DEX":
        return DEX(test_list)

    
output_lines = ''
line_count = 0
found = False
potential = input('Enter your desired 3 line stats, e.g: STR, DEX, INT, LUK, ATT, MATT: ')
while True:
    
    
    locate_potentail_redcube()
    test_list = image_processing()
    found = switch(potential, test_list)

    with open('D:/easymaple/output.txt', 'w') as file:
        output_lines += f'gray{image_count-1}' + ' ' + ', '.join(test_list) + '\n'
        file.write(output_lines)
                
    if found:
        break
        
    time.sleep(5)
   

    
