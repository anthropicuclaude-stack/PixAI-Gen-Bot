import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk, simpledialog
from PIL import Image, ImageTk
import asyncio
import threading
import json
import re
import shutil
from crawler import PixaiCrawler

import os, sys, shutil

# BASE: frozen(exe)면 exe 위치, 아니면 소스 위치
BASE = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(__file__)

# (선택) 상대경로 동작을 원하면 활성화
os.chdir(BASE)

# 외부 오버라이드 허용
PROMPT_FILE = os.environ.get("PROMPT_FILE", os.path.join(BASE, "prompts.json"))
MODEL_PRESETS_FILE = os.environ.get("MODEL_PRESETS_FILE", os.path.join(BASE, "model_presets.json"))
USER_DATA = os.environ.get("PLAYWRIGHT_USER_DATA",
                           os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"),
                                        "PixAI-Gen-Bot", "playwright_user_data"))
BROWSERS_PATH = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", os.path.join(BASE, "browsers"))
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS_PATH

# 디렉토리 보장
os.makedirs(os.path.dirname(PROMPT_FILE), exist_ok=True)
os.makedirs(os.path.dirname(MODEL_PRESETS_FILE), exist_ok=True)
# os.makedirs(USER_DATA, exist_ok=True)
os.makedirs(BROWSERS_PATH, exist_ok=True)

# prompts.json 존재하지 않으면 배포된 기본값을 복사
_default = os.path.join(BASE, "prompts.json")
if not os.path.exists(PROMPT_FILE) and os.path.exists(_default):
    try:
        shutil.copy2(_default, PROMPT_FILE)
    except PermissionError:
        # 안전하게 무시하거나 로그 남기기
        pass
_default_presets = os.path.join(BASE, "model_presets.json")
if not os.path.exists(MODEL_PRESETS_FILE) and os.path.exists(_default_presets):
    try:
        shutil.copy2(_default_presets, MODEL_PRESETS_FILE)
    except PermissionError:
        # 안전하게 무시하거나 로그 남기기
        pass

class CrawlerManager:
    """
    Runs a single PixaiCrawler instance on a dedicated background asyncio loop/thread.
    Provides a synchronous run_image_macro(...) method that schedules the crawler coroutine
    and returns a local file path to the generated image (renamed to requested output name).
    """

    def __init__(self):
        self.loop = None
        self.crawler: PixaiCrawler | None = None
        self.thread: threading.Thread | None = None
        self.ready = threading.Event()
        self._stop_requested = False
        self.start_exception: Exception | None = None

    def start(self, headless: bool = True, on_done=None):
        if self.thread and self.thread.is_alive():
            return

        self.ready.clear()
        self.start_exception = None

        def _thread_target():
            exception = None
            try:
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
                # instantiate crawler and enter context
                self.crawler = PixaiCrawler(headless=headless, USER_DATA_DIR=USER_DATA)
                self.loop.run_until_complete(self.crawler.__aenter__())
            except Exception as e:
                exception = e
                self.start_exception = e
            finally:
                self.ready.set()
                if on_done:
                    on_done(exception)

            if not exception:
                # keep loop running for scheduling tasks
                self.loop.run_forever()

            # cleanup if loop stops
            try:
                if self.loop and not self.loop.is_closed():
                    self.loop.close()
            except Exception:
                pass

        self.thread = threading.Thread(target=_thread_target, daemon=True)
        self.thread.start()

    def run_get_active_config(self, timeout: int = 30) -> dict:
        if self.start_exception:
            raise RuntimeError(f"Crawler failed to start: {self.start_exception}")
        if not self.ready.is_set() or not self.crawler or not self.loop:
            raise RuntimeError("Crawler is not ready.")
        
        coro = self.crawler.get_active_config()
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            future.cancel()
            raise

    def run_take_screenshot(self, timeout: int = 20) -> str | None:
        if self.start_exception:
            raise RuntimeError(f"Crawler failed to start: {self.start_exception}")
        if not self.ready.is_set() or not self.crawler or not self.loop:
            raise RuntimeError("Crawler is not ready.")
        
        coro = self.crawler.take_screenshot()
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            future.cancel()
            raise

    def run_set_model(self, model_info: tuple, timeout: int = 120):
        if self.start_exception:
            raise RuntimeError(f"Crawler failed to start: {self.start_exception}")
        if not self.ready.is_set() or not self.crawler or not self.loop:
            raise RuntimeError("Crawler is not ready.")
        
        coro = self.crawler.set_model(model_info)
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            future.cancel()
            raise

    def run_set_loras(self, loras: list, timeout: int = 300) -> str | None:
        if self.start_exception:
            raise RuntimeError(f"Crawler failed to start: {self.start_exception}")
        if not self.ready.is_set() or not self.crawler or not self.loop:
            raise RuntimeError("Crawler is not ready.")
        
        coro = self.crawler.set_loras(loras)
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            future.cancel()
            raise

    def run_add_booster(self, booster_name: str, timeout: int = 30):
        if not self.ready.is_set() or not self.crawler or not self.loop:
            raise RuntimeError("Crawler is not ready.")
        coro = self.crawler.add_booster(booster_name)
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        future.result(timeout=timeout)

    def run_remove_booster(self, booster_name: str, timeout: int = 30):
        if not self.ready.is_set() or not self.crawler or not self.loop:
            raise RuntimeError("Crawler is not ready.")
        coro = self.crawler.remove_booster(booster_name)
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        future.result(timeout=timeout)

    def run_get_active_boosters(self, timeout: int = 30) -> list[str]:
        if not self.ready.is_set() or not self.crawler or not self.loop:
            raise RuntimeError("Crawler is not ready.")
        coro = self.crawler.get_active_boosters()
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=timeout)

    def stop(self, timeout: int = 10):
        """
        Clean shutdown: call crawler.__aexit__ on loop, then stop loop and join thread.
        """
        if not self.thread or not self.thread.is_alive():
            return

        def _shutdown():
            try:
                if self.crawler:
                    return self.crawler.__aexit__(None, None, None)
            except Exception:
                pass
            return None

        try:
            if self.loop and self.crawler:
                fut = asyncio.run_coroutine_threadsafe(_shutdown(), self.loop)
                try:
                    fut.result(timeout=timeout)
                except Exception:
                    pass
            if self.loop:
                self.loop.call_soon_threadsafe(self.loop.stop)
        finally:
            self.thread.join(timeout=timeout)


class Tooltip:
    """
    Create a tooltip for a given widget.
    """
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        if self.tooltip_window or not self.text:
            return

        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 1

        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")

        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                         font=("tahoma", "9", "normal"), wraplength=300)
        label.pack(ipadx=2, ipady=2)

    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
        self.tooltip_window = None

class EntryWithPlaceholder(tk.Entry):
    def __init__(self, master=None, placeholder="PLACEHOLDER", color='grey', textvariable=None, **kwargs):
        super().__init__(master, textvariable=textvariable, **kwargs)
        self.placeholder = placeholder
        self.placeholder_color = color
        try:
            self.default_fg_color = self.cget('fg')
        except Exception:
            self.default_fg_color = 'black'
        self._has_placeholder = False

        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)

        # 초기값이 textvariable에 있으면 그 값을 사용, 아니면 플레이스홀더
        if textvariable and textvariable.get():
            self._put_text_without_flag(textvariable.get())
        else:
            self._put_placeholder()

    # 내부: placeholder 삽입 (항상 플레이스홀더 상태로 설정)
    def _put_placeholder(self):
        super().delete(0, tk.END)
        super().insert(0, self.placeholder)
        try:
            self.config(fg=self.placeholder_color)
        except Exception:
            pass
        self._has_placeholder = True

    # 내부: 텍스트 넣되 _has_placeholder 설정하지 않음 (초기화용)
    def _put_text_without_flag(self, text):
        super().delete(0, tk.END)
        super().insert(0, text)
        try:
            self.config(fg=self.default_fg_color)
        except Exception:
            pass
        self._has_placeholder = False

    # 외부에서 안전하게 텍스트를 설정할 때 사용
    def set_text(self, text: str):
        if not text:
            self._put_placeholder()
            return
        self._put_text_without_flag(text)

    # insert 오버라이드: 외부/프리셋에서 insert 호출될 때 상태 자동 갱신
    def insert(self, index, string):
        super().insert(index, string)
        if string == self.placeholder:
            self._has_placeholder = True
            try:
                self.config(fg=self.placeholder_color)
            except Exception:
                pass
        else:
            self._has_placeholder = False
            try:
                self.config(fg=self.default_fg_color)
            except Exception:
                pass

    def _remove_placeholder(self):
        if self._has_placeholder:
            super().delete(0, tk.END)
            try:
                self.config(fg=self.default_fg_color)
            except Exception:
                pass
            self._has_placeholder = False

    def _on_focus_in(self, *args):
        self._remove_placeholder()

    def _on_focus_out(self, *args):
        if not super().get():
            self._put_placeholder()

    def get(self) -> str:
        if self._has_placeholder:
            return ""
        return super().get()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PixAI 이미지 생성기")
        self.geometry("1200x700")

        # crawler manager
        self.crawler_manager = CrawlerManager()

        # Model presets
        self.model_presets = []
        self.current_model_preset = None

        # 이미지 체크박스 사용하지 않음. 내부 ttk.Checkbutton 사용.
        self.checkbox_vars = {}     # key -> BooleanVar
        self.preset_widgets = {}    # key -> widget frame
        self.checked_items = set()
        self.group_expanded_state = {}
        self.checked_keys = set()

        self.BOOSTER_OPTIONS = ["얼굴 수정", "고해상도", "품질 태그"]
        self.booster_vars = {}
        self.booster_checkboxes = {}

        self.style = ttk.Style(self)
        self.style.theme_use('clam')

        main_paned_window = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        preset_frame = ttk.LabelFrame(main_paned_window, text="프롬프트 프리셋", padding="10")
        main_paned_window.add(preset_frame, weight=4)

        right_frame = ttk.Frame(main_paned_window)
        main_paned_window.add(right_frame, weight=1)

        self.setup_preset_ui(preset_frame)
        self.setup_main_controls_ui(right_frame)

        self.presets = self.load_presets()
        self.load_model_presets()
        self.redirect_logging()
        self.filter_presets()

        # Schedule crawler start after mainloop begins
        self.after(100, self.start_crawler)
        # ensure crawler is stopped on exit
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ... (all other methods unchanged) ...

    def setup_preset_ui(self, parent_frame):
        top_frame = ttk.Frame(parent_frame)
        top_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(top_frame, text="검색:").pack(side=tk.LEFT, padx=(0,2))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(top_frame, textvariable=self.search_var, width=20)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,10))
        self.search_var.trace_add("write", lambda *args: self.filter_presets())

        self.search_filter_var = tk.StringVar(value="name")
        name_filter_rb = ttk.Radiobutton(top_frame, text="이름", variable=self.search_filter_var, value="name", command=self.filter_presets)
        name_filter_rb.pack(side=tk.LEFT)
        Tooltip(name_filter_rb, "프리셋 이름 또는 그룹 이름으로 검색합니다.")
        content_filter_rb = ttk.Radiobutton(top_frame, text="내용", variable=self.search_filter_var, value="content", command=self.filter_presets)
        content_filter_rb.pack(side=tk.LEFT, padx=(0,5))
        Tooltip(content_filter_rb, "프롬프트 내용으로 검색합니다.")

        # 스크롤 가능한 프레임 생성
        scroller_frame = ttk.Frame(parent_frame)
        scroller_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self._preset_canvas = tk.Canvas(scroller_frame, highlightthickness=0)
        self._preset_scrollbar = ttk.Scrollbar(scroller_frame, orient="vertical", command=self._preset_canvas.yview)
        self._preset_canvas.configure(yscrollcommand=self._preset_scrollbar.set)

        self._preset_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._preset_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # --- 캔버스 배경을 기준으로 체크버튼 스타일 고정
        canvas_bg = self._preset_canvas.cget("background")
        self.style.configure("Preset.TCheckbutton", background=canvas_bg)
        # 내부 컨테이너는 tk.Frame으로 생성해 배경 일관화
        self._preset_inner = tk.Frame(self._preset_canvas, bg=canvas_bg)
        self._preset_canvas_window = self._preset_canvas.create_window((0,0), window=self._preset_inner, anchor='nw')
        self._preset_inner.bind("<Configure>", lambda e: self._preset_canvas.configure(scrollregion=self._preset_canvas.bbox("all")))
        self._preset_canvas.bind("<Configure>", lambda e: self._preset_canvas.itemconfigure(self._preset_canvas_window, width=e.width))

        # 마우스휠 스크롤(윈도우/리눅스/macOS 간단 처리)
        def _on_mousewheel(event):
            if os.name == 'nt':
                delta = -1 * int(event.delta/120)
            else:
                delta = -1 * int(event.delta)
            self._preset_canvas.yview_scroll(delta, "units")
        self._preset_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # 프롬프트 미리보기 영역
        preview_frame = ttk.LabelFrame(parent_frame, text="프롬프트 미리보기", padding="5")
        preview_frame.pack(fill=tk.BOTH, pady=(4, 6))
        self.preview_text = scrolledtext.ScrolledText(preview_frame, wrap=tk.WORD, height=6, state='disabled')
        self.preview_text.pack(fill=tk.BOTH, expand=True)

        btn_frame = ttk.Frame(parent_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        self.select_all_btn = ttk.Button(btn_frame, text="전체 선택", width=10, command=self.toggle_select_all)
        self.select_all_btn.pack(side=tk.LEFT, padx=(0, 2))
        Tooltip(self.select_all_btn, "표시된 모든 프리셋을 선택하거나 해제합니다.")

        self.run_selected_btn = ttk.Button(btn_frame, text="선택 항목 실행", width=12, command=self.start_batch_macro)
        self.run_selected_btn.pack(side=tk.LEFT, padx=(0, 2))
        Tooltip(self.run_selected_btn, "선택된 모든 프리셋을 순차적으로 실행하여 이미지를 생성합니다.")

        add_btn = ttk.Button(btn_frame, text="추가", width=6, command=self.add_preset)
        add_btn.pack(side=tk.LEFT, padx=(0, 2))
        Tooltip(add_btn, "새로운 프롬프트 프리셋을 추가합니다.")

        edit_btn = ttk.Button(btn_frame, text="수정", width=6, command=self.edit_preset)
        edit_btn.pack(side=tk.LEFT, padx=2)
        Tooltip(edit_btn, "선택한 프리셋 또는 그룹을 수정합니다. (하나만 선택)")

        del_btn = ttk.Button(btn_frame, text="삭제", width=6, command=self.delete_preset)
        del_btn.pack(side=tk.LEFT, padx=(2, 0))
        Tooltip(del_btn, "선택한 프리셋 또는 그룹을 삭제합니다.")

    def _make_group_key(self, group_name):
        return f"group::{group_name}"

    def _make_preset_key(self, group_name, preset_name):
        return f"preset::{group_name}::{preset_name}"

    def filter_presets(self):
        search_term = self.search_var.get().lower()
        filter_mode = self.search_filter_var.get()

        # UI 갱신 전, UI의 현재 체크 상태를 self.checked_keys에 반영
        for key, var in self.checkbox_vars.items():
            if var.get():
                self.checked_keys.add(key)
            else:
                self.checked_keys.discard(key)

        # 이전 위젯 제거
        for child in self._preset_inner.winfo_children():
            child.destroy()
        self.checkbox_vars.clear()
        self.preset_widgets.clear()
        self.checked_items.clear()
        self.clear_preset_preview()

        canvas_bg = self._preset_canvas.cget("background")

        for group in self.presets.get("groups", []):
            group_name = group.get("name", "")
            presets = group.get("presets", [])

            matching_presets = []
            is_group_name_match = False
            if search_term:
                for preset in presets:
                    preset_name = preset.get("name", "")
                    prompt_text = preset.get("prompt", "")
                    if filter_mode == 'name':
                        if search_term in group_name.lower() or search_term in preset_name.lower():
                            matching_presets.append(preset)
                    else:
                        if search_term in prompt_text.lower():
                            matching_presets.append(preset)
                is_group_name_match = (search_term in group_name.lower() and filter_mode == 'name')
            else:
                matching_presets = presets
                is_group_name_match = True

            if matching_presets or (search_term and is_group_name_match):
                group_frame = tk.Frame(self._preset_inner, bg=canvas_bg)
                group_frame.pack(fill=tk.X, padx=4, pady=(6,2), anchor='nw')

                header_frame = tk.Frame(group_frame, bg=canvas_bg)
                header_frame.pack(fill=tk.X, anchor='w')

                group_key = self._make_group_key(group_name)
                gvar = tk.BooleanVar(value=(group_key in self.checked_keys))
                self.checkbox_vars[group_key] = gvar

                is_expanded = self.group_expanded_state.get(group_name, False)
                toggle_symbol = '[-]' if is_expanded else '[+]'
                toggle_label = tk.Label(header_frame, text=toggle_symbol, cursor="hand2", bg=canvas_bg, fg="blue")
                toggle_label.pack(side=tk.LEFT, padx=(0, 4))
                toggle_label.bind("<Button-1>", lambda e, gn=group_name: self.toggle_group_expand(gn))

                group_text = f"{group_name} ({len(presets)})"
                gchk = ttk.Checkbutton(header_frame, text=group_text, variable=gvar,
                                       command=lambda k=group_key: self._on_group_toggle(k),
                                       style="Preset.TCheckbutton")
                gchk.pack(side=tk.LEFT, anchor='w')

                if is_expanded:
                    child_container = tk.Frame(group_frame, bg=canvas_bg)
                    child_container.pack(fill=tk.X, padx=40, anchor='nw')

                    display_presets = matching_presets if search_term else presets
                    for preset in display_presets:
                        pname = preset.get("name", "")
                        pprompt = preset.get("prompt", "")

                        p_key = self._make_preset_key(group_name, pname)
                        pvar = tk.BooleanVar(value=(p_key in self.checked_keys))
                        self.checkbox_vars[p_key] = pvar

                        item_frame = tk.Frame(child_container, bg=canvas_bg)
                        item_frame.pack(fill=tk.X, anchor='nw', pady=1)

                        pchk = ttk.Checkbutton(item_frame, text=pname, variable=pvar,
                                                command=lambda pk=p_key, gk=group_key: self._on_preset_toggle(pk, gk),
                                                style="Preset.TCheckbutton")
                        pchk.pack(side=tk.LEFT, anchor='w')

                        # 마우스 호버로 프리뷰 표시
                        pchk.bind("<Enter>", lambda e, prm=pprompt: self.show_preset_preview(prm))
                        pchk.bind("<Leave>", lambda e: self.clear_preset_preview())
                        # 더블 클릭으로 프롬프트 로드
                        pchk.bind("<Double-1>", lambda e, prm=pprompt: self._load_prompt_into_entry(prm))

                        # 보조 라벨(프롬프트 Load 설명)
                        lbl = tk.Label(item_frame, text="(더블클릭으로 로드)", cursor="hand2", bg=canvas_bg)
                        lbl.pack(side=tk.LEFT, padx=8)
                        Tooltip(lbl, "더블클릭하면 이 프리셋의 프롬프트를 오른쪽 입력창으로 복사합니다.")
                        lbl.bind("<Double-1>", lambda e, prm=pprompt: self._load_prompt_into_entry(prm))
                        lbl.bind("<Enter>", lambda e, prm=pprompt: self.show_preset_preview(prm))
                        lbl.bind("<Leave>", lambda e: self.clear_preset_preview())

                        self.preset_widgets[p_key] = item_frame

        self.update_select_all_button_text()

    def _on_group_toggle(self, group_key):
        state = self.checkbox_vars[group_key].get()
        group_name = group_key.split("::", 1)[1]

        if state:
            self.checked_keys.add(group_key)
        else:
            self.checked_keys.discard(group_key)

        # 모든 자식 프리셋의 상태를 self.checked_keys에서 업데이트
        for group in self.presets.get("groups", []):
            if group.get("name") == group_name:
                for preset in group.get("presets", []):
                    p_key = self._make_preset_key(group_name, preset.get("name"))
                    if state:
                        self.checked_keys.add(p_key)
                    else:
                        self.checked_keys.discard(p_key)
                break

        # 현재 화면에 보이는 자식들의 체크박스 상태도 동기화
        prefix = f"preset::{group_name}::"
        for key, var in self.checkbox_vars.items():
            if key.startswith(prefix):
                var.set(state)

        self.update_select_all_button_text()

    def _on_preset_toggle(self, preset_key, group_key):
        state = self.checkbox_vars[preset_key].get()
        if state:
            self.checked_keys.add(preset_key)
        else:
            self.checked_keys.discard(preset_key)

        # 부모 그룹의 상태 업데이트
        group_name = group_key.split("::", 1)[1]
        all_sibling_keys = []
        for group in self.presets.get("groups", []):
            if group.get("name") == group_name:
                for preset in group.get("presets", []):
                    all_sibling_keys.append(self._make_preset_key(group_name, preset.get("name")))
                break
        
        all_checked = all(k in self.checked_keys for k in all_sibling_keys) if all_sibling_keys else False
        
        if all_checked:
            self.checked_keys.add(group_key)
        else:
            self.checked_keys.discard(group_key)
        
        if group_key in self.checkbox_vars:
            self.checkbox_vars[group_key].set(all_checked)
            
        self.update_select_all_button_text()

    def toggle_group_expand(self, group_name):
        """그룹 펼치기/접기 상태를 토글하고 프리셋 목록을 새로고침합니다."""
        current_state = self.group_expanded_state.get(group_name, False)
        self.group_expanded_state[group_name] = not current_state
        self.filter_presets()

    def _load_prompt_into_entry(self, prompt):
        self.prompt_entry.delete(0, tk.END)
        self.prompt_entry.insert(0, prompt)
        # 로드 시 미리보기도 갱신
        self.show_preset_preview(prompt)

    def show_preset_preview(self, prompt):
        self.preview_text.config(state='normal')
        self.preview_text.delete('1.0', tk.END)
        self.preview_text.insert(tk.END, prompt)
        self.preview_text.see('1.0')
        self.preview_text.config(state='disabled')

    def clear_preset_preview(self):
        self.preview_text.config(state='normal')
        self.preview_text.delete('1.0', tk.END)
        self.preview_text.config(state='disabled')

    def toggle_select_all(self):
        make_all = self.select_all_btn.cget("text") == "전체 선택"

        if make_all:
            for group in self.presets.get("groups", []):
                gname = group.get("name")
                gkey = self._make_group_key(gname)
                self.checked_keys.add(gkey)
                for preset in group.get("presets", []):
                    pname = preset.get("name")
                    pkey = self._make_preset_key(gname, pname)
                    self.checked_keys.add(pkey)
        else:
            self.checked_keys.clear()

        # 화면에 보이는 모든 체크박스 업데이트
        for key, var in self.checkbox_vars.items():
            var.set(make_all)
            
        self.select_all_btn.config(text="전체 해제" if make_all else "전체 선택")

    def update_select_all_button_text(self):
        preset_keys = [k for k in self.checkbox_vars.keys() if k.startswith("preset::")]
        is_all_checked = bool(preset_keys) and all(self.checkbox_vars[k].get() for k in preset_keys)
        self.select_all_btn.config(text="전체 해제" if is_all_checked else "전체 선택")

    def _gather_selected_presets_with_names(self):
        tasks = []
        # self.checked_keys는 순서가 없으므로 key 정렬
        for key in sorted(list(self.checked_keys)):
            if not key.startswith("preset::"): continue
            
            parts = key.split("::", 2)
            _, group_name, preset_name = parts
            prompt = None
            for g in self.presets.get("groups", []):
                if g.get("name") == group_name:
                    for p in g.get("presets", []):
                        if p.get("name") == preset_name:
                            prompt = p.get("prompt"); break
            if prompt:
                tasks.append((preset_name, prompt))
        return tasks

    def _parse_lora_string(self, lora_str: str) -> list[dict]:
        """Parses the LoRA string with optional weights (e.g., 'lora a:0.8, lora b')."""
        loras_with_weights = []
        if not lora_str:
            return loras_with_weights
        
        lora_parts = [l.strip() for l in lora_str.split(',') if l.strip()]
        for part in lora_parts:
            if ':' in part:
                name, _, weight_str = part.rpartition(':')
                try:
                    # Validate that weight is a float
                    float(weight_str)
                    loras_with_weights.append({'name': name.strip(), 'weight': weight_str.strip()})
                except ValueError:
                    # If weight is not a valid float, treat the whole thing as a name
                    loras_with_weights.append({'name': part, 'weight': None})
            else:
                loras_with_weights.append({'name': part, 'weight': None})
        return loras_with_weights
    def find_trigger_words_for_model(self, model_name, model_version, lora_str):
        """Finds a model preset and returns its trigger words."""
        parsed_loras = self._parse_lora_string(lora_str)
        lora_names = [l['name'] for l in parsed_loras]
        sanitized_loras_input = sorted([re.sub(r'[\W_]+', '', name).lower() for name in lora_names])

        found_preset = None
        for preset in self.model_presets:
            # The 'lora' field in the preset still contains the name:weight string
            preset_loras_str = preset.get('lora', '')
            parsed_preset_loras = self._parse_lora_string(preset_loras_str)
            preset_lora_names = [l['name'] for l in parsed_preset_loras]
            sanitized_loras_preset = sorted([re.sub(r'[\W_]+', '', name).lower() for name in preset_lora_names])

            if (preset.get('model_name') == model_name and
                preset.get('model_version') == model_version and
                sanitized_loras_preset == sanitized_loras_input):
                found_preset = preset
                break
        
        if found_preset:
            return found_preset.get('trigger_words', '')
        return ''

    def execute_generation_task(self, tasks, model_name, model_version, lora_str, headless):
        try:
            # --- 1. Get Target Config from GUI ---
            target_model_name = model_name
            target_model_version = model_version
            target_loras = self._parse_lora_string(lora_str)
            lora_names = [l['name'] for l in target_loras]

            # --- 2. Get Active Config from Page (for the first task) ---
            print("웹페이지의 현재 설정을 확인합니다...")
            active_config = self.crawler_manager.run_get_active_config()
            
            # --- 3. Compare and Set Model/LoRAs if necessary ---
            active_lora_names = [l['name'] for l in active_config.get('loras', [])]
            
            model_match = (active_config.get('model_name') == target_model_name and active_config.get('model_version') == target_model_version)
            lora_names_match = sorted(lora_names) == sorted(active_lora_names)
            
            new_trigger_words = None

            if not model_match:
                print(f"모델 설정이 다릅니다. 목표: {target_model_name} (v: {target_model_version}) / 현재: {active_config.get('model_name')} (v: {active_config.get('model_version')})")
                print("모델을 설정합니다...")
                model_info = (target_model_name, target_model_version)
                self.crawler_manager.run_set_model(model_info)
                
                # 모델 변경 시 LoRA는 초기화되므로 항상 다시 설정해야 함
                print("모델 변경에 따라 LoRA를 다시 설정합니다...")
                new_trigger_words = self.crawler_manager.run_set_loras(target_loras)

            elif not lora_names_match:
                print(f"LoRA 설정이 다릅니다. 목표: {lora_names} / 현재: {active_lora_names}")
                print("LoRA를 설정합니다...")
                new_trigger_words = self.crawler_manager.run_set_loras(target_loras)
            
            else:
                print("페이지에 이미 올바른 모델/LoRA가 설정되어 있습니다.")

            if new_trigger_words is not None:
                self.update_model_preset_with_trigger_words(target_model_name, target_model_version, lora_str, new_trigger_words)

            # --- 4. Run Generation for all tasks ---
            trigger_words = self.find_trigger_words_for_model(target_model_name, target_model_version, lora_str)

            # Create organized output directory
            lora_folder_name = '_'.join(sorted([re.sub(r'[\W_]+', '', name).lower() for name in lora_names])) or '-'
            model_folder_name = re.sub(r'[\W_]+', '', target_model_name).lower() or '-'
            base_output_dir = os.path.join("generated", f"{model_folder_name}_{lora_folder_name}")

            all_generated_files = []
            for i, (name, prompt) in enumerate(tasks):
                print(f"\n--- 작업 {i+1}/{len(tasks)}: {name} ---")

                # Determine final output directory, including preset name if applicable
                if name != "current_prompt_context":
                    preset_folder_name = re.sub(r'[\W_]+', '', name).lower()
                    output_dir = os.path.join(base_output_dir, preset_folder_name)
                else:
                    output_dir = base_output_dir
                os.makedirs(output_dir, exist_ok=True)

                final_prompt = f"{trigger_words}, {prompt}" if trigger_words and trigger_words not in prompt else prompt
                
                # Correctly call run_image_macro with output_name
                image_paths = self.run_image_macro(prompt=final_prompt, output_name=name, output_dir=output_dir)
                
                if image_paths:
                    print(f"성공: {len(image_paths)}개 이미지 저장됨")
                    all_generated_files.extend(image_paths)
                    self.after(100, self.load_generated_image, image_paths[-1])
                else:
                    print(f"작업 '{name}'에 대한 이미지 생성 실패.")

            print("\n모든 작업 완료.")
            if all_generated_files:
                 self.after(100, lambda: messagebox.showinfo("생성 완료", f"총 {len(all_generated_files)}개의 이미지가 생성되었습니다."))

        except Exception as e:
            print(f"생성 작업 중 오류 발생: {e}")
            self.after(100, lambda e=e: messagebox.showerror("실행 오류", f"매크로 실행 중 오류가 발생했습니다:\n{e}"))

    def start_batch_macro(self):
        tasks = self._gather_selected_presets_with_names()
        if not tasks:
            messagebox.showwarning("선택 오류", "실행할 프리셋을 하나 이상 체크하세요.")
            return

        model_name = self.model_name_entry.get().strip()
        model_version = self.model_version_entry.get().strip()
        lora = self.lora_entry.get().strip()

        version_display = f" (버전: {model_version})" if model_version and model_version != self.model_version_entry.placeholder else ""
        if messagebox.askyesno("일괄 실행 확인", f"{len(tasks)}개의 이미지를 생성하시겠습니까?\n\n모델: {model_name or '없음'}{version_display}\nLoRA: {lora or '없음'}"):
            headless = self.headless_var.get()
            self.run_async_task(self.execute_generation_task, tasks, model_name, model_version, lora, headless)

    def start_single_macro(self):
        prompt = self.prompt_entry.get()
        if not prompt or prompt == self.prompt_entry.placeholder:
            messagebox.showwarning("입력 오류", "프롬프트를 입력해주세요.")
            return
        
        model_name = self.model_name_entry.get().strip()
        model_version = self.model_version_entry.get().strip()
        lora = self.lora_entry.get().strip()
        headless = self.headless_var.get()
        
        tasks = [("current_prompt_context", prompt)]
        self.run_async_task(self.execute_generation_task, tasks, model_name, model_version, lora, headless)

    def run_image_macro(self, prompt: str, output_name: str, output_dir: str = "generated", timeout: int = 600) -> str | list | None:
        """
        Synchronous wrapper. Runs crawler.image_gen_macro on the crawler loop.
        Returns:
          - list of saved file paths (absolute) if crawler returned multiple saved files
          - single filepath string if crawler returned a single path (backcompat)
          - None on failure
        Note: 더 이상 output_dir 내에서 파일을 골라 이동하거나 이름을 변경하지 않습니다.
        """
        if self.crawler_manager.start_exception:
            raise RuntimeError(f"Crawler failed to start: {self.crawler_manager.start_exception}")
        if not self.crawler_manager.ready.is_set() or not self.crawler_manager.crawler or not self.crawler_manager.loop:
            raise RuntimeError("Crawler is not ready. Run setup or wait for crawler to initialize.")

        os.makedirs(output_dir, exist_ok=True)
        coro = self.crawler_manager.crawler.image_gen_macro(prompt_text=prompt, output_dir=output_dir)
        future = asyncio.run_coroutine_threadsafe(coro, self.crawler_manager.loop)
        try:
            _res = future.result(timeout=timeout)
        except Exception as e:
            future.cancel()
            raise

        if not _res:
            return None

        # 크롤러가 리스트를 반환하면 절대경로로 정리한 리스트를 그대로 반환
        if isinstance(_res, list):
            abs_list = [os.path.abspath(p) for p in _res]
            return abs_list

        # 과거 방식(단일 경로 문자열)도 처리
        if isinstance(_res, str):
            return os.path.abspath(_res)

        # 알 수 없는 반환형 처리
        return None


    def execute_macro_batch(self, tasks, headless):
        """
        Synchronous batch executor. run_async_task will run this in a worker thread.
        """
        print(f"총 {len(tasks)}개의 작업으로 일괄 실행을 시작합니다.")
        last_image = None
        for i, (name, prompt) in enumerate(tasks):
            print(f"\n--- 작업 {i+1}/{len(tasks)} --- ")
            output_filename = f"{name}"
            try:
                image_result = self.run_image_macro(prompt, output_filename)
            except Exception as e:
                print(f"매크로 실행 실패: {e}")
                image_result = None

            # image_result가 list인지 string인지 모두 처리
            if image_result:
                if isinstance(image_result, list):
                    # 생성된 모든 파일 경로를 로그에 출력
                    print("생성된 파일들:")
                    for p in image_result:
                        print("  ", p)
                    last_image = image_result[-1]  # 미리보기에는 마지막 파일 사용
                else:
                    last_image = image_result
                # UI에 로드
                self.after(100, self.load_generated_image, last_image)
        print("\n일괄 작업을 모두 완료했습니다.")

    def run_async_task(self, task_func, *args):
        def task_wrapper():
            # UI 상태 토글은 메인스레드에서 안전하게 수행되도록 after 사용
            self.after(0, lambda: self.set_ui_state(True))
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                if asyncio.iscoroutinefunction(task_func):
                    result = loop.run_until_complete(task_func(*args))
                    # execute_macro_batch 자체가 execute하며 이미 이미지를 로드함
                    if task_func != self.execute_macro_batch and result:
                        self.after(100, self.load_generated_image, result)
                else:
                    task_func(*args)
            except Exception as e:
                print(f"작업 중 오류 발생: {e}")
            finally:
                self.after(0, lambda: self.set_ui_state(False))
                loop.close()
        thread = threading.Thread(target=task_wrapper, daemon=True)
        thread.start()

    def load_presets(self):
        if not os.path.exists(PROMPT_FILE):
            return {"groups": [{"name": "기본", "presets": []}]}
        with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except json.JSONDecodeError: return {"groups": [{"name": "기본", "presets": []}]}

    def save_presets(self):
        with open(PROMPT_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.presets, f, ensure_ascii=False, indent=4)

    def load_model_presets(self):
        if not os.path.exists(MODEL_PRESETS_FILE):
            self.model_presets = []
        else:
            with open(MODEL_PRESETS_FILE, 'r', encoding='utf-8') as f:
                try:
                    self.model_presets = json.load(f)
                except json.JSONDecodeError:
                    self.model_presets = []
        self.populate_model_preset_combobox()

    def save_model_presets(self):
        with open(MODEL_PRESETS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.model_presets, f, ensure_ascii=False, indent=4)

    def populate_model_preset_combobox(self):
        preset_names = [p['name'] for p in self.model_presets]
        self.model_preset_combo['values'] = preset_names
        self.model_preset_combo.set('')

    def on_model_preset_select(self, event=None):
        selected_name = self.model_preset_combo.get()
        if not selected_name:
            # Also clear the current preset if the selection is cleared
            self.current_model_preset = None
            return
        
        new_preset = next((p for p in self.model_presets if p['name'] == selected_name), None)
        if not new_preset:
            return

        # Update model/lora entries
        self.model_name_entry.set_text(new_preset.get("model_name", ""))
        self.model_version_entry.set_text(new_preset.get("model_version", ""))
        self.lora_entry.set_text(new_preset.get("lora", ""))

        # Get old and new trigger words
        old_triggers = self.current_model_preset.get("trigger_words", "") if self.current_model_preset else ""
        new_triggers = new_preset.get("trigger_words", "")

        # If triggers are the same, do nothing to the prompt
        if old_triggers == new_triggers:
            self.current_model_preset = new_preset
            return

        # Update prompt
        current_prompt = self.prompt_entry.get()
        
        # Tokenize and process
        prompt_tokens = [t.strip() for t in current_prompt.split(',') if t.strip()]
        old_trigger_tokens = [t.strip() for t in old_triggers.split(',') if t.strip()] if old_triggers else []
        
        # Remove old trigger words from the prompt tokens
        if old_trigger_tokens:
            prompt_tokens = [t for t in prompt_tokens if t not in old_trigger_tokens]

        # Prepend new trigger words (and avoid duplicates)
        new_trigger_tokens = [t.strip() for t in new_triggers.split(',') if t.strip()] if new_triggers else []
        final_tokens = new_trigger_tokens + [t for t in prompt_tokens if t not in new_trigger_tokens]
        
        self.prompt_entry.set_text(', '.join(final_tokens))

        # Update current preset for the next change
        self.current_model_preset = new_preset

    def show_model_preset_dialog(self, is_edit=False, initial_data=None):
        if initial_data is None:
            initial_data = {}

        dialog = tk.Toplevel(self)
        dialog.title("모델 프리셋 " + ("수정" if is_edit else "추가"))
        dialog.geometry("500x350")
        dialog.transient(self)
        dialog.grab_set()

        # --- Widgets ---
        main_frame = ttk.Frame(dialog, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="프리셋 이름:").grid(row=0, column=0, sticky="w", pady=2)
        name_entry = ttk.Entry(main_frame)
        name_entry.grid(row=0, column=1, sticky="ew", pady=2)
        name_entry.insert(0, initial_data.get("name", ""))
        if is_edit:
            name_entry.config(state='readonly')

        ttk.Label(main_frame, text="모델 이름:").grid(row=1, column=0, sticky="w", pady=2)
        model_name_entry = ttk.Entry(main_frame)
        model_name_entry.grid(row=1, column=1, sticky="ew", pady=2)
        model_name_entry.insert(0, initial_data.get("model_name", ""))

        ttk.Label(main_frame, text="모델 버전:").grid(row=2, column=0, sticky="w", pady=2)
        model_version_entry = ttk.Entry(main_frame)
        model_version_entry.grid(row=2, column=1, sticky="ew", pady=2)
        model_version_entry.insert(0, initial_data.get("model_version", ""))

        ttk.Label(main_frame, text="LoRA:").grid(row=3, column=0, sticky="w", pady=2)
        lora_entry = ttk.Entry(main_frame)
        lora_entry.grid(row=3, column=1, sticky="ew", pady=2)
        lora_entry.insert(0, initial_data.get("lora", ""))

        ttk.Label(main_frame, text="트리거 워드:").grid(row=4, column=0, sticky="nw", pady=2)
        trigger_words_text = tk.Text(main_frame, height=5)
        trigger_words_text.grid(row=4, column=1, sticky="nsew", pady=2)
        trigger_words_text.insert("1.0", initial_data.get("trigger_words", ""))
        
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(4, weight=1)

        # --- Save Logic ---
        def on_save():
            new_name = name_entry.get().strip()
            if not new_name:
                messagebox.showerror("입력 오류", "프리셋 이름은 비워둘 수 없습니다.", parent=dialog)
                return

            if not is_edit and any(p['name'] == new_name for p in self.model_presets):
                messagebox.showerror("이름 중복", "같은 이름의 프리셋이 이미 존재합니다.", parent=dialog)
                return

            preset_to_update = next((p for p in self.model_presets if p['name'] == new_name), None)
            if not preset_to_update:
                preset_to_update = {"name": new_name}
                self.model_presets.append(preset_to_update)

            preset_to_update['model_name'] = model_name_entry.get().strip()
            preset_to_update['model_version'] = model_version_entry.get().strip()
            preset_to_update['lora'] = lora_entry.get().strip()
            preset_to_update['trigger_words'] = trigger_words_text.get("1.0", tk.END).strip()

            self.model_presets.sort(key=lambda p: p['name'])
            self.save_model_presets()
            self.populate_model_preset_combobox()
            self.model_preset_combo.set(new_name)
            dialog.destroy()

        # --- Buttons ---
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Button(btn_frame, text="저장", command=on_save).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="취소", command=dialog.destroy).pack(side=tk.RIGHT, padx=5)
        
        self.wait_window(dialog)

    def save_current_model_preset(self):
        initial_data = {
            "model_name": self.model_name_entry.get().strip(),
            "model_version": self.model_version_entry.get().strip(),
            "lora": self.lora_entry.get().strip(),
            "trigger_words": ""
        }
        if not initial_data["model_name"] and not initial_data["lora"]:
            messagebox.showwarning("저장 오류", "모델 이름 또는 LoRA를 하나 이상 입력해야 합니다.", parent=self)
            return
        self.show_model_preset_dialog(is_edit=False, initial_data=initial_data)

    def edit_selected_model_preset(self):
        selected_name = self.model_preset_combo.get()
        if not selected_name:
            return messagebox.showwarning("선택 오류", "수정할 프리셋을 선택하세요.", parent=self)
        
        preset = next((p for p in self.model_presets if p['name'] == selected_name), None)
        if preset:
            self.show_model_preset_dialog(is_edit=True, initial_data=preset)

    def delete_selected_model_preset(self):
        selected_name = self.model_preset_combo.get()
        if not selected_name:
            messagebox.showwarning("삭제 오류", "삭제할 프리셋을 선택하세요.", parent=self)
            return

        if not messagebox.askyesno("삭제 확인", f"'{selected_name}' 프리셋을 삭제하시겠습니까?", parent=self):
            return

        self.model_presets = [p for p in self.model_presets if p['name'] != selected_name]
        self.save_model_presets()
        self.populate_model_preset_combobox()

    def update_model_preset_with_trigger_words(self, model_name, model_version, lora_str, trigger_words):
        """Finds a model preset matching the configuration and updates its trigger_words."""
        parsed_loras = self._parse_lora_string(lora_str)
        lora_names = [l['name'] for l in parsed_loras]
        sanitized_loras_input = sorted([re.sub(r'[\W_]+', '', name).lower() for name in lora_names])

        found_preset = None
        for preset in self.model_presets:
            preset_loras_str = preset.get('lora', '')
            parsed_preset_loras = self._parse_lora_string(preset_loras_str)
            preset_lora_names = [l['name'] for l in parsed_preset_loras]
            sanitized_loras_preset = sorted([re.sub(r'[\W_]+', '', name).lower() for name in preset_lora_names])

            if (preset.get('model_name') == model_name and
                preset.get('model_version') == model_version and
                sanitized_loras_preset == sanitized_loras_input):
                found_preset = preset
                break
        
        if found_preset:
            if found_preset.get('trigger_words') != trigger_words:
                found_preset['trigger_words'] = trigger_words
                self.save_model_presets()
        else:
            print("트리거 워드를 저장할 일치하는 모델 프리셋을 찾지 못했습니다.")

    def on_preset_double_click(self, event):
        # 더 이상 트리뷰 기반이 아니므로 사용하지 않음.
        pass

    def add_preset(self):
        self.show_preset_dialog()

    def edit_preset(self):
        selected = [k for k, v in self.checkbox_vars.items() if v.get()]
        if not selected:
            return messagebox.showwarning("선택 오류", "수정할 항목을 선택하세요. (한 개만 선택)")
        if len(selected) > 1:
            return messagebox.showwarning("선택 오류", "수정은 한 항목만 선택해야 합니다.")
        key = selected[0]
        if key.startswith("group::"):
            old_name = key.split("::",1)[1]
            new_name = simpledialog.askstring("그룹 수정", "새 그룹 이름:", initialvalue=old_name)
            if new_name and new_name != old_name:
                for g in self.presets['groups']:
                    if g['name'] == old_name:
                        g['name'] = new_name
                        break
                self.save_presets()
                self.filter_presets()
        elif key.startswith("preset::"):
            _, group_name, preset_name = key.split("::",2)
            prompt = None
            for g in self.presets.get("groups", []):
                if g.get("name") == group_name:
                    for p in g.get("presets", []):
                        if p.get("name") == preset_name:
                            prompt = p.get("prompt")
                            break
            if prompt is None:
                return messagebox.showwarning("오류", "프리셋을 찾을 수 없습니다.")
            self.show_preset_dialog(is_edit=True, group_name=group_name, preset_name=preset_name, prompt=prompt)

    def delete_preset(self):
        to_delete_groups = []
        to_delete_presets = []
        for key, var in list(self.checkbox_vars.items()):
            if var.get():
                if key.startswith("group::"):
                    to_delete_groups.append(key.split("::",1)[1])
                elif key.startswith("preset::"):
                    _, group_name, preset_name = key.split("::",2)
                    to_delete_presets.append((group_name, preset_name))

        if not (to_delete_groups or to_delete_presets):
            return messagebox.showwarning("선택 오류", "삭제할 항목을 하나 이상 체크하세요.")

        if not messagebox.askyesno("삭제 확인", f"{len(to_delete_groups) + len(to_delete_presets)}개 항목을 삭제하시겠습니까?"):
            return

        # 그룹 삭제
        if to_delete_groups:
            self.presets['groups'] = [g for g in self.presets.get('groups', []) if g.get('name') not in to_delete_groups]

        # 프리셋 삭제
        for gname, pname in to_delete_presets:
            for g in self.presets.get('groups', []):
                if g.get('name') == gname:
                    g['presets'] = [p for p in g.get('presets', []) if p.get('name') != pname]

        self.save_presets()
        self.filter_presets()

    def show_preset_dialog(self, is_edit=False, group_name="", preset_name="", prompt=""):
        dialog = tk.Toplevel(self); dialog.title("프리셋 " + ("수정" if is_edit else "추가")); dialog.geometry("400x300")
        ttk.Label(dialog, text="그룹:").pack(padx=10, pady=(10,0), anchor='w')
        group_combo = ttk.Combobox(dialog, values=[g['name'] for g in self.presets['groups']])
        group_combo.pack(padx=10, fill=tk.X); group_combo.set(group_name)
        ttk.Label(dialog, text="이름:").pack(padx=10, pady=(10,0), anchor='w')
        name_entry = ttk.Entry(dialog); name_entry.pack(padx=10, fill=tk.X); name_entry.insert(0, preset_name)
        ttk.Label(dialog, text="프롬프트:").pack(padx=10, pady=(10,0), anchor='w')
        prompt_text = tk.Text(dialog, height=5); prompt_text.pack(padx=10, pady=(0,10), fill=tk.BOTH, expand=True)
        prompt_text.insert("1.0", prompt if is_edit else self.prompt_entry.get())
        def on_save():
            new_group, new_name, new_prompt = group_combo.get().strip(), name_entry.get().strip(), prompt_text.get("1.0", tk.END).strip()
            if not (new_group and new_name and new_prompt): return messagebox.showwarning("입력 오류", "모든 필드를 채워주세요.", parent=dialog)
            if is_edit:
                # remove old preset
                for g in self.presets['groups']:
                    if g['name'] == group_name:
                        g['presets'] = [p for p in g['presets'] if p['name'] != preset_name]
            target_group = next((g for g in self.presets['groups'] if g['name'] == new_group), None)
            if not target_group:
                target_group = {"name": new_group, "presets": []}
                self.presets['groups'].append(target_group)
            if any(p['name'] == new_name for p in target_group['presets']):
                return messagebox.showwarning("이름 중복", "같은 그룹 내에 동일한 이름의 프리셋이 존재합니다.", parent=dialog)
            target_group['presets'].append({"name": new_name, "prompt": new_prompt})
            self.save_presets()
            self.filter_presets()
            dialog.destroy()
        ttk.Button(dialog, text="저장", command=on_save).pack(padx=10, pady=5)
        dialog.transient(self); dialog.grab_set(); self.wait_window(dialog)

    def redirect_logging(self):
        class TextHandler:
            def __init__(self, text_widget, app): self.text_widget, self.app = text_widget, app
            def write(self, s): self.app.after(0, self.update_text, s)
            def update_text(self, s):
                self.text_widget.configure(state='normal'); self.text_widget.insert(tk.END, s)
                self.text_widget.see(tk.END); self.text_widget.configure(state='disabled')
            def flush(self): pass
        import sys; sys.stdout = TextHandler(self.log_text, self); sys.stderr = TextHandler(self.log_text, self)

    def set_ui_state(self, is_running):
        state = 'disabled' if is_running else 'normal'
        self.run_button.config(state=state)
        self.prompt_entry.config(state=state)
        self.model_name_entry.config(state=state)
        self.model_version_entry.config(state=state)
        self.lora_entry.config(state=state)

        self.model_preset_combo.config(state='disabled' if is_running else 'readonly')
        self.save_model_preset_btn.config(state=state)
        self.edit_model_preset_btn.config(state=state)
        self.delete_model_preset_btn.config(state=state)

        # Disable preset UI during operation
        try:
            self.select_all_btn.config(state=state)
            self.run_selected_btn.config(state=state)
            self.headless_check.config(state=state)
        except Exception:
            pass
        # disable/enable all checkbuttons in preset widgets
        for frame in self.preset_widgets.values():
            for child in frame.winfo_children():
                try:
                    child.config(state=state)
                except Exception:
                    pass
        # also the search entry and radio buttons
        try:
            self.search_entry.config(state=state)
        except Exception:
            pass

        # Booster checkboxes
        for chk in self.booster_checkboxes.values():
            try:
                chk.config(state=state)
            except Exception:
                pass

    def setup_main_controls_ui(self, parent_frame):
        control_frame = ttk.LabelFrame(parent_frame, text="명령어", padding="10")
        control_frame.pack(fill=tk.X, pady=(0, 5))

        # --- Prompt
        prompt_row = ttk.Frame(control_frame)
        prompt_row.pack(fill=tk.X, expand=True, pady=(0, 5))
        ttk.Label(prompt_row, text="프롬프트:", width=12).pack(side=tk.LEFT)
        self.prompt_entry = EntryWithPlaceholder(prompt_row, placeholder="생성할 이미지의 프롬프트를 입력하세요")
        self.prompt_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Separator(control_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # --- Model Preset
        model_preset_row = ttk.Frame(control_frame)
        model_preset_row.pack(fill=tk.X, expand=True, pady=(0, 5))
        ttk.Label(model_preset_row, text="모델 프리셋:", width=12).pack(side=tk.LEFT)
        
        self.model_preset_combo = ttk.Combobox(model_preset_row, state="readonly")
        self.model_preset_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.model_preset_combo.bind("<<ComboboxSelected>>", self.on_model_preset_select)

        self.save_model_preset_btn = ttk.Button(model_preset_row, text="추가", width=6, command=self.save_current_model_preset)
        self.save_model_preset_btn.pack(side=tk.LEFT, padx=(0, 2))
        Tooltip(self.save_model_preset_btn, "현재 모델, 버전, LoRA 설정을 새 프리셋으로 추가합니다.")

        self.edit_model_preset_btn = ttk.Button(model_preset_row, text="수정", width=6, command=self.edit_selected_model_preset)
        self.edit_model_preset_btn.pack(side=tk.LEFT, padx=(0, 2))
        Tooltip(self.edit_model_preset_btn, "선택된 모델 프리셋을 수정합니다.")

        self.delete_model_preset_btn = ttk.Button(model_preset_row, text="삭제", width=6, command=self.delete_selected_model_preset)
        self.delete_model_preset_btn.pack(side=tk.LEFT)
        Tooltip(self.delete_model_preset_btn, "선택된 모델 프리셋을 삭제합니다.")

        # --- Model Name
        model_name_row = ttk.Frame(control_frame)
        model_name_row.pack(fill=tk.X, expand=True, pady=(0, 5))
        ttk.Label(model_name_row, text="모델 이름:", width=12).pack(side=tk.LEFT)
        self.model_name_entry = EntryWithPlaceholder(model_name_row, placeholder="생성에 사용할 모델의 이름을 입력하세요. 예: Haruka v2")
        self.model_name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # --- Model Version
        model_version_row = ttk.Frame(control_frame)
        model_version_row.pack(fill=tk.X, expand=True, pady=(0, 5))
        ttk.Label(model_version_row, text="모델 버전:", width=12).pack(side=tk.LEFT)
        self.model_version_entry = EntryWithPlaceholder(model_version_row, placeholder="특정 버전 지정 (선택 사항)")
        self.model_version_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # --- LoRA
        lora_row = ttk.Frame(control_frame)
        lora_row.pack(fill=tk.X, expand=True, pady=(0, 5))
        ttk.Label(lora_row, text="LoRA:", width=12).pack(side=tk.LEFT)
        self.lora_entry = EntryWithPlaceholder(lora_row, placeholder="로라의 이름을 입력하세요. 쉼표(,)로 여러 개 입력이 가능하며, 콜론(:) 으로 가중치 조절이 가능합니다. 예: lora:0.5, rola:1.2")
        self.lora_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # --- Booster Options ---
        booster_frame = ttk.LabelFrame(control_frame, text="부스터 옵션", padding="10")
        booster_frame.pack(fill=tk.X, pady=5)

        for booster_name in self.BOOSTER_OPTIONS:
            var = tk.BooleanVar(value=False)
            self.booster_vars[booster_name] = var
            chk = ttk.Checkbutton(
                booster_frame,
                text=booster_name,
                variable=var,
                command=lambda name=booster_name, v=var: self.on_booster_toggle(name, v)
            )
            chk.pack(side=tk.LEFT, padx=5)
            self.booster_checkboxes[booster_name] = chk

        util_frame = ttk.Frame(control_frame)
        util_frame.pack(fill=tk.X, pady=5)

        self.headless_var = tk.BooleanVar(value=True)
        self.headless_check = ttk.Checkbutton(util_frame, text="Headless", variable=self.headless_var, command=self.on_headless_toggle)
        self.headless_check.pack(side=tk.LEFT, padx=5)
        Tooltip(self.headless_check, "체크 시, 브라우저 창을 숨기고 백그라운드에서 실행합니다. 변경 시 크롤러가 재시작됩니다.")

        self.screenshot_button = ttk.Button(util_frame, text="스크린샷 찍기", command=self.on_take_screenshot)
        self.screenshot_button.pack(side=tk.LEFT, padx=10)
        Tooltip(self.screenshot_button, "현재 브라우저 페이지의 스크린샷을 찍어 결과 이미지 창에 표시합니다.")

        license_button = ttk.Button(util_frame, text="License", command=self.show_license, width=8)
        license_button.pack(side=tk.RIGHT, padx=5)

        button_frame = ttk.Frame(parent_frame)
        button_frame.pack(fill=tk.X, pady=5)

        self.run_button = ttk.Button(button_frame, text="현재 프롬프트 실행", command=self.start_single_macro)
        self.run_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        Tooltip(self.run_button, "오른쪽 입력창의 프롬프트를 사용하여 이미지를 생성합니다.")



        merge_all_btn = ttk.Button(button_frame, text="전체 병합", command=self.open_merge_all_dialog)
        merge_all_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 2))
        Tooltip(merge_all_btn, "선택한 프리셋들을 현재 프롬프트와 병합하여 하나의 프롬프트로 만듭니다.")

        merge_each_btn = ttk.Button(button_frame, text="개별 병합 실행", command=self.open_merge_each_dialog)
        merge_each_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))
        Tooltip(merge_each_btn, "선택한 프리셋 각각을 현재 프롬프트와 병합하여 여러 개의 프롬프트를 만들고 실행합니다.")

        output_frame = ttk.Frame(parent_frame)
        output_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        output_frame.columnconfigure(0, weight=1)
        output_frame.columnconfigure(1, weight=1)
        output_frame.rowconfigure(0, weight=1)

        log_frame = ttk.LabelFrame(output_frame, text="로그", padding="10")
        log_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state='disabled', height=10)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        image_frame = ttk.LabelFrame(output_frame, text="결과 이미지", padding="10")
        image_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.image_label = ttk.Label(image_frame, text="실행 시 여기에 이미지가 표시됩니다.", anchor="center")
        self.image_label.pack(fill=tk.BOTH, expand=True)



    def load_generated_image(self, image_path):
        """
        image_path: str | Path | list[str|Path] | bytes | file-like
        - list이면 마지막 항목을 사용합니다.
        - bytes or file-like이면 메모리에서 읽습니다.
        """
        # 빈 값 처리
        if not image_path:
            self.image_label.config(text="이미지를 찾을 수 없습니다.")
            return

        # 리스트/튜플 처리: 마지막 항목 선택
        if isinstance(image_path, (list, tuple)):
            if not image_path:
                self.image_label.config(text="이미지를 찾을 수 없습니다.")
                return
            path = image_path[-1]
        else:
            path = image_path

        import io
        try:
            # bytes 또는 file-like이면 스트림으로 처리
            if isinstance(path, (bytes, bytearray)):
                stream = io.BytesIO(path)
                img = Image.open(stream)
            elif hasattr(path, "read"):
                img = Image.open(path)
            else:
                # 문자열/Path이면 절대경로로 변환 후 파일 존재 확인
                path = os.path.abspath(str(path))
                if not os.path.exists(path):
                    self.image_label.config(text="이미지를 찾을 수 없습니다.")
                    return
                img = Image.open(path)

            # PIL 모드 정리: Tkinter에 안전한 모드로 변환
            if img.mode not in ("RGB", "RGBA"):
                try:
                    img = img.convert("RGB")
                except Exception:
                    img = img.convert("RGBA")

            # 레이블 크기 얻기 (윈도우가 아직 그려지지 않았을 수 있으므로 최소값 보장)
            lbl_w = max(2, self.image_label.winfo_width())
            lbl_h = max(2, self.image_label.winfo_height())

            # 썸네일 생성 (Resampling 호환 처리)
            resampling = getattr(Image, "Resampling", Image).LANCZOS if hasattr(Image, "LANCZOS") else Image.NEAREST
            if lbl_w > 20 and lbl_h > 20:
                img.thumbnail((lbl_w - 20, lbl_h - 20), resampling)

            photo = ImageTk.PhotoImage(img)
            self.image_label.config(image=photo, text="")
            self.image_label.image = photo

        except Exception as e:
            self.image_label.config(text=f"이미지 로드 실패:\n{e}")


    # -------------------- 병합 기능 구현 --------------------
    def _tokenize_prompt(self, prompt_str):
        # 쉼표로 분리하고 앞뒤 공백 제거, 빈 항목 제거
        if not prompt_str:
            return []
        parts = [p.strip() for p in prompt_str.split(',')]
        return [p for p in parts if p]

    def _unique_preserve_order(self, items):
        seen = set()
        out = []
        for it in items:
            if it not in seen:
                seen.add(it)
                out.append(it)
        return out

    def _gather_selected_prompts(self):
        selected_presets = self._gather_selected_presets_with_names()
        return [prompt for name, prompt in selected_presets]

    def open_merge_each_dialog(self):
        selected_presets = self._gather_selected_presets_with_names()
        if not selected_presets:
            return messagebox.showwarning("선택 오류", "병합할 프리셋을 하나 이상 선택하세요.")

        original_prompt = self.prompt_entry.get().strip()
        original_tokens = self._tokenize_prompt(original_prompt)

        tasks = []
        for preset_name, preset_prompt in selected_presets:
            prompt_tokens = self._tokenize_prompt(preset_prompt)

            # 병합: 선택된 토큰 먼저, 그다음 원본 중 중복되지 않는 항목
            merged_tokens = self._unique_preserve_order(prompt_tokens + [t for t in original_tokens if t not in prompt_tokens])
            merged_text = ', '.join(merged_tokens)

            task_name = f"{preset_name}" # 파일명으로 바로 사용
            tasks.append((task_name, merged_text))

        # 모달 UI
        dlg = tk.Toplevel(self)
        dlg.title("개별 병합 실행 확인")
        dlg.geometry("600x400")

        model_name = self.model_name_entry.get().strip()
        model_version = self.model_version_entry.get().strip()
        lora = self.lora_entry.get().strip()
        version_display = f" (버전: {model_version})" if model_version and model_version != self.model_version_entry.placeholder else ""
        info_text = f"{len(tasks)}개의 프롬프트가 생성됩니다. 아래 목록을 확인 후 실행하세요.\n\n모델: {model_name or '없음'}{version_display}, LoRA: {lora or '없음'}"
        info_label = ttk.Label(dlg, text=info_text)
        info_label.pack(padx=10, pady=10, anchor='w')

        text_area = scrolledtext.ScrolledText(dlg, wrap=tk.WORD, height=15)
        text_area.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        full_prompt_list_text = ""
        for name, prompt in tasks:
            full_prompt_list_text += f"--- {name} ---\n{prompt}\n\n"

        text_area.insert('1.0', full_prompt_list_text)
        text_area.config(state='disabled')

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        def do_execute():
            dlg.destroy()
            headless = self.headless_var.get()
            self.run_async_task(self.execute_generation_task, tasks, model_name, model_version, lora, headless)

        run_btn = ttk.Button(btn_frame, text=f"{len(tasks)}개 전체 실행", command=do_execute)
        run_btn.pack(side=tk.RIGHT, padx=(5,0))

        cancel_btn = ttk.Button(btn_frame, text="취소", command=dlg.destroy)
        cancel_btn.pack(side=tk.RIGHT)

        dlg.transient(self)
        dlg.grab_set()
        self.wait_window(dlg)

    def open_merge_all_dialog(self):
        selected_prompts = self._gather_selected_prompts()
        if not selected_prompts:
            return messagebox.showwarning("선택 오류", "병합할 프리셋을 하나 이상 선택하세요.")

        # 선택된 프롬프트들을 앞쪽에 배치. 중복 제거.
        selected_tokens = []
        for sp in selected_prompts:
            selected_tokens.extend(self._tokenize_prompt(sp))
        selected_tokens = self._unique_preserve_order(selected_tokens)

        original_prompt = self.prompt_entry.get().strip()
        original_tokens = self._tokenize_prompt(original_prompt)

        # 병합: 선택된 토큰 먼저, 그다음 원본 중 중복되지 않는 항목
        merged_tokens = selected_tokens + [t for t in original_tokens if t not in selected_tokens]
        merged_text = ', '.join(merged_tokens)
        selected_text_combined = ', '.join(selected_tokens)

        # 모달 UI
        dlg = tk.Toplevel(self)
        dlg.title("프롬프트 병합")
        dlg.geometry("900x500") # 높이 조정

        # --- 하단 버튼 프레임 ---
        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=8)

        # --- 상단 좌/우 프레임 ---
        top_lr_frame = ttk.Frame(dlg)
        top_lr_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=0, pady=0)

        left_frame = ttk.LabelFrame(top_lr_frame, text="선택된 프롬프트 (좌측)", padding=6)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6,3), pady=6)

        right_frame = ttk.LabelFrame(top_lr_frame, text="원본 프롬프트 (우측)", padding=6)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(3,6), pady=6)

        # --- 중간 미리보기 프레임 ---
        center_frame = ttk.LabelFrame(dlg, text="병합 미리보기", padding=6)
        center_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6, pady=6)

        # --- 텍스트 위젯 ---
        left_txt = tk.Text(left_frame, wrap=tk.WORD, height=8)
        left_txt.pack(fill=tk.BOTH, expand=True)
        left_txt.insert('1.0', selected_text_combined)
        left_txt.config(state='disabled')

        right_txt = tk.Text(right_frame, wrap=tk.WORD, height=8)
        right_txt.pack(fill=tk.BOTH, expand=True)
        right_txt.insert('1.0', original_prompt)
        right_txt.config(state='disabled')

        center_txt = tk.Text(center_frame, wrap=tk.WORD, height=8)
        center_txt.pack(fill=tk.BOTH, expand=True)
        center_txt.insert('1.0', merged_text)
        # center is preview but editable so user can tweak before 적용

        # --- 버튼 로직 및 배치 ---
        def apply_merged():
            new_val = center_txt.get('1.0', tk.END).strip()
            # 재처리: 쉼표로 분리 후 중복 제거하여 깔끔하게 저장
            merged_tokens = self._unique_preserve_order(self._tokenize_prompt(new_val))
            final_text = ', '.join(merged_tokens)
            self.prompt_entry.delete(0, tk.END)
            self.prompt_entry.insert(0, final_text)
            # 갱신 미리보기
            self.show_preset_preview(final_text)
            dlg.destroy()

        def cancel():
            dlg.destroy()

        apply_btn = ttk.Button(btn_frame, text="적용", command=apply_merged)
        apply_btn.pack(side=tk.RIGHT, padx=6)
        cancel_btn = ttk.Button(btn_frame, text="취소", command=cancel)
        cancel_btn.pack(side=tk.RIGHT)

        dlg.transient(self); dlg.grab_set(); self.wait_window(dlg)

    def on_booster_toggle(self, booster_name, var):
        is_enabled = var.get()
        action = "추가" if is_enabled else "제거"
        print(f"부스터 '{booster_name}' {action} 요청...")

        def task():
            try:
                if is_enabled:
                    self.crawler_manager.run_add_booster(booster_name)
                else:
                    self.crawler_manager.run_remove_booster(booster_name)
                print(f"부스터 '{booster_name}' {action} 완료.")
            except Exception as e:
                print(f"부스터 '{booster_name}' {action} 중 오류: {e}")
                # Revert checkbox state on failure
                self.after(0, lambda: var.set(not is_enabled))
                self.after(100, lambda e=e: messagebox.showerror("부스터 오류", f"'{booster_name}' {action} 중 오류가 발생했습니다:\n{e}"))
        
        threading.Thread(target=task, daemon=True).start()

    def sync_booster_ui_from_page(self):
        print("웹페이지의 부스터 상태와 GUI를 동기화합니다...")

        def task():
            try:
                active_boosters = self.crawler_manager.run_get_active_boosters()
                
                def update_gui():
                    for name, var in self.booster_vars.items():
                        if name in active_boosters:
                            var.set(True)
                        else:
                            var.set(False)
                    print("부스터 UI 동기화 완료.")
                
                self.after(0, update_gui)

            except Exception as e:
                print(f"부스터 상태 동기화 중 오류: {e}")
                self.after(100, lambda: messagebox.showwarning("동기화 오류", f"부스터 상태를 웹페이지와 동기화하는 데 실패했습니다:\n{e}"))

        threading.Thread(target=task, daemon=True).start()

    def update_booster_ui_state(self):
        pass

    def on_crawler_started(self, exception: Exception | None):
        """Callback executed when crawler initialization is complete."""
        self.set_ui_state(False)  # Re-enable UI
        self.update_booster_ui_state()
        if exception:
            print(f"크롤러 초기화 중 오류: {exception}")
            messagebox.showerror("크롤러 오류", f"크롤러 초기화에 실패했습니다:\n{exception}")
        else:
            print("크롤러가 준비되었습니다.")
            if not self.headless_var.get():
                self.sync_booster_ui_from_page()

    def on_headless_toggle(self):
        """Handles the event when the headless checkbox is toggled."""
        self.update_booster_ui_state()  # Update UI immediately
        is_headless = self.headless_var.get()
        mode = "활성화" if is_headless else "비활성화"
        if not messagebox.askyesno("크롤러 재시작", f"Headless 모드를 '{mode}'(으)로 변경합니다.\n크롤러를 재시작하시겠습니까?"):
            # User cancelled, revert the checkbox and the UI state
            self.headless_var.set(not is_headless)
            self.update_booster_ui_state()
            return

        print(f"Headless 모드 변경: {mode}. 크롤러를 재시작합니다...")
        self.set_ui_state(True) # Disable UI

        def restart_task():
            try:
                self.crawler_manager.stop()
                print("기존 크롤러가 종료되었습니다.")

                # The original start_crawler logic
                print("새로운 설정으로 크롤러를 시작합니다...")
                callback = lambda e: self.after(0, self.on_crawler_restarted, e)
                self.crawler_manager.start(self.headless_var.get(), on_done=callback)

            except Exception as e:
                print(f"크롤러 재시작 중 오류: {e}")
                self.after(0, lambda: self.set_ui_state(False))
                self.after(100, lambda e=e: messagebox.showerror("재시작 오류", f"크롤러 재시작 중 오류가 발생했습니다:\n{e}"))

        threading.Thread(target=restart_task, daemon=True).start()

    def on_crawler_restarted(self, exception: Exception | None):
        """Callback executed when crawler has been restarted."""
        self.set_ui_state(False) # Re-enable UI
        self.update_booster_ui_state()
        if exception:
            print(f"크롤러 재시작 중 오류: {exception}")
            messagebox.showerror("크롤러 오류", f"크롤러 재시작에 실패했습니다:\n{exception}")
        else:
            print("크롤러가 새로운 설정으로 준비되었습니다.")
            if not self.headless_var.get():
                self.sync_booster_ui_from_page()

    def start_crawler(self):
        """Starts the crawler manager after the GUI has loaded."""
        print("크롤러 초기화를 시작합니다...")
        self.set_ui_state(True)  # Disable UI during initialization
        # The callback needs to run in the main thread.
        # The `on_done` will be called from the background thread.
        callback = lambda e: self.after(0, self.on_crawler_started, e)
        self.crawler_manager.start(self.headless_var.get(), on_done=callback)

    def on_take_screenshot(self):
        """Handles the screenshot button click."""
        print("스크린샷을 요청합니다...")
        
        def task():
            try:
                screenshot_path = self.crawler_manager.run_take_screenshot()
                if screenshot_path:
                    # Schedule image loading on the main thread
                    self.after(0, self.load_generated_image, screenshot_path)
                else:
                    self.after(0, lambda: messagebox.showwarning("스크린샷 실패", "스크린샷을 생성하지 못했습니다."))
            except Exception as e:
                print(f"스크린샷 작업 중 오류 발생: {e}")
                self.after(100, lambda e=e: messagebox.showerror("스크린샷 오류", f"스크린샷 생성 중 오류가 발생했습니다:\n{e}"))

        # Run in a separate thread to avoid blocking the GUI
        threading.Thread(target=task, daemon=True).start()

    def show_license(self):
        license_window = tk.Toplevel(self)
        license_window.title("MIT License")
        license_window.geometry("600x400")
        license_window.transient(self)
        license_window.grab_set()

        mit_license_text = """
MIT License

Copyright (c) 2024 [Copyright Holder]

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
        
        text_area = scrolledtext.ScrolledText(license_window, wrap=tk.WORD, height=10)
        text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_area.insert(tk.END, mit_license_text.strip())
        text_area.config(state='disabled')

        close_button = ttk.Button(license_window, text="Close", command=license_window.destroy)
        close_button.pack(pady=5)
        
        self.wait_window(license_window)

    def on_close(self):
        # Disable all UI to prevent user interaction and show a closing message.
        self.set_ui_state(True) 
        print("프로그램 종료 중... 크롤러를 안전하게 종료합니다.")

        def shutdown_task():
            try:
                print("백그라운드에서 크롤러 종료를 시작합니다...")
                self.crawler_manager.stop()
                print("크롤러 종료 완료.")
            except Exception as e:
                print(f"크롤러 종료 중 오류 발생: {e}")
            finally:
                # After the background task is done, schedule destroying the window 
                # on the main thread.
                self.after(0, self.destroy)

        # Run the blocking stop() call in a background thread to keep the GUI responsive.
        threading.Thread(target=shutdown_task, daemon=True).start()


if __name__ == "__main__":
    # PyInstaller로 패키징된 경우, 실행 파일의 위치를 기준으로 작동하도록 경로를 수정합니다.
    if hasattr(sys, 'frozen') and getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))

    app = App()
    app.mainloop()
