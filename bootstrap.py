import os
import sys

# 경로 정의
if getattr(sys, 'frozen', False):
    # PyInstaller로 패키징된 경우
    BASE = os.path.dirname(sys.executable)
    # 임시 압축 해제 폴더 (_MEIPASS)
    BUNDLE_DIR = sys._MEIPASS
else:
    # 개발 환경
    BASE = os.path.abspath(os.path.dirname(__file__))
    BUNDLE_DIR = BASE

USER_DATA = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "PixAI-Gen-Bot", "playwright_user_data")
FLAG_FILE = os.path.join(USER_DATA, '.setup_complete')

def is_chromium_installed():
    """Checks if Chromium is installed in the ms-playwright directory."""
    playwright_browsers_path = os.path.join(os.path.expanduser("~"), "AppData", "Local", "ms-playwright")
    if not os.path.isdir(playwright_browsers_path):
        return False
    for item in os.listdir(playwright_browsers_path):
        if item.startswith("chromium-") and os.path.isdir(os.path.join(playwright_browsers_path, item)):
            return True
    return False

def launch_module(module_name):
    """지정된 모듈을 직접 import하여 실행합니다."""
    print(f"Launching {module_name}...")
    
    # PyInstaller 환경에서는 sys.path에 번들 디렉토리 추가
    if BUNDLE_DIR not in sys.path:
        sys.path.insert(0, BUNDLE_DIR)
    
    try:
        if module_name == "gui":
            import gui
            app = gui.App()
            app.mainloop()
        elif module_name == "setup_wizard":
            import setup_wizard
            wizard = setup_wizard.SetupWizard()
            wizard.mainloop()
        else:
            print(f"알 수 없는 모듈: {module_name}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"모듈 실행 중 오류 발생: {e}", file=sys.stderr)
        # Tkinter 오류 메시지 박스
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("실행 오류", f"프로그램 실행 중 오류가 발생했습니다:\n{e}")
            root.destroy()
        except ImportError:
            pass
        sys.exit(1)

if __name__ == "__main__":
    # chdir을 bootstrap에서 한 번만 수행
    os.chdir(BASE)
    
    if is_chromium_installed():
        launch_module("gui")
    else:
        if not is_chromium_installed():
            print("Chromium 브라우저가 설치되어 있지 않습니다. 설정 마법사를 시작합니다...")
        else:
            print("Chromium 브라우저는 설치되어 있지만, 초기 설정이 완료되지 않았습니다. 설정 마법사를 시작합니다...")
        launch_module("setup_wizard")
