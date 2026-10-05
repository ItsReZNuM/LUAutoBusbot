import os
import sys
import time
import json
import logging
import telebot
from telebot import types, apihelper

import config
import database
from rana_client import RanaClient
from scheduler import AutoScheduler

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("RanaBot")

# Initialize database
database.init_db()

# Configure proxy for Telegram API if set
if config.TELEGRAM_PROXY:
    apihelper.proxy = {
        "http": config.TELEGRAM_PROXY,
        "https": config.TELEGRAM_PROXY
    }
    logger.info(f"Using Telegram Proxy: {config.TELEGRAM_PROXY}")
else:
    logger.info("Connecting to Telegram directly without proxy.")

bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode="Markdown")

# Register Bot Commands Menu in Telegram
try:
    bot.set_my_commands([
        types.BotCommand("start", "منوی اصلی ربات"),
        types.BotCommand("reserve", "رزرو سرویس جدید"),
        types.BotCommand("trips", "سفرهای رزروشده و فعال"),
        types.BotCommand("favorites", "ایستگاه‌های منتخب و موردعلاقه"),
        types.BotCommand("settings", "تنظیمات رزرو خودکار"),
        types.BotCommand("status", "بررسی وضعیت حساب و کوکی"),
        types.BotCommand("login", "ورود به حساب با پیامک (OTP)"),
        types.BotCommand("help", "راهنمای استفاده از ربات")
    ])
except Exception as e:
    logger.warning(f"Could not set bot commands: {e}")

# State storage for user interactive wizard per chat_id
user_states = {}

def get_client(telegram_id):
    return RanaClient(telegram_id=telegram_id)

def notify_user(telegram_id, message_text, markup=None):
    try:
        bot.send_message(telegram_id, message_text, reply_markup=markup)
    except Exception as e:
        logger.error(f"Failed to send notification to {telegram_id}: {e}")

# Initialize and start multi-user scheduler
scheduler = AutoScheduler(notify_callback=notify_user)
scheduler.start()

# ----------------- Keyboards -----------------

def get_main_keyboard(is_logged_in=False):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if is_logged_in:
        markup.add(
            types.KeyboardButton("🚌 رزرو سرویس جدید"),
            types.KeyboardButton("📋 سفرهای رزروشده")
        )
        markup.add(
            types.KeyboardButton("⭐ علاقه‌مندی‌ها (مسیرهای من)"),
            types.KeyboardButton("⏰ تنظیمات رزرو خودکار")
        )
        markup.add(
            types.KeyboardButton("👤 وضعیت حساب کاربری"),
            types.KeyboardButton("🔄 خروج / تغییر شماره")
        )
    else:
        markup.add(
            types.KeyboardButton("🔑 ورود با پیامک (OTP)"),
            types.KeyboardButton("👤 وضعیت حساب کاربری")
        )
    return markup

# ----------------- Command Handlers -----------------

@bot.message_handler(commands=["start", "menu"])
def cmd_start(message):
    chat_id = message.chat.id
    user = database.get_user(chat_id)
    is_logged_in = bool(user and user.get("rana_session"))

    client = get_client(chat_id)
    auth_ok = False
    user_name = "دانشجوی گرامی"

    if is_logged_in:
        auth_ok, info = client.check_auth()
        if auth_ok:
            user_name = info

    if auth_ok:
        text = (
            f"👋 *سلام {user_name} عزیز، خوش آمدید!*\n\n"
            f"🆔 شناسه تلگرام شما: `{chat_id}`\n"
            "✅ وضعیت سامانه وانابوم: *متصل و فعال*\n\n"
            "از منوی زیر یا دستورات ربات گزینه مورد نظر را انتخاب کنید:"
        )
    else:
        text = (
            f"👋 *سلام به ربات رزرواسیون اتوبوس دانشگاه خوش آمدید!*\n\n"
            f"🆔 شناسه تلگرام شما: `{chat_id}`\n"
            "⚠️ شما هنوز وارد حساب سامانه ترابری خود نشده‌اید.\n\n"
            "برای شروع، دکمه *«🔑 ورود با پیامک (OTP)»* را بزنید تا حساب دانشگاه شما به این اکانت تلگرام متصل شود."
        )

    bot.send_message(chat_id, text, reply_markup=get_main_keyboard(is_logged_in=auth_ok))

@bot.message_handler(commands=["help"])
def cmd_help(message):
    help_text = (
        "📖 *راهنمای جامع ربات رزرواسیون اتوبوس دانشگاه:*\n\n"
        "🔹 *۱. رزرو دستی سرویس (/reserve)*\n"
        "با انتخاب این گزینه، روزهای باز سامانه به شما نمایش داده می‌شود. می‌توانید نوع سرویس (رفت/برگشت/هردو)، ایستگاه دقیق همراه با مسیر، و ساعت‌های موجود را مشاهده و در لحظه رزرو کنید.\n\n"
        "🔹 *۲. علاقه‌مندی‌ها (/favorites)*\n"
        "مسیرهایی که مکرراً استفاده می‌کنید را به لیست علاقه‌مندی‌ها اضافه کنید تا در رزرو دستی و خودکار همیشه بالاتر از همه و دم‌دست باشند.\n\n"
        "🔹 *۳. رزرو خودکار با زمان‌بندی (/settings)*\n"
        "دیگر نگران جا ماندن از اتوبوس نباشید! کافیست ساعت باز شدن سامانه (مثلاً `00:01` بامداد) و ایستگاه‌های دلخواهتان را مشخص کنید. ربات در زمان موعود به صورت خودکار رزرو را ثبت کرده و نتیجه را برای شما پیامک/تلگرام می‌کند.\n\n"
        "🔹 *۴. مشاهده و لغو سفرها (/trips)*\n"
        "مشاهده تمام سفرهای فعال شما به همراه امکان لغو فوری هر سرویس با یک کلیک.\n\n"
        "🔹 *۵. ورود با پیامک (/login)*\n"
        "بدون نیاز به دستکاری کوکی، فقط شماره خود را وارد کرده و کد ۶ رقمی ارسالی از سامانه دانشگاه را برای ربات بفرستید."
    )
    bot.send_message(message.chat.id, help_text)

@bot.message_handler(commands=["reserve"])
def cmd_reserve(message):
    start_manual_reserve(message.chat.id)

@bot.message_handler(commands=["trips"])
def cmd_trips(message):
    show_booked_trips(message.chat.id)

@bot.message_handler(commands=["favorites"])
def cmd_favorites(message):
    show_favorites_menu(message.chat.id)

@bot.message_handler(commands=["settings"])
def cmd_settings(message):
    show_auto_reserve_settings(message.chat.id)

@bot.message_handler(commands=["status"])
def cmd_status(message):
    check_account_status(message.chat.id)

@bot.message_handler(commands=["login"])
def cmd_login(message):
    start_login_flow(message.chat.id)

@bot.message_handler(commands=["logout"])
def cmd_logout(message):
    handle_logout(message.chat.id)

# ----------------- Message Handlers -----------------

@bot.message_handler(func=lambda msg: True)
def handle_text(message):
    chat_id = message.chat.id
    text = message.text.strip()

    state_info = user_states.get(chat_id, {})
    curr_step = state_info.get("step")

    if curr_step == "WAITING_MOBILE":
        handle_mobile_input(chat_id, text)
        return
    elif curr_step == "WAITING_OTP":
        handle_otp_input(chat_id, text)
        return
    elif curr_step == "SEARCH_STATION":
        handle_station_search(chat_id, text)
        return
    elif curr_step == "SET_AUTO_TIME":
        handle_set_auto_time(chat_id, text)
        return

    if text == "🚌 رزرو سرویس جدید":
        start_manual_reserve(chat_id)
    elif text == "📋 سفرهای رزروشده":
        show_booked_trips(chat_id)
    elif text == "⭐ علاقه‌مندی‌ها (مسیرهای من)":
        show_favorites_menu(chat_id)
    elif text == "⏰ تنظیمات رزرو خودکار":
        show_auto_reserve_settings(chat_id)
    elif text == "👤 وضعیت حساب کاربری":
        check_account_status(chat_id)
    elif text == "🔑 ورود با پیامک (OTP)":
        start_login_flow(chat_id)
    elif text == "🔄 خروج / تغییر شماره":
        handle_logout(chat_id)
    else:
        user = database.get_user(chat_id)
        is_logged_in = bool(user and user.get("rana_session"))
        bot.send_message(chat_id, "لطفاً یکی از گزینه‌های منو را انتخاب کنید:", reply_markup=get_main_keyboard(is_logged_in))

# ----------------- Account Status & Logout -----------------

def check_account_status(chat_id):
    bot.send_chat_action(chat_id, "typing")
    user = database.get_user(chat_id)
    if not user or not user.get("rana_session"):
        text = (
            "👤 *وضعیت حساب کاربری:*\n"
            f"• شناسه عددی تلگرام: `{chat_id}`\n"
            "• وضعیت حساب: *وارد نشده ❌*\n\n"
            "برای فعال‌سازی و اتصال، دکمه *«🔑 ورود با پیامک (OTP)»* را بزنید."
        )
        bot.send_message(chat_id, text, reply_markup=get_main_keyboard(False))
        return

    client = get_client(chat_id)
    ok, user_info = client.check_auth()
    phone_display = user.get("phone", "نامشخص")

    if ok:
        text = (
            "👤 *وضعیت حساب کاربری:*\n"
            f"• نام و مشخصات: *{user_info}*\n"
            f"• شماره همراه: `{phone_display}`\n"
            f"• شناسه تلگرام متصل: `{chat_id}`\n"
            "• وضعیت سامانه: *متصل و فعال ✅*\n"
        )
        bot.send_message(chat_id, text, reply_markup=get_main_keyboard(True))
    else:
        text = (
            "👤 *وضعیت حساب کاربری:*\n"
            f"• شناسه تلگرام: `{chat_id}`\n"
            f"• شماره ثبت‌شده: `{phone_display}`\n"
            "• وضعیت نشست: *منقضی شده ❌*\n\n"
            "لطفاً مجدداً لاگین کنید تا کوکی نشست شما تمدید شود."
        )
        bot.send_message(chat_id, text, reply_markup=get_main_keyboard(False))

def handle_logout(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("بله، خروج", callback_data="confirm_logout"),
        types.InlineKeyboardButton("انصراف", callback_data="dismiss")
    )
    bot.send_message(chat_id, "⚠️ آیا می‌خواهید از حساب کاربری خود خارج شوید و کوکی شما حذف شود؟", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "confirm_logout")
def callback_confirm_logout(call):
    chat_id = call.message.chat.id
    database.delete_user_session(chat_id)
    bot.edit_message_text("✅ با موفقیت از حساب کاربری خارج شدید.", chat_id, call.message.message_id)
    bot.send_message(chat_id, "برای استفاده مجدد، وارد حساب شوید:", reply_markup=get_main_keyboard(False))

# ----------------- Login / OTP Flow (Per User) -----------------

def start_login_flow(chat_id):
    user = database.get_user(chat_id)
    existing_phone = user.get("phone") if user else None

    markup = types.InlineKeyboardMarkup(row_width=1)
    if existing_phone:
        markup.add(types.InlineKeyboardButton(f"📱 ارسال کد به {existing_phone}", callback_data=f"send_otp:{existing_phone}"))
    markup.add(types.InlineKeyboardButton("✏️ ورود شماره موبایل جدید", callback_data="input_new_phone"))

    text = (
        "🔐 *ورود به سامانه ترابری دانشگاه (دریافت کد پیامکی):*\n\n"
        f"شناسه تلگرام شما: `{chat_id}`\n"
        "شماره موبایل ثبت‌شده در سامانه وانابوم را مشخص کنید:"
    )
    bot.send_message(chat_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("send_otp:") or call.data == "input_new_phone")
def callback_otp_phone(call):
    chat_id = call.message.chat.id
    if call.data == "input_new_phone":
        user_states[chat_id] = {"step": "WAITING_MOBILE"}
        bot.edit_message_text(
            "📱 لطفاً شماره موبایل خود را وارد کنید:\n(مثال: `09166280889`)",
            chat_id,
            call.message.message_id
        )
        return

    phone = call.data.split(":")[1]
    trigger_otp_request(chat_id, phone, call.message.message_id)

def handle_mobile_input(chat_id, text):
    clean_phone = text.strip()
    if not (clean_phone.startswith("09") or clean_phone.startswith("989") or clean_phone.startswith("9")):
        bot.send_message(chat_id, "⚠️ فرمت شماره معتبر نیست. لطفاً یک شماره موبایل معتبر (مثال: `09123456789`) ارسال کنید:")
        return
    trigger_otp_request(chat_id, clean_phone)

def trigger_otp_request(chat_id, phone, message_id=None):
    if message_id:
        bot.edit_message_text(f"⏳ در حال ارسال پیامک تایید به شماره {phone}...", chat_id, message_id)
    else:
        bot.send_message(chat_id, f"⏳ در حال ارسال پیامک تایید به شماره {phone}...")

    client = get_client(chat_id)
    ok, result = client.request_otp(phone)
    if ok:
        query_val = result
        user_states[chat_id] = {
            "step": "WAITING_OTP",
            "query": query_val,
            "phone": phone
        }
        text = (
            f"📩 *کد تایید به شماره {phone} پیامک شد.*\n\n"
            "لطفاً کد ۶ رقمی ارسالی را در پاسخ به این پیام بنویسید:"
        )
        bot.send_message(chat_id, text)
    else:
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, f"❌ *خطا در ارسال کد تایید:*\n{result}")

def handle_otp_input(chat_id, text):
    code = text.strip()
    state = user_states.get(chat_id, {})
    query = state.get("query")
    phone = state.get("phone")

    if not code.isdigit() or len(code) < 4:
        bot.send_message(chat_id, "⚠️ لطفاً کد را به صورت عدد لاتین معتبر وارد کنید:")
        return

    bot.send_message(chat_id, "⏳ در حال تایید کد و اتصال حساب به شناسه تلگرام شما...")
    client = get_client(chat_id)
    client.phone = phone
    ok, msg = client.verify_otp(query, code)

    if ok:
        user_states.pop(chat_id, None)
        bot.send_message(
            chat_id,
            f"🎉 *{msg}*\n\nحساب شما با موفقیت متصل شد و کوکی ورود ذخیره گردید.",
            reply_markup=get_main_keyboard(is_logged_in=True)
        )
    else:
        bot.send_message(chat_id, f"❌ *تایید کد با شکست مواجه شد:*\n{msg}\n\nمجدداً کد را بفرستید یا دکمه «🔑 ورود با پیامک» را بزنید.")

# ----------------- Favorites Management -----------------

def show_favorites_menu(chat_id):
    favs = database.get_favorites(chat_id)
    text = "⭐ *ایستگاه‌ها و مسیرهای منتخب شما:*\n\n"

    if not favs:
        text += "شما هنوز هیچ ایستگاهی به لیست علاقه‌مندی‌ها اضافه نکرده‌اید.\n"
        text += "*(در هنگام رزرو دستی می‌توانید هر ایستگاه را با یک کلیک به این لیست اضافه کنید).*"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("➕ افزودن ایستگاه جدید به علاقه‌مندی‌ها", callback_data="fav_add_start"))
        bot.send_message(chat_id, text, reply_markup=markup)
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for f in favs:
        st_type_badge = "🟢 رفت" if f["station_type"] == "go" else "🔵 برگشت"
        label = f"{st_type_badge}: {f['station_name']} ({f['route_name']})"
        markup.add(types.InlineKeyboardButton(f"❌ حذف {label[:30]}", callback_data=f"del_fav:{f['station_type']}:{f['station_id']}"))

    markup.add(types.InlineKeyboardButton("➕ افزودن ایستگاه جدید", callback_data="fav_add_start"))
    bot.send_message(chat_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("del_fav:"))
def callback_delete_favorite(call):
    chat_id = call.message.chat.id
    _, st_type, st_id = call.data.split(":")
    database.remove_favorite(chat_id, st_type, st_id)
    bot.answer_callback_query(call.id, "ایستگاه از علاقه‌مندی‌ها حذف شد.")
    bot.delete_message(chat_id, call.message.message_id)
    show_favorites_menu(chat_id)

@bot.callback_query_handler(func=lambda call: call.data == "fav_add_start")
def callback_fav_add_start(call):
    chat_id = call.message.chat.id
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🟢 ایستگاه رفت", callback_data="fav_pick_type:go"),
        types.InlineKeyboardButton("🔵 ایستگاه برگشت", callback_data="fav_pick_type:return")
    )
    markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="show_favs"))
    bot.edit_message_text("نوع ایستگاهی که می‌خواهید به علاقه‌مندی‌ها اضافه کنید را انتخاب کنید:", chat_id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "show_favs")
def callback_show_favs(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    show_favorites_menu(call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("fav_pick_type:"))
def callback_fav_pick_type(call):
    chat_id = call.message.chat.id
    st_type = call.data.split(":")[1]
    client = get_client(chat_id)
    ok, stations = client.get_stations(st_type)

    if not ok or not stations:
        bot.edit_message_text("❌ خطا در دریافت لیست ایستگاه‌ها.", chat_id, call.message.message_id)
        return

    user_states[chat_id] = {
        "step": "PICK_FAV_STATION",
        "station_type": st_type,
        "stations": stations
    }

    markup = types.InlineKeyboardMarkup(row_width=1)
    for st in stations[:12]:
        markup.add(types.InlineKeyboardButton(st["name"][:38], callback_data=f"save_fav:{st_type}:{st['id']}"))

    markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="fav_add_start"))
    bot.edit_message_text("ایستگاه مورد نظر را جهت افزودن انتخاب کنید:", chat_id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("save_fav:"))
def callback_save_fav(call):
    chat_id = call.message.chat.id
    _, st_type, st_id = call.data.split(":")
    state = user_states.get(chat_id, {})
    stations = state.get("stations", [])
    st_info = next((s for s in stations if s["id"] == st_id), None)

    if st_info:
        database.add_favorite(chat_id, st_type, st_id, st_info["station_name"], st_info["route_name"])
        bot.answer_callback_query(call.id, "ایستگاه به علاقه‌مندی‌ها اضافه شد! ⭐")

    bot.delete_message(chat_id, call.message.message_id)
    show_favorites_menu(chat_id)

# ----------------- Show Booked Trips & Cancellation -----------------

def show_booked_trips(chat_id):
    bot.send_chat_action(chat_id, "typing")
    client = get_client(chat_id)
    ok, msg, tabs, booked = client.get_reserve_page()
    if not ok:
        bot.send_message(chat_id, f"❌ خطا در دریافت اطلاعات:\n{msg}\nلطفاً وضعیت ورود به حساب خود را بررسی کنید.")
        return

    if not booked:
        bot.send_message(chat_id, "ℹ️ شما در حال حاضر هیچ سرویس رزرو شده‌ای ندارید.")
        return

    text = "📋 *سفرهای رزروشده فعال شما:*\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)

    for i, trip in enumerate(booked, 1):
        info = trip["info"]
        r_id = trip["r_id"]
        text += f"*{i}.* {info}\n"
        if r_id:
            markup.add(types.InlineKeyboardButton(f"❌ لغو سرویس #{i}", callback_data=f"cancel_trip:{r_id}"))

    bot.send_message(chat_id, text, reply_markup=markup if markup.keyboard else None)

@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_trip:"))
def callback_cancel_trip(call):
    chat_id = call.message.chat.id
    r_id = call.data.split(":")[1]

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("بله، لغو کن", callback_data=f"confirm_cancel:{r_id}"),
        types.InlineKeyboardButton("انصراف", callback_data="dismiss")
    )
    bot.send_message(chat_id, "⚠️ آیا مطمئن هستید که می‌خواهید این سرویس را لغو کنید؟", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_cancel:"))
def callback_confirm_cancel(call):
    chat_id = call.message.chat.id
    r_id = call.data.split(":")[1]
    bot.edit_message_text("⏳ در حال لغو سرویس در سامانه...", chat_id, call.message.message_id)

    client = get_client(chat_id)
    ok, msg = client.cancel_reservation(r_id)
    if ok:
        bot.edit_message_text(f"✅ {msg}", chat_id, call.message.message_id)
    else:
        bot.edit_message_text(f"❌ خطا در لغو سرویس: {msg}", chat_id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "dismiss")
def callback_dismiss(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)

# ----------------- Manual Reservation Wizard -----------------

def start_manual_reserve(chat_id):
    bot.send_chat_action(chat_id, "typing")
    client = get_client(chat_id)
    ok, msg, tabs, booked = client.get_reserve_page()
    if not ok:
        bot.send_message(chat_id, f"❌ خطا: {msg}\nلطفاً ابتدا با پیامک وارد حساب خود شوید.")
        return

    if not tabs:
        bot.send_message(chat_id, "ℹ️ در حال حاضر هیچ روزی در سامانه دانشگاه برای رزرو باز نیست.")
        return

    user_states[chat_id] = {
        "step": "RESERVE_DATE",
        "tabs": tabs
    }

    markup = types.InlineKeyboardMarkup(row_width=1)
    for tab in tabs:
        markup.add(types.InlineKeyboardButton(f"📅 {tab['label']}", callback_data=f"sel_date:{tab['slug']}"))

    markup.add(types.InlineKeyboardButton("🏠 بازگشت به منوی اصلی", callback_data="back_to_main"))
    bot.send_message(chat_id, "🗓️ *مرحله ۱: لطفاً روز مورد نظر برای رزرو را انتخاب کنید:*", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def callback_back_to_main(call):
    user_states.pop(call.message.chat.id, None)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    cmd_start(call.message)

@bot.callback_query_handler(func=lambda call: call.data.startswith("sel_date:"))
def callback_select_date(call):
    chat_id = call.message.chat.id
    slug = call.data.split(":")[1]

    state = user_states.get(chat_id, {})
    tabs = state.get("tabs", [])
    tab_info = next((t for t in tabs if t["slug"] == slug), None)
    label = tab_info["label"] if tab_info else slug

    user_states[chat_id] = {
        "step": "RESERVE_TYPE",
        "date_slug": slug,
        "date_label": label,
        "tabs": tabs
    }

    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("🟢 فقط رفت", callback_data="sel_type:go"),
        types.InlineKeyboardButton("🔵 فقط برگشت", callback_data="sel_type:return"),
        types.InlineKeyboardButton("🟣 رفت و برگشت", callback_data="sel_type:both")
    )
    markup.add(types.InlineKeyboardButton("🔙 بازگشت به انتخاب تاریخ", callback_data="back_to_date_select"))

    bot.edit_message_text(
        f"📅 تاریخ انتخابی: *{label}*\n\n"
        "نوع سرویس مورد نظر را مشخص کنید:",
        chat_id,
        call.message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "back_to_date_select")
def callback_back_to_date_select(call):
    start_manual_reserve(call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("sel_type:"))
def callback_select_type(call):
    chat_id = call.message.chat.id
    service_type = call.data.split(":")[1]

    state = user_states.get(chat_id, {})
    state["type"] = service_type

    if service_type in ["go", "both"]:
        state["step"] = "SELECT_GO_STATION"
        show_station_picker(chat_id, call.message.message_id, station_type="go", prompt="ایستگاه مبدا (رفت)")
    else:
        state["step"] = "SELECT_RET_STATION"
        show_station_picker(chat_id, call.message.message_id, station_type="return", prompt="ایستگاه مقصد (برگشت)")

def show_station_picker(chat_id, message_id, station_type="go", prompt="انتخاب ایستگاه"):
    client = get_client(chat_id)
    ok, stations = client.get_stations(station_type)
    if not ok or not stations:
        bot.send_message(chat_id, "❌ خطا در دریافت ایستگاه‌ها از سامانه.")
        return

    state = user_states.get(chat_id, {})
    state[f"{station_type}_stations"] = stations

    # Fetch user favorites for this direction
    user_favs = database.get_favorites(chat_id, station_type)
    fav_ids = {f["station_id"] for f in user_favs}

    markup = types.InlineKeyboardMarkup(row_width=1)

    # 1. Display Favorites at the very top if any exist
    if user_favs:
        for f in user_favs:
            label = f"⭐ {f['station_name']} (مسیر: {f['route_name']})"
            markup.add(types.InlineKeyboardButton(label[:38], callback_data=f"sel_st:{station_type}:{f['station_id']}"))

    # 2. Display general stations (prioritizing non-favorites, first 8)
    non_fav_stations = [s for s in stations if s["id"] not in fav_ids]
    for st in non_fav_stations[:8]:
        markup.add(types.InlineKeyboardButton(st["name"][:38], callback_data=f"sel_st:{station_type}:{st['id']}"))

    # Search and View All buttons
    markup.add(types.InlineKeyboardButton("🔍 جستجوی ایستگاه با تایپ نام", callback_data=f"search_st:{station_type}"))
    markup.add(types.InlineKeyboardButton("📜 نمایش تمام ایستگاه‌ها (صفحه‌بندی)", callback_data=f"all_st:{station_type}:0"))
    markup.add(types.InlineKeyboardButton("🔙 بازگشت به مرحله قبل", callback_data="back_to_type_select"))

    fav_hint = "\n*(ایستگاه‌های ستاره‌دار ⭐ علاقه‌مندی‌های شما هستند)*" if user_favs else ""
    text = f"📍 *{prompt}:*{fav_hint}\nایستگاه و مسیر دقیق خود را انتخاب کنید:"

    if message_id:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_type_select")
def callback_back_to_type_select(call):
    chat_id = call.message.chat.id
    state = user_states.get(chat_id, {})
    slug = state.get("date_slug")
    if slug:
        call.data = f"sel_date:{slug}"
        callback_select_date(call)
    else:
        start_manual_reserve(chat_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("all_st:"))
def callback_all_stations(call):
    chat_id = call.message.chat.id
    _, station_type, page_str = call.data.split(":")
    page = int(page_str)
    page_size = 7

    state = user_states.get(chat_id, {})
    stations = state.get(f"{station_type}_stations", [])

    total_pages = (len(stations) + page_size - 1) // page_size
    current_page_items = stations[page * page_size:(page + 1) * page_size]

    markup = types.InlineKeyboardMarkup(row_width=1)
    for st in current_page_items:
        markup.add(types.InlineKeyboardButton(st["name"][:38], callback_data=f"sel_st:{station_type}:{st['id']}"))

    nav_btns = []
    if page > 0:
        nav_btns.append(types.InlineKeyboardButton("⬅️ قبلی", callback_data=f"all_st:{station_type}:{page-1}"))
    if page < total_pages - 1:
        nav_btns.append(types.InlineKeyboardButton("بعدی ➡️", callback_data=f"all_st:{station_type}:{page+1}"))
    if nav_btns:
        markup.row(*nav_btns)

    markup.add(types.InlineKeyboardButton("🔙 بازگشت به لیست اصلی", callback_data=f"back_quick_st:{station_type}"))

    bot.edit_message_text(
        f"📜 *لیست تمام ایستگاه‌های { 'رفت' if station_type == 'go' else 'برگشت' } (صفحه {page+1} از {total_pages}):*",
        chat_id,
        call.message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("back_quick_st:"))
def callback_back_quick_st(call):
    station_type = call.data.split(":")[1]
    show_station_picker(call.message.chat.id, call.message.message_id, station_type=station_type)

@bot.callback_query_handler(func=lambda call: call.data.startswith("search_st:"))
def callback_search_st(call):
    chat_id = call.message.chat.id
    station_type = call.data.split(":")[1]
    user_states[chat_id]["step"] = "SEARCH_STATION"
    user_states[chat_id]["search_target_type"] = station_type

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 انصراف و بازگشت", callback_data=f"back_quick_st:{station_type}"))
    bot.edit_message_text(
        "🔍 لطفاً نام ایستگاه یا مقصد خود را ارسال کنید (مثلاً: `مصلی` یا `ولیعصر` یا `کمالوند`):",
        chat_id,
        call.message.message_id,
        reply_markup=markup
    )

def handle_station_search(chat_id, query_text):
    state = user_states.get(chat_id, {})
    station_type = state.get("search_target_type", "go")
    stations = state.get(f"{station_type}_stations", [])

    matched = [s for s in stations if query_text in s["name"]]
    if not matched:
        bot.send_message(chat_id, f"نتیجه‌ای برای «{query_text}» یافت نشد. لطفاً عبارت دیگری تایپ کنید:")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for st in matched[:10]:
        markup.add(types.InlineKeyboardButton(st["name"][:38], callback_data=f"sel_st:{station_type}:{st['id']}"))

    markup.add(types.InlineKeyboardButton("🔙 بازگشت به لیست ایستگاه‌ها", callback_data=f"back_quick_st:{station_type}"))
    bot.send_message(chat_id, f"🔍 نتایج جستجو برای *«{query_text}»:*", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("sel_st:"))
def callback_selected_station(call):
    chat_id = call.message.chat.id
    _, station_type, station_id = call.data.split(":")

    state = user_states.get(chat_id, {})
    stations = state.get(f"{station_type}_stations", [])
    st_info = next((s for s in stations if s["id"] == station_id), None)
    st_name = st_info["name"] if st_info else station_id

    state[f"{station_type}_station_id"] = station_id
    state[f"{station_type}_station_name"] = st_name

    date_slug = state["date_slug"]
    bot.edit_message_text(f"⏳ در حال استعلام ساعت‌های فعال برای:\n*{st_name}*...", chat_id, call.message.message_id)

    client = get_client(chat_id)
    ok, slots = client.get_time_slots(date_slug, station_id, station_type)
    if not ok or not slots:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 انتخاب ایستگاه دیگر", callback_data=f"back_quick_st:{station_type}"))
        bot.edit_message_text("❌ هیچ زمان خالی برای این ایستگاه در تاریخ انتخاب شده یافت نشد.", chat_id, call.message.message_id, reply_markup=markup)
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    for slot in slots:
        label = slot["label"]
        markup.add(types.InlineKeyboardButton(f"⏰ {label}", callback_data=f"sel_slot:{station_type}:{slot['value']}"))

    # Quick toggle favorite button
    is_fav = database.is_favorite(chat_id, station_type, station_id)
    fav_toggle_btn = (
        types.InlineKeyboardButton("⭐ افزودن این ایستگاه به علاقه‌مندی‌ها", callback_data=f"add_fav_quick:{station_type}:{station_id}")
        if not is_fav else
        types.InlineKeyboardButton("❌ حذف از علاقه‌مندی‌ها", callback_data=f"del_fav_quick:{station_type}:{station_id}")
    )
    markup.add(fav_toggle_btn)
    markup.add(types.InlineKeyboardButton("🔙 بازگشت به لیست ایستگاه‌ها", callback_data=f"back_quick_st:{station_type}"))

    bot.edit_message_text(
        f"🕒 *انتخاب ساعت سرویس { 'رفت' if station_type == 'go' else 'برگشت' }:*\n"
        f"ایستگاه انتخابی: *{st_name}*\n\n"
        "یکی از ساعت‌های موجود را انتخاب کنید:",
        chat_id,
        call.message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("add_fav_quick:") or call.data.startswith("del_fav_quick:"))
def callback_toggle_fav_quick(call):
    chat_id = call.message.chat.id
    action, st_type, st_id = call.data.split(":")

    state = user_states.get(chat_id, {})
    stations = state.get(f"{st_type}_stations", [])
    st_info = next((s for s in stations if s["id"] == st_id), None)

    if action == "add_fav_quick" and st_info:
        database.add_favorite(chat_id, st_type, st_id, st_info["station_name"], st_info["route_name"])
        bot.answer_callback_query(call.id, "ایستگاه به علاقه‌مندی‌ها اضافه شد! ⭐")
    elif action == "del_fav_quick":
        database.remove_favorite(chat_id, st_type, st_id)
        bot.answer_callback_query(call.id, "از علاقه‌مندی‌ها حذف شد.")

    # Refresh current station view
    call.data = f"sel_st:{st_type}:{st_id}"
    callback_selected_station(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("sel_slot:"))
def callback_selected_slot(call):
    chat_id = call.message.chat.id
    _, station_type, slot_val = call.data.split(":")

    state = user_states.get(chat_id, {})
    state[f"{station_type}_slot_val"] = slot_val

    service_type = state.get("type", "go")
    if service_type == "both" and station_type == "go":
        state["step"] = "SELECT_RET_STATION"
        show_station_picker(chat_id, call.message.message_id, station_type="return", prompt="ایستگاه مقصد (برگشت)")
        return

    show_reservation_confirmation(chat_id, call.message.message_id)

def show_reservation_confirmation(chat_id, message_id):
    state = user_states.get(chat_id, {})
    date_label = state.get("date_label")
    service_type = state.get("type")

    summary = f"📋 *پیش‌نمایش درخواست رزرو:*\n\n"
    summary += f"📅 **تاریخ:** {date_label}\n"

    if service_type in ["go", "both"]:
        st_name = state.get("go_station_name", "")
        slot_val = state.get("go_slot_val", "")
        time_m = slot_val.split("_")[-3:]
        time_str = f"{time_m[0]}:{time_m[1]}" if len(time_m) >= 2 else slot_val
        summary += f"🟢 **رفت:** {st_name}\n⏰ ساعت رفت: *{time_str}*\n"

    if service_type in ["return", "both"]:
        st_name = state.get("return_station_name", "")
        slot_val = state.get("return_slot_val", "")
        time_m = slot_val.split("_")[-3:]
        time_str = f"{time_m[0]}:{time_m[1]}" if len(time_m) >= 2 else slot_val
        summary += f"🔵 **برگشت:** {st_name}\n⏰ ساعت برگشت: *{time_str}*\n"

    summary += "\nآیا مایل به ثبت نهایی و رزرو هستید؟"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ تایید و ثبت رزرو", callback_data="confirm_reserve_submit"),
        types.InlineKeyboardButton("❌ انصراف", callback_data="cancel_reserve_flow")
    )
    markup.add(types.InlineKeyboardButton("🔙 بازگشت و اصلاح انتخاب", callback_data="back_to_type_select"))

    if message_id:
        bot.edit_message_text(summary, chat_id, message_id, reply_markup=markup)
    else:
        bot.send_message(chat_id, summary, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "cancel_reserve_flow")
def callback_cancel_reserve_flow(call):
    user_states.pop(call.message.chat.id, None)
    bot.edit_message_text("❌ عملیات رزرو لغو شد.", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "confirm_reserve_submit")
def callback_submit_reserve(call):
    chat_id = call.message.chat.id
    state = user_states.get(chat_id, {})
    if not state:
        bot.edit_message_text("⚠️ اطلاعات منقضی شده است. مجدداً رزرو را شروع کنید.", chat_id, call.message.message_id)
        return

    bot.edit_message_text("⏳ در حال ثبت رزرو در سامانه دانشگاه و کسر اعتبار...", chat_id, call.message.message_id)

    date_slug = state.get("date_slug")
    date_label = state.get("date_label")
    go_station = state.get("go_station_id")
    go_slot = state.get("go_slot_val")
    ret_station = state.get("return_station_id")
    ret_slot = state.get("return_slot_val")

    client = get_client(chat_id)
    ok, msg, new_booked = client.reserve(
        date_slug=date_slug,
        go_station=go_station,
        go_slot=go_slot,
        return_station=ret_station,
        return_slot=ret_slot
    )

    user_states.pop(chat_id, None)
    if ok:
        success_text = (
            f"🎉 **{msg}**\n\n"
            f"📅 تاریخ: *{date_label}*\n"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        for b in new_booked:
            success_text += f"• {b['info']}\n"
            r_id = b.get("r_id")
            if r_id:
                markup.add(types.InlineKeyboardButton(f"❌ لغو همین سرویس ({r_id})", callback_data=f"cancel_trip:{r_id}"))

        markup.add(types.InlineKeyboardButton("🏠 بازگشت به منوی اصلی", callback_data="back_to_main"))
        bot.edit_message_text(success_text, chat_id, call.message.message_id, reply_markup=markup)
    else:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 تلاش مجدد", callback_data="back_to_type_select"))
        bot.edit_message_text(f"❌ **عدم موفقیت در رزرو:**\n{msg}", chat_id, call.message.message_id, reply_markup=markup)

# ----------------- Auto Reserve Settings (Per User) -----------------

def show_auto_reserve_settings(chat_id):
    settings = database.get_user_settings(chat_id)
    enabled = settings.get("enabled", False)
    target_time = settings.get("target_time", "00:01")
    go_st = settings.get("go_station_name") or "ثبت نشده"
    go_t = settings.get("go_time") or "ثبت نشده"
    ret_st = settings.get("return_station_name") or "ثبت نشده"
    ret_t = settings.get("return_time") or "ثبت نشده"

    status_icon = "فعال ✅" if enabled else "غیرفعال ❌"

    text = (
        "⚙️ *تنظیمات اختصاصی رزرو خودکار:*\n\n"
        f"• وضعیت سیستم: *{status_icon}*\n"
        f"• ساعت اجرای خودکار: *{target_time}*\n"
        f"• ایستگاه رفت: *{go_st}* (ساعت {go_t})\n"
        f"• ایستگاه برگشت: *{ret_st}* (ساعت {ret_t})\n\n"
        "برای تغییر هر یک از موارد از گزینه‌های زیر استفاده کنید:"
    )

    markup = types.InlineKeyboardMarkup(row_width=1)
    toggle_text = "🔴 غیرفعال‌سازی رزرو خودکار" if enabled else "🟢 فعال‌سازی رزرو خودکار"
    markup.add(
        types.InlineKeyboardButton(toggle_text, callback_data="toggle_auto"),
        types.InlineKeyboardButton("⏰ تغییر ساعت اجرای روزانه", callback_data="change_auto_time"),
        types.InlineKeyboardButton("🟢 انتخاب ایستگاه/ساعت رفت خودکار", callback_data="set_auto_st:go"),
        types.InlineKeyboardButton("🔵 انتخاب ایستگاه/ساعت برگشت خودکار", callback_data="set_auto_st:return"),
        types.InlineKeyboardButton("⚡ اجرای آزمایشی رزرو خودکار (همین الان)", callback_data="test_auto_now"),
        types.InlineKeyboardButton("🏠 بازگشت به منوی اصلی", callback_data="back_to_main")
    )
    bot.send_message(chat_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_auto_st:"))
def callback_set_auto_station(call):
    chat_id = call.message.chat.id
    st_type = call.data.split(":")[1]
    client = get_client(chat_id)
    ok, stations = client.get_stations(st_type)

    if not ok or not stations:
        bot.answer_callback_query(call.id, "خطا در دریافت لیست ایستگاه‌ها.")
        return

    # Check favorites first
    favs = database.get_favorites(chat_id, st_type)
    markup = types.InlineKeyboardMarkup(row_width=1)

    if favs:
        for f in favs:
            markup.add(types.InlineKeyboardButton(f"⭐ {f['station_name']} ({f['route_name']})", callback_data=f"save_auto_st:{st_type}:{f['station_id']}"))

    for st in stations[:8]:
        markup.add(types.InlineKeyboardButton(st["name"][:38], callback_data=f"save_auto_st:{st_type}:{st['id']}"))

    markup.add(types.InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="back_to_settings"))
    bot.edit_message_text(f"ایستگاه پیش‌فرض برای {'رفت' if st_type == 'go' else 'برگشت'} خودکار را انتخاب کنید:", chat_id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("save_auto_st:"))
def callback_save_auto_station(call):
    chat_id = call.message.chat.id
    _, st_type, st_id = call.data.split(":")

    client = get_client(chat_id)
    ok, stations = client.get_stations(st_type)
    st_info = next((s for s in stations if s["id"] == st_id), None) if ok else None
    st_name = st_info["name"] if st_info else st_id

    settings = database.get_user_settings(chat_id)
    if st_type == "go":
        settings["go_station_id"] = st_id
        settings["go_station_name"] = st_name
    else:
        settings["return_station_id"] = st_id
        settings["return_station_name"] = st_name
    database.save_user_settings(chat_id, settings)

    # Now ask for default time
    user_states[chat_id] = {
        "step": "SET_AUTO_SLOT_TIME",
        "station_type": st_type
    }

    markup = types.InlineKeyboardMarkup(row_width=3)
    common_hours = ["07:15", "08:15", "09:15", "11:15", "12:15", "13:30", "14:00", "15:00", "16:30", "17:30", "18:30"]
    for h in common_hours:
        markup.add(types.InlineKeyboardButton(f"⏰ {h}", callback_data=f"save_auto_time:{st_type}:{h}"))

    markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_settings"))
    bot.edit_message_text(f"ایستگاه ثبت شد.\nحالا ساعت پیش‌فرض برای {'رفت' if st_type == 'go' else 'برگشت'} را انتخاب کنید:", chat_id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("save_auto_time:"))
def callback_save_auto_time(call):
    chat_id = call.message.chat.id
    _, st_type, h_val = call.data.split(":")

    settings = database.get_user_settings(chat_id)
    if st_type == "go":
        settings["go_time"] = h_val
    else:
        settings["return_time"] = h_val
    database.save_user_settings(chat_id, settings)

    bot.answer_callback_query(call.id, f"ساعت {h_val} ذخیره شد.")
    bot.delete_message(chat_id, call.message.message_id)
    show_auto_reserve_settings(chat_id)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_settings")
def callback_back_to_settings(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    show_auto_reserve_settings(call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data == "toggle_auto")
def callback_toggle_auto(call):
    chat_id = call.message.chat.id
    settings = database.get_user_settings(chat_id)
    settings["enabled"] = not settings.get("enabled", False)
    database.save_user_settings(chat_id, settings)

    bot.answer_callback_query(call.id, "تنظیمات بروزرسانی شد.")
    bot.delete_message(chat_id, call.message.message_id)
    show_auto_reserve_settings(chat_id)

@bot.callback_query_handler(func=lambda call: call.data == "change_auto_time")
def callback_change_auto_time(call):
    chat_id = call.message.chat.id
    user_states[chat_id] = {"step": "SET_AUTO_TIME"}
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 انصراف", callback_data="back_to_settings"))
    bot.edit_message_text(
        "⏰ ساعت مورد نظر برای اجرای روزانه رزرو خودکار را در فرمت `HH:MM` ارسال کنید:\n"
        "(مثلاً: `00:01` یا `23:30`)",
        chat_id,
        call.message.message_id,
        reply_markup=markup
    )

def handle_set_auto_time(chat_id, text):
    time_str = text.strip()
    parts = time_str.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        bot.send_message(chat_id, "⚠️ فرمت ساعت صحیح نیست. لطفاً مانند `00:01` بفرستید:")
        return

    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        bot.send_message(chat_id, "⚠️ ساعت یا دقیقه در بازه معتبر نیست.")
        return

    formatted_time = f"{h:02d}:{m:02d}"
    settings = database.get_user_settings(chat_id)
    settings["target_time"] = formatted_time
    database.save_user_settings(chat_id, settings)
    user_states.pop(chat_id, None)

    bot.send_message(
        chat_id,
        f"✅ ساعت اجرای خودکار با موفقیت روی *{formatted_time}* تنظیم شد.",
        reply_markup=get_main_keyboard(True)
    )

@bot.callback_query_handler(func=lambda call: call.data == "test_auto_now")
def callback_test_auto_now(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id, "در حال بررسی و اجرای رزرو خودکار...")
    bot.send_message(chat_id, "🚀 شروع اجرای آزمایشی رزرو خودکار...")
    scheduler.run_auto_reserve_for_user(chat_id)

# ----------------- Start Bot -----------------

def main():
    logger.info("Starting Multi-User Telegram Bot with Infinity Polling...")
    print("Multi-User Autobus Bot is running...")

    while True:
        try:
            bot.infinity_polling(timeout=25, long_polling_timeout=25)
        except Exception as e:
            logger.error(f"Polling error: {e}. Retrying in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    main()
