import os
import sys
import json
import logging
import threading
import webbrowser
import socket
import time
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import config
import database
from rana_client import RanaClient
from scheduler import AutoScheduler

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("RanaWeb")

# Initialize database
database.init_db()

DEFAULT_USER_ID = 1

# Notification store for auto-scheduler logs
recent_notifications = []

def web_notify(telegram_id, message_text, markup=None):
    logger.info(f"Notification for user {telegram_id}: {message_text}")
    recent_notifications.insert(0, {
        "time": threading.current_thread().name,
        "text": message_text
    })
    if len(recent_notifications) > 20:
        recent_notifications.pop()

# Initialize background scheduler
scheduler = AutoScheduler(notify_callback=web_notify)
scheduler.start()

def get_client(user_id=DEFAULT_USER_ID):
    return RanaClient(telegram_id=user_id)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(BASE_DIR, "index.html")

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class RanaHTTPHandler(BaseHTTPRequestHandler):
    server_version = "LUAutoBus/2.0"

    def log_message(self, format, *args):
        # shortcut: suppress noisy 200/304 logs to keep terminal readable, log warnings/errors
        if len(args) > 1 and str(args[1]) in ("200", "304"):
            return
        logger.info(f"{self.client_address[0]} - {format % args}")

    def _send_response(self, status_code, content_type, body_bytes):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def _send_json(self, status_code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send_response(status_code, "application/json; charset=utf-8", body)

    def _send_html(self, status_code, html_str):
        self._send_response(status_code, "text/html; charset=utf-8", html_str.encode("utf-8"))

    def _read_json(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                raw_body = self.rfile.read(content_length).decode("utf-8")
                return json.loads(raw_body)
        except Exception as e:
            logger.warning(f"Failed to parse request JSON: {e}")
        return {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path in ("/", "/index.html"):
                if os.path.exists(INDEX_FILE):
                    with open(INDEX_FILE, "r", encoding="utf-8") as f:
                        return self._send_html(200, f.read())
                return self._send_html(404, "<h1>index.html not found</h1>")

            if path == "/api/status":
                user = database.get_user(DEFAULT_USER_ID)
                if not user or not user.get("rana_session"):
                    return self._send_json(200, {
                        "logged_in": False,
                        "user_name": None,
                        "phone": user.get("phone") if user else None,
                        "message": "وارد حساب کاربری نشده‌اید."
                    })
                client = get_client()
                ok, name = client.check_auth()
                if ok:
                    return self._send_json(200, {
                        "logged_in": True,
                        "user_name": name,
                        "phone": user.get("phone", "09166280889"),
                        "message": "متصل به سامانه وانابوم"
                    })
                else:
                    return self._send_json(200, {
                        "logged_in": False,
                        "user_name": None,
                        "phone": user.get("phone"),
                        "message": "نشست منقضی شده است. لطفاً مجدداً وارد شوید."
                    })

            if path == "/api/trips":
                client = get_client()
                ok, msg, tabs, booked = client.get_reserve_page()
                if not ok:
                    return self._send_json(200, {"ok": False, "msg": msg, "trips": []})
                return self._send_json(200, {"ok": True, "trips": booked, "msg": "موفق"})

            if path == "/api/reserve/days":
                client = get_client()
                ok, msg, tabs, booked = client.get_reserve_page()
                if not ok:
                    return self._send_json(200, {"ok": False, "msg": msg, "tabs": [], "booked": []})
                return self._send_json(200, {"ok": True, "tabs": tabs, "booked": booked})

            if path == "/api/reserve/stations":
                st_type = qs.get("type", ["go"])[0]
                client = get_client()
                ok, stations = client.get_stations(st_type)
                if not ok:
                    return self._send_json(200, {"ok": False, "msg": stations, "stations": []})
                return self._send_json(200, {"ok": True, "stations": stations})

            if path == "/api/reserve/slots":
                date_slug = qs.get("date_slug", [""])[0]
                station_id = qs.get("station_id", [""])[0]
                st_type = qs.get("type", ["go"])[0]
                client = get_client()
                ok, slots = client.get_time_slots(date_slug, station_id, st_type)
                if not ok:
                    return self._send_json(200, {"ok": False, "msg": slots, "slots": []})
                return self._send_json(200, {"ok": True, "slots": slots})

            if path == "/api/favorites":
                fav_type = qs.get("type", [None])[0]
                favs = database.get_favorites(DEFAULT_USER_ID, fav_type)
                return self._send_json(200, {"ok": True, "favorites": favs})

            if path == "/api/settings/auto":
                settings = database.get_user_settings(DEFAULT_USER_ID)
                return self._send_json(200, {
                    "ok": True,
                    "settings": settings,
                    "weekdays": database.WEEKDAYS,
                    "recent_logs": recent_notifications
                })

            if path == "/api/system/network":
                ip = get_local_ip()
                return self._send_json(200, {
                    "ok": True,
                    "local_ip": ip,
                    "port": 8000,
                    "mobile_url": f"http://{ip}:8000"
                })

            self._send_json(404, {"detail": "Not Found"})
        except Exception as e:
            logger.error(f"Error in GET {self.path}: {e}", exc_info=True)
            self._send_json(500, {"ok": False, "detail": str(e)})

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            data = self._read_json()

            if path == "/api/auth/request-otp":
                mobile = data.get("mobile", "").strip()
                if not mobile:
                    return self._send_json(400, {"ok": False, "detail": "شماره موبایل الزامی است."})
                client = get_client()
                ok, res = client.request_otp(mobile)
                if ok:
                    return self._send_json(200, {"ok": True, "query": res, "mobile": mobile, "msg": f"کد تایید به شماره {mobile} پیامک شد."})
                return self._send_json(200, {"ok": False, "msg": res})

            if path == "/api/auth/verify-otp":
                query = data.get("query", "").strip()
                code = data.get("code", "").strip()
                phone = data.get("mobile", "").strip()
                if not code or not query:
                    return self._send_json(400, {"ok": False, "detail": "کد و مشخصات درخواست الزامی است."})
                client = get_client()
                if phone:
                    client.phone = phone
                ok, msg = client.verify_otp(query, code)
                if ok:
                    client.check_auth()
                    user = database.get_user(DEFAULT_USER_ID)
                    return self._send_json(200, {
                        "ok": True,
                        "msg": "ورود با موفقیت انجام شد!",
                        "user_name": user.get("user_name", "کاربر گرامی"),
                        "phone": user.get("phone")
                    })
                return self._send_json(200, {"ok": False, "msg": msg})

            if path == "/api/auth/logout":
                database.delete_user_session(DEFAULT_USER_ID)
                return self._send_json(200, {"ok": True, "msg": "با موفقیت از حساب کاربری خارج شدید."})

            if path == "/api/trips/cancel":
                r_id = data.get("r_id")
                if not r_id:
                    return self._send_json(400, {"ok": False, "detail": "شناسه رزرو (r_id) الزامی است."})
                client = get_client()
                ok, msg = client.cancel_reservation(r_id)
                return self._send_json(200, {"ok": ok, "msg": msg})

            if path == "/api/trips/cancel-all":
                client = get_client()
                ok, msg, tabs, booked = client.get_reserve_page()
                if not ok:
                    return self._send_json(200, {"ok": False, "msg": msg, "total": 0, "success_count": 0})
                total = len(booked)
                if total == 0:
                    return self._send_json(200, {"ok": True, "msg": "هیچ سفر فعالی برای لغو وجود ندارد.", "total": 0, "success_count": 0})
                results = []
                success_count = 0
                for trip in booked:
                    r_id = trip.get("r_id")
                    if r_id:
                        c_ok, c_msg = client.cancel_reservation(r_id)
                        if c_ok:
                            success_count += 1
                        results.append({"r_id": r_id, "info": trip.get("info", ""), "ok": c_ok, "msg": c_msg})
                        time.sleep(0.3)
                return self._send_json(200, {
                    "ok": True,
                    "total": total,
                    "success_count": success_count,
                    "results": results,
                    "msg": f"{success_count} از {total} سرویس با موفقیت لغو شدند."
                })

            if path == "/api/reserve/single":
                date_slug = data.get("date_slug")
                station_type = data.get("station_type", "go")
                station_id = data.get("station_id")
                slot_val = data.get("slot_val")
                if not (date_slug and station_id and slot_val):
                    return self._send_json(400, {"ok": False, "detail": "اطلاعات رزرو ناقص است."})
                client = get_client()
                ok, msg = client.reserve_single(date_slug, station_type, station_id, slot_val)
                return self._send_json(200, {"ok": ok, "msg": msg})

            if path == "/api/reserve/batch":
                items = data.get("items", [])
                if not items:
                    return self._send_json(400, {"ok": False, "detail": "سبد رزرو خالی است."})
                client = get_client()
                results, updated_booked = client.reserve_batch(items)
                success_count = sum(1 for r in results if r.get("ok"))
                return self._send_json(200, {
                    "ok": True,
                    "total": len(items),
                    "success_count": success_count,
                    "results": results,
                    "updated_booked": updated_booked
                })

            if path == "/api/favorites/add":
                st_type = data.get("station_type", "go")
                st_id = data.get("station_id")
                st_name = data.get("station_name", "")
                route_name = data.get("route_name", "")
                if not st_id or not st_name:
                    return self._send_json(400, {"ok": False, "detail": "مشخصات ایستگاه ناقص است."})
                database.add_favorite(DEFAULT_USER_ID, st_type, st_id, st_name, route_name)
                return self._send_json(200, {"ok": True, "msg": f"ایستگاه {st_name} به علاقه‌مندی‌ها اضافه شد."})

            if path == "/api/favorites/remove":
                st_type = data.get("station_type", "go")
                st_id = data.get("station_id")
                if not st_id:
                    return self._send_json(400, {"ok": False, "detail": "شناسه ایستگاه الزامی است."})
                database.remove_favorite(DEFAULT_USER_ID, st_type, st_id)
                return self._send_json(200, {"ok": True, "msg": "ایستگاه از علاقه‌مندی‌ها حذف شد."})

            if path == "/api/settings/auto":
                database.save_user_settings(DEFAULT_USER_ID, data)
                return self._send_json(200, {"ok": True, "msg": "تنظیمات رزرو خودکار با موفقیت ذخیره شد."})

            if path == "/api/settings/auto/test":
                logger.info("Manual test of auto-reserve requested via Web API.")
                logs = []
                def log_collector(tg_id, msg, markup=None):
                    logs.append(msg)
                    web_notify(tg_id, msg, markup)
                test_sched = AutoScheduler(notify_callback=log_collector)
                test_sched.run_auto_reserve_for_user(DEFAULT_USER_ID)
                report_text = "\n\n".join(logs) if logs else "درخواست اجرا شد."
                return self._send_json(200, {"ok": True, "report": report_text})

            self._send_json(404, {"detail": "Not Found"})
        except Exception as e:
            logger.error(f"Error in POST {self.path}: {e}", exc_info=True)
            self._send_json(500, {"ok": False, "detail": str(e)})


def main():
    port = 8000
    host = "0.0.0.0"
    local_ip = get_local_ip()
    local_url = f"http://127.0.0.1:{port}"
    lan_url = f"http://{local_ip}:{port}"
    print("=" * 60)
    print(f"LUAutoBus Web Portal is running at:")
    print(f"  • Local (This PC):     {local_url}")
    print(f"  • Mobile (Same Wi-Fi): {lan_url}")
    print("Direct connection to https://rana-app.vanaboom.ir (VPN bypassed)")
    print("Zero-Dependency Server: Powered by Python Standard Library")
    print("=" * 60)

    # shortcut: 1.2s delay to launch browser after server initializes, skip if HEADLESS
    if not os.environ.get("HEADLESS"):
        threading.Timer(1.2, lambda: webbrowser.open(local_url)).start()

    server = ThreadingHTTPServer((host, port), RanaHTTPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.server_close()


if __name__ == "__main__":
    main()
