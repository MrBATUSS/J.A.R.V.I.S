# tools/google_calendar.py
"""Google Calendar entegrasyonu (OAuth2)."""
import os
import re
import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from tools import register_tool, get_config

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_service = None


def _get_service():
    global _service
    if _service is not None:
        return _service

    cfg = get_config().get("google_calendar", {})
    creds_path = cfg.get("credentials_path", "credentials.json")
    token_path = cfg.get("token_path", "token.json")

    creds = None
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            print(f"[google_calendar] token okunamadı: {e}")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"[google_calendar] token yenilenemedi: {e}")
                creds = None
        if not creds or not creds.valid:
            if not os.path.exists(creds_path):
                raise RuntimeError(
                    f"Google Calendar credentials bulunamadı: {creds_path}."
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    _service = build("calendar", "v3", credentials=creds)
    return _service


def _tz():
    return get_config().get("google_calendar", {}).get("timezone", "Europe/Istanbul")


def _calendar_id():
    return get_config().get("google_calendar", {}).get("default_calendar_id", "primary")


def _rfc3339(dt_str):
    if not dt_str:
        return dt_str
    s = str(dt_str).strip()
    if s.endswith("Z"):
        return s
    if "T" in s:
        time_part = s.split("T", 1)[1]
        if "+" in time_part or "-" in time_part:
            return s
    return s + "+03:00"


def _sanitize_times(start_time, end_time):
    try:
        if not start_time:
            raise ValueError("start_time yok")
        s = datetime.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        now = datetime.datetime.now()
        s = (now + datetime.timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        e = s + datetime.timedelta(hours=1)
        return s.isoformat(), e.isoformat()

    try:
        e = datetime.datetime.fromisoformat(end_time.replace("Z", "+00:00")) if end_time else None
    except (ValueError, AttributeError):
        e = None

    now = datetime.datetime.now(s.tzinfo) if s.tzinfo else datetime.datetime.now()

    if s < now:
        s = (now + datetime.timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        e = s + datetime.timedelta(hours=1)

    if s.hour == 0 and s.minute == 0 and (e is None or (e.hour == 0 and e.minute == 0)):
        s = s.replace(hour=9)
        e = s + datetime.timedelta(hours=1)

    if e is None or e <= s:
        e = s + datetime.timedelta(hours=1)

    return s.isoformat(), e.isoformat()


# ============ Türkçe normalizasyon + tarih parser ============

_TR_MAP = str.maketrans("ışğüöçİIŞĞÜÖÇ", "isguociisguoc")


def _norm(s):
    return (s or "").translate(_TR_MAP).casefold().strip()


_AYLAR = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6,
    "temmuz": 7, "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
}


def _parse_date_range(query):
    """Query'de tarih ifadesi varsa (start_dt, end_dt) döndürür, yoksa (None, None)."""
    q = _norm(query)
    now = datetime.datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if "bugun" in q:
        return today, today + datetime.timedelta(days=1)
    if "yarin" in q:
        d = today + datetime.timedelta(days=1)
        return d, d + datetime.timedelta(days=1)
    if "obur gun" in q:
        d = today + datetime.timedelta(days=2)
        return d, d + datetime.timedelta(days=1)
    if "gelecek hafta" in q or "haftaya" in q:
        return today + datetime.timedelta(days=7), today + datetime.timedelta(days=14)
    if "bu hafta" in q:
        return today, today + datetime.timedelta(days=7)

    # "19 kasım" / "19 kasim" gibi ifadeler
    m = re.search(r"(\d{1,2})\s*['\.]?\s*([a-z]{3,})", q)
    if m:
        try:
            gun = int(m.group(1))
            ay_str = m.group(2)[:6]
            ay_no = None
            for isim, no in _AYLAR.items():
                if ay_str.startswith(isim[:4]):
                    ay_no = no
                    break
            if ay_no:
                yil = now.year
                d = datetime.datetime(yil, ay_no, gun)
                if d < today:
                    d = datetime.datetime(yil + 1, ay_no, gun)
                return d, d + datetime.timedelta(days=1)
        except (ValueError, IndexError):
            pass

    return None, None


_BULK_KEYWORDS = ("tum", "hepsi", "butun", "tumunu", "hepsini")


def _is_bulk(query):
    q = _norm(query)
    return any(k in q for k in _BULK_KEYWORDS)


def _find_matching_events(service, query, days_ahead=365):
    """Tarih ifadesi varsa o günü, yoksa tüm aralıkta metin eşleşmesi yapar."""
    start_dt, end_dt = _parse_date_range(query)

    if start_dt and end_dt:
        time_min = start_dt.isoformat() + "Z"
        time_max = end_dt.isoformat() + "Z"
    else:
        now = datetime.datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + datetime.timedelta(days=days_ahead)).isoformat() + "Z"

    result = service.events().list(
        calendarId=_calendar_id(),
        timeMin=time_min,
        timeMax=time_max,
        maxResults=50,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    events = result.get("items", [])

    # Tarih ifadesi bulunduysa o günkü tüm etkinlikler zaten döndü
    if start_dt and end_dt:
        # "yarınki sınav" gibi hem tarih hem metin varsa ekstra metin filtresi
        q = _norm(query)
        # Tarih kelimelerini çıkar, kalan anlamlı kelimeler var mı?
        for kw in ("bugun", "yarin", "obur", "gun", "gelecek", "hafta", "haftaya",
                   "bu", "tum", "hepsi", "butun", "etkinlik", "etkinlikleri",
                   "kaldir", "sil"):
            q = q.replace(kw, " ")
        q_words = [w for w in q.split() if len(w) >= 3]
        if not q_words:
            return events  # sadece tarih filtresi yeterli
        filtered = []
        for ev in events:
            summary = _norm(ev.get("summary", ""))
            if any(w in summary for w in q_words):
                filtered.append(ev)
        return filtered if filtered else events

    # Tarih yok, metin eşleşmesi
    q = _norm(query)
    q_words = [w for w in q.split() if len(w) >= 3]
    matches = []
    for ev in events:
        summary = _norm(ev.get("summary", ""))
        start = ev["start"].get("dateTime") or ev["start"].get("date", "")
        if q in summary or (summary and summary in q):
            matches.append(ev)
        elif q_words and any(w in summary for w in q_words):
            matches.append(ev)
        elif q in _norm(start):
            matches.append(ev)
    return matches


# ============ ARAÇLAR ============

@register_tool(
    name="list_calendar_events",
    description=(
        "Kullanıcının Google Takvim'indeki etkinlikleri listeler. "
        "'Takvimimde ne var', 'bugün toplantı var mı', 'bu hafta neler yapacağım' "
        "gibi sorularda kullan."
    ),
    parameters={
        "max_results": "integer - maksimum etkinlik sayısı (varsayılan 10)",
        "time_min": "string - başlangıç zamanı, RFC3339 (opsiyonel)",
        "time_max": "string - bitiş zamanı, RFC3339 (opsiyonel)",
    },
)
def list_calendar_events(max_results=10, time_min=None, time_max=None):
    try:
        service = _get_service()
        if time_min:
            time_min = _rfc3339(time_min)
        else:
            time_min = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).isoformat() + "Z"
        if time_max:
            time_max = _rfc3339(time_max)
        else:
            time_max = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).isoformat() + "Z"

        result = service.events().list(
            calendarId=_calendar_id(),
            timeMin=time_min,
            timeMax=time_max,
            maxResults=int(max_results),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])
        if not events:
            return "Takvimde bu aralıkta etkinlik yok."

        lines = []
        for ev in events:
            start = ev["start"].get("dateTime") or ev["start"].get("date")
            summary = ev.get("summary", "(başlıksız)")
            lines.append(f"- {start}: {summary} (id: {ev['id']})")
        return "\n".join(lines)
    except HttpError as e:
        return f"Takvim hatası: {e}"
    except Exception as e:
        return f"Takvim hatası: {type(e).__name__}: {e}"


@register_tool(
    name="create_calendar_event",
    description=(
        "Google Takvim'de yeni etkinlik oluşturur. 'Yarın toplantı ekle', "
        "'cuma sınav var' gibi isteklerde kullan. Saat belirtilmemişse "
        "varsayılan 09:00-10:00 kullan, kullanıcıya SORMA. Tarihleri RFC3339 "
        "olarak ver."
    ),
    parameters={
        "summary": "string - etkinlik başlığı (zorunlu)",
        "start_time": "string - başlangıç RFC3339 (opsiyonel, varsayılan yarın 09:00)",
        "end_time": "string - bitiş RFC3339 (opsiyonel, varsayılan start+1 saat)",
        "description": "string - açıklama (opsiyonel)",
        "location": "string - konum (opsiyonel)",
    },
)
def create_calendar_event(summary, start_time=None, end_time=None,
                          description=None, location=None):
    try:
        service = _get_service()
        s, e = _sanitize_times(_rfc3339(start_time) if start_time else None,
                              _rfc3339(end_time) if end_time else None)
        event = {
            "summary": summary,
            "start": {"dateTime": s, "timeZone": _tz()},
            "end": {"dateTime": e, "timeZone": _tz()},
        }
        if description:
            event["description"] = description
        if location:
            event["location"] = location

        created = service.events().insert(
            calendarId=_calendar_id(), body=event
        ).execute()

        start = created["start"].get("dateTime") or created["start"].get("date")
        return f"Etkinlik oluşturuldu: '{created.get('summary')}' — {start} (id: {created['id']})"
    except HttpError as e:
        return f"Takvim hatası: {e}"
    except Exception as e:
        return f"Takvim hatası: {type(e).__name__}: {e}"


@register_tool(
    name="update_calendar_event",
    description=(
        "Google Takvim'de MEVCUT bir etkinliği günceller. event_id bilinmiyorsa "
        "'query' ile doğal dil tanımı ver (örn. 'sınav', 'yarınki sınav')."
    ),
    parameters={
        "query": "string - güncellenecek etkinliğin tanımı (event_id yoksa zorunlu)",
        "event_id": "string - opsiyonel, doğrudan id ile güncelle",
        "summary": "string - yeni başlık (opsiyonel)",
        "start_time": "string - yeni başlangıç RFC3339 (opsiyonel)",
        "end_time": "string - yeni bitiş RFC3339 (opsiyonel)",
        "description": "string - yeni açıklama (opsiyonel)",
        "location": "string - yeni konum (opsiyonel)",
    },
)
def update_calendar_event(query=None, event_id=None, summary=None,
                          start_time=None, end_time=None,
                          description=None, location=None):
    try:
        service = _get_service()

        if not event_id:
            if not query:
                return "Güncellenecek etkinliği tanımlamadınız."
            matches = _find_matching_events(service, query)
            if not matches:
                return f"'{query}' ile eşleşen etkinlik bulunamadı."
            if len(matches) > 1:
                lines = ["Birden fazla eşleşme var:"]
                for ev in matches:
                    s = ev["start"].get("dateTime") or ev["start"].get("date")
                    lines.append(f"- {s}: {ev.get('summary')} (id: {ev['id']})")
                lines.append("Hangisini güncelleyeyim? Tarihiyle söyleyin.")
                return "\n".join(lines)
            event_id = matches[0]["id"]

        event = service.events().get(
            calendarId=_calendar_id(), eventId=event_id
        ).execute()

        if summary:
            event["summary"] = summary

        if start_time or end_time:
            cur_s = event["start"].get("dateTime") or event["start"].get("date")
            cur_e = event["end"].get("dateTime") or event["end"].get("date")
            s, e = _sanitize_times(
                _rfc3339(start_time) if start_time else cur_s,
                _rfc3339(end_time) if end_time else cur_e,
            )
            event["start"] = {"dateTime": s, "timeZone": _tz()}
            event["end"] = {"dateTime": e, "timeZone": _tz()}

        if description is not None:
            event["description"] = description
        if location is not None:
            event["location"] = location

        updated = service.events().update(
            calendarId=_calendar_id(), eventId=event_id, body=event
        ).execute()
        return f"Etkinlik güncellendi: '{updated.get('summary')}' (id: {updated['id']})"
    except HttpError as e:
        return f"Takvim hatası: {e}"
    except Exception as e:
        return f"Takvim hatası: {type(e).__name__}: {e}"


@register_tool(
    name="delete_calendar_event",
    description=(
        "Google Takvim'den etkinlik siler. 'yarınki etkinlikleri kaldır', "
        "'19 Kasım'daki tüm etkinlikleri sil', 'sınavı iptal et' gibi "
        "isteklerde kullan. Tarih ifadeleri (yarın, bugün, 19 Kasım) "
        "desteklenir. 'Tüm/hepsi' geçiyorsa eşleşen tüm etkinlikler silinir. "
        "event_id bilinmiyorsa 'query' ver."
    ),
    parameters={
        "query": "string - silinecek etkinliğin tanımı (tarih ve/veya başlık, örn. 'yarınki etkinlikler', '19 Kasım sınavı')",
        "event_id": "string - opsiyonel, doğrudan id ile sil",
    },
)
def delete_calendar_event(query=None, event_id=None):
    try:
        service = _get_service()

        if event_id:
            service.events().delete(
                calendarId=_calendar_id(), eventId=event_id
            ).execute()
            return f"Etkinlik silindi (id: {event_id})"

        if not query:
            return "Silinecek etkinliği tanımlamadınız."

        matches = _find_matching_events(service, query)
        if not matches:
            return f"'{query}' ile eşleşen etkinlik bulunamadı."

        # Toplu silme: "tüm/hepsi/bütün" varsa veya birden fazla eşleşme + tarih ifadesi
        bulk = _is_bulk(query)
        if bulk or (len(matches) > 1 and _parse_date_range(query)[0]):
            deleted = []
            errors = []
            for ev in matches:
                try:
                    service.events().delete(
                        calendarId=_calendar_id(), eventId=ev["id"]
                    ).execute()
                    s = ev["start"].get("dateTime") or ev["start"].get("date")
                    deleted.append(f"- {s}: {ev.get('summary')}")
                except Exception as e:
                    errors.append(f"- {ev.get('summary')}: {e}")
            msg = f"{len(deleted)} etkinlik silindi:"
            if deleted:
                msg += "\n" + "\n".join(deleted)
            if errors:
                msg += f"\n{len(errors)} hata:\n" + "\n".join(errors)
            return msg

        if len(matches) > 1:
            lines = ["Birden fazla eşleşme var:"]
            for ev in matches:
                s = ev["start"].get("dateTime") or ev["start"].get("date")
                lines.append(f"- {s}: {ev.get('summary')} (id: {ev['id']})")
            lines.append("Hangisini sileyim? Tarihiyle söyleyin, ya da 'tümünü sil' deyin.")
            return "\n".join(lines)

        ev = matches[0]
        service.events().delete(
            calendarId=_calendar_id(), eventId=ev["id"]
        ).execute()
        start = ev["start"].get("dateTime") or ev["start"].get("date")
        return f"Etkinlik silindi: '{ev.get('summary')}' — {start}"
    except HttpError as e:
        return f"Takvim hatası: {e}"
    except Exception as e:
        return f"Takvim hatası: {type(e).__name__}: {e}"