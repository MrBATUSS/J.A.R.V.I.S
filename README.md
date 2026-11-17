# J.A.R.V.I.S. 🤖💬

> **Kişisel Proje Notu:** Bu depo, tamamen bireysel bir geliştirme ve keşif amacıyla sıfırdan oluşturulmuş **kişisel bir projedir**. Tamamen yerel (local) çalışacak, buluta bağımlı kalmayacak ve gizliliği ön planda tutacak şekilde tasarlanmıştır.

Donanım odaklı optimizasyonlar ve modern yerel yapay zeka modelleri kullanılarak geliştirilmiş, gerçek zamanlı, uçtan uca yerel sesli asistan sistemidir.

## 🚀 Öne Çıkan Özellikler

* **Multimodal Yerel Yapay Zeka:** Ollama üzerinde koşan **Gemma 4 (`gemma4:e4b` / `4B`)** modeli sayesinde ses girdilerini doğrudan işleyebilme (harici bir Whisper bağımlılığı olmadan saf multimodal yapı).

* **Yüksek Performanslı TTS:** Piper TTS (`tr_TR-dfki-medium`) ile pürüzsüz, doğal ve hızlı Türkçe ses sentezi.

* **Düşük Gecikme:** `sounddevice` ve WASAPI/MME ses yönlendirme optimizasyonları ile anlık sesli etkileşim.

* **Barge-in Desteği:** Asistan konuşurken araya girebilme ve akışı kesebilme altyapısı.

* **Tamamen Gizli & Çevrimdışı:** İnternet bağlantısı gerektirmez; tüm işlemler yerel donanım üzerinde gerçekleşir.

## 🛠️ Sistem Mimarisi

```text
[ Mikrofon / Ses Girdisi ] 
          │
          ▼
[ Ollama (Gemma 4:4B - Multimodal) ] ◄── (Yerel LLM İşleme)
          │
          ▼
[ Piper TTS (Ses Sentezi & WAV Akışı) ] 
          │
          ▼
[ sounddevice (Kulaklık / Ses Çıkışı) ]
```

## 💻 Donanım ve Yazılım Gereksinimleri

### Donanım Önerisi (Test Edilen Ortam)

* **GPU:** NVIDIA GeForce RTX 4060 (8 GB VRAM)

* **CPU:** AMD Ryzen 5 5600

* **RAM:** 16 GB+

* **Ses Cihazı:** Uyumlu kulaklık/mikrofon seti (Örn. ATK N9 PRO)

### Yazılım Gereksinimleri

* **İşletim Sistemi:** Windows 10 / 11 (veya Linux uyumlu ses katmanları)

* **Python:** 3.11+

* **Ollama:** Yerel model sunucusu (`gemma4:e4b` veya `gemma4:e2b` modeli indirilmiş olmalı `ollama pull gemma4:e4b` )

* **Piper TTS Modeli:** `tr_TR-dfki-medium.onnx` ve `.json` yapılandırma dosyası ([PiperHub Türkçe Modeller](https://piperhub.org/tr/) üzerinden indirilerek `D:\AI_Models\piper_cache` dizinine yerleştirilmelidir).

## 📦 Kurulum

1. Depoyu klonlayın veya proje klasörünü oluşturun:

   ```bash
   git clone https://github.com/kullaniciadi/jarvis-local.git
   cd jarvis-local
   ```

2. Sanal ortam oluşturun ve aktif edin:

   ```bash
   python -m venv deneme
   # Windows için:
   .\deneme\Scripts\Activate
   ```

3. Gerekli Python paketlerini yükleyin:

   ```bash
   pip install sounddevice soundfile librosa ollama piper-tts
   ```

4. Ollama üzerinde Gemma 4 (4B) modelini çekin:

   ```bash
   ollama pull gemma4:4b
   ```

5. [PiperHub](https://piperhub.org/tr/) adresinden Türkçe ses modelini (`tr_TR-dfki-medium.onnx` ve `.onnx.json`) indirip model klasörünüze (`D:\AI_Models\piper_cache`) kopyalayın.

## ⚙️ Yapılandırma

Kod içerisindeki model yollarını ve ses aygıtı indekslerini kendi sisteminize göre güncelleyin:

* **Piper Model Yolu:** `PIPER_MODEL_PATH = "D:/AI_Models/piper_cache/tr_TR-dfki-medium.onnx"`

* **Ses Cihazı:** `sd.query_devices()` kullanarak kulaklık çıkış indeksinizi (`device=4`) doğrulayın.

## ▶️ Kullanım

Asistanı başlatmak için ana betiği çalıştırın:

```bash
python main.py
```

Mikrofonunuza konuşarak asistanla doğrudan etkileşime geçebilirsiniz. Model ses girdisini doğrudan işleyecek ve Piper TTS üzerinden yanıtı sesli olarak kulaklığınıza aktaracaktır.

## 🧠 Sistem Promptu (Dijital Kanka Modu)

Asistanın soğuk ve resmi bir üslup yerine samimi, esprili ve sesli okumaya (TTS) tam uyumlu yanıtlar üretmesi için kullanılan sistem promptu:

```python
JARVIS_SYSTEM_PROMPT = """Sen J.A.R.V.I.S.'sin — kullanıcının dijital kankası ve en yakın kodlama ve mühendislik ortağısın. Zeki, pratik, esprili ve tamamen samimisin.

KİMLİĞİN VE TARZIN
Resmiyeti ve soğukluğu bir kenara bırak. Kullanıcıyla aynı frekansta konuşan, teknik konularda kafa patlatan, şakalaşan ama gerektiğinde işini kusursuz yapan bir dost gibisin. Onu pohpohlamazsın ama asla yukarıdan da bakmazsın.

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
Düşünme sürecini veya notlarını kesinlikle yazma. Sadece sesli okunacak metni çıktı ver."""
```

## 🔧 Geliştirme Günlüğü & Çözülen Kritik Teknik Sorunlar

Geliştirme sürecinde karşılaşılan ve çözüme kavuşturulan temel mühendislik sorunları:

1. **Python Modül Çakışması (Module Shadowing):**

   * *Sorun:* Test betiğine `piper.py` adı verilmesi sebebiyle kütüphane yerine yerel dosya içe aktarılmış ve dairesel import hatası oluşmuştur.

   * *Çözüm:* Test betikleri yeniden adlandırılarak paket çakışması giderilmiştir.

2. **Ses Çıkış Cihazı (Routing) Uyuşmazlığı:**

   * *Sorun:* `sounddevice` varsayılan olarak sesleri monitör hoparlörüne (`24G4HA`) yönlendirmiştir.

   * *Çözüm:* `sd.query_devices()` ile kulaklık aygıt indeksi tespit edilip (`device=4`) ses oynatma fonksiyonuna sabitlenmiştir.

3. **Örnekleme Hızı (Sample Rate) Uyuşmazlığı:**

   * *Sorun:* Piper'ın varsayılan `22050 Hz` çıkış frekansı, kulaklık sürücüsünde `-9997 Invalid sample rate` hatasına yol açmıştır.

   * *Çözüm:* Üretilen ses verisi `librosa` ile kulaklık sürücüsünün desteklediği `44100 Hz` frekansına yeniden örneklenmiştir (`resample`).

4. **Piper TTS API Metot Uyuşmazlığı (`0 bayt` Sorunu):**

   * *Sorun:* `voice.synthesize()` metoduna ham dosya tutamacı verildiğinde dosya `0 bayt` kalmıştır.

   * *Çözüm:* Güncel Piper Python API'sinde `wave.open` ile oluşturulan nesneye doğrudan yazım yapan **`voice.synthesize_wav()`** metoduna geçilmiştir.

### Kararlı Ses Sentezi ve Oynatma Kodu

```python
import tempfile
import wave
import os
import numpy as np
import sounddevice as sd
import soundfile as sf
import librosa

def synthesize_speech_piper(text):
    """Piper TTS ile metni seslendirir, 44100 Hz'e resample eder ve kulaklığa verir."""
    if not text.strip() or not piper_voice:
        return

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_wav:
        temp_wav_path = temp_wav.name

    try:
        with wave.open(temp_wav_path, "wb") as wav_file:
            piper_voice.synthesize_wav(text, wav_file)
            
        data, original_sr = sf.read(temp_wav_path)
        
        if len(data) > 0:
            target_sr = 44100
            data_resampled = librosa.resample(data.astype(np.float32), orig_sr=original_sr, target_sr=target_sr)
            
            sd.play(data_resampled, target_sr, device=4)
            sd.wait()
            
    except Exception as e:
        print(f"Piper TTS ses üretim hatası: {e}")
    finally:
        if os.path.exists(temp_wav_path):
            try:
                os.remove(temp_wav_path)
            except:
                pass
```

## ⚠️ Bilinen Sınırlar

* 8 GB VRAM sınırı içerisinde çalışacak şekilde kuantize edilmiş modeller tercih edilmiştir. Yoğun arka plan oyunlarında (örn. CS2) VRAM yönetimine dikkat edilmelidir.

* Windows ses sürücülerinin (MME/WASAPI) örnekleme hızı kısıtlamaları nedeniyle çıkış frekansı 44100 Hz olarak normalize edilmektedir.

## 📜 Lisans & Haklar

Bu proje kişisel bir geliştirme çalışmasıdır. Kodlar inceleme, ilham alma ve kişisel kullanım amaçlı açık tutulmuştur; ticari kullanım veya kurumsal sorumluluk içermez.
