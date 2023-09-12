import cv2
from matplotlib import pyplot as plt

# 读取图像
image = cv2.imread('screenshot.png')

# Get the dimensions of the image
height, width = image.shape[:2]

# Double the DPI (this will quadruple the number of pixels)
new_width = int(width * 2)
new_height = int(height * 2)

# Resize the image
image_high_res = cv2.resize(image, (new_width, new_height), interpolation = cv2.INTER_AREA)

# ... (continue with your existing code but replace "image" with "image_high_res")

# At the end of your script, save the high-resolution plot with a high DPI value
plt.savefig('high_res_output.png', dpi=300)
