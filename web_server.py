import os
import sys
import json
import logging
import threading
import webbrowser
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

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

# Target local user ID (can support multi-user if needed)
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

app = FastAPI(title="LUAutoBus Web Portal", description="سامانه وب رزرو اتوبوس دانشگاه لرستان (وانابوم)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_client(user_id=DEFAULT_USER_ID):
    return RanaClient(telegram_id=user_id)

# ----------------- Static & Page Routes -----------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(BASE_DIR, "index.html")

@app.get("/", response_class=HTMLResponse)
def read_root():
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), media_type="text/html")
    return HTMLResponse("<h1>index.html not found</h1>", status_code=404)

# ----------------- Auth & Session APIs -----------------

@app.get("/api/status")
def get_status():
    user = database.get_user(DEFAULT_USER_ID)
    if not user or not user.get("rana_session"):
        return {
            "logged_in": False,
            "user_name": None,
            "phone": user.get("phone") if user else None,
            "message": "وارد حساب کاربری نشده‌اید."
        }
    
    client = get_client()
    ok, name = client.check_auth()
    if ok:
        return {
            "logged_in": True,
            "user_name": name,
            "phone": user.get("phone", "09166280889"),
            "message": "متصل به سامانه وانابوم"
        }
    else:
        return {
            "logged_in": False,
            "user_name": None,
            "phone": user.get("phone"),
            "message": "نشست منقضی شده است. لطفاً مجدداً وارد شوید."
        }

@app.post("/api/auth/request-otp")
def request_otp(data: Dict[str, str] = Body(...)):
    mobile = data.get("mobile", "").strip()
    if not mobile:
        raise HTTPException(status_code=400, detail="شماره موبایل الزامی است.")
    
    client = get_client()
    ok, res = client.request_otp(mobile)
    if ok:
        return {"ok": True, "query": res, "mobile": mobile, "msg": f"کد تایید به شماره {mobile} پیامک شد."}
    return {"ok": False, "msg": res}

@app.post("/api/auth/verify-otp")
def verify_otp(data: Dict[str, str] = Body(...)):
    query = data.get("query", "").strip()
    code = data.get("code", "").strip()
    phone = data.get("mobile", "").strip()

    if not code or not query:
        raise HTTPException(status_code=400, detail="کد و مشخصات درخواست الزامی است.")

    client = get_client()
    if phone:
        client.phone = phone
    ok, msg = client.verify_otp(query, code)
    if ok:
        client.check_auth()
        user = database.get_user(DEFAULT_USER_ID)
        return {
            "ok": True,
            "msg": "ورود با موفقیت انجام شد!",
            "user_name": user.get("user_name", "کاربر گرامی"),
            "phone": user.get("phone")
        }
    return {"ok": False, "msg": msg}

@app.post("/api/auth/logout")
def logout():
    database.delete_user_session(DEFAULT_USER_ID)
    return {"ok": True, "msg": "با موفقیت از حساب کاربری خارج شدید."}

# ----------------- Trips & Cancellation APIs -----------------

@app.get("/api/trips")
def get_trips():
    client = get_client()
    ok, msg, tabs, booked = client.get_reserve_page()
    if not ok:
        return {"ok": False, "msg": msg, "trips": []}
    return {"ok": True, "trips": booked, "msg": "موفق"}

@app.post("/api/trips/cancel")
def cancel_trip(data: Dict[str, str] = Body(...)):
    r_id = data.get("r_id")
    if not r_id:
        raise HTTPException(status_code=400, detail="شناسه رزرو (r_id) الزامی است.")
    client = get_client()
    ok, msg = client.cancel_reservation(r_id)
    return {"ok": ok, "msg": msg}

@app.post("/api/trips/cancel-all")
def cancel_all_trips():
    import time
    client = get_client()
    ok, msg, tabs, booked = client.get_reserve_page()
    if not ok:
        return {"ok": False, "msg": msg, "total": 0, "success_count": 0}
    
    total = len(booked)
    if total == 0:
        return {"ok": True, "msg": "هیچ سفر فعالی برای لغو وجود ندارد.", "total": 0, "success_count": 0}

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
    
    return {
        "ok": True,
        "total": total,
        "success_count": success_count,
        "results": results,
        "msg": f"{success_count} از {total} سرویس با موفقیت لغو شدند."
    }

# ----------------- Reservation Wizard APIs -----------------

@app.get("/api/reserve/days")
def get_days():
    client = get_client()
    ok, msg, tabs, booked = client.get_reserve_page()
    if not ok:
        return {"ok": False, "msg": msg, "tabs": [], "booked": []}
    return {"ok": True, "tabs": tabs, "booked": booked}

@app.get("/api/reserve/stations")
def get_stations(type: str = Query("go", pattern="^(go|return)$")):
    client = get_client()
    ok, stations = client.get_stations(type)
    if not ok:
        return {"ok": False, "msg": stations, "stations": []}
    return {"ok": True, "stations": stations}

@app.get("/api/reserve/slots")
def get_slots(
    date_slug: str = Query(...),
    station_id: str = Query(...),
    type: str = Query("go", pattern="^(go|return)$")
):
    client = get_client()
    ok, slots = client.get_time_slots(date_slug, station_id, type)
    if not ok:
        return {"ok": False, "msg": slots, "slots": []}
    return {"ok": True, "slots": slots}

@app.post("/api/reserve/single")
def reserve_single_slot(item: Dict[str, Any] = Body(...)):
    date_slug = item.get("date_slug")
    station_type = item.get("station_type", "go")
    station_id = item.get("station_id")
    slot_val = item.get("slot_val")
    if not (date_slug and station_id and slot_val):
        raise HTTPException(status_code=400, detail="اطلاعات رزرو ناقص است.")
    client = get_client()
    ok, msg = client.reserve_single(date_slug, station_type, station_id, slot_val)
    return {"ok": ok, "msg": msg}

@app.post("/api/reserve/batch")
def reserve_batch(payload: Dict[str, Any] = Body(...)):
    items = payload.get("items", [])
    if not items:
        raise HTTPException(status_code=400, detail="سبد رزرو خالی است.")

    client = get_client()
    results, updated_booked = client.reserve_batch(items)
    
    success_count = sum(1 for r in results if r["ok"])
    return {
        "ok": True,
        "total": len(items),
        "success_count": success_count,
        "results": results,
        "updated_booked": updated_booked
    }

# ----------------- Favorites APIs -----------------

@app.get("/api/favorites")
def get_favorites(type: Optional[str] = None):
    favs = database.get_favorites(DEFAULT_USER_ID, type)
    return {"ok": True, "favorites": favs}

@app.post("/api/favorites/add")
def add_favorite(data: Dict[str, str] = Body(...)):
    st_type = data.get("station_type", "go")
    st_id = data.get("station_id")
    st_name = data.get("station_name", "")
    route_name = data.get("route_name", "")

    if not st_id or not st_name:
        raise HTTPException(status_code=400, detail="مشخصات ایستگاه ناقص است.")

    database.add_favorite(DEFAULT_USER_ID, st_type, st_id, st_name, route_name)
    return {"ok": True, "msg": f"ایستگاه {st_name} به علاقه‌مندی‌ها اضافه شد."}

@app.post("/api/favorites/remove")
def remove_favorite(data: Dict[str, str] = Body(...)):
    st_type = data.get("station_type", "go")
    st_id = data.get("station_id")
    if not st_id:
        raise HTTPException(status_code=400, detail="شناسه ایستگاه الزامی است.")
    database.remove_favorite(DEFAULT_USER_ID, st_type, st_id)
    return {"ok": True, "msg": "ایستگاه از علاقه‌مندی‌ها حذف شد."}

# ----------------- Auto Reserve Settings APIs -----------------

@app.get("/api/settings/auto")
def get_auto_settings():
    settings = database.get_user_settings(DEFAULT_USER_ID)
    return {
        "ok": True,
        "settings": settings,
        "weekdays": database.WEEKDAYS,
        "recent_logs": recent_notifications
    }

@app.post("/api/settings/auto")
def save_auto_settings(settings: Dict[str, Any] = Body(...)):
    database.save_user_settings(DEFAULT_USER_ID, settings)
    return {"ok": True, "msg": "تنظیمات رزرو خودکار با موفقیت ذخیره شد."}

@app.post("/api/settings/auto/test")
def test_auto_reserve():
    logger.info("Manual test of auto-reserve requested via Web API.")
    logs = []
    def log_collector(tg_id, msg, markup=None):
        logs.append(msg)
        web_notify(tg_id, msg, markup)

    test_sched = AutoScheduler(notify_callback=log_collector)
    test_sched.run_auto_reserve_for_user(DEFAULT_USER_ID)

    report_text = "\n\n".join(logs) if logs else "درخواست اجرا شد."
    return {"ok": True, "report": report_text}

def get_local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

@app.get("/api/system/network")
def get_network_info():
    ip = get_local_ip()
    return {
        "ok": True,
        "local_ip": ip,
        "port": 8000,
        "mobile_url": f"http://{ip}:8000"
    }

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
    print("=" * 60)

    # shortcut: simple 1.2s delay to launch browser after uvicorn initializes, upgrade to server startup hook if needed
    threading.Timer(1.2, lambda: webbrowser.open(local_url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")

if __name__ == "__main__":
    main()
