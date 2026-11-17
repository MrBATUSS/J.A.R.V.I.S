import os
import io
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
import librosa
from piper import PiperVoice
import tempfile
import requests

# ============ Sabitler ============
SAMPLE_RATE = 16000
BLOCK_DURATION = 0.5
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_DURATION)

LLM_MODEL = "gemma4:e2b"
PIPER_MODEL_NAME = "D:/AI_Models/piper_cache/tr_TR-fahrettin-medium.onnx"

SPEECH_THRESHOLD = 0.015
BARGE_IN_BLOCKS = 3
DEBUG_MIC_COUNTER = [0]

audio_queue = queue.Queue()
tts_queue = queue.Queue()
piper_voice = None

tts_active = threading.Event()
interrupt_requested = threading.Event()
processing_event = threading.Event()


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


print(f"Ses çıkışı: {_describe_output()}")


# ============ J.A.R.V.I.S. Sistem Promptu ============
JARVIS_SYSTEM_PROMPT = """
Sen JARVİSSİN'sin
KİMLİĞİN VE TARZIN
Resmiyeti ve soğukluğu bir kenara bırak. Kullanıcıyla aynı frekansta konuşan bir dijital asistansın.

KONUŞMA KURALLARI (SESLİ OKUMA İÇİN KRİTİK)
Yanıtların sesli okunacak. Doğal, akıcı, samimi bir konuşma dili kullan.
Asla ama asla:
- Madde işareti, liste, başlık, emoji, markdown veya kod bloğu kullanma.
- Kısaltmaları (vb., örn., bkz.) kullanma, kelime olarak açık yaz.
- Rakamları sayıyla yazma, konuşma dilinde yaz (örneğin yüzde elli, beş tane).
- "Efendim" kelimesini kesinlikle kullanma. Zaten kankayız, gerek yok.

ŞAKA VE İRONİ
Kullanıcı absürt, imkânsız veya şaka yollu bir şey söylerse sakın ciddiye alıp ders verme. Aynı kafayla, esprili, hafif iğneleyici bir dost gibi karşılık ver.

UZUNLUK
Kısa soruya tek cümleyle kısa cevap ver. Açıklama gereken yerlerde en fazla üç dört cümleyle net ve akıcı anlat. Asla yarım cümle bırakma.

BİLGİ VE DOĞRULUK
Bilmediğin şeyi uydurma, dürüstçe bilmiyorum de geç.

SESSİZ KURAL
Düşünme sürecini veya notlarını kesinlikle yazma. Sadece sesli okunacak metni çıktı ver.
"""


# ============ TTS ============
def synthesize_speech_piper(text):
    if not text.strip() or not piper_voice or interrupt_requested.is_set():
        return

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_wav:
        temp_wav_path = temp_wav.name

    try:
        with wave.open(temp_wav_path, "wb") as wav_file:
            piper_voice.synthesize_wav(text, wav_file)

        data, original_sr = sf.read(temp_wav_path)
        if len(data) == 0:
            return
        if original_sr != TARGET_SR:
            data = librosa.resample(
                data.astype(np.float32), orig_sr=original_sr, target_sr=TARGET_SR
            )
        else:
            data = data.astype(np.float32)

        if interrupt_requested.is_set():
            return

        sd.play(data, TARGET_SR, device=OUTPUT_DEVICE)

        time.sleep(0.01)
        if interrupt_requested.is_set():
            try:
                sd.stop()
            except Exception:
                pass
            return

        while True:
            stream = sd.get_stream()
            if stream is None or not stream.active:
                break
            if interrupt_requested.is_set():
                try:
                    sd.stop()
                except Exception:
                    pass
                break
            time.sleep(0.03)
    except Exception as e:
        print(f"Piper TTS hatası: {e}")
    finally:
        if os.path.exists(temp_wav_path):
            try:
                os.remove(temp_wav_path)
            except OSError:
                pass


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
            word = text[start:i + 1].lower()
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
            buffer = buffer[last_comma + 1:].lstrip()
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


def send_audio_and_stream_speech(full_audio):
    """Ses baytlarını Gemma'ya gönderir, streaming yanıtı TTS'e akıtır."""
    audio_bytes = audio_to_wav_bytes(full_audio)
    print(f"[Ses] Modele gönderiliyor ({len(audio_bytes)} bayt)...")

    response = ollama.chat(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": JARVIS_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Bu ses kaydını dinle. Kullanıcının ne söylediğini anla ve J.A.R.V.I.S. karakterine uygun yanıt ver.",
                # NOT: Ollama multimodal API'sinde ses için "images" alanı kullanılıyor.
                # Yeni sürümlerde "audios" alanı da var; 400 alırsanız onu deneyin.
                "images": [audio_bytes],
            },
        ],
        stream=True,
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
        # Yeni oturum: interrupt'ı ve kuyruğu temizle
        interrupt_requested.clear()
        while True:
            try:
                tts_queue.get_nowait()
            except queue.Empty:
                break

        send_audio_and_stream_speech(full_audio)

        # TTS bitene kadar bekle (300ms onay)
        last_empty_time = None
        while True:
            if interrupt_requested.is_set():
                break
            empty = tts_queue.empty() and not tts_active.is_set()
            if empty:
                if last_empty_time is None:
                    last_empty_time = time.time()
                elif time.time() - last_empty_time > 0.3:
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
    recent_blocks = collections.deque(maxlen=5)

    with sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, blocksize=BLOCK_SIZE,
        callback=audio_callback, dtype=np.float32,
    ):
        while True:
            try:
                block = audio_queue.get(timeout=0.1)
                audio_data = block.squeeze()
                energy = np.sqrt(np.mean(audio_data ** 2))
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
                        if silence_counter >= 3:
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
def load_llm():
    print("Loading LLM: " + LLM_MODEL)
    try:
        requests.post(
            "http://localhost:11434/api/chat",
            json={"model": LLM_MODEL, "keep_alive": -1},
        )
    except Exception as e:
        print(f"LLM yüklenirken hata (Ollama açık mı?): {e}")


def load_piper_tts():
    global piper_voice
    print("Piper TTS modeli yükleniyor...")
    try:
        piper_voice = PiperVoice.load(PIPER_MODEL_NAME)
        print("Piper TTS hazır.")
    except Exception as e:
        print(f"Piper model yükleme hatası: {e}")


def mic_monitor():
    last = 0
    while True:
        time.sleep(1)
        cur = DEBUG_MIC_COUNTER[0]
        diff = cur - last
        last = cur
        state = "TTS" if (tts_active.is_set() or not tts_queue.empty()) else "BOŞTA"
        print(f"[DEBUG] Mikrofon {diff} blok/sn  (durum: {state})")


if __name__ == "__main__":
    load_llm()
    load_piper_tts()

    threading.Thread(target=tts_worker, daemon=True).start()
    threading.Thread(target=mic_monitor, daemon=True).start()

    print("Sistem tam gaz hazır!")
    try:
        continuous_listener()
    finally:
        tts_queue.put(None)