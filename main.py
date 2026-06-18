import sys
import os

try:
    from PyQt5.QtWidgets import QApplication
except ImportError:
    print("错误：需要安装 PyQt5，运行：pip install PyQt5")
    sys.exit(1)

from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("屏幕录制与标注工具")
    app.setOrganizationName("ScreenRecorder")
    
    try:
        app.setStyle("Fusion")
    except Exception:
        pass

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
