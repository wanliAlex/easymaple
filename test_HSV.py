import cv2
from matplotlib import pyplot as plt

# 读取图像
image = cv2.imread('screenshot.png')

# 转换到 HSV
hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

# 分割成 H, S 和 V 通道
h, s, v = cv2.split(hsv_image)

# 转换到 Grayscale
gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

# 显示原图像和各个通道的图像
plt.subplot(2, 3, 1)
plt.imshow(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
plt.title('Original Image')

plt.subplot(2, 3, 2)
plt.imshow(h, cmap='gray')
plt.title('H Channel')

plt.subplot(2, 3, 3)
plt.imshow(s, cmap='gray')
plt.title('S Channel')

plt.subplot(2, 3, 4)
plt.imshow(v, cmap='gray')
plt.title('V Channel')

plt.subplot(2, 3, 5)
plt.imshow(gray_image, cmap='gray')
plt.title('Grayscale Image')

plt.show()
