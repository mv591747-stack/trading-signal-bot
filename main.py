import os
import logging
import asyncio
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from keep_alive import keep_alive
from dotenv import load_dotenv

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

def get_menu():
    keyboard = [
        [InlineKeyboardButton("📈 Анализ BTC/USDT", callback_data="btc")],
        [InlineKeyboardButton("📈 Анализ ETH/USDT", callback_data="eth")],
        [InlineKeyboardButton("📈 Анализ EUR/USD (Forex)", callback_data="eur")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text("👋 Привет! Я бот для анализа рынка.\nВыбери актив для анализа:", reply_markup=get_menu())

async def analyze_market(symbol: str, interval: str = "15m"):
    # === ФОРЕКС (EUR/USD) ===
    if symbol == "EURUSD":
        url = "https://api.frankfurter.app/latest?from=EUR&to=USD"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    data = await resp.json()
                    price = data['rates']['USD']
                    return f"📊 <b>Анализ EUR/USD</b>\n\nЦена: <code>{price:.4f}</code>\n\n<b>Сигнал: НАБЛЮДЕНИЕ</b>\nДля Форекса нужен брокер, API бесплатно дает только текущую цену."
        except Exception as e:
            return f"❌ Ошибка Форекс API: {e}"

    # === КРИПТА (Bybit) ===
    # Bybit принимает интервалы: 15, 60, 240, D
    bybit_interval = "15"
    url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}&interval={bybit_interval}&limit=100"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return f"❌ Ошибка Bybit API: {resp.status}"
                data = await resp.json()
                if data.get("retCode") != 0:
                    return f"❌ Ошибка данных Bybit: {data.get('retMsg')}"
                
                # Bybit отдает свечи в обратном порядке (сначала новые), переворачиваем
                klines = data["result"]["list"]
                klines.reverse()
    except Exception as e:
        return f"❌ Ошибка сети: {str(e)}"

    # Закрывающие цены (в Bybit это 5-й элемент)
    closes = [float(candle[4]) for candle in klines]
    
    # EMA
    def calc_ema(prices, period):
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    
    # RSI
    def calc_rsi(prices, period=14):
        gains, losses = [], []
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i-1]
            if diff >= 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(diff))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0: return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    rsi = calc_rsi(closes)
    current_price = closes[-1]
    
    signal = "НЕТ СИГНАЛА"
    confidence = 0
    
    if ema9 > ema21 and rsi < 70:
        signal = "📈 ПОКУПКА (LONG)"
        confidence = round(70 + (50 - rsi) if rsi < 50 else 65, 1)
    elif ema9 < ema21 and rsi > 30:
        signal = "📉 ПРОДАЖА (SHORT)"
        confidence = round(70 + (rsi - 50) if rsi > 50 else 65, 1)

    text = (
        f"📊 <b>Анализ {symbol} (15m)</b>\n\n"
        f"Цена: <code>{current_price:.2f}</code>\n"
        f"Тренд: {'Восходящий 🟢' if ema9 > ema21 else 'Нисходящий 🔴'}\n"
        f"RSI (14): <code>{rsi:.1f}</code>\n\n"
        f"<b>Сигнал: {signal}</b>\n"
        f"Уверенность: {confidence}%\n\n"
        f"<i>Анализ по алгоритму EMA+RSI. Не является финансовой рекомендацией.</i>"
    )
    return text

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != OWNER_ID:
        return

    # Защита от быстрых повторных нажатий
    if context.user_data.get('is_analyzing'):
        await query.answer("⏳ Подожди, анализ уже идет...", show_alert=True)
        return
    context.user_data['is_analyzing'] = True

    try:
        if query.data == "btc":
            await query.edit_message_text("⏳ Анализирую BTC/USDT...")
            res = await analyze_market("BTCUSDT")
            await query.edit_message_text(res, parse_mode="HTML", reply_markup=get_menu())
        elif query.data == "eth":
            await query.edit_message_text("⏳ Анализирую ETH/USDT...")
            res = await analyze_market("ETHUSDT")
            await query.edit_message_text(res, parse_mode="HTML", reply_markup=get_menu())
        elif query.data == "eur":
            res = await analyze_market("EURUSD")
            await query.edit_message_text(res, parse_mode="HTML", reply_markup=get_menu())
    finally:
        # Снимаем блокировку через 5 секунд
        await asyncio.sleep(5)
        context.user_data['is_analyzing'] = False

def main():
    if not BOT_TOKEN or not OWNER_ID:
        print("Ошибка: нет токена или ID")
        return

    keep_alive()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    logging.info("🚀 Трейдинг-бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
