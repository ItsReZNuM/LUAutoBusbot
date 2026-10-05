import logging
import threading
import time
from datetime import datetime
from telebot import types

import database
from rana_client import RanaClient

logger = logging.getLogger(__name__)

class AutoScheduler:
    def __init__(self, notify_callback):
        self.notify_callback = notify_callback
        self.running = False
        self.thread = None

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            logger.info("Multi-User AutoScheduler started.")

    def stop(self):
        self.running = False

    def _run_loop(self):
        while self.running:
            try:
                self._check_and_execute_all()
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
            time.sleep(25)

    def _check_and_execute_all(self):
        active_users = database.get_all_active_auto_users()
        if not active_users:
            return

        now = datetime.now()
        current_time_str = now.strftime("%H:%M")

        for user in active_users:
            try:
                tg_id = user["telegram_id"]
                target_time = user.get("target_time", "00:01")
                last_key = user.get("last_reserve_key", "")

                today_key = f"{now.strftime('%Y-%m-%d')}_{target_time}"

                if current_time_str == target_time and last_key != today_key:
                    settings = database.get_user_settings(tg_id)
                    settings["last_reserve_key"] = today_key
                    database.save_user_settings(tg_id, settings)

                    logger.info(f"Triggering auto-reserve for user {tg_id} at {current_time_str}...")
                    threading.Thread(target=self.run_auto_reserve_for_user, args=(tg_id,), daemon=True).start()
            except Exception as e:
                logger.error(f"Error checking user {user.get('telegram_id')}: {e}")

    def _get_persian_day_name(self, weekday_int):
        mapping = {
            5: "شنبه",
            6: "یکشنبه",
            0: "دوشنبه",
            1: "سه‌شنبه",
            2: "چهارشنبه",
            3: "پنج‌شنبه",
            4: "جمعه"
        }
        return mapping.get(weekday_int, "")

    def run_auto_reserve_for_user(self, telegram_id):
        """Executes auto-reserve logic for a specific user and sends notification with cancel button."""
        user = database.get_user(telegram_id)
        if not user or not user.get("rana_session"):
            self.notify_callback(telegram_id, "⚠️ **خطا در رزرو خودکار:**\nنشست شما نامعتبر یا منقضی شده است. لطفاً وارد حساب شوید.")
            return

        settings = database.get_user_settings(telegram_id)
        client = RanaClient(telegram_id=telegram_id)

        # 1. Fetch available tabs
        ok, msg, tabs, booked = client.get_reserve_page()
        if not ok:
            self.notify_callback(telegram_id, f"⚠️ **خطا در رزرو خودکار:**\n{msg}\nلطفاً وضعیت ورود به حساب را بررسی کنید.")
            return

        if not tabs:
            self.notify_callback(telegram_id, "ℹ️ **گزارش رزرو خودکار:**\nدر حال حاضر هیچ روزی در سامانه دانشگاه برای رزرو باز نیست.")
            return

        # Target latest open date
        target_tab = tabs[-1]
        date_slug = target_tab["slug"]
        date_label = target_tab["label"]

        # Determine target day of week
        target_day = None
        for d in ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه"]:
            if d in date_label:
                target_day = d
                break

        if not target_day:
            tomorrow_weekday = (datetime.now().weekday() + 1) % 7
            target_day = self._get_persian_day_name(tomorrow_weekday)

        # Look up day-specific schedule
        daily_schedules = settings.get("daily_schedules", {})
        day_cfg = daily_schedules.get(target_day)

        if day_cfg:
            if not day_cfg.get("enabled", True):
                logger.info(f"Target day '{target_day}' is disabled in daily schedule for user {telegram_id}. Skipping.")
                return
            go_st_id = day_cfg.get("go_station_id", "")
            go_st_name = day_cfg.get("go_station_name", "")
            go_time_str = day_cfg.get("go_time", "")
            return_st_id = day_cfg.get("return_station_id", "")
            return_st_name = day_cfg.get("return_station_name", "")
            return_time_str = day_cfg.get("return_time", "")
        else:
            go_st_id = settings.get("go_station_id", "")
            go_st_name = settings.get("go_station_name", "")
            go_time_str = settings.get("go_time", "")
            return_st_id = settings.get("return_station_id", "")
            return_st_name = settings.get("return_station_name", "")
            return_time_str = settings.get("return_time", "")

        if not go_time_str and not return_time_str:
            self.notify_callback(
                telegram_id,
                f"ℹ️ **اطلاعیه رزرو خودکار:**\nبرای روز *«{target_day}»* ({date_label}) هیچ ایستگاه یا ساعتی در برنامه روزانه شما ثبت نشده است."
            )
            return

        # Check if already booked
        already_booked = [b for b in booked if b.get("slug") == date_slug]
        if already_booked:
            details = "\n".join([f"• {b['info']}" for b in already_booked])
            self.notify_callback(telegram_id, f"ℹ️ **اطلاعیه:** برای تاریخ {date_label} از قبل سرویس رزرو شده دارید:\n{details}")
            return

        # 2. Match Go Station & Slot
        go_slot_val = None
        target_go_id = go_st_id
        if not target_go_id and go_st_name:
            ok_go_st, go_stations = client.get_stations("go")
            if ok_go_st:
                for st in go_stations:
                    if go_st_name in st["name"]:
                        target_go_id = st["id"]
                        break

        if target_go_id:
            ok_slots, slots = client.get_time_slots(date_slug, target_go_id, "go")
            if ok_slots:
                for s in slots:
                    if go_time_str in s["label"]:
                        go_slot_val = s["value"]
                        break

        # 3. Match Return Station & Slot
        ret_slot_val = None
        target_ret_id = return_st_id
        if not target_ret_id and return_st_name:
            ok_ret_st, ret_stations = client.get_stations("return")
            if ok_ret_st:
                for st in ret_stations:
                    if return_st_name in st["name"]:
                        target_ret_id = st["id"]
                        break

        if target_ret_id:
            ok_slots, slots = client.get_time_slots(date_slug, target_ret_id, "return")
            if ok_slots:
                for s in slots:
                    if return_time_str in s["label"]:
                        ret_slot_val = s["value"]
                        break

        # 4. Submit reservation
        if not go_slot_val and not ret_slot_val:
            self.notify_callback(
                telegram_id,
                f"❌ **عدم موفقیت در رزرو خودکار برای {date_label}:**\n"
                f"ساعت‌های مورد نظر شما در لیست سرویس‌های این تاریخ یافت نشدند:\n"
                f"• رفت: {go_st_name or 'ثبت‌نشده'} ساعت {go_time_str or '-'} ({'یافت نشد' if not go_slot_val else 'موجود'})\n"
                f"• برگشت: {return_st_name or 'ثبت‌نشده'} ساعت {return_time_str or '-'} ({'یافت نشد' if not ret_slot_val else 'موجود'})"
            )
            return

        res_ok, res_msg, new_booked = client.reserve(
            date_slug=date_slug,
            go_station=target_go_id if go_slot_val else None,
            go_slot=go_slot_val,
            return_station=target_ret_id if ret_slot_val else None,
            return_slot=ret_slot_val
        )

        if res_ok:
            report = (
                f"✅ **رزرو خودکار برنامه روز «{target_day}» با موفقیت انجام شد!** 🎉\n\n"
                f"📅 **تاریخ:** {date_label}\n"
            )
            if go_slot_val:
                report += f"🟢 **رفت:** {go_st_name or target_go_id} - ساعت {go_time_str}\n"
            if ret_slot_val:
                report += f"🔵 **برگشت:** {return_st_name or target_ret_id} - ساعت {return_time_str}\n"

            # Create cancel button for newly booked trips
            markup = types.InlineKeyboardMarkup(row_width=1)
            for b in new_booked:
                r_id = b.get("r_id")
                if r_id:
                    markup.add(types.InlineKeyboardButton(f"❌ لغو سرویس: {b['info'][:30]}", callback_data=f"cancel_trip:{r_id}"))

            self.notify_callback(telegram_id, report, markup=markup if markup.keyboard else None)
        else:
            self.notify_callback(telegram_id, f"⚠️ **خطا در ثبت رزرو خودکار برای {date_label}:**\n{res_msg}")
