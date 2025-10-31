import os
import sys
import subprocess

# 경로 정의
BASE = os.path.abspath(os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else __file__))
USER_DATA = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "PixAI-Gen-Bot", "playwright_user_data")
FLAG_FILE = os.path.join(USER_DATA, '.setup_complete')

def launch_script(script_name):
    """지정된 스크립트 또는 그에 해당하는 exe를 실행합니다."""
    script_path = os.path.join(BASE, script_name)
    executable_path = os.path.join(BASE, script_name.replace('.py', '.exe'))

    # PyInstaller로 빌드된 환경인지 확인
    if getattr(sys, 'frozen', False) and os.path.exists(executable_path):
        print(f"Executing {executable_path}...")
        subprocess.Popen([executable_path])
    elif os.path.exists(script_path):
        print(f"Executing {script_path} with python...")
        subprocess.Popen([sys.executable, script_path])
    else:
        print(f"오류: 실행 파일을 찾을 수 없습니다. ({script_path} 또는 {executable_path})", file=sys.stderr)
        # 간단한 Tkinter 오류 메시지 박스
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("실행 오류", f"필수 파일을 찾을 수 없습니다:\n{script_name}")
            root.destroy()
        except ImportError:
            pass # Tkinter가 없는 최소 환경일 경우 무시
        sys.exit(1)

if __name__ == "__main__":
    # chdir을 bootstrap에서 한 번만 수행
    os.chdir(BASE)
    
    if os.path.exists(FLAG_FILE):
        # 설정 완료, 메인 앱 실행
        print("설정이 완료되었습니다. 메인 프로그램을 시작합니다...")
        launch_script("gui.py")
    else:
        # 설정 미완료, 설정 마법사 실행
        print("최초 설정이 필요합니다. 설정 마법사를 시작합니다...")
        launch_script("setup_wizard.py")
