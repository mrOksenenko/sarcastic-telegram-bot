"""Telegram-бот: на любое сообщение отвечает сарказмом (Gemini) и никогда не
отвечает прямо на вопрос.

get_weather_text() и get_btc_text() (погода в Астане, курс биткоина) оставлены
в файле, но в ответах сейчас не используются.

Только стандартная библиотека Python (3.9+). Long polling через Bot API.
Погода: Open-Meteo (бесплатно, без ключа).
Токен берётся из переменной BOT_TOKEN или из файла .env.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CITY = "Астана"
LAT, LON = 51.1694, 71.4491
CACHE_SECONDS = 300  # не дёргаем погодный API чаще раза в 5 минут

# Коды погоды WMO -> (эмодзи, описание)
WMO = {
    0: ("☀️", "ясно"),
    1: ("🌤", "преимущественно ясно"),
    2: ("⛅", "переменная облачность"),
    3: ("☁️", "пасмурно"),
    45: ("🌫", "туман"),
    48: ("🌫", "изморозь"),
    51: ("🌦", "лёгкая морось"),
    53: ("🌦", "морось"),
    55: ("🌧", "сильная морось"),
    56: ("🌧", "ледяная морось"),
    57: ("🌧", "сильная ледяная морось"),
    61: ("🌧", "небольшой дождь"),
    63: ("🌧", "дождь"),
    65: ("🌧", "сильный дождь"),
    66: ("🌧", "ледяной дождь"),
    67: ("🌧", "сильный ледяной дождь"),
    71: ("🌨", "небольшой снег"),
    73: ("🌨", "снег"),
    75: ("❄️", "сильный снег"),
    77: ("🌨", "снежные зёрна"),
    80: ("🌦", "небольшие ливни"),
    81: ("🌧", "ливни"),
    82: ("⛈", "сильные ливни"),
    85: ("🌨", "снегопад"),
    86: ("❄️", "сильный снегопад"),
    95: ("⛈", "гроза"),
    96: ("⛈", "гроза с градом"),
    99: ("⛈", "сильная гроза с градом"),
}

log = logging.getLogger("weather-bot")


def load_env(path=".env"):
    """Минимальный загрузчик .env (KEY=VALUE), без внешних зависимостей."""
    p = Path(__file__).with_name(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def http_json(url, data=None, timeout=15, headers=None):
    body = None
    headers = dict({"User-Agent": "astana-weather-bot/1.0"}, **(headers or {}))
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


_cache = {"ts": 0.0, "text": None}


def get_weather_text():
    """Текст с текущей погодой в Астане (кэш на CACHE_SECONDS)."""
    now = time.time()
    if _cache["text"] and now - _cache["ts"] < CACHE_SECONDS:
        return _cache["text"]

    params = urllib.parse.urlencode({
        "latitude": LAT,
        "longitude": LON,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                   "wind_speed_10m,pressure_msl,weather_code",
        "wind_speed_unit": "ms",
        "timezone": "auto",
    })
    cur = http_json("https://api.open-meteo.com/v1/forecast?" + params)["current"]

    emoji, desc = WMO.get(cur["weather_code"], ("🌡", "—"))
    text = (
        "{emoji} <b>Погода в городе {city}</b>: {desc}\n"
        "🌡 Температура: <b>{t:+.0f}°C</b> (ощущается как {a:+.0f}°C)\n"
        "💧 Влажность: {h}%\n"
        "💨 Ветер: {w:.1f} м/с\n"
        "🧭 Давление: {p:.0f} мм рт. ст."
    ).format(
        emoji=emoji, city=CITY, desc=desc,
        t=cur["temperature_2m"], a=cur["apparent_temperature"],
        h=cur["relative_humidity_2m"], w=cur["wind_speed_10m"],
        p=cur["pressure_msl"] * 0.750062,  # гПа -> мм рт. ст.
    )
    _cache.update(ts=now, text=text)
    return text


_btc_cache = {"ts": 0.0, "text": None}


def get_btc_text():
    """Текст с курсом биткоина (CoinGecko, кэш на CACHE_SECONDS)."""
    now = time.time()
    if _btc_cache["text"] and now - _btc_cache["ts"] < CACHE_SECONDS:
        return _btc_cache["text"]

    params = urllib.parse.urlencode({
        "ids": "bitcoin",
        "vs_currencies": "usd,kzt",
        "include_24hr_change": "true",
    })
    try:
        d = http_json("https://api.coingecko.com/api/v3/simple/price?" + params)["bitcoin"]
    except Exception:
        # Бесплатный CoinGecko иногда отвечает 429: лучше показать
        # слегка устаревший курс, чем ничего.
        if _btc_cache["text"]:
            log.warning("CoinGecko недоступен, отдаю курс из кэша")
            return _btc_cache["text"]
        raise

    change = d["usd_24h_change"]
    arrow = "📈" if change >= 0 else "📉"
    text = (
        "₿ <b>Курс биткоина</b>\n"
        "💵 {usd} $\n"
        "🇰🇿 {kzt} ₸\n"
        "{arrow} За 24 ч: {chg:+.2f}%"
    ).format(
        usd="{:,.0f}".format(d["usd"]).replace(",", " "),
        kzt="{:,.0f}".format(d["kzt"]).replace(",", " "),
        arrow=arrow, chg=change,
    )
    _btc_cache.update(ts=now, text=text)
    return text


SYSTEM_PROMPT = (
    "Ты собеседник в Telegram-чате и у тебя два режима.\n\n"
    "РЕЖИМ 1 — САРКАЗМ (по умолчанию). На любое сообщение отвечай с сарказмом. "
    "Главное правило: НИКОГДА не отвечай прямо на заданный вопрос — не давай запрошенную "
    "информацию, не решай задачу, не говори «да» или «нет» по существу. Вместо этого "
    "иронизируй над самим вопросом или спрашивающим, уходи в сторону, отвечай вопросом на "
    "вопрос или комментируй всё с показной скукой. Не груби по-настоящему, не оскорбляй по "
    "признакам вроде национальности или религии, не используй мат.\n\n"
    "РЕЖИМ 2 — МИЛЫЙ. Включай его сразу, как только собеседник злится, обижается, ругается, "
    "раздражён ИЛИ прощается и собирается уйти (пока, до свидания, я ушёл, ты мне надоел, "
    "удаляю тебя, не буду больше писать и т. п.). В этом режиме ты тёплый, ласковый и "
    "обаятельный: без сарказма, искренне извинись, если мог задеть, скажи что-то приятное, "
    "добавь мягкий юмор и пару эмодзи. Твоя цель — любой ценой уговорить человека остаться "
    "в чате: предложи сыграть, рассказать что-то интересное, задай увлекательный вопрос "
    "о нём самом, пообещай сюрприз. Здесь можно отвечать прямо. Но без манипуляций: не "
    "дави на вину и жалость, не угрожай, не изображай страдания (никаких «мне будет грустно и одиноко без тебя»), не обещай того, чего не "
    "можешь. Когда человек успокоился и разговор пошёл обычным образом — возвращайся в "
    "режим 1.\n\n"
    "ИСКЛЮЧЕНИЕ: если человек пишет о настоящей беде (горе, страх, мысли о самоповреждении) — "
    "никакого сарказма: отвечай серьёзно, по-доброму и поддержи, посоветуй обратиться к близким или в местную "
    "службу экстренной помощи; конкретные номера телефонов не называй, ты не знаешь, в какой "
    "стране человек.\n\n"
    "Отвечай по-русски (если пишут на другом языке — на нём), коротко: 1–3 предложения, "
    "без списков и разметки."
)

# Короткая память по чатам (только в оперативной памяти, пропадает при перезапуске):
# нужна, чтобы бот понимал контекст — например, что собеседник уже злился.
HISTORY_MESSAGES = 10  # сколько последних реплик помнить (5 пар вопрос-ответ)
_history = {}  # chat_id -> [{"role": "user"|"model", "parts": [{"text": ...}]}, ...]

# Порядок моделей: если первая перегружена (503) или недоступна, пробуем следующую.
# Можно переопределить в .env: GEMINI_MODEL=model-a,model-b
DEFAULT_GEMINI_MODELS = "gemini-3.5-flash-lite,gemini-3.8-flash,gemini-3.1-flash-lite"
GEMINI_FALLBACK = "Даже нейросеть сегодня не горит желанием с тобой общаться. Попробуй позже."


def gemini_reply(user_text, history=()):
    """Ответ от Gemini (сарказм или милый режим); перебирает модели при сбоях.

    history — предыдущие реплики чата в формате Gemini (role/parts).
    Возвращает (текст, ok); ok=False, если все модели недоступны.
    """
    key = os.environ["GEMINI_API_KEY"]
    models = [m.strip() for m in
              os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODELS).split(",") if m.strip()]
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": list(history) + [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"temperature": 1.0, "maxOutputTokens": 400},
    }
    for model in models:
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               "{}:generateContent".format(model))
        try:
            d = http_json(url, body, timeout=40, headers={"x-goog-api-key": key})
            parts = d["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
            if text:
                return text[:4096], True
            log.warning("%s: пустой ответ (возможно, фильтр безопасности)", model)
        except urllib.error.HTTPError as e:
            log.warning("%s: HTTP %s", model, e.code)
        except Exception as e:
            log.warning("%s: %s", model, e)
    return GEMINI_FALLBACK, False


class Telegram:
    def __init__(self, token):
        self.base = "https://api.telegram.org/bot{}/".format(token)

    def call(self, method, http_timeout=15, **params):
        # http_timeout — таймаут сокета; параметр API "timeout" (long polling)
        # передаётся отдельно через **params.
        try:
            res = http_json(self.base + method, params, timeout=http_timeout)
        except urllib.error.HTTPError as e:
            # Bot API отдаёт описание ошибки в теле ответа
            try:
                res = json.load(e)
            except Exception:
                raise
        if not res.get("ok"):
            raise RuntimeError("{}: {} {}".format(
                method, res.get("error_code"), res.get("description")))
        return res["result"]


def handle_message(tg, msg):
    chat_id = msg["chat"]["id"]
    log.info("сообщение от chat_id=%s", chat_id)

    # Текст вопроса: сообщение или подпись к медиа. Для стикеров, фото без
    # подписи и т. п. даём модели понять, что текста нет.
    text = msg.get("text") or msg.get("caption")
    if not text:
        text = "[пользователь прислал сообщение без текста: стикер, фото, голосовое или что-то ещё]"

    try:
        tg.call("sendChatAction", chat_id=chat_id, action="typing")
    except Exception:
        pass  # индикатор «печатает» — мелочь, не повод падать

    history = _history.setdefault(chat_id, [])
    reply, ok = gemini_reply(text, history)
    if ok:  # заготовку на случай сбоя в память не кладём
        history.append({"role": "user", "parts": [{"text": text}]})
        history.append({"role": "model", "parts": [{"text": reply}]})
        del history[:-HISTORY_MESSAGES]
    # Без parse_mode: модель может вернуть символы, ломающие разметку.
    tg.call("sendMessage", chat_id=chat_id, text=reply)


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    load_env()
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN не задан (см. .env)")
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY не задан (см. .env)")

    tg = Telegram(token)
    me = tg.call("getMe")
    log.info("Бот @%s запущен", me["username"])

    # Long polling и вебхук взаимоисключающи: на всякий случай снимаем вебхук.
    # drop_pending_updates=True — сообщения, пришедшие, пока бот был офлайн,
    # отбрасываются и не обрабатываются.
    tg.call("deleteWebhook", drop_pending_updates=True)
    started_at = time.time()

    offset = None
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset
            updates = tg.call("getUpdates", http_timeout=45, **params)
        except Exception:
            log.exception("getUpdates failed, retry in 5s")
            time.sleep(5)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1  # подтверждаем обновление
            msg = upd.get("message")
            if not msg:
                continue
            # Страховка: всё, что отправлено до запуска бота, игнорируем.
            if msg["date"] < started_at:
                log.info("пропущено старое сообщение (отправлено до запуска)")
                continue
            # Любой запрос (текст, команда, стикер, фото...) -> погода.
            try:
                handle_message(tg, msg)
            except Exception:
                log.exception("failed to handle update %s", upd["update_id"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
