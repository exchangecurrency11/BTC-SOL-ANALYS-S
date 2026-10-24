# V2 — Üç ayrı karar ve 24 Ekim doğrulaması

**Durum:** Deneysel dal; gerçek emir YOK, main branch kodu değişmedi.

- `signal_decision_v2.py` 4H+Daily yönünü; yeni 1H BOS/CHoCH/teyitli OB retestinden üretilen erken uyarıyı; ve işlem girişinin henüz doğrulanmadığı statüsünü AYRI üretir.
- Her 4H ve 1D için `fiyat-EMA20`, `fiyat-EMA50`, MACD histogram ve RSI50 ile dört şeffaf oy: >=+3 bullish, <=-3 bearish, diğerleri karışık; yalnızca karşılaştırmalı yön filtresi, başarı oranı DEĞİLDİR.
- Yeni 1H BOS için ilgili mumun gerçek kapanışı, RSI/MACD yönü ve önceki saate göre en az %20 hacim artışı zorunlu. Yeni CHoCH ayrı erken yön değişimidir. OB retesti için bir önceki saat anlık kayıt + kapanmış mum tepkisi zorunlu. Aksi durumda teması teyit etme.
- 4H ve Daily aynı yöndeyse LONG/SHORT öncelikli; uymuyorsa çatışma/ağırlık raporlanır. Giriş-stop-hedefler henüz doğrulanmadığı için null.
- `tests/fixtures/oct24_point_in_time_snapshots.json` içindeki örnekler GitHub'ın **tam o saatlerde yazılmış** 12:00, 13:00, 18:00, 19:00, 23:00 TSİ BTC/SOL Coinalyze snapshot commitlerinden türetilmiştir. İlgili SHA'lar her kayıtta yazılıdır.
- `python3 audit_signal_v2.py --output oct24_signal_v2_audit.json` komutu beş eski kapanışı alt alta çıkarır; bundan kazanç oranı çıkarma.
- 24 Ekim 13:00 TSİ SOL için v2 çıktı: `SHORT_PRIORITY + EARLY_SHORT_WARNING + NOT_CONFIRMED`. Kapanış 101,38 $; 101,63 $ bearish BOS; RSI29,5891; MACD hist-0,1217; hacim değişimi +%107,9519. Aşırı satım nedeniyle hareketi kovalama riski vardır.
- 24 Ekim 19:00 TSİ SOL ve BTC için de EARLY_SHORT_WARNING tespit edilir; ikisinde işlem girişi yine teyitsizdir.
- Mevcut `BTC SOL Saatlik Erken Sinyal Durumu` ChatGPT görevinin **rapor FORMAT/KURALLARI** aynı üç aşamalı karar mantığına güncellendi. Bu, Python v2 kodunun canlı ana sisteme kurulduğu anlamına GELMEZ. 4H/Daily otomasyonu, Cloudflare ve main dokunulmadı.
- 22 regresyon testi GitHub Actions üzerinden başarıyla tamamlandı. Testler no-lookahead, zaman damgası, BOS yönü/hacim, OB retesti için önceki snapshot ve teyitsiz giriş içerir.

**Sınırlamalar:** Beş eski kapanış, istatistiksel geriye dönük başarı testi değildir.
Henüz tek bir tam strateji için giriş-stop-TP1–3, işlem maliyetleri,
slippage, funding, yürütülebilir emir-fiyat eşleşmesi veya uzun out-of-sample
performans kanıtı yok. Bunlar doğrulanana kadar V2 bir **ERKEN İZLEME** aracıdır.

---

# Deneysel Erken Sinyal Motoru — V1 (21–22 Ekim 2026)

**Bu dal üretim sistemi değildir.** Ana `main` dalı, Cloudflare Workers,
fiyat veri dosyaları, teknik analiz otomasyonu ve bildirimleri değiştirilmez.

## Çözdüğümüz üç sorun

1. **Olay zamanı:** `at`, `breakAt`, `invalidatedAt` gibi v1 alanlarının
   çoğu mumun AÇILIŞ zamanıdır. Bu test dalında eklenen
   `confirmedAt`, `breakConfirmedAt`, `invalidationConfirmedAt` ve
   `fullyFilledConfirmedAt`, olayın kapanışta teyit edilebildiği zamanı gösterir.
   Eski alanlar geriye dönük uyumluluk için korunmuştur.
2. **1H erken gözlem:** `early_signal_experiment.py` 1H CHoCH yön değişimi,
   hacim+MACD uyumlu BOS ve OB retesti sonrasındaki kapanmış mum tepkisini
   gözlemler. Yalnızca `WATCH_LONG`, `WATCH_SHORT`, `BEKLE`, `CONFLICT`
   gibi **deneysel izleme** statüleri üretir.
3. **İptal:** Bullish/bearish OB geçersizleşirse eski yön için ayrı
   `OB_INVALIDATED` olayı üretir; tek başına ters yönde işlem açmaz.

## Gözlem testi nasıl yapılır?

Coinalyze kökenli yalnızca KAPANMIŞ 1H mumların JSON yanıtını kaydet:

```bash
curl -fL 'https://btc-sol-futures-test.exchange-currency-1111.workers.dev/history?interval=1hour' -o history_1hour.json
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 replay_early_signals.py --input history_1hour.json --output paper_report.json --lookback 168
```

`paper_report.json` içerisinde tüm uyarılar **ancak ilgili mum kapanışından
itibaren biliniyormuş gibi** hesaplanır. Aynı test `Early Signal Historical
Replay (read-only)` GitHub Actions iş akışında örnek olarak koşturulur ve
raporu Actions artifact olarak kaydeder. Analizde özel anahtar veya borsa
hesabına erişim kullanılmaz.

## Henüz YAPILMAYANLAR

- Gerçek emir, otomatik işlem veya canlı bildirim bağlantısı YOK
- Daily/4H ile tutarlı yön filtresi YOK (bu V1 yalnızca 1H aday uyarıdır)
- Giriş, stop, TP1–TP3, ücret/slippage/funding doğrulaması ve R/R YOK
- Gerçek tarihsel P&L, kazanma oranı veya güvenilirlik iddiası YOK
- Ham OHLCV OB sınıflandırmasının başarılı olduğu kanıtlanmış değildir
- Tarihsel testte pivotun ve OB'nin bilinebilirlik zamanını izle,
  aynı mumdaki fitil temasını emir dolumu varsayma

**Sonraki sürüm:** Çoklu zaman dilimi filtreleri; aday sinyalin
entry/invalidation/stop/target ve maliyet kuralları; daha uzun bir veri
geçmişinde out-of-sample test; sonuçların gerçek 4H mumları üzerinde
görselleştirilmesi. Bir gecelik başarı göstergesi uydurma.
