# tools/weather.py
"""Hava durumu (OpenWeatherMap)."""
import os
import requests
from dotenv import load_dotenv
from tools import register_tool, get_config

load_dotenv()

API_URL = "https://api.openweathermap.org/data/2.5/weather"


def _get_api_key():
    return (
        os.environ.get("OPENWEATHER_API_KEY")
        or os.environ.get("OWM_API_KEY")
        or get_config().get("openweather", {}).get("api_key", "")
    )


@register_tool(
    name="get_weather",
    description=(
        "Belirtilen şehir için anlık hava durumunu getirir. Sıcaklık, "
        "hissedilen, nem, rüzgar ve genel durum bilgisi döner. Kullanıcı "
        "'hava nasıl', 'sıcaklık kaç derece', 'yağmur var mı' gibi sorular "
        "sorduğunda bu aracı kullan."
    ),
    parameters={
        "city": "string - şehir adı (örn. 'Istanbul', 'Ankara', 'New York')"
    },
)
def get_weather(city):
    api_key = _get_api_key()
    if not api_key:
        return "Hava durumu hatası: OPENWEATHER_API_KEY tanımlı değil (.env)"

    try:
        r = requests.get(
            API_URL,
            params={
                "q": city,
                "appid": api_key,
                "units": "metric",   # Celsius
                "lang": "tr",        # Türkçe açıklama
            },
            timeout=5,
        )

        if r.status_code == 401:
            return "Hava durumu hatası: API anahtarı geçersiz"
        if r.status_code == 404:
            return f"Hava durumu hatası: '{city}' bulunamadı"
        r.raise_for_status()

        d = r.json()
        name = d.get("name", city)
        main = d.get("main", {})
        weather = (d.get("weather") or [{}])[0]
        wind = d.get("wind", {})

        temp = main.get("temp")
        feels = main.get("feels_like")
        humidity = main.get("humidity")
        desc = weather.get("description", "").strip()
        wind_kmh = round(wind.get("speed", 0) * 3.6, 1)

        parts = [f"{name}: {desc}" if desc else name]
        if temp is not None:
            parts.append(f"sıcaklık {temp:.0f} derece")
        if feels is not None and temp is not None and abs(feels - temp) >= 2:
            parts.append(f"hissedilen {feels:.0f} derece")
        if humidity is not None:
            parts.append(f"nem yüzde {humidity}")
        if wind_kmh:
            parts.append(f"rüzgar saatte {wind_kmh:.0f} kilometre")

        return ", ".join(parts) + "."
    except requests.exceptions.Timeout:
        return "Hava durumu hatası: istek zaman aşımına uğradı"
    except Exception as e:
        return f"Hava durumu hatası: {e}"