"""
Salaris Disabled — скрипт для проставления Internal Status = "No status" для списка айтемов.

Логика:
- заходит в Mosaica (логин + переход в Showoff Collections);
- использует поле full search для поиска айтема по ID;
- открывает карточку, меняет Internal Status на "No status", Save.
"""

from __future__ import annotations

import os
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Callable

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

# Загружаем .env до создания драйвера, чтобы HEADLESS=false сработал при локальном запуске
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Тот же хост, что в mosaica_shapes_female.py (sandbox без -prod)
# Только прод
MOSAICA_BASE_URL = os.environ.get("MOSAICA_BASE_URL", "https://sandbox-prod.mosaica.ai")


class MosaicaUploader:
    """Минимальный класс: Chrome, логин в Mosaica, переход в Showoff Collections. Без Fast-track."""

    def __init__(self):
        opts = Options()
        # HEADLESS=false — как в Bot-otchet: без headless Google реже блокирует. На сервере нужен Xvfb (виртуальный дисплей).
        headless = os.environ.get("HEADLESS", "true").strip().lower() in ("1", "true", "yes")
        if headless:
            opts.add_argument("--headless")
        else:
            print("[DEBUG] Режим: видимый браузер (HEADLESS=false)")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        screen_width = (os.environ.get("DISPLAY_WIDTH") or "1920").strip()
        screen_height = (os.environ.get("DISPLAY_HEIGHT") or "1080").strip()
        window_size = f"{screen_width},{screen_height}"
        opts.add_argument(f"--window-size={window_size}")
        opts.add_argument("--start-maximized")
        opts.add_argument("--force-device-scale-factor=1")
        print(f"[DEBUG] Размер окна Chrome: {window_size}")
        opts.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        # Как в Bot-otchet: меньше шансов, что Google примет за бота
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_argument("--disable-infobars")
        opts.add_argument("--disable-extensions")
        # Опционально: постоянный профиль Chrome (user-data-dir), чтобы сохранять Google-сессию
        # и не проходить капчу/2FA при каждом запуске.
        chrome_user_data_dir = (os.environ.get("CHROME_USER_DATA_DIR") or "").strip()
        chrome_profile_directory = (os.environ.get("CHROME_PROFILE_DIRECTORY") or "").strip()
        if chrome_user_data_dir:
            opts.add_argument(f"--user-data-dir={chrome_user_data_dir}")
            print(f"[DEBUG] Используется Chrome user-data-dir: {chrome_user_data_dir}")
            if chrome_profile_directory:
                opts.add_argument(f"--profile-directory={chrome_profile_directory}")
                print(f"[DEBUG] Используется Chrome profile-directory: {chrome_profile_directory}")
        if os.environ.get("CHROME_BIN"):
            opts.binary_location = os.environ.get("CHROME_BIN")
        service = None
        if os.environ.get("CHROMEDRIVER_PATH"):
            service = Service(executable_path=os.environ.get("CHROMEDRIVER_PATH"))
        self.driver = webdriver.Chrome(options=opts, service=service) if service else webdriver.Chrome(options=opts)
        try:
            # Профиль Chrome может запоминать маленькое окно; принудительно разворачиваем на весь Xvfb.
            w = int(screen_width)
            h = int(screen_height)
            self.driver.set_window_position(0, 0)
            self.driver.set_window_size(w, h)
        except Exception:
            pass
        self.driver.set_page_load_timeout(25)
        self.driver.implicitly_wait(0)
        self.wait = WebDriverWait(self.driver, 15)
        self.wait_short = WebDriverWait(self.driver, 5)
        self.debug_enabled = os.environ.get("SELENIUM_DEBUG", "false").strip().lower() in ("1", "true", "yes")
        self.debug_dir = Path(os.environ.get("SELENIUM_DEBUG_DIR", "/tmp/salaris-debug"))
        if self.debug_enabled:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            print(f"[DEBUG] SELENIUM_DEBUG включен, дампы: {self.debug_dir}")

    def _dump_debug_state(self, label: str) -> None:
        """Сохраняет screenshot и HTML страницы для разбора проблем на сервере."""
        if not self.debug_enabled:
            return
        try:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in label)[:80]
            prefix = self.debug_dir / f"{ts}_{safe}"
            png_path = str(prefix.with_suffix(".png"))
            html_path = str(prefix.with_suffix(".html"))
            self.driver.save_screenshot(png_path)
            html = self.driver.page_source or ""
            Path(html_path).write_text(html, encoding="utf-8")
            print(f"[DEBUG] dump: url={self.driver.current_url[:120]} screenshot={png_path} html={html_path}")
        except Exception as e:
            print(f"[DEBUG] Не удалось сохранить dump ({label}): {e}")

    def _is_google_account_chooser(self) -> bool:
        """Проверяет, что Google показывает выбор уже сохраненного аккаунта."""
        try:
            cur = (self.driver.current_url or "").lower()
        except Exception:
            cur = ""
        if "accountchooser" in cur:
            return True
        try:
            return bool(self.driver.execute_script("""
                const txt = (document.body && document.body.innerText ? document.body.innerText : '').toLowerCase();
                return txt.includes('choose an account') || txt.includes('выберите аккаунт');
            """))
        except Exception:
            return False

    def _click_google_account_chooser(self) -> bool:
        """Кликает по первому доступному аккаунту на странице выбора Google."""
        selectors = [
            (By.CSS_SELECTOR, "[data-identifier]"),
            (By.CSS_SELECTOR, "li [data-identifier]"),
            (By.CSS_SELECTOR, "div[data-identifier]"),
            (By.XPATH, "//li[@data-identifier]"),
            (By.XPATH, "//div[@role='link' and @data-identifier]"),
            (By.XPATH, "(//li[@role='link' or @role='button'])[1]"),
        ]
        for by, sel in selectors:
            try:
                el = WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((by, sel)))
                if el and el.is_displayed():
                    self.driver.execute_script("arguments[0].click();", el)
                    print("[DEBUG] Выбран аккаунт на Google account chooser")
                    time.sleep(3)
                    self._dump_debug_state("after_account_chooser_click")
                    return True
            except Exception:
                continue
        return False

    def _google_password_challenge_open(self) -> bool:
        """Проверяет, что открыта страница challenge/pwd (ввод пароля Google)."""
        try:
            cur = (self.driver.current_url or "").lower()
            if "challenge/pwd" in cur:
                return True
        except Exception:
            pass
        try:
            return bool(self.driver.execute_script("""
                const pwd = document.querySelector('input[type="password"], input[name="Passwd"], input[autocomplete="current-password"]');
                return !!pwd;
            """))
        except Exception:
            return False

    def login(self, email: str, password: str) -> bool:
        """Вход в Mosaica: как в Bot-otchet — открыть страницу, искать «Please, Login», нажать и ввести email/пароль. Не считать «уже авторизован» только по URL (SPA может показывать mosaica в URL до входа)."""
        base = MOSAICA_BASE_URL.rstrip("/")
        try:
            print(f"[DEBUG] Открываю {base} ...")
            self.driver.get(base)
            self._dump_debug_state("01_open_base")
            time.sleep(2)
            try:
                print(f"[DEBUG] Загружено: url={self.driver.current_url}, title={self.driver.title[:80] if self.driver.title else ''}")
            except Exception:
                pass
            # Как в Bot-otchet: сначала ищем кнопку «Please, Login». Только если её нет — считаем, что уже авторизованы (по URL).
            please_login_selectors = [
                (By.CSS_SELECTOR, "a.link-over"),
                (By.XPATH, "//a[contains(text(), 'Please, Login')]"),
                (By.XPATH, "//a[contains(@onclick, 'login')]"),
                (By.CSS_SELECTOR, "div.t-header-menu_item.login-tab a"),
                (By.CSS_SELECTOR, "a[onclick='login()']"),
                (By.CSS_SELECTOR, ".login-tab a.link-over"),
            ]
            login_button_found = False
            for by, sel in please_login_selectors:
                try:
                    btn = self.wait_short.until(EC.element_to_be_clickable((by, sel)))
                    if btn and btn.is_displayed():
                        login_button_found = True
                        break
                except Exception:
                    continue
            if not login_button_found:
                cur = self.driver.current_url
                if "mosaica.ai" in cur and "accounts.google.com" not in cur and "login" not in cur.lower():
                    print("[DEBUG] Кнопки «Please, Login» нет — уже авторизованы (mosaica в URL, не Google)")
                    return True
            # Есть кнопка входа или мы на Google — выполняем вход: JS login() или клик по кнопке
            # Как в Bot-otchet: сначала пробуем вызов login() через JavaScript
            clicked = False
            try:
                self.driver.execute_script("login();")
                print("[DEBUG] Вызван login() через JavaScript")
                clicked = True
                time.sleep(2)
                self._dump_debug_state("02_after_login_js")
            except Exception:
                pass
            if not clicked:
                for by, sel in please_login_selectors:
                    try:
                        btn = self.wait_short.until(EC.element_to_be_clickable((by, sel)))
                        if btn and btn.is_displayed():
                            self.driver.execute_script("arguments[0].click();", btn)
                            print("[DEBUG] Нажата кнопка «Please, Login»")
                            clicked = True
                            break
                    except Exception:
                        continue
            if not clicked:
                print("[DEBUG] Кнопка «Please, Login» не найдена; возможно уже на странице Google или форма на странице")
            time.sleep(5)
            self._dump_debug_state("03_before_email")
            if self._is_google_account_chooser():
                print("[DEBUG] Google account chooser: email вводить не нужно, выбираем аккаунт")
                self._click_google_account_chooser()
                time.sleep(2)
                cur_after_choose = self.driver.current_url
                if "mosaica.ai" in cur_after_choose and "accounts.google.com" not in cur_after_choose:
                    print("[DEBUG] После выбора аккаунта вернулись в Mosaica")
                    self._dump_debug_state("account_chooser_to_mosaica")
                    return True
            if self._google_password_challenge_open():
                print("[DEBUG] Уже открыта страница ввода пароля Google (challenge/pwd), пропускаем шаг email")
            else:
            # Ввод email/пароля как в Bot-otchet (селекторы и ввод через JS при спецсимволах $, #)
                email_selectors = [
                    (By.CSS_SELECTOR, 'input[type="email"]'),
                    (By.CSS_SELECTOR, 'input[autocomplete="username"]'),
                    (By.ID, 'identifierId'),
                ]
                email_el = None
                for by, sel in email_selectors:
                    try:
                        email_el = self.wait.until(EC.presence_of_element_located((by, sel)))
                        if email_el and email_el.is_displayed():
                            break
                    except Exception:
                        continue
                if not email_el:
                    cur_no_email = self.driver.current_url
                    if self._is_google_account_chooser():
                        print("[DEBUG] Email поле не найдено, но это account chooser — пробуем выбрать аккаунт")
                        if self._click_google_account_chooser():
                            cur_after_choose = self.driver.current_url
                            if "mosaica.ai" in cur_after_choose and "accounts.google.com" not in cur_after_choose:
                                print("[DEBUG] После выбора аккаунта вернулись в Mosaica")
                                self._dump_debug_state("account_chooser_success_no_email")
                                return True
                    if self._google_password_challenge_open():
                        print("[DEBUG] Email поле не найдено, но страница пароля уже открыта — продолжаем")
                    elif "mosaica.ai" in cur_no_email and "accounts.google.com" not in cur_no_email:
                        print("[DEBUG] Email поле не найдено, но уже в Mosaica — считаем вход успешным")
                        self._dump_debug_state("email_not_found_but_in_mosaica")
                        return True
                    else:
                        print("[ERROR] После «Please, Login» поле email не найдено")
                        self._dump_debug_state("email_not_found")
                        return False
                else:
                    try:
                        email_el.clear()
                    except Exception:
                        pass
                    email_el.send_keys(email)
                    time.sleep(1)
                    next_btn = None
                    try:
                        next_btn = self.driver.find_element(By.XPATH, '//button[contains(., "Далее") or contains(., "Next")]')
                        next_btn.click()
                        time.sleep(2)
                    except Exception:
                        email_el.send_keys(Keys.RETURN)
                        time.sleep(2)
                    self._dump_debug_state("04_after_email_next")
            print("[DEBUG] Ожидание поля пароля...")
            time.sleep(3)
            password_selectors = [
                (By.CSS_SELECTOR, 'input[type="password"]'),
                (By.CSS_SELECTOR, 'input[name="password"]'),
                (By.CSS_SELECTOR, 'input[name="Passwd"]'),
                (By.ID, 'password'),
                (By.ID, 'Passwd'),
                (By.NAME, 'Passwd'),
                (By.XPATH, '//input[@type="password"]'),
                (By.XPATH, '//input[@autocomplete="current-password"]'),
            ]
            pwd_el = None
            for attempt in range(3):
                for by, sel in password_selectors:
                    try:
                        pwd_el = WebDriverWait(self.driver, 15).until(EC.presence_of_element_located((by, sel)))
                        if pwd_el and pwd_el.is_displayed():
                            break
                    except Exception:
                        continue
                if pwd_el:
                    break
                time.sleep(3)
            if not pwd_el:
                try:
                    pwd_el = self.driver.execute_script("""
                        var inputs = document.querySelectorAll('input[type="password"]');
                        for (var i = 0; i < inputs.length; i++) {
                            if (inputs[i].offsetParent !== null) return inputs[i];
                        }
                        return null;
                    """)
                except Exception:
                    pass
            if not pwd_el:
                print("[ERROR] Поле пароля не найдено")
                self._dump_debug_state("password_not_found")
                return False
            try:
                info = self.driver.execute_script("""
                    const el = arguments[0];
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return {
                        tag: el.tagName,
                        type: el.type,
                        displayed: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
                        disabled: !!el.disabled,
                        readOnly: !!el.readOnly,
                        visible: s.visibility,
                        display: s.display,
                        opacity: s.opacity,
                        x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height),
                        active: document.activeElement === el
                    };
                """, pwd_el)
                print(f"[DEBUG] Поле пароля (diagnostics): {info}")
            except Exception:
                pass
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", pwd_el)
                time.sleep(0.5)
            except Exception:
                pass
            try:
                pwd_el.clear()
            except Exception:
                self.driver.execute_script("arguments[0].value = '';", pwd_el)
            try:
                pwd_el.send_keys(password)
                print("[DEBUG] Пароль введён через send_keys")
            except Exception as e:
                print(f"[DEBUG] send_keys не сработал ({e}), ввод через JavaScript (как в Bot-otchet)")
                self._dump_debug_state("send_keys_failed_password")
                self.driver.execute_script("arguments[0].value = arguments[1];", pwd_el, password)
                self.driver.execute_script("""
                    arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                    arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                """, pwd_el)
            time.sleep(1)
            try:
                next_btn = self.wait.until(
                    EC.element_to_be_clickable((By.XPATH, '//button[contains(., "Далее") or contains(., "Next")]'))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                time.sleep(0.5)
                next_btn.click()
                print("[DEBUG] Нажата кнопка Далее (пароль)")
            except Exception:
                try:
                    pwd_el.send_keys(Keys.RETURN)
                except Exception:
                    self.driver.execute_script("arguments[0].form.submit();", pwd_el)
            time.sleep(5)
            self._dump_debug_state("05_after_password_submit")
            # Ждём редирект; обрабатываем страницу согласия Google (как в Bot-otchet)
            for attempt in range(12):
                time.sleep(2)
                cur = self.driver.current_url
                if self.debug_enabled:
                    print(f"[DEBUG] wait_redirect[{attempt + 1}/12] url={cur[:120]}")
                if "mosaica.ai" in cur and "accounts.google.com" not in cur:
                    print(f"[DEBUG] Редирект выполнен: {cur[:80]}")
                    self._dump_debug_state("06_redirect_success")
                    return True
                if "consent" in cur.lower():
                    print("[DEBUG] Страница согласия Google, ищем «Разрешить»...")
                    self._dump_debug_state(f"consent_page_attempt_{attempt + 1}")
                    for xpath in [
                        "//button[contains(., 'Разрешить') or contains(., 'Allow')]",
                        "//button[contains(., 'Продолжить') or contains(., 'Continue')]",
                        "//*[@id='submit_approve_access']",
                    ]:
                        try:
                            btn = WebDriverWait(self.driver, 3).until(
                                EC.element_to_be_clickable((By.XPATH, xpath))
                            )
                            if btn.is_displayed():
                                self.driver.execute_script("arguments[0].click();", btn)
                                print("[DEBUG] Нажата кнопка согласия")
                                time.sleep(5)
                                self._dump_debug_state("after_click_allow")
                                break
                        except Exception:
                            continue
            final_url = self.driver.current_url
            print(f"[DEBUG] После входа: url={final_url[:100]}")
            ok = ("mosaica.ai" in final_url and "accounts.google.com" not in final_url)
            if not ok:
                print("[DEBUG] Всё ещё на Google: возможны 2FA, капча или блокировка. Попробуй HEADLESS=false и Xvfb на сервере.")
                self._dump_debug_state("login_failed_final_google")
            return ok
        except Exception as e:
            err_msg = getattr(e, "msg", None) or str(e) or repr(e) or type(e).__name__
            print(f"[ERROR] Логин: {type(e).__name__} {err_msg}")
            try:
                if self.driver:
                    print(f"[DEBUG] current_url={self.driver.current_url}, title={self.driver.title}")
                    self._dump_debug_state("login_exception")
            except Exception:
                pass
            return False

    def _showoff_content_loaded(self) -> bool:
        """Проверяет, что экран Showoff загружен: в DOM есть поле full search (URL при SPA не меняется)."""
        try:
            el = self.driver.execute_script(
                "return document.getElementById('so_full_search_name') || document.querySelector('input.custom-collection_search-input') || document.querySelector('input[id*=\"full_search\"]');"
            )
            return el is not None
        except Exception:
            return False

    def navigate_to_showoff_collections(self) -> bool:
        """Переход в Showoff Collections: как в Bot-otchet — вызов view_custom_collections() через JS. URL при SPA может не меняться, проверяем появление поля full search в DOM."""
        try:
            base = MOSAICA_BASE_URL.rstrip("/")
            self.driver.get(base)
            time.sleep(3)
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except Exception:
                pass
            time.sleep(5)
            # Вызов view_custom_collections() через JS (как в Bot-otchet)
            for attempt in range(30):
                try:
                    exists = self.driver.execute_script(
                        "return typeof view_custom_collections === 'function' || typeof window.view_custom_collections === 'function';"
                    )
                    if exists:
                        self.driver.execute_script("view_custom_collections();")
                        print("[DEBUG] Вызван view_custom_collections()")
                        time.sleep(5)
                        # SPA: URL может остаться тем же — проверяем появление контента Showoff (поле full search)
                        for wait_attempt in range(15):
                            if self._showoff_content_loaded():
                                print("[DEBUG] Контент Showoff загружен (поле full search в DOM)")
                                return True
                            time.sleep(1)
                        if "mosaica.ai" in self.driver.current_url and "accounts.google.com" not in self.driver.current_url:
                            return True
                        break
                except Exception:
                    pass
                time.sleep(1)
            # Кнопка в меню (как в Bot-otchet: a с onclick view_custom_collections)
            for showoff_sel in ["a[onclick='view_custom_collections()']", "a.link-over[onclick*='view_custom_collections']", "a.v03-aside-menu__main-link"]:
                try:
                    btn = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, showoff_sel)))
                    if btn and btn.is_displayed():
                        self.driver.execute_script("arguments[0].click();", btn)
                        print("[DEBUG] Нажата кнопка Showoff в меню")
                        time.sleep(5)
                        for wait_attempt in range(15):
                            if self._showoff_content_loaded():
                                return True
                            time.sleep(1)
                        return True
                except Exception:
                    continue
            # Прямая смена URL на этом SPA не даёт результата — всегда один URL, остальные выдают ошибку. Не пробуем get(base+path).
            return False
        except Exception as e:
            print(f"[ERROR] Переход в Showoff: {e}")
            return False

    def close(self) -> None:
        if self.driver:
            self.driver.quit()
            self.driver = None


@dataclass
class ItemProcessResult:
    item_id: str
    status: str  # "changed" | "skipped_not_found" | "error"
    message: str


def read_item_ids(file_path: Path) -> List[str]:
    """Читает item_id из файла (по одному на строку)."""
    ids: List[str] = []
    if not file_path.exists():
        print(f"[ERROR] Файл с item_id не найден: {file_path}")
        return ids

    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            v = line.strip()
            if v and not v.startswith("#"):
                ids.append(v)
    print(f"[OK] Прочитано {len(ids)} item_id из {file_path.name}")
    return ids


class ItemStatusNoStatusProcessor(MosaicaUploader):
    """Расширение MosaicaUploader для поиска айтемов через full search и смены статуса."""

    def __init__(self):
        super().__init__()
        # WebDriverWait есть в базовом классе, но на всякий случай
        self.wait: WebDriverWait = self.wait

    # --- Поиск айтема через full search ---

    def _find_full_search_input(self):
        """Ищет поле full search (вверху списка коллекций/айтемов)."""
        selectors = [
            # Текущая разметка Showoff (id so_full_search_name, класс custom-collection_search-input)
            (By.CSS_SELECTOR, 'input#so_full_search_name'),
            (By.CSS_SELECTOR, 'input[id*="so_full_search_name"]'),
            (By.CSS_SELECTOR, 'input.custom-collection_search-input'),
            (By.CSS_SELECTOR, 'input[id*="full_search"]'),
            (By.CSS_SELECTOR, 'input[name*="full_search"]'),
            (By.CSS_SELECTOR, 'input[id*="so_full_search"]'),
            (By.CSS_SELECTOR, 'input[id*="item_search"]'),
            (By.CSS_SELECTOR, 'input[placeholder*="full search" i]'),
            (By.CSS_SELECTOR, 'input[placeholder*="Full search"]'),
            (By.XPATH, '//input[contains(translate(@placeholder,"FULLSEARCH","fullsearch"), "full") and contains(translate(@placeholder,"FULLSEARCH","fullsearch"), "search")]'),
            (By.XPATH, '//input[contains(@placeholder, "Full search") or contains(@placeholder, "Search full") or contains(@placeholder, "full search")]'),
            (By.XPATH, '//input[contains(@id, "search") or contains(@name, "search")]'),
            (By.XPATH, '//input[@type="text" and (contains(@placeholder, "search") or contains(@placeholder, "Search"))]'),
        ]
        for by, selector in selectors:
            try:
                el = self.wait_short.until(EC.presence_of_element_located((by, selector)))
                if el and el.is_displayed():
                    return el
            except Exception:
                continue
        # Через JS: любой input с placeholder/name/id про full search
        try:
            el = self.driver.execute_script("""
                var inputs = document.querySelectorAll('input[type="search"], input[type="text"], input:not([type])');
                for (var i = 0; i < inputs.length; i++) {
                    var inp = inputs[i];
                    if (!inp.offsetParent) continue;
                    var ph = (inp.placeholder || '').toLowerCase();
                    var id = (inp.id || '').toLowerCase();
                    var nm = (inp.name || '').toLowerCase();
                    var cls = (inp.className || '').toLowerCase();
                    if (ph.indexOf('full') >= 0 && ph.indexOf('search') >= 0) return inp;
                    if (id.indexOf('full_search') >= 0 || nm.indexOf('full_search') >= 0) return inp;
                    if (id.indexOf('so_full_search') >= 0 || cls.indexOf('custom-collection_search-input') >= 0) return inp;
                }
                return null;
            """)
            if el:
                return el
        except Exception:
            pass
        return None

    def search_item_by_id_full(self, item_id: str) -> bool:
        """
        Вводит item_id в поле full search и выбирает первую подсказку/результат.

        Returns:
            True, если получилось кликнуть по результату.
        """
        try:
            print(f"  [SEARCH] full search по ID {item_id}...")
            search_input = self._find_full_search_input()
            if not search_input:
                print("  [ERROR] Поле full search не найдено")
                return False

            # очищаем и вводим ID
            search_input.clear()
            time.sleep(0.2)
            search_input.send_keys(item_id)
            time.sleep(1.0)  # ждём появления дропа/результатов

            # пробуем нажать Enter, чтобы применить поиск
            search_input.send_keys(Keys.ENTER)
            time.sleep(1.0)

            # ищем первый видимый результат в дропдауне / списке
            result_selectors = [
                (By.CSS_SELECTOR, "div.dropdown-item"),
                (By.XPATH, '//div[contains(@class, "dropdown-item")][1]'),
                (By.XPATH, '//li[contains(@class, "js-select-item-li") or contains(@class, "collection-items_item")][1]'),
            ]
            result_el = None
            for by, selector in result_selectors:
                try:
                    cand = self.wait.until(EC.presence_of_element_located((by, selector)))
                    if cand.is_displayed():
                        result_el = cand
                        break
                except Exception:
                    continue

            if not result_el:
                print("  [WARNING] Результаты поиска не найдены")
                return False

            # скролл к элементу и клик
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", result_el)
                time.sleep(0.2)
            except Exception:
                pass

            try:
                result_el.click()
            except Exception:
                # fallback через JS
                try:
                    self.driver.execute_script("arguments[0].click();", result_el)
                except Exception as e:
                    print(f"  [ERROR] Не удалось кликнуть по результату: {e}")
                    return False

            time.sleep(1.5)  # ждём открытия карточки
            return True

        except Exception as e:
            print(f"  [ERROR] Ошибка в search_item_by_id_full: {e}")
            print(traceback.format_exc())
            return False

    # --- Работа с карточкой айтема ---

    def change_internal_status_to_no_status(self) -> bool:
        """Меняет Internal Status на 'No status' / 'Нет статуса' / сбрасывает статус."""
        try:
            print("  [STATUS] Смена Internal Status на 'No status'...")

            # те же селекторы, что и в других скриптах
            status_selectors = [
                (By.ID, "so_coll_i_status"),
                (By.XPATH, '//select[@id="so_coll_i_status"]'),
                (By.XPATH, '//label[contains(text(), "Internal Status")]/following-sibling::select'),
                (By.XPATH, '//span[contains(text(), "Internal Status")]/following-sibling::select'),
            ]

            status_el = None
            for by, selector in status_selectors:
                try:
                    el = self.driver.find_element(by, selector)
                    if el.is_displayed():
                        status_el = el
                        break
                except Exception:
                    continue

            if not status_el:
                print("  [ERROR] Не нашли dropdown Internal Status")
                return False

            sel = Select(status_el)

            # пробуем разные варианты
            tried = False
            for text in ["No status", "no status", "Нет статуса", "нет статуса"]:
                try:
                    sel.select_by_visible_text(text)
                    tried = True
                    print(f"  [OK] Выбран статус по тексту: {text}")
                    time.sleep(0.5)
                    return True
                except Exception:
                    continue

            if not tried:
                # пробуем по value
                for val in ["no_status", "none", ""]:
                    try:
                        sel.select_by_value(val)
                        print(f"  [OK] Выбран статус по value: {val}")
                        time.sleep(0.5)
                        return True
                    except Exception:
                        continue

            # если ничего не подошло — пробуем выбрать первую опцию
            try:
                if sel.options:
                    sel.select_by_index(0)
                    print("  [OK] Выбран первый вариант статуса (fallback)")
                    time.sleep(0.5)
                    return True
            except Exception as e:
                print(f"  [ERROR] Не удалось выбрать статус: {e}")
                return False

            print("  [ERROR] Не удалось определить вариант 'No status'")
            return False

        except Exception as e:
            print(f"  [ERROR] Ошибка при смене статуса: {e}")
            return False

    def click_save_button(self) -> bool:
        """Нажимает кнопку Save на карточке айтема."""
        try:
            print("  [SAVE] Нажатие кнопки Save...")
            selectors = [
                (By.ID, "so_item_save"),
                (By.XPATH, '//button[@id="so_item_save"]'),
                (By.XPATH, '//button[.//span[contains(text(), "Save")]]'),
                (By.XPATH, '//button[contains(text(), "Save")]'),
            ]
            btn = None
            for by, selector in selectors:
                try:
                    el = self.driver.find_element(by, selector)
                    if el.is_displayed():
                        btn = el
                        break
                except Exception:
                    continue

            if not btn:
                print("  [ERROR] Кнопка Save не найдена")
                return False

            try:
                self.driver.execute_script("arguments[0].click();", btn)
            except Exception:
                btn.click()

            time.sleep(1.5)
            return True
        except Exception as e:
            print(f"  [ERROR] Ошибка при нажатии Save: {e}")
            return False


def process_items(
    item_ids: List[str],
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, object]:
    """Основной цикл обработки айтемов. on_progress(обработано, всего) вызывается после каждого айтема."""
    results: List[ItemProcessResult] = []

    processor = ItemStatusNoStatusProcessor()
    try:
        # логин
        from dotenv import load_dotenv

        load_dotenv()
        email = (os.getenv("MOSAICA_EMAIL") or os.getenv("ADMIN_EMAIL") or os.getenv("EMAIL") or "").strip().strip('"\'')
        password = (os.getenv("MOSAICA_PASSWORD") or os.getenv("ADMIN_PASSWORD") or os.getenv("PASSWORD_M") or "").strip().strip('"\'')
        # В .env пароль с кавычками и $$ часто приходит как "SIm#HH$$NyuzZ" — нужен один $: SIm#HH$NyuzZ
        if password and "$$" in password:
            password = password.replace("$$", "$")

        if email and password:
            print("Выполняется вход в Mosaica...")
            if not processor.login(email, password):
                print("[ERROR] Не удалось войти в Mosaica. Проверьте учетные данные.")
                return {"results": results}
            print("[OK] Вход в Mosaica выполнен")
        else:
            print("[WARNING] MOSAICA_EMAIL/PASSWORD не заданы, пробуем использовать сохранённую сессию...")
            processor.driver.get("https://sandbox-prod.mosaica.ai/")
            time.sleep(5)

        # переход на страницу коллекций / showoff
        print("\nПереход в Showoff Collections...")
        if not processor.navigate_to_showoff_collections():
            print("[ERROR] Не удалось перейти в Showoff Collections")
            return {"results": results}
        print("[OK] Страница Showoff загружена")
        time.sleep(3)

        total = len(item_ids)
        # цикл по айтемам
        for idx, item_id in enumerate(item_ids, start=1):
            print("\n" + "-" * 60)
            print(f"[{idx}/{total}] Обработка item_id: {item_id}")
            try:
                if not processor.search_item_by_id_full(item_id):
                    msg = "Не найден через full search"
                    print(f"  [SKIP] {msg}")
                    results.append(ItemProcessResult(item_id=item_id, status="skipped_not_found", message=msg))
                    if on_progress:
                        on_progress(idx, total)
                    continue

                # смена статуса
                if not processor.change_internal_status_to_no_status():
                    msg = "Не удалось сменить статус"
                    print(f"  [ERROR] {msg}")
                    results.append(ItemProcessResult(item_id=item_id, status="error", message=msg))
                    if on_progress:
                        on_progress(idx, total)
                    continue

                if not processor.click_save_button():
                    msg = "Ошибка при сохранении"
                    print(f"  [ERROR] {msg}")
                    results.append(ItemProcessResult(item_id=item_id, status="error", message=msg))
                    if on_progress:
                        on_progress(idx, total)
                    continue

                msg = "Статус изменён на 'No status'"
                print(f"  [OK] {msg}")
                results.append(ItemProcessResult(item_id=item_id, status="changed", message=msg))
                if on_progress:
                    on_progress(idx, total)

            except KeyboardInterrupt:
                print("\n[INFO] Прервано пользователем")
                if on_progress:
                    on_progress(len(results), total)
                break
            except Exception as e:
                msg = f"Исключение: {e}"
                print(f"  [ERROR] {msg}")
                print(traceback.format_exc())
                results.append(ItemProcessResult(item_id=item_id, status="error", message=msg))
                if on_progress:
                    on_progress(idx, total)
                continue

        return {"results": results}

    finally:
        print("\nЗакрытие браузера...")
        processor.close()
        print("[OK] Браузер закрыт")


def print_summary(results: List[ItemProcessResult]) -> None:
    total = len(results)
    changed = sum(1 for r in results if r.status == "changed")
    skipped = sum(1 for r in results if r.status == "skipped_not_found")
    errors = sum(1 for r in results if r.status == "error")

    print("\n" + "=" * 60)
    print("ОТЧЁТ ПО ОБРАБОТКЕ АЙТЕМОВ (No status)")
    print("=" * 60)
    print(f"Всего в файле: {total}")
    print(f"Статус изменён: {changed}")
    print(f"Не найдены в full search: {skipped}")
    print(f"Ошибки: {errors}")


def main():
    print("=" * 60)
    print("СКРИПТ ПРОСТАВЛЕНИЯ 'NO STATUS' ДЛЯ АЙТЕМОВ")
    print("=" * 60)

    script_dir = Path(__file__).parent.absolute()
    item_file = script_dir / "item_id"

    item_ids = read_item_ids(item_file)
    if not item_ids:
        print("[ERROR] Нет item_id для обработки. Завершаю.")
        return

    result_dict = process_items(item_ids)
    results: List[ItemProcessResult] = result_dict.get("results", [])
    print_summary(results)


if __name__ == "__main__":
    main()


