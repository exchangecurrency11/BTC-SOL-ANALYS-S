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
