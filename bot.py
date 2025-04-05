import logging
import re
import asyncio
from datetime import datetime
import pytz

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

import database  # وحدة قراءة الإعدادات

# تحميل الإعدادات من config.json
config = database.load_config()
numeric = config["numeric"]
text_config = config["text"]
status_config = config["status"]

# تحميل المتغيرات الأساسية من ملف الإعدادات
TOKEN = numeric["TOKEN"]
S1_XPB = numeric["S1_XPB"]
S1_RE = numeric["RE"]
S1_PA = numeric["PA"]

S2_XPS = numeric["S2_XPS"]
S2_REA = numeric["REA"]
S2_REB = numeric["REB"]
# في خدمة S2 للبند بيع [PUSD] يتم استخدام متغير PA كعنوان التحويل في البيع أيضاً
S2_PA = numeric["PA"]

SYRIATEL_CASH_ACCOUNT = numeric["SYRIATEL_CASH"]
MTN_CASH_ACCOUNT = numeric["MTN_CASH"]
SHAM_CASH_ACCOUNT = numeric["SHAM_CASH"]
BEMO_BANK_ACCOUNT = numeric["BEMO_BANK"]

CHAT_IDS = numeric["chat_ids"]
CHANNEL_URL = numeric["channel_url"]

# إعدادات البوت
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# لتخزين الطلبات بشكل مؤقت
orders = {}

# دوال تقريب الأسعار
def format_usd(value):
    rounded = round(value, 1)
    if rounded == int(rounded):
        return str(int(rounded))
    else:
        return str(rounded)

def format_syp(value):
    rounded = round(value / 1000) * 1000
    return str(int(rounded))

# -----------------------
# تعريف حالات FSM للخدمات
# -----------------------
class OrderS1(StatesGroup):
    waiting_for_amount = State()
    waiting_for_company = State()
    waiting_for_phone = State()
    waiting_for_confirmation = State()
    waiting_for_payeer = State()

class OrderS2a(StatesGroup):
    waiting_for_amount = State()
    waiting_for_payeer = State()
    waiting_for_payment_method = State()
    waiting_for_transfer_code = State()

class OrderS2b(StatesGroup):
    waiting_for_amount = State()
    waiting_for_payment_method = State()
    waiting_for_account_input = State()
    waiting_for_completion = State()

# -----------------------
# كيبورد القائمة الرئيسية
# -----------------------
def main_menu_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📱 تعبئة رصيد", callback_data="service_S1"),
        InlineKeyboardButton("💱 بيع/شراء PUSD", callback_data="service_S2")
    )
    keyboard.add(
        InlineKeyboardButton("بيع وشراء عملات رقمية", callback_data="service_S3"),
        InlineKeyboardButton("📢 انضم للقناة", url=CHANNEL_URL)
    )
    return keyboard

WELCOME_TEXT = text_config.get("welcome_message", "<b>أهلاً وسهلاً!</b>")

# -----------------------
# أوامر البداية والقائمة الرئيسية
# -----------------------
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    if not status_config.get("bot_active", True):
        await message.answer("البوت تحت الصيانة حاليًا.")
        return
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard())

@dp.callback_query_handler(lambda c: c.data == "back_main", state="*")
async def process_back_main(callback_query: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await callback_query.message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard())
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "cancel", state="*")
async def process_cancel(callback_query: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await callback_query.message.answer("تم إلغاء العملية.", reply_markup=main_menu_keyboard())
    await callback_query.answer()

# -----------------------
# خدمة S1: تعبئة رصيد اتصالات
# -----------------------
@dp.callback_query_handler(lambda c: c.data == "service_S1")
async def service_s1(callback_query: types.CallbackQuery):
    amounts = [str(x) for x in numeric["S1_prices"]]
    keyboard = InlineKeyboardMarkup(row_width=2)
    for amt in amounts:
        keyboard.insert(InlineKeyboardButton(f"{amt} ل.س", callback_data=f"s1_amount_{amt}"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await OrderS1.waiting_for_amount.set()
    await callback_query.message.answer("نرجو اختيار المبلغ المراد تعبئته:", reply_markup=keyboard)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("s1_amount_"), state=OrderS1.waiting_for_amount)
async def s1_amount_selected(callback_query: types.CallbackQuery, state: FSMContext):
    amount = callback_query.data.split("_")[-1]
    await state.update_data(amount=amount)
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("SYRIATEL", callback_data="s1_company_SYRIATEL"),
        InlineKeyboardButton("MTN", callback_data="s1_company_MTN")
    )
    keyboard.add(InlineKeyboardButton("رجوع 🔙", callback_data="back_main"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await OrderS1.waiting_for_company.set()
    await callback_query.message.answer("اختر الشركة المطلوبة للتعبئة:", reply_markup=keyboard)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("s1_company_"), state=OrderS1.waiting_for_company)
async def s1_company_selected(callback_query: types.CallbackQuery, state: FSMContext):
    company = callback_query.data.split("_")[-1]
    await state.update_data(company=company)
    await OrderS1.waiting_for_phone.set()
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("رجوع 🔙", callback_data="back_s1_amount"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await callback_query.message.answer("نرجو منك ادخال رقم الهاتف الخليوي (يبدأ ب09 ومكون من 10 أرقام):", reply_markup=keyboard)
    await callback_query.answer()

@dp.message_handler(state=OrderS1.waiting_for_phone)
async def s1_phone_received(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if not re.fullmatch(r"09\d{8}", phone):
        await message.answer("رقم الهاتف غير صحيح. يرجى إدخال رقم هاتف يبدأ بـ09 ومكون من 10 أرقام.")
        return
    await state.update_data(phone=phone)
    data = await state.get_data()
    amount = data.get("amount")
    try:
        U = float(amount)
        J = (U * S1_RE) / S1_XPB
        J = format_usd(J)
    except Exception:
        J = "N/A"
    summary = f"""<b>تفاصيل طلب التعبئة:</b>
المبلغ: {amount} ل.س
الشركة: {data.get("company")}
رقم الهاتف: {phone}
● المبلغ المراد تعبئته: {amount} ل.س
● رقم هاتف المستخدم: {phone}
● نرجو تحويل مبلغ <b>{J} دولار بايير</b> إلى عنوان بايير التالي: <b>{S1_PA}</b>
● عند الإنتهاء من عملية التحويل انقر على تأكيد العملية
"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(InlineKeyboardButton("تأكيد العملية ✅️", callback_data="s1_confirm_yes"))
    keyboard.add(InlineKeyboardButton("رجوع 🔙", callback_data="back_s1_phone"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await OrderS1.waiting_for_confirmation.set()
    await message.answer(summary, reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data == "s1_confirm_yes", state=OrderS1.waiting_for_confirmation)
async def s1_confirm(callback_query: types.CallbackQuery, state: FSMContext):
    await OrderS1.waiting_for_payeer.set()
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("رجوع 🔙", callback_data="back_s1_confirm"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await callback_query.message.answer("الرجاء إدخال حساب بايير الخاص بك (10 أرقام، يمكن أن يبدأ بحرف p):", reply_markup=keyboard)
    await callback_query.answer()

@dp.message_handler(state=OrderS1.waiting_for_payeer)
async def s1_payeer_received(message: types.Message, state: FSMContext):
    payeer = message.text.strip()
    if not re.fullmatch(r"[pP]?\d{10}", payeer):
        await message.answer("حساب بايير غير صحيح. يرجى التأكد من أنه مكون من 10 أرقام وقد يبدأ بحرف p.")
        return
    await state.update_data(payeer=payeer)
    data = await state.get_data()
    tz = pytz.timezone("Asia/Damascus")
    order_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    order_id = str(int(datetime.now().timestamp()))
    summary = f"""<b>تم استلام طلب التعبئة بنجاح!</b>

<b>تفاصيل الطلب:</b>
رقم الطلب: {order_id}
تاريخ الطلب: {order_time}
المبلغ: {data.get("amount")} ل.س
الشركة: {data.get("company")}
رقم الهاتف: {data.get("phone")}
حساب بايير: {payeer}
"""
    await message.answer(summary)
    orders[order_id] = {"chat_id": message.chat.id, "service": "S1", "status": "معلق"}
    admin_kb = InlineKeyboardMarkup(row_width=1)
    admin_kb.add(InlineKeyboardButton("تم استلام الطلب وجاري العمل على تنفيذه سوف يأخذ هذا بعض الوقت، نرجو منكم الإنتظار وشكرا، سيتم إعلامكم عند نجاح العملية.", callback_data=f"admin_receive_{order_id}"))
    admin_kb.add(InlineKeyboardButton("تم معالجة الطلب بنجاح، فقط في حالة وجود اي مشكلة مراسلة الأدمن لكي يتم ارسال إثباتات نجاح العملية، على عنوان معرف التلغرام التالي @useretc.", callback_data=f"admin_success_{order_id}"))
    admin_kb.add(InlineKeyboardButton("تم إلغاء العملية بسبب عدم إكمال الشروط، نرجو إعادة تشغيل البوت وإعادة الطلب بشكل مكتمل.", callback_data=f"admin_cancel_{order_id}"))
    admin_message = f"""🚀 <b>طلب تعبئة رصيد جديد</b> 🚀
رقم الطلب: {order_id}
تاريخ الطلب: {order_time}
👤 المستخدم: @{message.from_user.username if message.from_user.username else message.from_user.full_name}
المبلغ: {data.get("amount")} ل.س
الشركة: {data.get("company")}
رقم الهاتف: {data.get("phone")}
حساب بايير: {payeer}
"""
    for admin_id in CHAT_IDS:
        try:
            await bot.send_message(admin_id, admin_message, reply_markup=admin_kb)
        except Exception as e:
            logging.error(f"Error sending to admin {admin_id}: {e}")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "back_s1_amount", state=OrderS1.waiting_for_company)
async def back_s1_amount(callback_query: types.CallbackQuery, state: FSMContext):
    await OrderS1.waiting_for_amount.set()
    amounts = [str(x) for x in numeric["S1_prices"]]
    keyboard = InlineKeyboardMarkup(row_width=2)
    for amt in amounts:
        keyboard.insert(InlineKeyboardButton(f"{amt} ل.س", callback_data=f"s1_amount_{amt}"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await callback_query.message.answer("نرجو اختيار المبلغ المراد تعبئته:", reply_markup=keyboard)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "back_s1_phone", state=OrderS1.waiting_for_confirmation)
async def back_s1_phone(callback_query: types.CallbackQuery, state: FSMContext):
    await OrderS1.waiting_for_phone.set()
    await callback_query.message.answer("أعد إدخال رقم الهاتف الخليوي:")
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "back_s1_confirm", state=OrderS1.waiting_for_payeer)
async def back_s1_confirm(callback_query: types.CallbackQuery, state: FSMContext):
    await OrderS1.waiting_for_confirmation.set()
    data = await state.get_data()
    try:
        U = float(data.get("amount"))
        J = (U * S1_RE) / S1_XPB
        J = format_usd(J)
    except Exception:
        J = "N/A"
    summary = f"""<b>تفاصيل طلب التعبئة:</b>
المبلغ: {data.get("amount")} ل.س
الشركة: {data.get("company")}
رقم الهاتف: {data.get("phone")}
● المبلغ المراد تعبئته: {data.get("amount")} ل.س
● رقم هاتف المستخدم: {data.get("phone")}
● نرجو تحويل مبلغ <b>{J} دولار بايير</b> إلى عنوان بايير التالي: <b>{S1_PA}</b>
● عند الإنتهاء من عملية التحويل انقر على تأكيد العملية
"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(InlineKeyboardButton("تأكيد العملية ✅️", callback_data="s1_confirm_yes"))
    keyboard.add(InlineKeyboardButton("رجوع 🔙", callback_data="back_s1_phone"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await callback_query.message.answer(summary, reply_markup=keyboard)
    await callback_query.answer()

# -----------------------
# خدمة S2: بيع وشراء [PUSD]
# -----------------------
@dp.callback_query_handler(lambda c: c.data == "service_S2")
async def service_s2(callback_query: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("شراء [PUSD]", callback_data="s2a_start"),
        InlineKeyboardButton("بيع [PUSD]", callback_data="s2b_start")
    )
    keyboard.add(InlineKeyboardButton("رجوع 🔙", callback_data="back_main"))
    await callback_query.message.answer("اختر العملية المطلوبة في خدمة PUSD:", reply_markup=keyboard)
    await callback_query.answer()

# --- خدمة S2a: شراء [PUSD] ---
@dp.callback_query_handler(lambda c: c.data == "s2a_start")
async def s2a_start(callback_query: types.CallbackQuery):
    amounts = ["5", "10", "25", "50", "100"]
    keyboard = InlineKeyboardMarkup(row_width=3)
    for amt in amounts:
        keyboard.insert(InlineKeyboardButton(f"{amt} $", callback_data=f"s2a_amount_{amt}"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await OrderS2a.waiting_for_amount.set()
    instruction_text = ("● الرجاء اختيار المبلغ الذي ترغب في شرائه.\n"
                        "● المبالغ من 5 الى 25 يتم الدفع عن طريق SYRIATEL & MTN CASH.\n"
                        "● باقي المبالغ الأكبر يتم الدفع عن طريق شام كاش وبنك بيمو.")
    await callback_query.message.answer(instruction_text, reply_markup=keyboard)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("s2a_amount_"), state=OrderS2a.waiting_for_amount)
async def s2a_amount_selected(callback_query: types.CallbackQuery, state: FSMContext):
    amount = callback_query.data.split("_")[-1]
    await state.update_data(amount=amount)
    await OrderS2a.waiting_for_payeer.set()
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("رجوع 🔙", callback_data="back_s2a_amount"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await callback_query.message.answer("الرجاء إدخال حساب بايير الخاص بك:", reply_markup=keyboard)
    await callback_query.answer()

@dp.message_handler(state=OrderS2a.waiting_for_payeer)
async def s2a_payeer_received(message: types.Message, state: FSMContext):
    payeer = message.text.strip()
    if not re.fullmatch(r"[pP]?\d{10}", payeer):
        await message.answer("حساب بايير غير صحيح. يرجى التأكد من أنه مكون من 10 أرقام وقد يبدأ بحرف p.")
        return
    await state.update_data(payeer=payeer)
    data = await state.get_data()
    try:
        amount = float(data.get("amount"))
    except Exception:
        amount = 0
    if amount <= 25:
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("SYRIATEL CASH", callback_data="s2a_method_SYRIATEL"),
            InlineKeyboardButton("MTN CASH", callback_data="s2a_method_MTN")
        )
    else:
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("SHAM CASH", callback_data="s2a_method_SHAM"),
            InlineKeyboardButton("BEMO BANK", callback_data="s2a_method_BEMO")
        )
    keyboard.add(InlineKeyboardButton("رجوع 🔙", callback_data="back_s2a_payeer"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await OrderS2a.waiting_for_payment_method.set()
    await message.answer("اختر طريقة الدفع المناسبة:", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith("s2a_method_"), state=OrderS2a.waiting_for_payment_method)
async def s2a_payment_method_selected(callback_query: types.CallbackQuery, state: FSMContext):
    method = callback_query.data.split("_")[-1]
    await state.update_data(payment_method=method)
    data = await state.get_data()
    try:
        amount = float(data.get("amount"))
    except Exception:
        amount = 0
    L = amount * S2_XPS * S2_REA
    L = format_syp(L)
    if method in ["SYRIATEL", "MTN"]:
        account = SYRIATEL_CASH_ACCOUNT if method == "SYRIATEL" else MTN_CASH_ACCOUNT
    else:
        account = SHAM_CASH_ACCOUNT if method == "SHAM" else BEMO_BANK_ACCOUNT

    method_full = {"SYRIATEL": "SYRIATEL CASH", "MTN": "MTN CASH", "SHAM": "SHAM CASH", "BEMO": "BEMO BANK"}.get(method, "")
        
    await state.update_data(payment_account=account, calculated_amount=L)
    instruction = f"""<b>تعليمات الدفع:</b>
● الرجاء إرسال مبلغ <b>{L} ل.س</b> عبر طريقة الدفع <b>{method_full}</b> إلى الحساب التالي: <b>{account}</b>
● الاحتفاظ بكود نجاح عملية التحويل.
● بعد الانتهاء، اضغط على زر "إتمام عملية الدفع".
"""
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("إتمام عملية الدفع ✅️", callback_data="s2a_done"))
    keyboard.add(InlineKeyboardButton("رجوع 🔙", callback_data="back_s2a_method"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await OrderS2a.waiting_for_transfer_code.set()
    await callback_query.message.answer(instruction, reply_markup=keyboard)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "s2a_done", state=OrderS2a.waiting_for_transfer_code)
async def s2a_done(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.answer("الرجاء إدخال كود عملية التحويل (10 أرقام أو أكثر):")
    await callback_query.answer()

@dp.message_handler(state=OrderS2a.waiting_for_transfer_code)
async def s2a_transfer_code_received(message: types.Message, state: FSMContext):
    code = message.text.strip()
    if not re.fullmatch(r"\d{10,}", code):
        await message.answer("الكود غير صحيح. يرجى إدخال كود يتكون من 10 أرقام أو أكثر.")
        return
    await state.update_data(transfer_code=code)
    data = await state.get_data()
    tz = pytz.timezone("Asia/Damascus")
    order_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    order_id = str(int(datetime.now().timestamp()))
    summary = f"""<b>تم استلام طلب شراء [PUSD] بنجاح!</b>

<b>تفاصيل الطلب:</b>
رقم الطلب: {order_id}
تاريخ الطلب: {order_time}
المبلغ: {data.get("amount")} $
حساب بايير: {data.get("payeer")}
طريقة الدفع: {data.get("payment_method")}
كود التحويل: {code}
"""
    await message.answer(summary)
    orders[order_id] = {"chat_id": message.chat.id, "service": "S2a", "status": "معلق"}
    admin_kb = InlineKeyboardMarkup(row_width=1)
    admin_kb.add(InlineKeyboardButton("تم استلام الطلب وجاري العمل على تنفيذه سوف يأخذ هذا بعض الوقت، نرجو منكم الإنتظار وشكرا، سيتم إعلامكم عند نجاح العملية.", callback_data=f"admin_receive_{order_id}"))
    admin_kb.add(InlineKeyboardButton("تم معالجة الطلب بنجاح، فقط في حالة وجود اي مشكلة مراسلة الأدمن لكي يتم ارسال إثباتات نجاح العملية، على عنوان معرف التلغرام التالي @useretc.", callback_data=f"admin_success_{order_id}"))
    admin_kb.add(InlineKeyboardButton("تم إلغاء العملية بسبب عدم إكمال الشروط، نرجو إعادة تشغيل البوت وإعادة الطلب بشكل مكتمل.", callback_data=f"admin_cancel_{order_id}"))
    admin_message = f"""🚀 <b>طلب شراء [PUSD] جديد</b> 🚀
رقم الطلب: {order_id}
تاريخ الطلب: {order_time}
👤 المستخدم: @{message.from_user.username if message.from_user.username else message.from_user.full_name}
المبلغ: {data.get("amount")} $
حساب بايير: {data.get("payeer")}
طريقة الدفع: {data.get("payment_method")}
كود التحويل: {code}
"""
    for admin_id in CHAT_IDS:
        try:
            await bot.send_message(admin_id, admin_message, reply_markup=admin_kb)
        except Exception as e:
            logging.error(f"Error sending to admin {admin_id}: {e}")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "back_s2a_amount", state=OrderS2a.waiting_for_amount)
async def back_s2a_amount(callback_query: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await service_s2(callback_query)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "back_s2a_payeer", state=OrderS2a.waiting_for_payment_method)
async def back_s2a_payeer(callback_query: types.CallbackQuery, state: FSMContext):
    await OrderS2a.waiting_for_payeer.set()
    await callback_query.message.answer("أعد إدخال حساب بايير الخاص بك:")
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "back_s2a_method", state=OrderS2a.waiting_for_transfer_code)
async def back_s2a_method(callback_query: types.CallbackQuery, state: FSMContext):
    await OrderS2a.waiting_for_payment_method.set()
    data = await state.get_data()
    try:
        amount = float(data.get("amount"))
    except Exception:
        amount = 0
    if amount <= 25:
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("SYRIATEL CASH", callback_data="s2a_method_SYRIATEL"),
            InlineKeyboardButton("MTN CASH", callback_data="s2a_method_MTN")
        )
    else:
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("SHAM CASH", callback_data="s2a_method_SHAM"),
            InlineKeyboardButton("BEMO BANK", callback_data="s2a_method_BEMO")
        )
    keyboard.add(InlineKeyboardButton("رجوع 🔙", callback_data="back_s2a_payeer"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await callback_query.message.answer("اختر طريقة الدفع المناسبة:", reply_markup=keyboard)
    await callback_query.answer()

# --- خدمة S2b: بيع [PUSD] ---
@dp.callback_query_handler(lambda c: c.data == "s2b_start")
async def s2b_start(callback_query: types.CallbackQuery):
    amounts = ["5", "10", "25", "50", "100"]
    keyboard = InlineKeyboardMarkup(row_width=3)
    for amt in amounts:
        keyboard.insert(InlineKeyboardButton(f"{amt} $", callback_data=f"s2b_amount_{amt}"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await OrderS2b.waiting_for_amount.set()
    instruction_text = ("● الرجاء اختيار المبلغ الذي ترغب في بيعه.\n"
                        "● المبالغ من 5 الى 25 يتم الدفع عن طريق SYRIATEL & MTN CASH.\n"
                        "● باقي المبالغ الأكبر يتم الدفع عن طريق شام كاش وبنك بيمو.")
    await callback_query.message.answer(instruction_text, reply_markup=keyboard)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("s2b_amount_"), state=OrderS2b.waiting_for_amount)
async def s2b_amount_selected(callback_query: types.CallbackQuery, state: FSMContext):
    amount = callback_query.data.split("_")[-1]
    await state.update_data(amount=amount)
    try:
        amount_val = float(amount)
    except Exception:
        amount_val = 0
    if amount_val <= 25:
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("SYRIATEL CASH", callback_data="s2b_method_SYRIATEL"),
            InlineKeyboardButton("MTN CASH", callback_data="s2b_method_MTN")
        )
    else:
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("SHAM CASH", callback_data="s2b_method_SHAM"),
            InlineKeyboardButton("BEMO BANK", callback_data="s2b_method_BEMO")
        )
    keyboard.add(InlineKeyboardButton("رجوع 🔙", callback_data="back_s2b_amount"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await OrderS2b.waiting_for_payment_method.set()
    await callback_query.message.answer("اختر طريقة الدفع المناسبة:", reply_markup=keyboard)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("s2b_method_"), state=OrderS2b.waiting_for_payment_method)
async def s2b_payment_method_selected(callback_query: types.CallbackQuery, state: FSMContext):
    method = callback_query.data.split("_")[-1]
    await state.update_data(payment_method=method)
    method_full = {"SYRIATEL": "SYRIATEL CASH", "MTN": "MTN CASH", "SHAM": "SHAM CASH", "BEMO": "BEMO BANK"}.get(method, "")
    await OrderS2b.waiting_for_account_input.set()
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("رجوع 🔙", callback_data="back_s2b_method"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await callback_query.message.answer(f"الرجاء إدخال رقم حسابك على {method_full}:", reply_markup=keyboard)
    await callback_query.answer()

@dp.message_handler(state=OrderS2b.waiting_for_account_input)
async def s2b_account_received(message: types.Message, state: FSMContext):
    account_input = message.text.strip()
    await state.update_data(user_account=account_input)
    data = await state.get_data()
    try:
        amount = float(data.get("amount"))
    except Exception:
        amount = 0
    M = amount * S1_XPB * S2_REB
    M = format_syp(M)
    instruction = f"""<b>تعليمات عملية البيع:</b>
● سوف تستلم مبلغ <b>{M} ل.س</b> على حسابك.
● الرجاء إرسال مبلغ <b>{data.get("amount")} $</b> إلى الحساب: <b>{S2_PA}</b> على بايير.
● بعد التحويل، اضغط على زر "إتمام العملية".
"""
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("إتمام العملية ✅️", callback_data="s2b_done"))
    keyboard.add(InlineKeyboardButton("رجوع 🔙", callback_data="back_s2b_account"))
    keyboard.add(InlineKeyboardButton("إلغاء العملية", callback_data="cancel"))
    await OrderS2b.waiting_for_completion.set()
    await message.answer(instruction, reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data == "s2b_done", state=OrderS2b.waiting_for_completion)
async def s2b_done(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.answer("الرجاء إدخال حساب بايير الذي تم التحويل منه (10 أرقام، يمكن أن يبدأ بحرف p):")
    await callback_query.answer()

@dp.message_handler(state=OrderS2b.waiting_for_completion)
async def s2b_completion_received(message: types.Message, state: FSMContext):
    payeer = message.text.strip()
    if not re.fullmatch(r"[pP]?\d{10}", payeer):
        await message.answer("حساب بايير غير صحيح. يرجى التأكد من أنه مكون من 10 أرقام وقد يبدأ بحرف p.")
        return
    await state.update_data(payeer=payeer)
    data = await state.get_data()
    tz = pytz.timezone("Asia/Damascus")
    order_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    order_id = str(int(datetime.now().timestamp()))
    summary = f"""<b>تم استلام طلب بيع [PUSD] بنجاح!</b>

<b>تفاصيل الطلب:</b>
رقم الطلب: {order_id}
تاريخ الطلب: {order_time}
المبلغ: {data.get("amount")} $
طريقة الدفع: {data.get("payment_method")}
حساب الدفع: {data.get("user_account")}
حساب بايير: {payeer}
"""
    await message.answer(summary)
    orders[order_id] = {"chat_id": message.chat.id, "service": "S2b", "status": "معلق"}
    admin_kb = InlineKeyboardMarkup(row_width=1)
    admin_kb.add(InlineKeyboardButton("تم استلام الطلب وجاري العمل على تنفيذه سوف يأخذ هذا بعض الوقت، نرجو منكم الإنتظار وشكرا، سيتم إعلامكم عند نجاح العملية.", callback_data=f"admin_receive_{order_id}"))
    admin_kb.add(InlineKeyboardButton("تم معالجة الطلب بنجاح، فقط في حالة وجود اي مشكلة مراسلة الأدمن لكي يتم ارسال إثباتات نجاح العملية، على عنوان معرف التلغرام التالي @useretc.", callback_data=f"admin_success_{order_id}"))
    admin_kb.add(InlineKeyboardButton("تم إلغاء العملية بسبب عدم إكمال الشروط، نرجو إعادة تشغيل البوت وإعادة الطلب بشكل مكتمل.", callback_data=f"admin_cancel_{order_id}"))
    admin_message = f"""🚀 <b>طلب بيع [PUSD] جديد</b> 🚀
رقم الطلب: {order_id}
تاريخ الطلب: {order_time}
👤 المستخدم: @{message.from_user.username if message.from_user.username else message.from_user.full_name}
المبلغ: {data.get("amount")} $
طريقة الدفع: {data.get("payment_method")}
حساب الدفع: {data.get("user_account")}
حساب بايير: {payeer}
"""
    for admin_id in CHAT_IDS:
        try:
            await bot.send_message(admin_id, admin_message, reply_markup=admin_kb)
        except Exception as e:
            logging.error(f"Error sending to admin {admin_id}: {e}")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "back_s2b_amount", state=OrderS2b.waiting_for_amount)
async def back_s2b_amount(callback_query: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await service_s2(callback_query)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "back_s2b_method", state=OrderS2b.waiting_for_payment_method)
async def back_s2b_method(callback_query: types.CallbackQuery, state: FSMContext):
    await OrderS2b.waiting_for_amount.set()
    await callback_query.message.answer("أعد اختيار المبلغ:")
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "back_s2b_account", state=OrderS2b.waiting_for_completion)
async def back_s2b_account(callback_query: types.CallbackQuery, state: FSMContext):
    await OrderS2b.waiting_for_account_input.set()
    await callback_query.message.answer("أعد إدخال رقم حساب الدفع الخاص بك:")
    await callback_query.answer()

# -----------------------
# خدمة S3: بيع وشراء عملات رقمية
# -----------------------
@dp.callback_query_handler(lambda c: c.data == "service_S3")
async def service_s3(callback_query: types.CallbackQuery):
    text = text_config.get("service_S3_message", "● بيع وشراء جميع انواع العملات الرقمية.\n● يرجى التواصل مع الأدمن مباشرة @admin.")
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("العودة الى القائمة الرئيسية", callback_data="back_main"))
    await callback_query.message.answer(text, reply_markup=keyboard)
    await callback_query.answer()

# -----------------------
# معالجات استجابة المشرفين للطلبات
# -----------------------
@dp.callback_query_handler(lambda c: c.data.startswith("admin_receive_"))
async def admin_receive(callback_query: types.CallbackQuery):
    order_id = callback_query.data.split("_")[-1]
    if order_id in orders:
        orders[order_id]["status"] = "جاري التنفيذ"
        await callback_query.answer("تم تحديث حالة الطلب إلى: جاري التنفيذ")
        chat_id = orders[order_id]["chat_id"]
        await bot.send_message(chat_id, f"تم استلام طلبك برقم {order_id} وجاري العمل عليه.")
    else:
        await callback_query.answer("طلب غير موجود.")

@dp.callback_query_handler(lambda c: c.data.startswith("admin_success_"))
async def admin_success(callback_query: types.CallbackQuery):
    order_id = callback_query.data.split("_")[-1]
    if order_id in orders:
        orders[order_id]["status"] = "تم التنفيذ بنجاح"
        await callback_query.answer("تم تحديث حالة الطلب إلى: تم التنفيذ بنجاح")
        chat_id = orders[order_id]["chat_id"]
        await bot.send_message(chat_id, f"تم معالجة طلبك برقم {order_id} بنجاح.")
    else:
        await callback_query.answer("طلب غير موجود.")

@dp.callback_query_handler(lambda c: c.data.startswith("admin_cancel_"))
async def admin_cancel(callback_query: types.CallbackQuery):
    order_id = callback_query.data.split("_")[-1]
    if order_id in orders:
        orders[order_id]["status"] = "تم إلغاء الطلب"
        await callback_query.answer("تم تحديث حالة الطلب إلى: تم إلغاء الطلب")
        chat_id = orders[order_id]["chat_id"]
        await bot.send_message(chat_id, f"تم إلغاء طلبك برقم {order_id} بسبب عدم استيفاء الشروط.")
    else:
        await callback_query.answer("طلب غير موجود.")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)