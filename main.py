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
        [InlineKeyboardButton("📈 Анализ SOL/USDT", callback_data="sol")],
        [InlineKeyboardButton("📈 Анализ EUR/USD (Forex)", callback_data="eur")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text(
        "👋 <b>Трейдинг-терминал активирован.</b>\n\n"
        "Я анализирую рынок по тренду (EMA) и волатильности (ATR).\n"
        "Для каждой сделки я рассчитываю: Точку входа, Стоп-Лосс и Тейк-Профит.\n\n"
        "Выбери актив:", 
        reply_markup=get_menu(), 
        parse_mode="HTML"
    )

async def analyze_market(symbol: str, interval: str = "15m"):
    if symbol == "EURUSD":
        return "📊 <b>Анализ EUR/USD</b>\n\nДля Форекса бесплатные API не дают историю для расчетов. Используй крипту для теста."

    # Запрос к Bybit (100 свечей по 15 минут)
    url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}&interval=15&limit=100"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return f"❌ Ошибка API: {resp.status}"
                data = await resp.json()
                if data.get("retCode") != 0:
                    return f"❌ Ошибка Bybit: {data.get('retMsg')}"
                
                klines = data["result"]["list"]
                klines.reverse()
    except Exception as e:
        return f"❌ Ошибка сети: {str(e)}"

    closes = [float(candle[4]) for candle in klines]
    highs = [float(candle[2]) for candle in klines]
    lows = [float(candle[3]) for candle in klines]
    
    # 1. EMA (9 и 21)
    def calc_ema(prices, period):
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price - ema) * multiplier + ema
        return ema
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    
    # 2. RSI (14)
    def calc_rsi(prices, period=14):
        gains, losses = [], []
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i-1]
            if diff >= 0:
                gains.append(diff); losses.append(0)
            else:
                gains.append(0); losses.append(abs(diff))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0: return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    rsi = calc_rsi(closes)

    # 3. ATR (14) - для расчета стопов
    def calc_atr(highs, lows, closes, period=14):
        trs = []
        for i in range(1, len(closes)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            trs.append(tr)
        return sum(trs[-period:]) / period
    atr = calc_atr(highs, lows, closes)

    current_price = closes[-1]
    signal = "НЕТ СИГНАЛА"
    entry, stop_loss, take_profit = 0, 0, 0
    risk_reward = "1:2"
    confidence = 0

    # Логика: если тренд вверх и RSI не перекуплен
    if ema9 > ema21 and rsi < 65:
        signal = "🟢 ПОКУПКА (LONG)"
        entry = current_price
        stop_loss = entry - (atr * 1.5) # Стоп на 1.5 ATR ниже
        take_profit = entry + (atr * 3.0) # Тейк на 3 ATR выше
        confidence = round(70 + (50 - rsi) / 2, 1)
    # Логика: если тренд вниз и RSI не перепродан
    elif ema9 < ema21 and rsi > 35:
        signal = "🔴 ПРОДАЖА (SHORT)"
        entry = current_price
        stop_loss = entry + (atr * 1.5) # Стоп на 1.5 ATR выше
        take_profit = entry - (atr * 3.0) # Тейк на 3 ATR ниже
        confidence = round(70 + (rsi - 50) / 2, 1)
    else:
        return f"📊 <b>Анализ {symbol}</b>\n\nЦена: <code>{current_price:.2f}</code>\nRSI: <code>{rsi:.1f}</code>\n\n⚖️ <b>Сигнала нет.</b>\nРынок в неопределенности (флэт). Ждем тренд."

    # Форматируем текст
    text = (
        f"📊 <b>Терминал: {symbol} (15m)</b>\n\n"
        f"💰 Цена входа: <code>{entry:.4f}</code>\n"
        f"📉 RSI: <code>{rsi:.1f}</code>\n\n"
        f"<b>СИГНАЛ: {signal}</b>\n"
        f"Уверенность: {confidence}%\n\n"
        f"🛑 <b>Стоп-лосс:</b> <code>{stop_loss:.4f}</code>\n"
        f"🎯 <b>Тейк-профит:</b> <code>{take_profit:.4f}</code>\n"
        f"⚖️ <b>Риск/Прибыль:</b> {risk_reward}\n\n"
        f"<i>⚠️ Не является финансовой рекомендацией. Риск-менеджмент обязателен!</i>"
    )
    return text

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != OWNER_ID:
        return

    if context.user_data.get('is_analyzing'):
        await query.answer("⏳ Подожди, идет расчет...", show_alert=True)
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
        elif query.data == "sol":
            await query.edit_message_text("⏳ Анализирую SOL/USDT...")
            res = await analyze_market("SOLUSDT")
            await query.edit_message_text(res, parse_mode="HTML", reply_markup=get_menu())
        elif query.data == "eur":
            res = await analyze_market("EURUSD")
            await query.edit_message_text(res, parse_mode="HTML", reply_markup=get_menu())
    finally:
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
    
    logging.info("🚀 Трейдинг-терминал запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
