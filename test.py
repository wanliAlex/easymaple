import pygetwindow as gw

window = gw.getWindowsWithTitle("MapleStory")[0]
anchor = tuple(window.topleft)
print(anchor)