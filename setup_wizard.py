import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import subprocess
import os
import sys
import asyncio
import shutil

# crawler.py와 gui.py의 경로 설정을 일관성 있게 가져옵니다.
try:
    from crawler import PixaiCrawler
except ImportError:
    # PyInstaller 환경 등에서 crawler.py를 직접 찾지 못할 경우를 대비
    sys.path.append(os.path.dirname(__file__))
    from crawler import PixaiCrawler

# 경로 설정
USER_DATA = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "PixAI-Gen-Bot", "playwright_user_data")
FLAG_FILE = os.path.join(USER_DATA, '.setup_complete')

if getattr(sys, 'frozen', False):
    BASE = os.path.dirname(sys.executable)
else:
    BASE = os.path.abspath(os.path.dirname(__file__))

class SetupWizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PixAI Gen Bot - 초기 설정")
        self.geometry("600x400")
        self.resizable(False, False)

        style = ttk.Style(self)
        style.theme_use('clam')

        self.label = ttk.Label(self, text="프로그램 사용에 필요한 설정을 시작합니다.", font=("Malgun Gothic", 14))
        self.label.pack(pady=20)

        self.log_text = scrolledtext.ScrolledText(self, wrap=tk.WORD, state='disabled', height=15, font=("Malgun Gothic", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        self.progress = ttk.Progressbar(self, orient='horizontal', length=100, mode='indeterminate')
        self.progress.pack(fill=tk.X, padx=20, pady=(0, 20))

        self.after(200, self.start_setup_thread)

    def log(self, message):
        def _update():
            self.log_text.configure(state='normal')
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state='disabled')
        if self.winfo_exists():
            self.after(0, _update)

    def start_setup_thread(self):
        self.progress.start()
        thread = threading.Thread(target=self.run_setup, daemon=True)
        thread.start()

    def run_setup(self):
        try:
            self.log("--- 1/2: 브라우저 설치 ---")
            if not self.install_chromium():
                raise Exception("브라우저 설치에 실패했습니다.")
            
            # self.log("\n--- 2/2: 사용자 로그인 설정 ---")
            # if not self.run_user_login_setup():
            #     raise Exception("사용자 로그인 설정에 실패했습니다.")

            self.log("\n--- 설정 완료 ---")
            with open(FLAG_FILE, 'w') as f:
                f.write('done')
            self.after(100, self.launch_main_app)

        except Exception as e:
            error_message = f"\n오류: 설정에 실패했습니다.\n{e}"
            self.log(error_message)
            self.after(100, lambda: messagebox.showerror("설치 실패", f"초기 설정에 실패했습니다:\n{e}"))
        finally:
            self.after(0, self.progress.stop)

    def launch_main_app(self):
        self.destroy()
        # 설정이 완료되었으므로 애플리케이션을 재시작하여 메인 GUI를 로드합니다.
        try:
            # 현재 실행 파일 경로로 재시작
            os.execl(sys.executable, *sys.argv)
        except Exception as e:
            messagebox.showerror("재시작 실패", f"프로그램을 재시작하는 데 실패했습니다. 수동으로 다시 시작해주세요.\n오류: {e}")
            sys.exit(1)

    def install_chromium(self):
        try:
            # frozen(EXE)일 때 sys.executable로 다시 호출하면 재귀 발생.
            # 따라서 frozen이면 시스템 파이썬을 먼저 찾고, 없으면 플레이라이트 API로 설치 시도.
            if getattr(sys, "frozen", False):
                python_cmd = shutil.which("python") or shutil.which("py")
            else:
                python_cmd = sys.executable

            if python_cmd is None:
                # 시스템 파이썬이 없으면 파이썬 API 직접 호출(플레이라이트 내부 API는 변경될 수 있음)
                try:
                    from playwright.__main__ import main as pw_main
                    pw_main(["install", "chromium"])
                    return True
                except Exception as e:
                    self.log(f"시스템 Python 없음 및 Playwright API 호출 실패: {e}")
                    return False

            self.log("Chromium 브라우저 다운로드를 시작합니다 (몇 분 소요될 수 있습니다).")
            install_cmd = [python_cmd, "-m", "playwright", "install", "chromium"]
            proc = subprocess.Popen(
                install_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                shell=False
            )
            # 실시간 로그 표출
            for line in iter(proc.stdout.readline, ""):
                if line:
                    self.log(line.rstrip())
            proc.wait()
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(proc.returncode, install_cmd)
            self.log("Chromium 브라우저 설치가 완료되었습니다.")
            return True
        except Exception as e:
            self.log(f"브라우저 설치 중 오류: {e}")
            return False

    def run_user_login_setup(self):
        self.log("로그인 설정을 위해 브라우저를 실행합니다.")
        self.log("잠시 후 열리는 브라우저에서 PixAI에 로그인해주세요.")
        self.log("로그인이 완료되면, 반드시 브라우저 창을 닫아야 다음 단계로 진행됩니다.")
        
        loop = None
        try:
            crawler_for_setup = PixaiCrawler(headless=False, USER_DATA_DIR=USER_DATA)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(crawler_for_setup._run_first_time_setup())
            self.log("사용자 설정이 저장되었습니다.")
            return True
        except Exception as e:
            self.log(f"로그인 설정 중 오류 발생: {e}")
            return False
        finally:
            if loop and not loop.is_closed():
                loop.close()

if __name__ == "__main__":
    # 이 파일은 bootstrap.py를 통해 실행되어야 합니다.
    # 직접 실행 시 설정 마법사를 띄웁니다.
    os.makedirs(USER_DATA, exist_ok=True)
    wizard = SetupWizard()
    wizard.mainloop()
