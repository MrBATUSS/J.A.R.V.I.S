import os
import io
import json
import queue
import sys
import threading
import time
import collections
import wave
import numpy as np
import sounddevice as sd
import ollama
import soundfile as sf
import soxr
from piper import PiperVoice
import requests
from tavily import TavilyClient
from dotenv import load_dotenv
import subprocess
from tools import discover_tools, TOOLS
import re
from datetime import datetime, timedelta

# ============ Config ============
CONFIG_PATH = "config.json"

DEFAULT_CONFIG = {
    "models": {
        "llm": "gemma4:e4b",
        "piper_onnx": "D:/AI_Models/piper_cache/tr_TR-fahrettin-medium.onnx",
    },
    "audio": {
        "sample_rate": 16000,
        "block_duration": 0.5,
    },
    "vad": {
        "speech_threshold": 0.015,
        "barge_in_blocks": 3,
        "silence_blocks": 3,
        "recent_blocks_maxlen": 5,
    },
    "tts": {
        "wait_timeout_seconds": 0.3,
    },
    "ollama": {
        "base_url": "http://localhost:11434",
        "keep_alive": -1,
    },
    "system_prompt": "Sen JARVIS'sin. Kısa, doğal, akıcı konuş.",
    "tools": {
        "tavily": {
            "api_key": ""
        },
        "openweather": {
            "api_key": ""
        }
    },
}
load_dotenv()

def _deep_merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v


def load_config(path=CONFIG_PATH):
    """config.json'u yükle; yoksa varsayılanlarla oluştur; eksik anahtarları tamamla."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user = json.load(f)
            _deep_merge(cfg, user)
            print(f"[config] {path} yüklendi.")
        except Exception as e:
            print(f"[config] {path} okunamadı ({e}); varsayılanlar kullanılıyor.")
    else:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
            print(f"[config] {path} oluşturuldu (varsayılanlarla).")
        except Exception as e:
            print(f"[config] {path} yazılamadı ({e}); varsayılanlar kullanılıyor.")
    return cfg


CONFIG = load_config()

SAMPLE_RATE = int(CONFIG["audio"]["sample_rate"])
BLOCK_DURATION = float(CONFIG["audio"]["block_duration"])
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_DURATION)

LLM_MODEL = CONFIG["models"]["llm"]
PIPER_MODEL_NAME = CONFIG["models"]["piper_onnx"]

SPEECH_THRESHOLD = float(CONFIG["vad"]["speech_threshold"])
BARGE_IN_BLOCKS = int(CONFIG["vad"]["barge_in_blocks"])
SILENCE_BLOCKS = int(CONFIG["vad"]["silence_blocks"])
RECENT_BLOCKS_MAXLEN = int(CONFIG["vad"]["recent_blocks_maxlen"])

TTS_WAIT_TIMEOUT = float(CONFIG["tts"]["wait_timeout_seconds"])

OLLAMA_BASE_URL = CONFIG["ollama"]["base_url"]
OLLAMA_KEEP_ALIVE = CONFIG["ollama"]["keep_alive"]

JARVIS_SYSTEM_PROMPT = CONFIG["system_prompt"]
DEBUG_MOD = False

# ============ State ============
audio_queue = queue.Queue()
tts_queue = queue.Queue()
piper_voice = None

tts_active = threading.Event()
interrupt_requested = threading.Event()
processing_event = threading.Event()
DEBUG_MIC_COUNTER = [0]

# -------- TARİH ve SAAT -----------
def _current_time_context():
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Europe/Istanbul"))
    except Exception:
        now = datetime.now()
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    yarin = now + timedelta(days=1)
    return (
        f"ŞU AN: {now.strftime('%Y-%m-%d')} {gunler[now.weekday()]} "
        f"saat {now.strftime('%H:%M')}. Yarın: {yarin.strftime('%Y-%m-%d')}. "
        f"Göreceli ifadeleri bu tarihe göre hesapla, geçmiş tarih yazma."
    )

# ============ Otomatik ses çıkışı ============
def pick_output_device():
    try:
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_output_channels"] > 0:
                name = dev["name"].lower()
                if any(k in name for k in ("headphone", "kulaklık", "headset")):
                    return idx
        default_out = sd.default.device[1]
        if default_out is not None and default_out >= 0:
            return default_out
    except Exception as e:
        print(f"Cihaz seçim hatası: {e}")
    return None


def pick_target_samplerate(device_idx, fallback=44100):
    if device_idx is None:
        try:
            device_idx = sd.default.device[1]
        except Exception:
            return fallback
    try:
        sr = int(round(sd.query_devices(device_idx)["default_samplerate"]))
        return sr if sr > 0 else fallback
    except Exception:
        return fallback


OUTPUT_DEVICE = pick_output_device()
TARGET_SR = pick_target_samplerate(OUTPUT_DEVICE)


def _describe_output():
    if OUTPUT_DEVICE is None:
        return f"sistem default ({TARGET_SR} Hz)"
    try:
        name = sd.query_devices(OUTPUT_DEVICE)["name"]
        return f"[{OUTPUT_DEVICE}] {name} ({TARGET_SR} Hz)"
    except Exception:
        return f"cihaz {OUTPUT_DEVICE} ({TARGET_SR} Hz)"


if DEBUG_MOD == True:
    print(f"Ses çıkışı: {_describe_output()}")


# ============ TTS ============


def resample_audio(data, orig_sr, target_sr):
    """float32 numpy dizisini soxr ile hızlıca resample eder."""
    return soxr.resample(data.astype(np.float32), orig_sr, target_sr)


def synthesize_speech_piper(text):
    if not text.strip() or not piper_voice or interrupt_requested.is_set():
        return

    try:
        # Jeneratörden gelen parçaları doğrudan çal
        for chunk in piper_voice.synthesize(text):
            if interrupt_requested.is_set():
                break
            # chunk.audio_float_array: float32 numpy dizisi
            # chunk.sample_rate: modelin doğal örnekleme hızı (örn. 22050)
            data = chunk.audio_float_array
            if len(data) == 0:
                continue

            # Resample (aşağıda soxr ile hızlandıracağız)
            if chunk.sample_rate != TARGET_SR:
                data = resample_audio(data, chunk.sample_rate, TARGET_SR)

            sd.play(data, TARGET_SR, device=OUTPUT_DEVICE)

            # Çalma bitene veya interrupt gelene kadar bekle
            while sd.get_stream() is not None and sd.get_stream().active:
                if interrupt_requested.is_set():
                    sd.stop()
                    return
                time.sleep(0.02)

    except Exception as e:
        print(f"Piper TTS hatası: {e}")


def tts_worker():
    while True:
        text = tts_queue.get()
        if text is None:
            break
        tts_active.set()
        try:
            if not interrupt_requested.is_set():
                synthesize_speech_piper(text)
        except Exception as e:
            print(f"TTS worker hatası: {e}")
        finally:
            tts_active.clear()


def trigger_interrupt():
    print("\n[Barge-in] Kesinti algılandı, dinlemeye geçiliyor...")
    interrupt_requested.set()
    try:
        sd.stop()
    except Exception:
        pass
    for _ in range(3):
        while True:
            try:
                tts_queue.get_nowait()
            except queue.Empty:
                break
        time.sleep(0.02)


# ============ Cümle bölme ============
_ABBREV = ("dr.", "prof.", "doç.", "av.", "vb.", "örn.", "bkz.", "vs.", "sn.")


def _find_sentence_end(text):
    for i in range(len(text) - 1, -1, -1):
        ch = text[i]
        if ch == "\n":
            return i + 1
        if ch in ".!?":
            if ch == "." and 0 < i < len(text) - 1:
                if text[i - 1].isdigit() and text[i + 1].isdigit():
                    continue
            start = max(0, i - 6)
            word = text[start : i + 1].lower()
            if any(word.endswith(a) for a in _ABBREV):
                continue
            if ch == "." and i > 0 and text[i - 1].isupper():
                if i == 1 or not text[i - 2].isalnum():
                    continue
            if i + 1 < len(text) and not text[i + 1].isspace():
                continue
            return i + 1
    return -1


def extract_ready_sentences(buffer, max_chunk=180):
    sentences = []
    while True:
        idx = _find_sentence_end(buffer)
        if idx == -1:
            break
        s = buffer[:idx].strip()
        if s:
            sentences.append(s)
        buffer = buffer[idx:].lstrip()
    if len(buffer) > max_chunk:
        last_comma = buffer.rfind(",", 0, max_chunk)
        if last_comma > 60:
            sentences.append(buffer[: last_comma + 1].strip())
            buffer = buffer[last_comma + 1 :].lstrip()
    return sentences, buffer


# ============ Ses -> Gemma (multimodal) ============
def audio_to_wav_bytes(full_audio):
    """float32 [-1, 1] numpy dizisini 16-bit mono WAV baytlarına çevirir."""
    audio_int16 = np.clip(full_audio * 32767.0, -32768, 32767).astype(np.int16)
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_int16.tobytes())
    return wav_buffer.getvalue()


def decide_tools(audio_bytes):
    """Model bir kez çağrılır; hangi araç(lar) ve parametreleri JSON olarak döner."""
    if not TOOLS:
        return []

    tools_desc = "\n".join(
        f"- {t['name']}: {t['description']}\n  Parametreler: {json.dumps(t['parameters'], ensure_ascii=False)}"
        for t in TOOLS.values()
    )

    prompt = f"""{_current_time_context()} Kullanıcının sesli komutunu dinle. Aşağıdaki araçlardan hangisi(leri) gerekli?

    {tools_desc}

    KURAL: Cevabı SADECE şu JSON formatında ver, başka hiçbir şey yazma:
    {{"tools": [{{"name": "arac_adi", "args": {{"param": "deger"}}}}]}}

    Hiçbir araç gerekmiyorsa: {{"tools": []}}
    Birden fazla araç gerekiyorsa listeye ekle."""

    try:
        response = ollama.chat(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Sen bir araç yönlendiricisisin. Sadece JSON yazarsın.",
                },
                {"role": "user", "content": prompt, "images": [audio_bytes]},
            ],
            stream=False,
            think=False,
        )
        text = response.get("message", {}).get("content", "")
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return []
        data = json.loads(m.group(0))
        return data.get("tools", []) or []
    except Exception as e:
        print(f"[tools] Karar hatası: {e}")
        return []

# ============ Metin Modu ============
def decide_tools_text(prompt_text):
    """Metin için araç kararı - Ollama native tools API kullanır."""
    if not TOOLS:
        return []

    # parameters dict'ini JSON Schema'ya çevir
    tools_schema = []
    for t in TOOLS.values():
        props = {}
        for pname, pdesc in t["parameters"].items():
            props[pname] = {"type": "string", "description": pdesc}
        tools_schema.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": list(t["parameters"].keys()),
                },
            },
        })

    try:
        enriched = f"{_current_time_context()}\n\nKullanıcı mesajı: {prompt_text}"
        response = ollama.chat(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": enriched}],
            tools=tools_schema,
            stream=False,
            think=False,
        )

        msg = response.get("message", {})
        raw_calls = msg.get("tool_calls") or []

        # Debug: model gerçekten tool çağırdı mı?
        if raw_calls:
            print(f"[tools-debug] {len(raw_calls)} tool call döndü")
        else:
            print(f"[tools-debug] tool çağrısı yok; model cevabı: {msg.get('content','')[:150]!r}")

        out = []
        for tc in raw_calls:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            out.append({"name": fn.get("name"), "args": args})
        return out
    except Exception as e:
        print(f"[tools] Karar hatası (native): {type(e).__name__}: {e}")
        return []


def send_text_and_stream_speech(prompt_text, speak=True):
    """Metin promptunu LLM'e gönderir. speak=True ise yanıtı sesli de okur."""
    if not prompt_text.strip():
        return

    # 1) Araç kararı
    tool_calls = decide_tools_text(prompt_text)
    tool_context = ""
    if tool_calls:
        print(f"[tools] Seçilen: {[c.get('name') for c in tool_calls]}")
        tool_context = execute_tools(tool_calls)
        print(f"[tools] Sonuç: {tool_context[:200]}...")

    # 2) Nihai yanıt (streaming)
    final_messages = [
        {"role": "system", "content": JARVIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{_current_time_context()}\n\n"
                f"Kullanıcının mesajı: {prompt_text}"
                + (f"\n\nAraç sonuçları:\n{tool_context}" if tool_context else "")
            ),
        },
    ]

    response = ollama.chat(
        model=LLM_MODEL,
        messages=final_messages,
        stream=True,
        think=False,
    )

    buffer = ""
    print("[AI Yanıtı]: ", end="", flush=True)

    for chunk in response:
        piece = chunk.get("message", {}).get("content", "")
        if not piece:
            continue
        buffer += piece
        print(piece, end="", flush=True)

        if speak:
            ready, buffer = extract_ready_sentences(buffer)
            for sentence in ready:
                tts_queue.put(sentence)

    if speak and buffer.strip():
        tts_queue.put(buffer.strip())
    print()

    # TTS açıksa bitene kadar bekle
    if speak:
        last_empty_time = None
        while True:
            if tts_queue.empty() and not tts_active.is_set():
                if last_empty_time is None:
                    last_empty_time = time.time()
                elif time.time() - last_empty_time > TTS_WAIT_TIMEOUT:
                    break
            else:
                last_empty_time = None
            time.sleep(0.05)


def run_text_mode(speak=True):
    """Klavyeden prompt alır, her prompt için pipeline'ı çalıştırır."""
    print("\n=== METİN MODU ===")
    if speak:
        print("Yanıtlar hem yazılı hem sesli. Çıkmak için 'exit' veya Ctrl+C.\n")
    else:
        print("TTS kapalı, sadece yazılı yanıt. Çıkmak için 'exit' veya Ctrl+C.\n")

    try:
        while True:
            try:
                prompt = input("Sen> ").strip()
            except EOFError:
                break
            if not prompt:
                continue
            if prompt.lower() in ("exit", "quit", "çık", "cik", "q"):
                break
            try:
                send_text_and_stream_speech(prompt, speak=speak)
            except Exception as e:
                print(f"Hata: {type(e).__name__}: {e}")
            print()
    except KeyboardInterrupt:
        print("\nGörüşürüz.")

def execute_tools(tool_calls):
    """Karar JSON'undaki araçları sırayla çalıştırır, sonuçları metne çevirir."""
    if not tool_calls:
        return ""
    results = []
    for call in tool_calls:
        name = call.get("name")
        args = call.get("args", {}) or {}
        tool = TOOLS.get(name)
        if not tool:
            results.append(f"[{name}] bilinmeyen araç")
            continue
        try:
            print(f"[tools] {name}({args}) çalışıyor...")
            output = tool["fn"](**args)
            results.append(f"[{name}] {output}")
        except Exception as e:
            results.append(f"[{name}] hata: {e}")
    return "\n\n".join(results)

def send_audio_and_stream_speech(full_audio):
    audio_bytes = audio_to_wav_bytes(full_audio)
    print(f"[Ses] Modele gönderiliyor ({len(audio_bytes)} bayt)...")

    if interrupt_requested.is_set():
        return

    # 1) TEK KARAR ÇAĞRISI: hangi araçlar, hangi parametrelerle?
    tool_calls = decide_tools(audio_bytes)
    tool_context = ""
    if tool_calls:
        print(f"[tools] Seçilen: {[c.get('name') for c in tool_calls]}")
        tool_context = execute_tools(tool_calls)
        print(f"[tools] Sonuç: {tool_context[:200]}...")

    if interrupt_requested.is_set():
        return

    # 2) NİHAİ YANIT (streaming)
    final_messages = [
        {"role": "system", "content": JARVIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{_current_time_context()}\n\n"
                "Bu ses kaydını dinle ve kullanıcıya J.A.R.V.I.S. karakterine uygun yanıt ver."
                + (f"\n\nAraç sonuçları:\n{tool_context}" if tool_context else "")
            ),
            "images": [audio_bytes],
        },
    ]

    response = ollama.chat(
        model=LLM_MODEL,
        messages=final_messages,
        stream=True,
        think=False,
    )

    buffer = ""
    print("[AI Yanıtı]: ", end="", flush=True)

    for chunk in response:
        if interrupt_requested.is_set():
            print("\n[Akış kesildi]")
            break
        piece = chunk.get("message", {}).get("content", "")
        if not piece:
            continue
        buffer += piece
        print(piece, end="", flush=True)

        ready, buffer = extract_ready_sentences(buffer)
        for sentence in ready:
            if interrupt_requested.is_set():
                break
            tts_queue.put(sentence)

    if buffer.strip() and not interrupt_requested.is_set():
        tts_queue.put(buffer.strip())
    print()


# ============ Ses Pipeline ============
def process_audio_wrapper(full_audio):
    try:
        interrupt_requested.clear()
        while True:
            try:
                tts_queue.get_nowait()
            except queue.Empty:
                break

        send_audio_and_stream_speech(full_audio)

        # TTS bitene kadar bekle
        last_empty_time = None
        while True:
            if interrupt_requested.is_set():
                break
            empty = tts_queue.empty() and not tts_active.is_set()
            if empty:
                if last_empty_time is None:
                    last_empty_time = time.time()
                elif time.time() - last_empty_time > TTS_WAIT_TIMEOUT:
                    break
            else:
                last_empty_time = None
            time.sleep(0.05)
    except Exception as e:
        print(f"Hata: {type(e).__name__}: {e}")
    finally:
        processing_event.clear()
        print("\nMikrofon tekrar dinlemede...")


# ============ Mikrofon ============
def audio_callback(indata, frames, time_info, status):
    DEBUG_MIC_COUNTER[0] += 1
    if status:
        print(f"Ses akış uyarısı: {status}", file=sys.stderr)
    audio_queue.put(indata.copy())


def continuous_listener():
    buffer = []
    silence_counter = 0
    is_speaking = False
    bargein_counter = 0
    recent_blocks = collections.deque(maxlen=RECENT_BLOCKS_MAXLEN)

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        blocksize=BLOCK_SIZE,
        callback=audio_callback,
        dtype=np.float32,
    ):
        while True:
            try:
                block = audio_queue.get(timeout=0.1)
                audio_data = block.squeeze()
                energy = np.sqrt(np.mean(audio_data**2))
                recent_blocks.append(audio_data)

                # ---- BARGE-IN ----
                if tts_active.is_set() or not tts_queue.empty():
                    if energy > SPEECH_THRESHOLD:
                        bargein_counter += 1
                        if bargein_counter >= BARGE_IN_BLOCKS:
                            trigger_interrupt()
                            bargein_counter = 0
                            is_speaking = True
                            buffer = list(recent_blocks)[:-1]
                            silence_counter = 0
                    else:
                        bargein_counter = 0
                    if not is_speaking:
                        continue
                else:
                    bargein_counter = 0

                if processing_event.is_set() and not is_speaking:
                    continue

                if energy > SPEECH_THRESHOLD:
                    if not is_speaking:
                        print("\n[Dinleniyor...] Ses algılandı...")
                        is_speaking = True
                    buffer.append(audio_data)
                    silence_counter = 0
                else:
                    if is_speaking:
                        buffer.append(audio_data)
                        silence_counter += 1
                        if silence_counter >= SILENCE_BLOCKS:
                            print("Konuşma bitti, işleniyor...")
                            full_audio = np.concatenate(buffer)
                            buffer = []
                            is_speaking = False
                            silence_counter = 0

                            if not processing_event.is_set():
                                processing_event.set()
                                threading.Thread(
                                    target=process_audio_wrapper,
                                    args=(full_audio,),
                                    daemon=True,
                                ).start()
                            else:
                                print("[Atlandı] Önceki işlem devam ediyor...")
            except queue.Empty:
                continue
            except KeyboardInterrupt:
                print("\nDinleme durduruluyor...")
                break


# ============ Yükleme ============
def isOllamaRunning(base_url):
    try:
        response = requests.get(base_url, timeout=4)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

def load_llm():
    if not isOllamaRunning(OLLAMA_BASE_URL):
        print("Serving Ollama...")
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        for _ in range(20):
            if isOllamaRunning(OLLAMA_BASE_URL):
                break
            time.sleep(0.5)
        else:
            print("Ollama Server Cannot be started.")
    else:
        print("Ollama allready running!")
    
    print("Loading LLM: " + LLM_MODEL)
    try:
        requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={"model": LLM_MODEL, "keep_alive": OLLAMA_KEEP_ALIVE},
        )
    except Exception as e:
        print(f"LLM yüklenirken hata (Ollama açık mı?): {e}")


def load_piper_tts():
    global piper_voice
    print("Piper TTS modeli yükleniyor...")
    piper_voice = PiperVoice.load(PIPER_MODEL_NAME)  # CPU fallback
    print("Piper TTS hazır (CPU).")


def mic_monitor():
    last = 0
    while True:
        time.sleep(1)
        cur = DEBUG_MIC_COUNTER[0]
        diff = cur - last
        last = cur
        state = "TTS" if (tts_active.is_set() or not tts_queue.empty()) else "BOŞTA"
        if DEBUG_MOD == True:
            print(f"[DEBUG] Mikrofon {diff} blok/sn  (durum: {state})")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="J.A.R.V.I.S.")
    parser.add_argument("--text", "-t", action="store_true",
                        help="Metin modu (mikrofon yerine klavye)")
    parser.add_argument("--no-tts", action="store_true",
                        help="TTS'i kapat (sadece yazılı yanıt)")
    args = parser.parse_args()

    load_llm()
    discover_tools()

    if args.text:
        # ===== METİN MODU =====
        speak = not args.no_tts
        if speak:
            load_piper_tts()
            threading.Thread(target=tts_worker, daemon=True).start()
        try:
            run_text_mode(speak=speak)
        finally:
            if speak:
                tts_queue.put(None)
    else:
        # ===== SESLİ MOD (mevcut) =====
        load_piper_tts()
        threading.Thread(target=tts_worker, daemon=True).start()
        threading.Thread(target=mic_monitor, daemon=True).start()
        print("Sistem tam gaz hazır!")
        try:
            continuous_listener()
        finally:
            tts_queue.put(None)
