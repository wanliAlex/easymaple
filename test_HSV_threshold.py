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


# 对 H, S, V 通道应用 Otsu's 二值化
_, h_thresh = cv2.threshold(h, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
_, s_thresh = cv2.threshold(s, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
_, v_thresh = cv2.threshold(v, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
_, g_thresh = cv2.threshold(gray_image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

# 显示原图像和三个通道的图像
plt.subplot(2, 3, 1)
plt.imshow(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
plt.title('Original Image')

plt.subplot(2, 3, 2)
plt.imshow(h_thresh, cmap='gray')
plt.title('H Channel (Thresholded)')

plt.subplot(2, 3, 3)
plt.imshow(s_thresh, cmap='gray')
plt.title('S Channel (Thresholded)')

plt.subplot(2, 3, 4)
plt.imshow(v_thresh, cmap='gray')
plt.title('V Channel (Thresholded)')


plt.subplot(2, 3, 5)
plt.imshow(g_thresh, cmap='gray')
plt.title('Grayscale Image')

plt.show()
