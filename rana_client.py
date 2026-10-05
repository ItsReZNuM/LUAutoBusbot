import re
import json
import logging
import urllib.parse
import requests
from bs4 import BeautifulSoup

import config
import database

logger = logging.getLogger(__name__)

class RanaClient:
    BASE_URL = "https://rana-app.vanaboom.ir"
    COMPANY_ID = "10"

    def __init__(self, telegram_id=None, rana_session=None, csrf_token=None, phone=None):
        self.telegram_id = telegram_id
        self.phone = phone
        self.csrf_token = csrf_token
        self.user_name = None

        self.session = requests.Session()
        if config.IRAN_PROXY:
            self.session.proxies = {
                "http": config.IRAN_PROXY,
                "https": config.IRAN_PROXY
            }
        else:
            self.session.trust_env = False  # Direct connection (bypass VPN proxy for Iran national network)

        if rana_session:
            self.session.cookies.set("rana_session", rana_session, domain="rana-app.vanaboom.ir")
        elif telegram_id:
            self.load_user_session()

    def load_user_session(self):
        if not self.telegram_id:
            return
        user = database.get_user(self.telegram_id)
        if user:
            self.phone = user.get("phone")
            self.csrf_token = user.get("csrf_token")
            self.user_name = user.get("user_name")
            session_cookie = user.get("rana_session")
            if session_cookie:
                self.session.cookies.set("rana_session", session_cookie, domain="rana-app.vanaboom.ir")

    def save_user_session(self):
        if not self.telegram_id:
            return
        cookies = self.session.cookies.get_dict()
        session_cookie = cookies.get("rana_session", "")
        if session_cookie:
            database.save_user_session(
                telegram_id=self.telegram_id,
                phone=self.phone,
                rana_session=session_cookie,
                csrf_token=self.csrf_token,
                user_name=self.user_name
            )

    def _headers(self, ajax=True):
        h = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "fa,en-US;q=0.9,en;q=0.8",
        }
        if ajax:
            h["X-Requested-With"] = "XMLHttpRequest"
            if self.csrf_token:
                h["X-CSRF-TOKEN"] = self.csrf_token
        return h

    def check_auth(self):
        """Checks if logged in, extracts user name and fresh CSRF token."""
        try:
            r = self.session.get(f"{self.BASE_URL}/webapp", headers=self._headers(ajax=False), timeout=12)
            if r.status_code == 200 and "/users/auth/login" not in r.url:
                csrf = re.search(r'name="csrf-token" content="([^"]+)"', r.text)
                if csrf:
                    self.csrf_token = csrf.group(1)

                soup = BeautifulSoup(r.text, "html.parser")
                lead_text = soup.select_one(".user-info .lead-text")
                if lead_text:
                    self.user_name = lead_text.text.strip()
                elif "رضا محمدنیای" in r.text:
                    self.user_name = "رضا محمدنیای الوار"

                self.save_user_session()
                return True, self.user_name or "کاربر سرویس"
            return False, "نشست نامعتبر است یا منقضی شده"
        except Exception as e:
            return False, f"خطای شبکه: {e}"

    def request_otp(self, mobile):
        """Step 1: Request SMS code for mobile."""
        try:
            r_get = self.session.get(f"{self.BASE_URL}/users/auth/login", headers=self._headers(ajax=False), timeout=12)
            soup = BeautifulSoup(r_get.text, "html.parser")
            token_el = soup.find("input", {"name": "_token"})
            if not token_el:
                return False, "توکن امنیتی فرم یافت نشد"
            token = token_el.get("value")

            clean_mobile = re.sub(r"\D", "", mobile)
            if clean_mobile.startswith("98"):
                clean_mobile = clean_mobile[2:]
            if clean_mobile.startswith("0"):
                clean_mobile = clean_mobile[1:]

            payload = {
                "_token": token,
                "mobile": clean_mobile,
                "mobile_prefix": "98",
                "mobile_country": "ir",
                "otpToken": ""
            }

            headers = self._headers(ajax=True)
            headers["X-CSRF-TOKEN"] = token
            headers["Accept"] = "application/json"

            r_post = self.session.post(f"{self.BASE_URL}/users/auth/login", data=payload, headers=headers, timeout=12)
            res = r_post.json()

            if res.get("status") or res.get("data", {}).get("loginType") == "code":
                query = res.get("data", {}).get("query", f"IR-98-{clean_mobile}")
                self.phone = "0" + clean_mobile
                return True, query
            else:
                msg = res.get("message") or res.get("data", {}).get("message") or "خطا در ارسال کد"
                return False, msg
        except Exception as e:
            return False, f"خطای ارتباط با سرور: {e}"

    def verify_otp(self, query, code):
        """Step 2: Submit 6-digit SMS code."""
        try:
            r_code_page = self.session.get(f"{self.BASE_URL}/users/auth/code?query={query}", headers=self._headers(ajax=False), timeout=12)
            soup = BeautifulSoup(r_code_page.text, "html.parser")
            token_el = soup.find("input", {"name": "_token"})
            token = token_el.get("value") if token_el else ""

            payload = {
                "_token": token,
                "query": query,
                "code": str(code).strip()
            }

            headers = self._headers(ajax=True)
            if token:
                headers["X-CSRF-TOKEN"] = token
            headers["Accept"] = "application/json"

            r_post = self.session.post(f"{self.BASE_URL}/users/auth/code", data=payload, headers=headers, timeout=12)

            if "rana_session" in self.session.cookies.get_dict():
                self.check_auth()
                self.save_user_session()
                return True, "ورود با موفقیت انجام شد!"

            try:
                res = r_post.json()
                msg = res.get("message") or res.get("data", {}).get("message") or "کد وارد شده صحیح نیست"
                return False, msg
            except Exception:
                return False, "خطا در تایید کد ورود"
        except Exception as e:
            return False, f"خطای تایید کد: {e}"

    def get_reserve_page(self):
        """Fetches available days and active booked trips."""
        try:
            url = f"{self.BASE_URL}/webapp/ssm/users/reserveProgram/{self.COMPANY_ID}"
            r = self.session.get(url, headers=self._headers(ajax=False), timeout=12)
            if r.status_code != 200 or "/users/auth/login" in r.url:
                return False, "نیاز به ورود به حساب کاربری دارد", [], []

            csrf = re.search(r'name="csrf-token" content="([^"]+)"', r.text)
            if csrf:
                self.csrf_token = csrf.group(1)

            soup = BeautifulSoup(r.text, "html.parser")

            tabs = []
            for tab in soup.select("#ssm_reserve_tab_menu .nav-link"):
                tab_id = tab.get("id", "")
                slug = tab_id.replace("ssm_reserve_", "")
                day_name = tab.select_one(".small").text.strip() if tab.select_one(".small") else ""
                day_num = tab.select_one("strong").text.strip() if tab.select_one("strong") else ""
                divs = tab.find_all("div")
                month = divs[-1].text.strip() if divs else ""
                label = f"{day_name} {day_num} {month}".strip()
                tabs.append({
                    "slug": slug,
                    "date_dash": slug.replace("_", "-"),
                    "label": label
                })

            booked_trips = []
            for pane in soup.select("#ssm_reserve_tab_body .tab-pane"):
                pane_id = pane.get("id", "")
                slug = pane_id.replace("ssm_reserve_content_", "")
                alerts = pane.select(".d-flex.justify-content-center.align-items-center.my-1")
                for box in alerts:
                    alert = box.select_one(".alert-primary.alert-pro")
                    cancel_btn = box.select_one("button[onclick*='ssm_reserve_date_cancel']")
                    r_id = None
                    if cancel_btn:
                        m = re.search(r"ssm_reserve_date_cancel\('(\d+)'\)", cancel_btn.get("onclick", ""))
                        if m:
                            r_id = m.group(1)

                    if alert:
                        text = " ".join(alert.text.split())
                        booked_trips.append({
                            "slug": slug,
                            "info": text,
                            "r_id": r_id
                        })

            return True, "موفق", tabs, booked_trips
        except Exception as e:
            return False, f"خطا در دریافت اطلاعات صفحه: {e}", [], []

    def get_stations(self, station_type="go"):
        """Fetches station options for 'go' or 'return' with precise route parsing."""
        try:
            url = f"{self.BASE_URL}/webapp/ssm/users/reserveStationSelection/{self.COMPANY_ID}?type={station_type}"
            headers = self._headers(ajax=True)
            r = self.session.post(url, headers=headers, timeout=12)

            raw = r.json()
            items = raw if isinstance(raw, list) else raw.get("results", [])

            stations = []
            for item in items:
                s_id = item.get("id")
                raw_text = item.get("text", "")
                
                # Precise separation of station name and route name
                parts = raw_text.split("/")
                st_name = re.sub(r"<[^>]+>", "", parts[0]).strip()
                route_name = ""
                if len(parts) > 1:
                    route_raw = re.sub(r"<[^>]+>", "", parts[1]).strip()
                    route_name = route_raw.replace("مسیر:", "").strip()

                display_name = f"{st_name} (مسیر: {route_name})" if route_name else st_name

                stations.append({
                    "id": s_id,
                    "name": display_name,
                    "station_name": st_name,
                    "route_name": route_name
                })
            return True, stations
        except Exception as e:
            return False, f"خطا در دریافت ایستگاه‌ها: {e}"

    def get_time_slots(self, date_slug, station_id, station_type="go"):
        """Fetches time slots for selected station and date."""
        try:
            url = f"{self.BASE_URL}/webapp/ssm/users/reserveStationSelectionAddress/{self.COMPANY_ID}?date_slug={date_slug}&address_id={station_id}&type={station_type}"
            headers = self._headers(ajax=False)
            r = self.session.get(url, headers=headers, timeout=12)

            soup = BeautifulSoup(r.text, "html.parser")
            inputs = soup.select('input[type="radio"]')
            slots = []
            for inp in inputs:
                val = inp.get("value")
                lbl = soup.select_one(f'label[for="{inp.get("id")}"]')
                lbl_text = " ".join(lbl.text.split()) if lbl else val
                slots.append({
                    "value": val,
                    "label": lbl_text
                })
            return True, slots
        except Exception as e:
            return False, f"خطا در دریافت ساعت‌ها: {e}"

    def reserve(self, date_slug, go_station=None, go_slot=None, return_station=None, return_slot=None):
        """Submits reservation to server and retrieves newly booked trip details and cancel ID."""
        try:
            url = f"{self.BASE_URL}/webapp/ssm/users/reserveStationSelectionReserve/{self.COMPANY_ID}"
            date_dash = date_slug.replace("_", "-")

            params = {}
            if go_station and go_slot:
                params[f"route_date_station_go[{date_slug}]"] = go_station
                params[f"route_select[go][{date_dash}]"] = go_slot
            if return_station and return_slot:
                params[f"route_date_station_return[{date_slug}]"] = return_station
                params[f"route_select[return][{date_dash}]"] = return_slot

            if not params:
                return False, "هیچ سرویسی برای رزرو انتخاب نشده است.", []

            reserve_data = urllib.parse.urlencode(params)
            payload = {
                "date_slug": date_slug,
                "reserve_data": reserve_data
            }

            headers = self._headers(ajax=True)
            headers["Accept"] = "application/json"

            r = self.session.post(url, data=payload, headers=headers, timeout=15)

            is_success = False
            try:
                res = r.json()
                if res.get("status") or (res.get("data") and res.get("data", {}).get("date_slug")):
                    is_success = True
                else:
                    msg = res.get("message") or res.get("data", {}).get("message") or str(res)
                    return False, f"پاسخ سایت: {msg}", []
            except Exception:
                if r.status_code == 200:
                    is_success = True
                else:
                    return False, f"خطای سرور: کد وضعیت {r.status_code}", []

            if is_success:
                # Query newly booked trips to retrieve cancel IDs
                _, _, _, updated_booked = self.get_reserve_page()
                new_booked_for_date = [b for b in updated_booked if b.get("slug") == date_slug]
                return True, "رزرو با موفقیت ثبت شد!", new_booked_for_date

            return False, "خطای نامشخص در ثبت رزرو", []
        except Exception as e:
            return False, f"خطا در ثبت رزرو: {e}", []

    def cancel_reservation(self, r_id):
        """Cancels a booked trip."""
        try:
            url = f"{self.BASE_URL}/webapp/ssm/users/reserveStationSelectionReserveCancel/{self.COMPANY_ID}"
            headers = self._headers(ajax=True)
            headers["Accept"] = "application/json"
            payload = {"r_id": str(r_id)}
            r = self.session.post(url, data=payload, headers=headers, timeout=12)
            try:
                res = r.json()
                if res.get("status") or res.get("data"):
                    return True, "سرویس با موفقیت لغو شد."
                msg = res.get("message") or res.get("data", {}).get("message") or "لغو نشد"
                return False, msg
            except Exception:
                return True, "درخواست لغو ارسال شد."
        except Exception as e:
            return False, f"خطا در لغو رزرو: {e}"
