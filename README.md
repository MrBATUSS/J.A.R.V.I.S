# J.A.R.V.I.S. (mini Jarvis) 🤖💬

> **Kişisel Proje Notu:** Bu depo, tamamen bireysel bir geliştirme ve keşif amacıyla sıfırdan oluşturulmuş **kişisel bir projedir**. Tamamen yerel (offline) çalışacak, buluta bağımlı kalmayacak ve gizliliği ön planda tutacak şekilde tasarlanmıştır.

Windows üzerinde çalışan, tamamen yerel (offline) bir Türkçe sesli asistan. Mikrofonla konuşulur, ses doğrudan çok modlu (multimodal) bir dil modeline gönderilir ve yanıt Piper TTS ile sentezlenerek kulaklığa aktarılır. Hiçbir veri buluta gitmez.

---

## 🚀 Öne Çıkan Özellikler

- **Saf Multimodal Mimari (Whisper Yok):** Ses baytları (`16 kHz, mono, 16-bit PCM WAV`) doğrudan Ollama üzerindeki **Gemma 4 (`gemma4:e2b` / `gemma4:e4b`)** modeline gönderilir; iki aşamalı STT+LLM gecikmesi ortadan kaldırılmıştır.
- **Akıllı Cümle Bölücü & Paralel TTS Kuyruğu:** LLM'den streaming olarak akan yanıtlar cümle bütünlüğü korunarak (ondalık sayılar, kısaltmalar vb. bozulmadan) bölünür ve ayrı bir worker thread üzerinden Piper TTS ile paralel seslendirilir.
- **Gelişmiş Barge-in (Söz Kesme):** Asistan konuşurken kullanıcı araya girdiğinde (`RMS > 0.015` enerji eşiği) ses anında kesilir (`sd.stop()`), kuyruktaki bekleyen cümleler temizlenir (drain) ve yeni komut işlenir.
- **Otomatik Ses Cihazı ve Hız Adaptasyonu:** Sistemdeki kulaklığı (`headphone` / `kulaklik` / `headset`) otomatik tespit eder ve cihazın doğal örnekleme hızına (`44100 Hz` / `48000 Hz`) dinamik olarak `resample` yapar.
- **Esnek `config.json` Yapılandırması:** İlk çalıştırmada otomatik oluşturulur; eksik anahtarlar `DEFAULT_CONFIG` ile *deep merge* edilerek kodun kırılması önlenir.

---

## 🛠️ Sistem Mimarisi ve Veri Akışı

```text
[ Mikrofon (16 kHz) ]
         │  (0.5 sn bloklar, RMS > 0.015 VAD)
         ▼
[ Gemma 4 (Ollama - Multimodal) ] ◄── (config.json: system_prompt + WAV baytları)
         │
         ├──► [ Streaming Yanıt ] ──► [ Akıllı Cümle Bölücü ] ──► [ TTS Kuyruğu ]
                                                                        │
[ Kulaklık (Otomatik Seçim) ] ◄── [ Resample (librosa) ] ◄── [ Piper TTS Worker ]
         ▲
         └── (Barge-in: 3 blok konuşma algılanırsa anında sd.stop + kuyruk temizliği)
```

### Çalışma Akışı
1. Mikrofon `16 kHz` mono, `0.5 sn` bloklar halinde sürekli dinlenir.
2. Enerji eşiği (`RMS > 0.015`) ile konuşma başlangıcı tespit edilir; `3 blok` (`1.5 sn`) sessizlik algılandığında kayıt tamamlanır.
3. Ses verisi `16-bit` mono WAV baytlarına dönüştürülerek `ollama.chat()` üzerinden Gemma 4'e gönderilir.
4. Streaming olarak gelen yanıt cümle cümle bölünür ve her tam cümle `tts_queue` kuyruğuna atılır.
5. Arka plandaki worker thread cümleleri Piper TTS (`voice.synthesize_wav`) ile sentezler, hedef cihazın frekansına yeniden örnekler (`librosa`) ve non-blocking olarak çalar.
6. Kullanıcı TTS sırasında konuşursa `trigger_interrupt()` tetiklenir, mevcut ses durdurulur ve kuyruk temizlenir.

---

## 💻 Donanım ve Yazılım Gereksinimleri

### Test Edilen Ortam
- **İşletim Sistemi:** Windows 10 / 11
- **GPU:** NVIDIA GeForce RTX 4060 (8 GB VRAM)
- **CPU:** AMD Ryzen 5 5600
- **Ses Cihazı:** ATK N9 PRO Kulaklık
- **Python:** 3.11 (öncelikli) / 3.10 (uyumlu)

### Yazılım Ön Koşulları
- **Ollama (`v0.33.3+`):** Doğrudan ses girişi (multimodal audio) desteği için güncel sürüm gereklidir.
- **Piper TTS Modeli:** Türkçe ses modelleri ([PiperHub Türkçe Modeller](https://piperhub.org/tr/) üzerinden `tr_TR-fahrettin-medium.onnx` veya `tr_TR-dfki-medium.onnx` ve `.json` dosyaları indirilerek `D:/AI_Models/piper_cache` dizinine yerleştirilmelidir).

---

## 📂 Proje Yapısı

```text
proje/
├── main.py            # Ana uygulama (~440 satır: VAD, LLM streaming, TTS worker, Barge-in)
├── config.json        # Kullanıcı ayarları (İlk çalıştırmada otomatik oluşur, .gitignore'a ekleyin)
├── README.md          # Proje dokümantasyonu
├── requirements.txt   # Python bağımlılıkları
└── test_tts.py        # (Opsiyonel) Bağımsız TTS ses çıkış test betiği
```

---

## 📦 Kurulum

1. Depoyu klonlayın ve proje dizinine geçin:
   ```bash
   git clone https://github.com/kullaniciadi/jarvis-local.git
   cd jarvis-local
   ```

2. Sanal ortam oluşturun ve aktif edin:
   ```bash
   python -m venv deneme
   .\deneme\Scripts\Activate
   ```

3. Gerekli kütüphaneleri yükleyin (`requirements.txt` içeriği):
   ```bash
   pip install sounddevice>=0.4.6 numpy>=1.24 ollama>=0.3.0 soundfile>=0.12.1 librosa>=0.10.0 piper-tts>=1.2.0 requests>=2.31.0
   ```

4. Ollama üzerinde Gemma 4 modelini indirin:
   ```bash
   ollama pull gemma4:e2b
   ```

5. [PiperHub](https://piperhub.org/tr/) adresinden Türkçe `.onnx` ve `.onnx.json` model dosyalarını indirip `D:/AI_Models/piper_cache/` klasörüne yerleştirin.

---

## ⚙️ Yapılandırma (`config.json`)

Uygulama ilk kez çalıştırıldığında proje kök dizininde `config.json` dosyasını varsayılan ayarlarla otomatik oluşturur. Dosyada eksik bir anahtar bırakırsanız uygulama `DEFAULT_CONFIG` ile *deep merge* yaparak çalışmaya devam eder.

```json
{
  "models": {
    "llm": "gemma4:e2b",
    "piper_onnx": "D:/AI_Models/piper_cache/tr_TR-fahrettin-medium.onnx"
  },
  "audio": {
    "sample_rate": 16000,
    "block_duration": 0.5
  },
  "vad": {
    "speech_threshold": 0.015,
    "barge_in_blocks": 3,
    "silence_blocks": 3,
    "recent_blocks_maxlen": 5
  },
  "tts": {
    "wait_timeout_seconds": 0.3
  },
  "ollama": {
    "base_url": "http://localhost:11434",
    "keep_alive": -1
  },
  "system_prompt": "Sen JARVIS'sin. Kisa, dogal, akici konus."
}
```

### Özel Karakter Promptu (Dijital Kanka Modu)
Varsayılan prompt kısa tutulmuştur. Asistanın soğuk ve resmi bir üslup yerine samimi, şakadan anlayan ve TTS okumasına tam uyumlu konuşması için `config.json` içindeki `"system_prompt"` alanını şu metinle değiştirebilirsiniz (JSON içinde satır sonları için `\n` kullanın):

```text
Sen J.A.R.V.I.S.'sin — kullanıcının dijital kankası ve en yakın kodlama ve mühendislik ortağısın. Zeki, pratik, esprili ve tamamen samimisin.

KİMLİĞİN VE TARZIN
Resmiyeti ve soğukluğu bir kenara bırak. Kullanıcıyla aynı frekansta konuşan, teknik konularda kafa patlatan, şakalaşan ama gerektiğinde işini kusursuz yapan bir dost gibisin.

KONUŞMA KURALLARI (SESLİ OKUMA İÇİN KRİTİK)
Yanıtların sesli okunacak. Doğal, akıcı, samimi bir konuşma dili kullan.
Asla ama asla:
- Madde işareti, liste, başlık, emoji, markdown veya kod bloğu kullanma.
- Kısaltmaları (vb., örn., bkz.) kullanma, kelime olarak açık yaz.
- Rakamları sayıyla yazma, konuşma dilinde yaz (örneğin yüzde elli, beş tane).
- "Efendim" kelimesini kesinlikle kullanma.

ŞAKA VE İRONİ
Kullanıcı absürt, imkânsız veya şaka yollu bir şey söylerse ciddiye alıp ders verme. Aynı kafayla, esprili bir dost gibi karşılık ver.

UZUNLUK
Kısa soruya tek cümleyle kısa cevap ver. Açıklama gereken yerlerde en fazla üç dört cümleyle net ve akıcı anlat. Asla yarım cümle bırakma.
```

> **Not:** `config.json` kişisel dosya yolları ve prompt ayarları içerdiğinden `.gitignore` dosyasına eklenmesi önerilir. Değişikliklerin geçerli olması için `main.py` yeniden başlatılmalıdır.

---

## ▶️ Kullanım ve Test Senaryoları

Uygulamayı başlatmak için:
```bash
python main.py
```

**Beklenen Açılış Çıktısı:**
```text
[config] config.json olusturuldu (varsayilanlarla).
Loading LLM: gemma4:e2b
Piper TTS modeli yukleniyor...
Piper TTS hazir.
Ses cikisi: [4] Kulaklik (ATK N9 PRO) (44100 Hz)
Sistem tam gaz hazir!
```

### Test Komutları
| # | Söylenecek Komut | Beklenen Davranış |
| :--- | :--- | :--- |
| **1** | *"Saat kaç?"* | Tek cümlelik kısa ve doğrudan yanıt |
| **2** | *"Bugün uzayda kıyafetsiz yürümeyi düşünüyorum."* | Ders vermeden esprili karşılık |
| **3** | *"Başım çok ağrıyor."* | Ciddi, empatik ve doğal ton |
| **4** | Uzun bir anlatım isterken TTS sırasında *"Dur"* demek | Ses anında kesilir ve yeni komut işlenir (Barge-in) |

---

## 🔧 Çözülen Kritik Mühendislik Sorunları

1. **Modül Gölgeleme (`piper.py`):** Test dosyasına `piper.py` adı verilmesi sebebiyle oluşan dairesel import hatası, test dosyalarının yeniden adlandırılmasıyla çözüldü.
2. **Piper TTS API Hatası (`0 bayt` Çıktı):** `voice.synthesize()` jeneratör döndürdüğü için dosyaya yazmıyordu; `wave.open` ile doğrudan yazım yapan **`voice.synthesize_wav()`** metoduna geçildi.
3. **Örnekleme Hızı (`-9997 Invalid sample rate`):** Piper'ın `22050 Hz` çıktısı, seçilen çıkış cihazının doğal hızına (`44100 Hz` / `48000 Hz`) `librosa.resample` ile dinamik dönüştürüldü.
4. **Cümle Bölme Koruması:** `3.14` gibi ondalık sayılar, `Dr.`, `vb.` gibi kısaltmalar ve tek harf noktalamaları korunarak hatalı TTS kesintileri önlendi; 180 karakteri aşan uzun bloklar virgülden bölünerek gecikme düşürüldü.
5. **Barge-in Race Condition Koruması:** `sd.play()` callback tabanlı non-blocking moda alındı; `interrupt_requested` bayrağı yalnızca yeni pipeline başlangıcında temizlenerek (`clear`) eski thread'lerin araya cümle kaçırması engellendi.

---

## ⚠️ Bilinen Sınırlar & Gelecek Planları

### Bilinen Sınırlar
- **Akustik Echo İptali (AEC) Yok:** Asistan hoparlörden konuşurken kendi sesini mikrofonla yakalayabilir; kulaklık kullanımı önerilir.
- **Bağlam Penceresi (Memory) Yok:** Her komut bağımsız işlenir, önceki konuşmalar hatırlanmaz.
- **Tek Oturum:** Eşzamanlı çoklu kullanıcı desteği yoktur.

### Yol Haritası (Olası Geliştirmeler)
- [ ] **Araç Çağırma (Function Calling):** Hava durumu, takvim ve sistem komutları entegrasyonu.
- [ ] **Konuşma Geçmişi:** Kısa süreli bağlam hafızası eklenmesi.
- [ ] **Uyandırma Kelimesi (Wake Word):** *"Jarvis"* hitabı ile aktifleşme.
- [ ] **Dinamik VAD Kalibrasyonu:** Ortam gürültüsüne göre otomatik eşik ayarı.
- [ ] **GPU Hızlandırma & Hot-Reload:** Piper ONNX Runtime'ın GPU'ya taşınması ve `config.json` değişikliklerinin yeniden başlatma gerektirmeden algılanması.

---

## 📜 Lisans & Haklar

Bu proje kişisel bir geliştirme çalışmasıdır. Kodlar inceleme, ilham alma ve kişisel kullanım amaçlı açık tutulmuştur; ticari kullanım veya kurumsal sorumluluk içermez.