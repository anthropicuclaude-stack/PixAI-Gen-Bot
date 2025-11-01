import os
import asyncio
import time
from datetime import datetime
from urllib.parse import urlparse
from playwright.async_api import async_playwright, Page, BrowserContext
from playwright_stealth import Stealth
import re
import difflib
import sys

if getattr(sys, 'frozen', False):
    # When running as a bundled app, tell Playwright to use the browsers installed in the user's AppData
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = os.path.join(os.path.expanduser("~"), "AppData", "Local", "ms-playwright")

class Logger:
    """Simple hierarchical logger with Unicode box drawing characters"""
    
    # Box drawing characters
    BOX_V = "│"      # Vertical line
    BOX_H = "─"      # Horizontal line
    BOX_VR = "├"     # Vertical and right
    BOX_DR = "┌"     # Down and right
    BOX_UR = "└"     # Up and right
    BOX_VL = "┤"     # Vertical and left
    
    # Status indicators
    SUCCESS = "✓"
    ERROR = "✗"
    WARNING = "⚠"
    INFO = "●"
    ARROW = "→"
    
    def __init__(self):
        self.indent_level = 0
        self.indent_str = "  "
    
    def _get_prefix(self):
        return self.indent_str * self.indent_level
    
    def _format_msg(self, msg, symbol=""):
        prefix = self._get_prefix()
        if symbol:
            return f"{prefix}{symbol} {msg}"
        return f"{prefix}{msg}"
    
    def section(self, title):
        """Print a major section header"""
        print(f"\n{'═' * 60}")
        print(f"  {title}")
        print(f"{'═' * 60}")
    
    def subsection(self, title):
        """Print a subsection header"""
        prefix = self._get_prefix()
        print(f"\n{prefix}{self.BOX_DR}{'─' * 50}")
        print(f"{prefix}{self.BOX_V} {title}")
        print(f"{prefix}{self.BOX_UR}{'─' * 50}")
    
    def info(self, msg):
        print(self._format_msg(msg, self.INFO))
    
    def success(self, msg):
        print(self._format_msg(msg, self.SUCCESS))
    
    def error(self, msg):
        print(self._format_msg(msg, self.ERROR))
    
    def warning(self, msg):
        print(self._format_msg(msg, self.WARNING))
    
    def step(self, msg):
        print(self._format_msg(msg, self.ARROW))
    
    def detail(self, msg):
        print(self._format_msg(msg, self.BOX_VR))
    
    def result(self, key, value):
        prefix = self._get_prefix()
        print(f"{prefix}{self.BOX_VR} {key}: {value}")
    
    def indent(self):
        """Increase indentation level"""
        self.indent_level += 1
    
    def dedent(self):
        """Decrease indentation level"""
        if self.indent_level > 0:
            self.indent_level -= 1
    
    def context(self, title):
        """Context manager for automatic indentation"""
        return LogContext(self, title)


class LogContext:
    """Context manager for automatic log indentation"""
    def __init__(self, logger, title=None):
        self.logger = logger
        self.title = title
    
    def __enter__(self):
        if self.title:
            self.logger.step(self.title)
        self.logger.indent()
        return self.logger
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logger.dedent()


# Create global logger instance
log = Logger()

if getattr(sys, 'frozen', False):
    # PyInstaller 환경
    script_dir = os.path.dirname(sys.executable)
    bundle_dir = sys._MEIPASS  # 압축 해제된 임시 폴더
else:
    # 개발 환경
    script_dir = os.path.dirname(os.path.abspath(__file__))
    bundle_dir = script_dir

# --- Constants and Setup ---
script_dir = os.path.dirname(os.path.abspath(__file__))
user_data_dir = os.path.join(script_dir, "playwright_user_data")
url = "https://pixai.art/ko/generator/image"


# --- Main Crawler Class ---
class PixaiCrawler:
    def __init__(self, headless: bool = True, USER_DATA_DIR: str = user_data_dir):
        self.IMG_PATTERN = re.compile(r"https://images-ng\.pixai\.art/gi/orig/.*")
        self.headless = headless
        self.USER_DATA_DIR = USER_DATA_DIR
        self.p = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self._response_handler = None
        # Stealth helper
        try:
            self._stealth = Stealth()
        except Exception:
            self._stealth = None

    async def _apply_stealth(self, context: BrowserContext | None):
        """주어진 BrowserContext에 stealth 적용. 실패해도 예외를 올리지 않음."""
        if not context or not self._stealth:
            return
        with log.context("Stealth 적용"):
            try:
                await self._stealth.apply_stealth_async(context)
                log.success("스텔스 적용 완료.")
                # 디버그용으로 navigator.webdriver 확인 (있으면 출력)
                try:
                    pages = context.pages
                    if pages:
                        val = await pages[0].evaluate("() => navigator.webdriver")
                        log.detail(f"navigator.webdriver after stealth: {val}")
                except Exception:
                    pass
            except Exception as e:
                log.error(f"스텔스 적용 실패: {e}")


    async def _run_first_time_setup(self):
        """
        최초 1회 실행 시, 사용자가 수동으로 로그인하고 설정을 저장하도록 안내합니다.
        이 메서드는 __aenter__에 의해 내부적으로 호출됩니다.
        """
        context = None
        try:
            async with async_playwright() as p:
                log.section("최초 1회 설정 모드")
                log.info("브라우저가 열리면 수동으로 로그인하세요.")
                log.info("로그인 완료 후, 브라우저를 닫으면 설정이 자동으로 저장됩니다.")

                # launch_persistent_context가 user_data_dir을 생성합니다.
                context = await p.chromium.launch_persistent_context(self.USER_DATA_DIR, headless=False)

                # apply stealth to the persistent context used for manual setup
                with log.context("설정 모드 Stealth 적용"):
                    try:
                        temp_stealth = Stealth()
                        await temp_stealth.apply_stealth_async(context)
                        log.success("스텔스 적용 완료.")
                    except Exception as se:
                        log.error(f"스텔스 적용 실패: {se}")

                
                page = await context.new_page()
                await page.goto(url, timeout=120000)

                log.info("브라우저 확대 비율을 100%로 초기화합니다.")
                await page.evaluate("document.body.style.zoom = '1.0'")
                
                log.info("페이지 로딩 및 설정 완료를 기다립니다...")
                # Wait for a reliable element that indicates the page is ready
                prompt_textarea_selector = 'section[class*="z-10"] textarea'
                await page.locator(prompt_textarea_selector).wait_for(state="visible", timeout=120000)

                ss_js_path = os.path.join(script_dir, "ss.js")
                with open(ss_js_path, 'r', encoding='utf-8') as f:
                    ss_js_content = f.read()

                await page.evaluate(ss_js_content)

                log.info("로그인 및 설정이 완료되었다면 브라우저를 닫아주세요.")
                await page.context.wait_for_event("close", timeout=0)
                
                log.success("브라우저 닫힘 감지됨. 설정이 저장되었습니다.")
                
        except Exception as e:
            log.error(f"설정 중 오류 발생: {e}")
            raise # 오류를 다시 발생시켜 상위 컨텍스트에서 처리하도록 함
        finally:
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
            log.info("최초 설정 절차를 종료합니다.")


    async def _is_logged_in(self, page: Page) -> bool:
        """Checks if the user is logged in by verifying the presence of specific login cookies."""
        with log.context("쿠키 기반 로그인 상태 확인"):
            try:
                # Get all cookies from the current browser context
                cookies = await page.context.cookies()
                
                # Check for the presence of 'user_token' and 'user_token_expire_at'
                cookie_names = {cookie['name'] for cookie in cookies}
                has_token = 'user_token' in cookie_names
                has_expire_at = 'user_token_expire_at' in cookie_names

                if has_token and has_expire_at:
                    log.success("쿠키를 발견했습니다. 로그인 상태로 판단합니다.")
                    return True
                else:
                    log.warning("쿠키가 없습니다. 로그아웃 상태로 판단합니다.")
                    log.detail(f"user_token 발견: {has_token}, user_token_expire_at 발견: {has_expire_at}")
                    return False
            except Exception as e:
                log.error(f"쿠키 확인 중 오류 발생: {e}. 로그아웃 상태로 간주합니다.")
                return False

    async def _verify_login_and_cleanup(self):
        """
        Launches a temporary browser to check login status. 
        If not logged in, it cleans up the user data directory.
        """
        if not os.path.exists(self.USER_DATA_DIR):
            return

        with log.context("기존 로그인 세션 유효성 검사"):
            p = None
            context = None
            try:
                p = await async_playwright().start()
                context = await p.chromium.launch_persistent_context(self.USER_DATA_DIR, headless=True)
                page = await context.new_page()
                await page.goto(url, timeout=60000, wait_until="domcontentloaded")

                if not await self._is_logged_in(page):
                    log.warning("유효하지 않은 세션을 감지했습니다. 사용자 데이터를 삭제합니다.")
                    await context.close()
                    context = None
                    await p.stop()
                    p = None
                    
                    import shutil
                    shutil.rmtree(self.USER_DATA_DIR)
                    log.success("사용자 데이터 삭제 완료.")
                else:
                    log.success("기존 세션이 유효합니다.")
            except Exception as e:
                log.error(f"로그인 검증 중 오류 발생: {e}. 안전을 위해 사용자 데이터를 삭제합니다.")
                if os.path.exists(self.USER_DATA_DIR):
                    import shutil
                    try:
                        if context: await context.close()
                        if p: await p.stop()
                        shutil.rmtree(self.USER_DATA_DIR)
                        log.success("사용자 데이터 삭제 완료.")
                    except Exception as cleanup_e:
                        log.error(f"검증 오류 후 사용자 데이터 삭제 실패: {cleanup_e}")
            finally:
                if context: await context.close()
                if p: await p.stop()

    async def __aenter__(self):
        if getattr(sys, 'frozen', False):
            playwright_browsers_path = os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
            log.info(f"PLAYWRIGHT_BROWSERS_PATH: {playwright_browsers_path}")
            if playwright_browsers_path and os.path.isdir(playwright_browsers_path):
                log.info(f"Contents of {playwright_browsers_path}:")
                for item in os.listdir(playwright_browsers_path):
                    log.info(f"- {item}")
            else:
                log.warning("PLAYWRIGHT_BROWSERS_PATH is not set or not a directory.")

        # 0. Verify existing user data if it exists, and clean up if invalid.
        await self._verify_login_and_cleanup()

        # 1. Check for first-time setup
        if not os.path.exists(self.USER_DATA_DIR):
            log.warning("사용자 프로필이 없습니다. 최초 설정을 시작합니다...")
            try:
                await self._run_first_time_setup()
            except Exception as e:
                # _run_first_time_setup에서 발생한 오류를 처리
                if os.path.exists(self.USER_DATA_DIR):
                    import shutil
                    try:
                        # 브라우저 프로세스가 파일 잠금을 해제할 시간을 줍니다.
                        await asyncio.sleep(2)
                        shutil.rmtree(self.USER_DATA_DIR)
                        log.warning(f"최초 설정 실패로 인해 생성된 사용자 프로필({self.USER_DATA_DIR})을 삭제했습니다.")
                    except Exception as cleanup_e:
                        log.error(f"사용자 프로필 디렉토리 삭제 실패: {cleanup_e}")
                raise Exception(f"최초 설정에 실패했습니다: {e}")
        
        # 2. Proceed with normal crawler launch
        self.p = await async_playwright().start()
        log.section("크롤러 시작")
        
        try:
            self.context = await self.p.chromium.launch_persistent_context(
                self.USER_DATA_DIR,
                headless=self.headless,
                user_agent="Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                args=[
                    '--disable-blink-features=AutomationControlled', "--no-sandbox", "--disable-infobars"
                ]
            )

            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

            try:
                await self._apply_stealth(self.context)
            except Exception as e:
                log.warning(f"스텔스 적용 시 예외 발생 (계속 진행): {e}")

            if url not in self.page.url:
                log.info(f"페이지 여는 중: {url}")
                await self.page.goto(url)

            # Final login verification after launch
            with log.context("최종 로그인 상태 검증"):
                if not await self._is_logged_in(self.page):
                    log.error("초기 설정 후에도 로그인이 확인되지 않았습니다. 사용자가 로그인하지 않고 설정 창을 닫았을 수 있습니다.")
                    await self.context.close()
                    await self.p.stop()
                    import shutil
                    if os.path.exists(self.USER_DATA_DIR):
                        shutil.rmtree(self.USER_DATA_DIR)
                    raise Exception("로그인 설정이 올바르게 완료되지 않았습니다. 프로그램을 다시 시작하여 로그인을 진행해주세요.")
                            
            if not self.headless:
                with log.context("헤드리스 모드가 아니므로, 브라우저 확대 비율을 100%로 초기화합니다."):
                    try:
                        await self.page.evaluate("document.body.style.zoom = '1.0'")
                    except Exception as e:
                        log.error(f"확대 비율 설정 실패: {e}")
            
            # Check for daily credits after page load
            await self.check_and_claim_daily_credit()
            
            # Disable helper features
            await self.disable_helper_features()
            
            log.success("크롤러 준비 완료.")
            return self
        except Exception as e:
            # If launch fails, stop playwright
            if self.p:
                await self.p.stop()
            raise e
        
    async def _find_and_click_button_by_text(self, text, timeout=5000):
        """
        Robustly find a <button> whose visible text includes `text` and click it.
        Returns True if clicked, False otherwise.
        """
        with log.context(f"'{text}' 버튼 찾기 및 클릭"):
            # 1) Fast try: playwright locator
            try:
                btn = self.page.locator(f'button:has-text("{text}")')
                await btn.first.wait_for(state="attached", timeout=1000)
                box = await btn.first.bounding_box()
                if box:
                    # try normal click first
                    try:
                        await btn.first.click(timeout=1500)
                        log.success("Playwright 로케이터로 클릭 성공.")
                        return True
                    except Exception:
                        # try mouse sequence
                        try:
                            await self.page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                            await self.page.mouse.down()
                            await self.page.mouse.up()
                            await self.page.wait_for_timeout(150)
                            log.success("Playwright 마우스 시퀀스로 클릭 성공.")
                            return True
                        except Exception:
                            pass
            except Exception:
                pass

            # 2) Fallback: document scan and diagnostics
            # returns list of candidates with outerHTML and bbox
            candidates = await self.page.evaluate(f"""
                (txt) => {{
                    const normalized = s => s && s.replace(/\\s+/g,' ').trim().toLowerCase();
                    const buttons = Array.from(document.querySelectorAll('button'));
                    const hits = [];
                    for (const b of buttons) {{
                        const t = normalized(b.textContent || '');
                        if (t.includes(normalized(txt))) {{
                            const r = b.getBoundingClientRect();
                            hits.push({{outer: b.outerHTML.slice(0,800), x:r.x, y:r.y, w:r.width, h:r.height, visible: !!(r.width&&r.height)}})
                        }}
                    }}
                    return hits;
                }}
            """, text)

            # debug log
            log.info(f"찾은 후보 수: {len(candidates)}")
            for i,c in enumerate(candidates):
                log.detail(f"candidate[{i}] visible={c['visible']} bbox=({c['x']},{c['y']},{c['w']},{c['h']}) html_snippet={c['outer'][:200]}")

            if not candidates:
                log.warning("클릭할 후보를 찾지 못했습니다.")
                return False

            # 3) Try clicking each candidate via safe flows: scroll -> CDP -> mouse -> pointer dispatch -> js click
            for i,c in enumerate(candidates):
                with log.context(f"후보 {i} 클릭 시도"):
                    try:
                        # scroll into view via evaluate (more reliable)
                        await self.page.evaluate("""
                            (x,y,w,h) => {
                                const el = document.elementFromPoint(x + w/2, y + h/2);
                                if (el) el.scrollIntoView({{block:'center', inline:'center', behavior:'instant'}});
                            }
                        """, c["x"], c["y"], c["w"], c["h"])
                        await self.page.wait_for_timeout(120)

                        # try CDP mouse events first (Chromium)
                        try:
                            cdp = await self.context.new_cdp_session(self.page)
                            x = c["x"] + c["w"]/2
                            y = c["y"] + c["h"]/2
                            await cdp.send("Input.dispatchMouseEvent", {"type":"mouseMoved","x":x,"y":y})
                            await cdp.send("Input.dispatchMouseEvent", {"type":"mousePressed","x":x,"y":y,"button":"left","clickCount":1})
                            await cdp.send("Input.dispatchMouseEvent", {"type":"mouseReleased","x":x,"y":y,"button":"left","clickCount":1})
                            await self.page.wait_for_timeout(200)
                            # quick check: did dialog appear?
                            dialog = self.page.locator('[role="dialog"]:has-text("부스터 추가")')
                            if await dialog.count() and await dialog.first.is_visible():
                                log.success("CDP 이벤트로 클릭 성공.")
                                return True
                        except Exception:
                            pass

                        # try Playwright mouse sequence at bounding box
                        try:
                            await self.page.mouse.move(c["x"] + c["w"]/2, c["y"] + c["h"]/2)
                            await self.page.mouse.down()
                            await self.page.wait_for_timeout(30)
                            await self.page.mouse.up()
                            await self.page.wait_for_timeout(200)
                            dialog = self.page.locator('[role="dialog"]:has-text("부스터 추가")')
                            if await dialog.count() and await dialog.first.is_visible():
                                log.success("마우스 시퀀스로 클릭 성공.")
                                return True
                        except Exception:
                            pass

                        # try pointer events dispatch on the element found by point (if any)
                        try:
                            ok = await self.page.evaluate("""
                                (x,y) => {
                                    const el = document.elementFromPoint(x,y);
                                    if(!el) return false;
                                    const r = el.getBoundingClientRect();
                                    const cx = Math.floor(r.left + r.width/2);
                                    const cy = Math.floor(r.top + r.height/2);
                                    ['pointerover','pointerenter','pointerdown','pointerup','click'].forEach(t=>{
                                        el.dispatchEvent(new PointerEvent(t,{{bubbles:true,cancelable:true,clientX:cx,clientY:cy,pointerId:1,pointerType:'mouse'}}));
                                    });
                                    return true;
                                }
                            """, c["x"] + c["w"]/2, c["y"] + c["h"]/2)
                            if ok:
                                await self.page.wait_for_timeout(200)
                                dialog = self.page.locator('[role="dialog"]:has-text("부스터 추가")')
                                if await dialog.count() and await dialog.first.is_visible():
                                    log.success("Pointer 이벤트 디스패치로 클릭 성공.")
                                    return True
                        except Exception:
                            pass

                        # final: JS click on element from point
                        try:
                            await self.page.evaluate("""
                                (x,y) => {
                                    const el = document.elementFromPoint(x,y);
                                    if (el) {{ el.click(); return true; }}
                                    return false;
                                }
                            """, c["x"] + c["w"]/2, c["y"] + c["h"]/2)
                            await self.page.wait_for_timeout(200)
                            dialog = self.page.locator('[role="dialog"]:has-text("부스터 추가")')
                            if await dialog.count() and await dialog.first.is_visible():
                                log.success("JavaScript 클릭으로 성공.")
                                return True
                        except Exception:
                            pass

                    except Exception as outer_e:
                        log.error(f"candidate[{i}] 클릭 시도 중 예외: {outer_e}")

            # 모두 실패
            log.error("모든 클릭 방법 실패.")
            return False

    async def _click_with_mouse(self, box):
        """마우스 시퀀스(신뢰된 이벤트)를 보냄."""
        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2
        await self.page.mouse.move(x, y)
        await self.page.mouse.down()
        await self.page.wait_for_timeout(40)
        await self.page.mouse.up()
        await self.page.wait_for_timeout(150)

    async def _click_with_cdp(self, box):
        """Chromium CDP Input.dispatchMouseEvent를 사용해 하드웨어 레벨 클릭을 보냄."""
        try:
            cdp = await self.context.new_cdp_session(self.page)
            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2
            await cdp.send("Input.dispatchMouseEvent", {"type":"mouseMoved","x":x,"y":y})
            await cdp.send("Input.dispatchMouseEvent", {"type":"mousePressed","x":x,"y":y,"button":"left","clickCount":1})
            await cdp.send("Input.dispatchMouseEvent", {"type":"mouseReleased","x":x,"y":y,"button":"left","clickCount":1})
            await self.page.wait_for_timeout(150)
            return True
        except Exception:
            return False

    async def _dispatch_pointer_sequence(self, el_handle):
        """PointerEvent 시퀀스를 직접 디스패치."""
        try:
            await self.page.evaluate(
                """el=>{
                    const r = el.getBoundingClientRect();
                    const cx = Math.floor(r.left + r.width/2);
                    const cy = Math.floor(r.top + r.height/2);
                    ['pointerover','pointerenter','pointerdown','pointerup','click'].forEach(t=>{
                        el.dispatchEvent(new PointerEvent(t,{
                            bubbles:true,cancelable:true,clientX:cx,clientY:cy,pointerId:1,pointerType:'mouse'
                        }));
                    });
                    return true;
                }""",
                el_handle
            )
            await self.page.wait_for_timeout(150)
            return True
        except Exception:
            return False

    async def _js_click(self, locator_js):
        """최후의 수단, JS에서 .click() 호출."""
        try:
            await self.page.evaluate(locator_js)
            await self.page.wait_for_timeout(150)
            return True
        except Exception:
            return False

    async def _wait_for_dialog_or_expanded(self, toggle_locator, dialog_selector, timeout=5000):
        """클릭 후 dialog 보이거나 aria-expanded 변경을 폴링해서 성공判定."""
        end = self.page._loop.time() + timeout / 1000.0
        while self.page._loop.time() < end:
            try:
                # 1) dialog 존재 확인
                if await self.page.locator(dialog_selector).is_visible():
                    return True
            except Exception:
                pass
            try:
                # 2) 토글 버튼 aria-expanded 체크 (있다면 true로 바뀌는지)
                ae = await toggle_locator.get_attribute("aria-expanded")
                if ae and ae.lower() == "true":
                    return True
            except Exception:
                pass
            await self.page.wait_for_timeout(150)
        return False


    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.context:
            await self.context.close()
        if self.p:
            await self.p.stop()
        log.section("크롤러 종료")

    async def check_and_claim_daily_credit(self):
        """
        Checks for and claims the daily credit modal if it appears.
        """
        with log.context("매일 크레딧 보상 확인"):
            try:
                # Use a selector for the dialog content that contains the specific title
                modal_selector = 'div[data-ui="dialog-content"]:has-text("매일 크레딧")'
                
                # Wait for the modal to appear, but with a short timeout
                await self.page.locator(modal_selector).wait_for(state="visible", timeout=3000)
                log.info("매일 크레딧 보상을 발견했습니다.")

                # Find the button to claim credits
                claim_button_regex = re.compile(r"매일 크레딧 ([\d,]+) 받아보세요")
                claim_button = self.page.get_by_role("button", name=claim_button_regex)
                
                button_text = await claim_button.inner_text()
                match = claim_button_regex.search(button_text)
                
                if match:
                    credits_amount = match.group(1)
                    log.info(f"'{credits_amount}' 크레딧 수령을 시도합니다...")
                    await claim_button.click(timeout=2000)
                    log.success(f"크레딧 {credits_amount}을(를) 수령했습니다.")
                    await self.page.get_by_role("button", name="닫기").click(timeout=2000)
                else:
                    log.warning("크레딧을 수령했지만, 크레딧 양을 확인할 수 없습니다.")
                    await claim_button.click(timeout=2000)

            except Exception as e:
                log.info(f"매일 크레딧 보상을 이미 받았거나, 찾을 수 없습니다. 계속 진행합니다.")

    async def take_screenshot(self) -> str | None:
        """
        Takes a screenshot of the current page and saves it to a file.
        Returns the absolute path to the saved screenshot file.
        """
        if not self.page:
            log.error("스크린샷을 찍을 페이지가 없습니다.")
            return None
        
        with log.context("스크린샷 저장"):
            try:
                # Create a unique filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"manual_screenshot_{timestamp}.png"
                
                # Ensure the 'generated' directory exists
                output_dir = "screenshot"
                os.makedirs(output_dir, exist_ok=True)
                
                filepath = os.path.join(output_dir, filename)
                
                await self.page.screenshot(path=filepath)
                
                log.success(f"스크린샷을 저장했습니다: {filepath}")
                return filepath
            except Exception as e:
                log.error(f"스크린샷 저장 중 오류 발생: {e}")
                return None

    async def disable_helper_features(self):
        """
        Checks for and disables "Autocomplete" and "Prompt Helper" if they are enabled.
        """
        with log.context("자동 완성 및 프롬프트 도우미 기능 비활성화"):
            try:
                # --- 1. Disable "자동 완성" (Autocomplete) ---
                autocomplete_label = self.page.locator('label:has-text("자동 완성")')
                
                await autocomplete_label.wait_for(state="attached", timeout=5000)

                is_selected = await autocomplete_label.get_attribute("data-selected")
                if is_selected == "true":
                    log.info("'자동 완성' 기능이 활성화되어 있어 비활성화를 시도합니다.")
                    await autocomplete_label.click()
                    await self.page.wait_for_function(
                        "el => el.getAttribute('data-selected') !== 'true'",
                        autocomplete_label,
                        timeout=5000
                    )
                    log.success("'자동 완성' 기능이 비활성화되었습니다.")
                else:
                    log.info("'자동 완성' 기능이 이미 비활성화 상태입니다.")

            except Exception:
                log.warning("'자동 완성' 스위치를 찾지 못했습니다. 계속 진행합니다.")

            try:
                # --- 2. Disable "프롬프트 도우미" (Prompt Helper) ---
                prompt_helper_label = self.page.locator('label:has-text("프롬프트 도우미")')

                await prompt_helper_label.wait_for(state="attached", timeout=5000)

                is_selected = await prompt_helper_label.get_attribute("data-selected")
                if is_selected == "true":
                    log.info("'프롬프트 도우미' 기능이 활성화되어 있어 비활성화를 시도합니다.")
                    await prompt_helper_label.click()
                    await self.page.wait_for_function(
                        "el => el.getAttribute('data-selected') !== 'true'",
                        prompt_helper_label,
                        timeout=5000
                    )
                    log.success("'프롬프트 도우미' 기능이 비활성화되었습니다.")
                else:
                    log.info("'프롬프트 도우미' 기능이 이미 비활성화 상태입니다.")

            except Exception:
                log.warning("'프롬프트 도우미' 스위치를 찾지 못했습니다. 계속 진행합니다.")

    async def add_booster(self, booster_name: str):
        with log.context(f"부스터 추가: {booster_name}"):
            try:
                clicked = await self._find_and_click_button_by_text("부스터 추가", timeout=5000)
                if not clicked:
                    path = await self.take_screenshot()
                    log.error(f"부스터 다이얼로그를 열 수 없습니다. 스크린샷: {path}")
                    raise Exception("부스터 다이얼로그가 열리지 않음 (headless 특이).")

                # 다이얼로그가 열렸는지 확실히 대기
                dialog = self.page.locator('[role="dialog"]:has-text("부스터 추가")')
                await dialog.wait_for(state="visible", timeout=5000)
                booster_item = dialog.locator(f'li:has-text("{booster_name}")')
                await booster_item.wait_for(state="visible", timeout=3000)
                add_button = booster_item.get_by_role("button", name="추가")
                await add_button.click()
                log.success(f"'{booster_name}' 부스터 추가 완료.")
                await dialog.get_by_role("button").first.click()
                await dialog.wait_for(state="hidden", timeout=5000)

            except Exception as e:
                log.error(f"'{booster_name}' 부스터 추가 중 오류 발생: {e}")
                # 닫기 시도
                try:
                    dialog = self.page.locator('[role="dialog"]:has-text("부스터 추가")')
                    if await dialog.is_visible():
                        await dialog.get_by_role("button").first.click()
                except Exception:
                    pass
                raise

    async def remove_booster(self, booster_name: str):
        with log.context(f"부스터 제거: {booster_name}"):
            try:
                # 1단계: 부스터 컨테이너 찾기
                booster_container = self.page.locator(f'div[style*="order"]:has(div.content:text-is("{booster_name}"))')
                await booster_container.wait_for(state="visible", timeout=3000)
                
                # 2단계: 제거 버튼 찾기 (여러 방법 시도)
                button_clicked = False
                
                # 시도 1: 일반 클릭
                with log.context("일반 클릭 시도"):
                    try:
                        remove_button = booster_container.get_by_role("button").nth(1)
                        await remove_button.click(timeout=2000)
                        button_clicked = True
                        log.success(f"'{booster_name}' 부스터 제거 완료.")
                    except Exception as e1:
                        log.warning(f"일반 클릭 실패: {e1}, 강제 클릭 시도...")
                
                # 시도 2: 강제 클릭
                if not button_clicked:
                    with log.context("강제 클릭 시도"):
                        try:
                            remove_button = booster_container.get_by_role("button").nth(1)
                            await remove_button.click(force=True, timeout=2000)
                            button_clicked = True
                            log.success(f"'{booster_name}' 부스터 제거 완료.")
                        except Exception as e2:
                            log.warning(f"강제 클릭 실패: {e2}, JavaScript 클릭 시도...")
                
                # 시도 3: JavaScript 클릭
                if not button_clicked:
                    with log.context("JavaScript 클릭 시도"):
                        await self.page.evaluate(f"""
                            () => {{
                                const containers = Array.from(document.querySelectorAll('div[style*="order"]'));
                                const targetContainer = containers.find(container => {{
                                    const contentDiv = container.querySelector('div.content');
                                    return contentDiv && contentDiv.textContent.trim() === '{booster_name}';
                                }});
                                if (targetContainer) {{
                                    const buttons = targetContainer.querySelectorAll('button');
                                    if (buttons.length >= 2) {{
                                        buttons[1].click();
                                        return true;
                                    }}
                                }}
                                return false;
                            }}
                        """)
                        button_clicked = True
                        log.success(f"'{booster_name}' 부스터 제거 완료.")
                
                # 제거 확인을 위한 짧은 대기
                await self.page.wait_for_timeout(500)
                
            except Exception as e:
                log.error(f"'{booster_name}' 부스터 제거 중 오류 발생: {e}")
                raise

    async def remove_lora(self, lora_name: str):
        with log.context(f"LoRA 제거: {lora_name}"):
            try:
                # LoRA 이름을 포함하는 링크를 먼저 찾습니다.
                lora_link = self.page.locator(f'a.font-bold.text-sm.break-words:has-text("{lora_name}")')
                
                # 링크의 상위 컨테이너(LoRA 카드)를 찾습니다.
                lora_container = lora_link.locator('xpath=ancestor::div[contains(@class, "relative") and contains(@class, "flex") and contains(@class, "bg-background-light")]')
                await lora_container.wait_for(state="visible", timeout=3000)
                
                # 제거 버튼을 찾습니다 (일반적으로 두 번째 버튼).
                remove_button = lora_container.get_by_role("button").nth(1)
                
                # 여러 방법으로 클릭 시도
                try:
                    await remove_button.click(timeout=2000)
                    log.success(f"'{lora_name}' LoRA 제거 완료 (일반 클릭).")
                except Exception:
                    log.warning("일반 클릭 실패, 강제 클릭 시도...")
                    await remove_button.click(force=True, timeout=2000)
                    log.success(f"'{lora_name}' LoRA 제거 완료 (강제 클릭).")

                # 제거 확인을 위한 짧은 대기
                await self.page.wait_for_timeout(500)
                
            except Exception as e:
                log.error(f"'{lora_name}' LoRA 제거 중 오류 발생: {e}")
                # JavaScript를 사용한 최후의 수단
                with log.context("JavaScript 클릭으로 재시도"):
                    try:
                        await self.page.evaluate(f'''
                            () => {{
                                const allCards = document.querySelectorAll('.relative.flex.gap-3.bg-background-light.p-2.rounded-xl');
                                for (const card of allCards) {{
                                    const nameLink = card.querySelector('a.font-bold.text-sm');
                                    if (nameLink && nameLink.textContent.trim() === '{lora_name}') {{
                                        const buttons = card.querySelectorAll('button');
                                        if (buttons.length > 1) {{
                                            buttons[1].click();
                                            return true;
                                        }}
                                    }}
                                }}
                                return false;
                            }}
                        ''')
                        log.success(f"'{lora_name}' LoRA 제거 완료 (JavaScript 클릭).")
                    except Exception as e2:
                        log.error(f"'{lora_name}' LoRA 제거 최종 실패: {e2}")
                        raise

    async def get_active_boosters(self) -> list[str]:
        with log.context("활성화된 부스터 목록 가져오기"):
            try:
                booster_containers = self.page.locator('div[style*="order"]:has(div.content)')
                
                count = await booster_containers.count()
                if count == 0:
                    log.info("활성화된 부스터가 없습니다.")
                    return []

                active_boosters = []
                for i in range(count):
                    container = booster_containers.nth(i)
                    name = await container.locator('div.content').inner_text()
                    if name:
                        active_boosters.append(name)
                
                log.result("활성화된 부스터", active_boosters)
                return active_boosters
            except Exception as e:
                log.error(f"활성화된 부스터를 가져오는 중 오류 발생: {e}")
                return []

    async def get_active_loras(self) -> list[str]:
        """현재 활성화된 LoRA의 이름 목록을 가져옵니다."""
        with log.context("활성화된 LoRA 이름 목록 가져오기"):
            try:
                config = await self.get_active_config()
                return [lora.get('name') for lora in config.get('loras', []) if lora.get('name')]
            except Exception as e:
                log.error(f"활성화된 LoRA 목록 가져오기 실패: {e}")
                return []



    async def set_model(self, model_info: tuple):
        if not model_info or not model_info[0]:
            log.info("모델 설정 건너뜀: 설정할 모델 이름이 없습니다.")
            return

        model_name, model_version = model_info
        log.section(f"UI 모델 설정 실행: {model_name} (버전: {model_version or '최신'})")

        DEFAULT_TIMEOUT = 15000

        try:
            # 1. 생성 페이지로 이동 확인
            if "/generator/image" not in self.page.url:
                with log.context("생성 페이지로 이동"):
                    await self.page.get_by_role("button", name="생성").click()
                    await self.page.wait_for_url("**/generator/image", timeout=DEFAULT_TIMEOUT)
                    await self.page.locator('section[class*="z-10"] textarea').wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
                    log.success("UI 로드 완료. 모델 선택 패널을 엽니다.")
            # 2. 모델 선택
            with log.context("모델 선택"):
                log.step("'모델 더 보기' 버튼을 클릭합니다.")
                model_button = self.page.locator('button:has-text("모델 더 보기")')
                await model_button.click(timeout=3000)
                await self.page.wait_for_timeout(500)
                await self.page.get_by_role("tab", name="마켓").click()
                model_search_input = self.page.locator('input[placeholder="모델 이름으로 검색"]')
                try:
                    await model_search_input.wait_for(state="visible", timeout=3000)
                except Exception:
                    log.info("모델 검색창이 보이지 않아 검색 아이콘을 클릭합니다.")
                    search_icon_button = self.page.locator('button.MuiIconButton-root.ml-auto:has(svg.size-6)')
                    await search_icon_button.click()
                    await model_search_input.wait_for(state="visible", timeout=3000)

                log.info(f"모델 검색: {model_name}")
                await model_search_input.fill(model_name)
                model_result_locator = self.page.locator(f'a:has-text("{model_name}")').first
                await model_result_locator.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
                await model_result_locator.click()
            # 3. 모델 버전 선택 (선택적)
            with log.context("모델 버전 선택"):
                try:
                    version_selector = self.page.get_by_label("버전")
                    await version_selector.wait_for(state="visible", timeout=3000)
                    await version_selector.click()

                    version_list = self.page.locator('ul[role="listbox"]')
                    await version_list.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

                    if model_version and model_version.strip():
                        await version_list.locator(f'li[role="option"]:has-text("{model_version}")').click()
                    else:
                        await version_list.locator('li[role="option"]').first.click()
                    await version_list.wait_for(state="hidden", timeout=DEFAULT_TIMEOUT)
                except Exception:
                    log.info("버전 선택기가 없거나 사용할 수 없습니다. 계속 진행합니다.")
            # 4. 모델 사용 버튼 클릭
            use_model_button = self.page.get_by_role("button", name="이 모델 사용")
            await use_model_button.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
            await use_model_button.click()

            log.success(f"'{model_name}' 모델 사용 설정 완료.")
        except Exception as e:
            log.error(f"모델 설정 매크로 실행 중 오류 발생: {e}")
            raise

    async def set_loras(self, loras: list):
        log.section(f"UI LoRA 설정 실행: {len(loras)}개")
        DEFAULT_TIMEOUT = 15000
        try:
            # 1. 기존 LoRA 모두 제거
            with log.context("기존 LoRA 제거"):
                active_lora_names = await self.get_active_loras()
                if active_lora_names:
                    for lora_name in active_lora_names:
                        await self.remove_lora(lora_name)
                    log.success("기존 LoRA 제거 완료.")
                else:
                    log.info("제거할 기존 LoRA가 없습니다.")
            if not loras:
                log.info("설정할 LoRA가 없습니다. LoRA 설정이 완료되었습니다.")
                return ""
            # 2. LoRA 선택 패널 열기
            with log.context("LoRA 선택 패널 열기"):
                await self.page.locator('button:has-text("로라 더 보기")').click()
                await self.page.wait_for_timeout(500)
                await self.page.get_by_role("tab", name="마켓").click()

            # 3. LoRA 검색 및 선택
            lora_search_input = self.page.locator('input[placeholder="LoRA 이름으로 검색"]')
            await self.page.wait_for_timeout(500)
            for lora_info in loras:
                with log.context(f"LoRA 검색 및 선택: {lora_info['name']}"):
                    lora_name = lora_info['name']
                    log.info(f"LoRA 검색: {lora_name}")
                    await lora_search_input.fill(lora_name)
                    await self.page.wait_for_timeout(2000) # Wait for search results to load

                    # --- New logic to find best match ---
                    results_locator = self.page.locator('div.virtuoso-grid-item:has(label:not(.Mui-disabled))')
                    
                    # 3. 결과가 나타날 때까지 대기
                    try:
                        await results_locator.first.wait_for(state='visible', timeout=5000)
                    except:
                        log.error(f"'{lora_name}'에 대한 검색 결과를 찾을 수 없습니다.")
                        return False
                    
                    # 4. 카운트 확인
                    count = await results_locator.count()
                    log.info(f"검색 결과: {count}개 항목 발견")
                    
                    if count == 0:
                        log.warning("선택 가능한 LoRA가 없습니다. 기존 방식으로 재시도합니다.")
                        try:
                            lora_result_locator = self.page.locator(f'a:has-text("{lora_name}")').first
                            await lora_result_locator.wait_for(state='visible', timeout=5000)
                            await lora_result_locator.click()
                            await self.page.wait_for_timeout(1000)
                            log.success(f"'{lora_name}' LoRA 선택됨 (기존 방식).")
                            return True
                        except:
                            log.error(f"기존 방식으로도 '{lora_name}'를 찾을 수 없습니다.")
                            return False
                    
                    # 5. 모든 타이틀 수집 (개선된 방법)
                    exact_match_index = -1
                    best_match_index = -1
                    highest_similarity = -1.0
                    all_titles = []
                    
                    for i in range(count):
                        item_locator = results_locator.nth(i)
                        
                        # title 속성에서 가져오기
                        title_attr = await item_locator.locator('label').get_attribute('title')
                        
                        # 또는 p 태그의 텍스트에서 가져오기 (fallback)
                        if not title_attr:
                            title_text = await item_locator.locator('p.font-semibold').text_content()
                            title = title_text.strip() if title_text else ""
                        else:
                            title = title_attr.strip()
                        
                        all_titles.append(title)
                        log.detail(f"  [{i}] {title}")
                        
                        if not title:
                            continue
                        
                        # 정확한 일치 확인
                        if title.lower() == lora_name.lower():
                            exact_match_index = i
                            break
                        
                        # 유사도 계산
                        similarity = difflib.SequenceMatcher(None, lora_name.lower(), title.lower()).ratio()
                        if similarity > highest_similarity:
                            highest_similarity = similarity
                            best_match_index = i
                    
                    # 6. 선택할 인덱스 결정
                    target_index = -1
                    selected_lora_name = ""
                    
                    if exact_match_index != -1:
                        target_index = exact_match_index
                        selected_lora_name = all_titles[target_index]
                        log.success(f"정확한 일치: '{selected_lora_name}'")
                    elif best_match_index != -1 and highest_similarity > 0.6:  # 유사도 임계값 추가
                        target_index = best_match_index
                        selected_lora_name = all_titles[best_match_index]
                        log.info(f"유사 항목 선택: '{selected_lora_name}' (유사도: {highest_similarity:.2f})")
                    else:
                        if count > 0:
                            target_index = 0
                            selected_lora_name = all_titles[0] if all_titles and all_titles[0] else lora_name
                            log.warning(f"유사 항목 없음. 첫 번째 결과 선택: '{selected_lora_name}'")
                        else:
                            raise Exception(f"LoRA '{lora_name}'에 대한 검색 결과가 없습니다.")
                    
                    # 7. 클릭 (더 안전한 방법)
                    target_item = results_locator.nth(target_index)
                    
                    # 아이템이 보이도록 스크롤
                    await target_item.scroll_into_view_if_needed()
                    await self.page.wait_for_timeout(500)
                    
                    # 클릭
                    await target_item.locator('a').click()
                    await self.page.wait_for_timeout(1000)

            # 4. 최종 확인
            await self.page.wait_for_timeout(1000)
            confirm_button = self.page.get_by_role("button", name="확인")
            await confirm_button.click()
            # 5. 가중치 설정

            for lora_info in loras:
                lora_name = lora_info['name']
                lora_weight = lora_info.get('weight')

                if lora_weight is not None:
                    with log.context(f"'{lora_name}'의 가중치를 '{lora_weight}'로 설정"):
                        try:
                            # 더 정확한 선택자 사용: LoRA 카드 컨테이너 찾기
                            # 1. 먼저 해당 LoRA 이름을 가진 링크 찾기
                            lora_link = self.page.locator(f'a.font-bold.text-sm.break-words:has-text("{lora_name}")')
                            
                            # 2. 그 링크의 부모 컨테이너(LoRA 카드) 찾기
                            lora_container = lora_link.locator('xpath=ancestor::div[contains(@class, "relative") and contains(@class, "flex") and contains(@class, "bg-background-light")]')
                            
                            # 3. 해당 컨테이너 내의 MUI 입력 필드 찾기
                            weight_input = lora_container.locator('input.MuiInputBase-input.MuiInput-input[type="number"]')
                            
                            # 입력 필드가 보일 때까지 대기
                            await weight_input.wait_for(state="visible", timeout=3000)
                            
                            # 기존 값 지우고 새 값 입력
                            await weight_input.click()
                            await weight_input.fill("")  # 먼저 지우기
                            await weight_input.fill(str(lora_weight))
                            await weight_input.press("Enter")  # Enter로 확정
                            
                            log.success(f"가중치 설정 완료: {lora_weight}")
                            
                        except Exception as e:
                            log.error(f"'{lora_name}'의 가중치 설정 중 오류 발생: {e}")
                            # 대체 방법 시도
                            with log.context("대체 선택자로 재시도"):
                                try:
                                    # 더 단순한 접근: 모든 LoRA 카드를 순회하며 이름 매칭
                                    all_cards = self.page.locator('div.relative.flex.gap-3.bg-background-light.p-2.rounded-xl')
                                    card_count = await all_cards.count()
                                    
                                    for i in range(card_count):
                                        card = all_cards.nth(i)
                                        card_text = await card.inner_text()
                                        
                                        if lora_name in card_text:
                                            weight_input = card.locator('input.MuiInputBase-input[type="number"]')
                                            await weight_input.click()
                                            await weight_input.fill(str(lora_weight))
                                            await weight_input.press("Enter")
                                            log.success(f"대체 방법으로 가중치 설정 완료")
                                            break
                                except Exception as e2:
                                    log.error(f"대체 방법도 실패: {e2}")


            await self.page.wait_for_timeout(500)

            log.success("모델/LoRA 설정이 완료되었습니다.")
            # 6. 트리거 워드 반환

            prompt_textarea = self.page.locator('section[class*="z-10"] textarea')
            await prompt_textarea.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

            trigger_words = await prompt_textarea.input_value()
            log.info(f"가져온 트리거 워드: {trigger_words or '없음'}")
            return trigger_words

        except Exception as e:
            log.error(f"LoRA 설정 매크로 실행 중 오류 발생: {e}")
            raise

    async def image_gen_macro(self, prompt_text: str, output_dir: str = "."):
        log.section(f"이미지 생성 실행: {prompt_text[:30]}...")
        DEFAULT_TIMEOUT = 30000 # 30초로 늘림

        os.makedirs(output_dir, exist_ok=True)

        saved_urls = set()
        saved_files = []
        save_tasks = []

        async def _handle_response(response):
            try:
                url = response.url
                if self.IMG_PATTERN.match(url) and url not in saved_urls:
                    saved_urls.add(url)
                    # ... (rest of the function is unchanged)
                    path = urlparse(url).path
                    basename = os.path.basename(path)
                    name, ext = os.path.splitext(basename)
                    if not name:
                        name = f"pixai_{int(time.time()*1000)}"
                    filename_base = name
                    filename = f"{filename_base}.png"
                    outpath = os.path.join(output_dir, filename)
                    counter = 1
                    while os.path.exists(outpath):
                        outpath = os.path.join(output_dir, f"{filename_base}_{counter}.png")
                        counter += 1
                    log.info(f"다운로드 감지: {url} -> {outpath}")
                    body = await response.body()
                    with open(outpath, "wb") as f:
                        f.write(body)
                    saved_files.append(outpath)
                    log.success(f"저장 완료: {outpath}")
            except Exception as e:
                log.error(f"응답 처리 중 오류: {e}")

        response_handler = lambda resp: save_tasks.append(asyncio.create_task(_handle_response(resp)))
        self.page.on("response", response_handler)

        try:
            if "generator/image" not in self.page.url:
                with log.context("생성 페이지로 이동"):
                    await self.page.get_by_role("button", name="생성").click()
                    await self.page.wait_for_url("**/generator/image", timeout=DEFAULT_TIMEOUT)
            
            log.info("생성 페이지를 기다립니다...")
            prompt_textarea_selector = 'section[class*="z-10"] textarea'
            await self.page.locator(prompt_textarea_selector).wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

            # 1. Fill the prompt
            log.step("프롬프트를 입력했습니다.")
            await self.page.locator(prompt_textarea_selector).fill(prompt_text)

            # 2. Click generate
            await self.page.get_by_role("button", name="생성!").click()

            # 3. Check for the "prompt cannot be empty" error toast
            try:
                toast_selector = 'div.Toastify__toast--warning:has-text("프롬프트는 비워 둘 수 없습니다.")'
                toast = self.page.locator(toast_selector)
                await toast.wait_for(state="visible", timeout=2000)
                
                log.warning("'프롬프트 비워둘 수 없음' 알림 감지. 재시도합니다.")
                
                # Try to close the toast before retrying
                close_button = toast.locator('button[aria-label="close"]')
                if await close_button.is_visible():
                    await close_button.click()
                    await toast.wait_for(state="hidden", timeout=2000)

                log.step("프롬프트를 다시 입력했습니다.")
                await self.page.locator(prompt_textarea_selector).fill(prompt_text)
                await self.page.get_by_role("button", name="생성!").click()

                toast_selector = 'div.Toastify__toast--warning:has-text("프롬프트는 비워 둘 수 없습니다.")'
                toast = self.page.locator(toast_selector)
                await toast.wait_for(state="visible", timeout=2000)
            except Exception:
                # Timeout means toast did NOT appear, which is the success case.
                log.success("생성 요청 성공. 이미지 응답을 대기합니다...")

            TOTAL_TIMEOUT = 600_000
            IDLE_WAIT = 3.0
            start_ts = time.time()
            last_seen = time.time()
            prev_count = 0

            with log.context("이미지 응답 대기"):
                while (time.time() - start_ts) * 1000 < TOTAL_TIMEOUT:
                    await asyncio.sleep(0.5)
                    if len(saved_urls) != prev_count:
                        prev_count = len(saved_urls)
                        last_seen = time.time()
                    if saved_urls and (time.time() - last_seen) > IDLE_WAIT:
                        log.info("일정 시간 동안 새 이미지가 감지되지 않아 대기를 중단합니다.")
                        break
                
                if not save_tasks and not saved_files:
                     log.warning(f"{TOTAL_TIMEOUT/1000}초 동안 이미지 응답이 없습니다. 타임아웃.")

            if save_tasks:
                await asyncio.gather(*save_tasks, return_exceptions=True)

            if not saved_files:
                with log.context("대체 이미지 저장 (스크린샷)"):
                    log.warning("원본 이미지 응답을 찾지 못했습니다. UI에서 직접 이미지를 저장하는 대체 로직을 시도합니다.")
                    image_locator = self.page.locator('div[class*="relative"] img[class*="w-full"]')
                    try:
                        await image_locator.last.wait_for(state="visible", timeout=10000)
                        image_count = await image_locator.count()
                        if image_count > 0:
                            final_image = image_locator.nth(image_count - 1)
                            fallback_name = os.path.abspath(os.path.join(output_dir, f"pixai_fallback_{int(time.time())}.png"))
                            await final_image.screenshot(path=fallback_name)
                            log.success(f"요소 스크린샷 저장: {fallback_name}")
                            saved_files.append(fallback_name)
                        else:
                            log.error("생성된 이미지 요소를 찾을 수 없습니다.")
                    except Exception as e:
                        log.error(f"대체 스크린샷 저장 중 오류 발생: {e}")

            log.info(f"총 저장된 항목: {len(saved_files)}")
            return saved_files

        except Exception as e:
            log.error(f"매크로 실행 중 오류 발생: {e}")
            # 스크린샷을 찍어 디버깅 정보 제공
            debug_path = os.path.join(script_dir, "headless_error_screenshot.png")
            try:
                await self.page.screenshot(path=debug_path)
                log.info(f"오류 발생 시점의 스크린샷을 저장했습니다: {debug_path}")
            except Exception as se:
                log.error(f"오류 스크린샷 저장 실패: {se}")
            return None
        finally:
            try:
                self.page.remove_listener("response", response_handler)
            except Exception:
                pass

    async def get_active_config(self):
        with log.context("현재 설정된 모델/LoRA 확인"):
            try:
                # 모델 정보 추출
                model_info = await self.page.evaluate('''() => {
                    const modelHeader = document.querySelector('.px-4.py-2.bg-background-light.rounded-xl');
                    if (!modelHeader) return null;
                    const modelNameLink = modelHeader.querySelector('a[href*="/ko/model/"]:first-of-type') || modelHeader.querySelector('a[href*="/model/"]:first-of-type');
                    const modelName = modelNameLink ? modelNameLink.textContent.trim() : '';
                    const modelVersionLink = modelHeader.querySelector('a.font-mono.text-xs');
                    const modelVersion = modelVersionLink ? modelVersionLink.textContent.trim() : '';
                    return { model_name: modelName, model_version: modelVersion };
                }''')

                # LoRA 정보 추출 (0..15개, 이름+가중치만)
                loras_info = await self.page.evaluate('''() => {
                    const sections = Array.from(document.querySelectorAll('section'));
                    const loraSection = sections.find(s => {
                        const h2 = s.querySelector('h2');
                        return h2 && h2.textContent.trim().toLowerCase().includes('lora');
                    });
                    if (!loraSection) return [];

                    const cards = Array.from(loraSection.querySelectorAll('div.relative.flex.gap-3.bg-background-light.p-2.rounded-xl'));
                    const loras = [];
                    for (const card of cards) {
                        // 이름
                        const nameEl = card.querySelector('a.font-bold.text-sm, a.font-bold, a[href*="/ko/model/"], a[href*="/model/"]');
                        const name = nameEl ? nameEl.textContent.trim() : '';
                        if (!name) continue;

                        // 가중치 추출 우선순위: number -> range -> aria-valuenow -> slider label -> 기본 0.7
                        let weight = 0.7;
                        const numberInput = card.querySelector('input[type="number"]');
                        const rangeInput = card.querySelector('input[type="range"]');
                        if (numberInput && numberInput.value !== undefined && numberInput.value !== '') {
                            const p = parseFloat(numberInput.value);
                            if (!isNaN(p)) weight = p;
                        } else if (rangeInput && rangeInput.value !== undefined && rangeInput.value !== '') {
                            const p = parseFloat(rangeInput.value);
                            if (!isNaN(p)) weight = p;
                        } else {
                            const ariaNode = card.querySelector('[aria-valuenow]');
                            if (ariaNode) {
                                const p = parseFloat(ariaNode.getAttribute('aria-valuenow') || ariaNode.value || ariaNode.getAttribute('value'));
                                if (!isNaN(p)) weight = p;
                            } else {
                                const valueLabel = card.querySelector('.MuiSlider-valueLabelLabel, .MuiSlider-valueLabelLabel');
                                if (valueLabel) {
                                    const p = parseFloat(valueLabel.textContent.trim());
                                    if (!isNaN(p)) weight = p;
                                }
                            }
                        }

                        loras.push({ name: name, weight: weight });
                        if (loras.length >= 15) break; // 최대 15개
                    }
                    return loras;
                }''')

                # 안전하게 파이썬 쪽에서도 최대 15개로 자름
                if loras_info and isinstance(loras_info, list) and len(loras_info) > 15:
                    loras_info = loras_info[:15]

                if not model_info:
                    return {'model_name': 'unknown_model', 'model_version': 'unknown_version', 'loras': loras_info or []}

                result = {
                    'model_name': model_info.get('model_name', 'unknown'),
                    'model_version': model_info.get('model_version', 'unknown'),
                    'loras': loras_info or []
                }

                log.result("모델", f"{result['model_name']} ({result['model_version']})")
                log.result("LoRA 개수", len(result['loras']))
                for lora in result['loras']:
                    log.detail(f"{lora['name']} : {lora['weight']}")

                return result

            except Exception as e:
                log.error(f"설정 정보 크롤링 실패 - {e}")
                return {'model_name': 'error_reading_model', 'model_version': 'error_reading_version', 'loras': []}
