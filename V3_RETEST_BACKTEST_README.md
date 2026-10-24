# V3 — BTC/SOL erken uyarıdan varsayımsal işlem testine

**Durum:** yalnızca `experiment/early-signals-v1-20261022` test dalı.
Ana `main` kodu, Cloudflare ve mevcut ChatGPT 1H/4H bildirim görevleri
**değişmedi**. Borsa emri açılmaz. Bu bir yatırım tavsiyesi değil.

## Üç ayrı aşama

1. **YÖN:** Yalnızca o anda kapanmış 4H/1D mumlarından EMA20/50,
   RSI14 ve MACD histogram oyu. İki zaman dilimi aynı yönde olmalı.
2. **ERKEN UYARI:** Son kapanmış 1H mumu yeni BOS yaptıysa,
   MACD/RSI aynı yöndeyse ve önceki 1H mumuna kıyasla hacim
   en az %20 arttıysa uyarı adayı. Bu henüz işlem değildir.
3. **İŞLEM TEYİDİ (deneysel):** Sonraki **1–6 kapanmış 1H mumundan**
   birinin kırılmış BOS seviyesine tekrar temas ederek doğru yöne
   kapanması gerekir. Varsayımsal emir ancak **bir sonraki 1H
   mumunun açılış fiyatından** hesaplanır. Retest yoksa işlem yok.

## Risk, stop ve hedefler

- Stop: kırılma mumuyla retest mumunun en kötü fitili, buna 0,1×ATR payı
- İşlem risk mesafesi: varsayımsal girişin %0,1–%4'ü arasında olmalı
- TP1 = 1R, TP2 = 2R, TP3 = 3R; her hedefte pozisyonun 1/3'ü kapanmış sayılır
- Hem stop hem TP aynı saatlik mumda görülürse **stop önce** sayılır
- En fazla 24 saatlik pozisyon; tamamlanmazsa son mum kapanışında mark-to-close
- Varsayımsal gider: her yönde 6 baz puan işlem ücreti + 3 baz puan
  kayma; **gerçek borsa tarifesi veya gerçekleşmiş maliyet değildir**
- Fonlama, emir defteri, anlık spread, gerçek emir dolumu modellenmez

## İlk gerçek tarihsel tarama — 25 Ekim 2026 00:26 TSİ civarı

Kaynak: Coinalyze üzerinden gelen `/history` endpoint'i.
**BTC ve SOL için yalnızca 300 kapanmış 1H mum (~12,5 gün)**
incelemeye alınabildi. 4H örneklem 299, 1D 259 mumdu.

| Kriter | BTC | SOL |
|---|---:|---:|
| Katı 4H+1D uyumlu erken BOS uyarısı | 0 | 3 |
| Varsayımsal kapanmış işlem | 0 | 1 |
| Tamamlanan örneğin riske göre sonucu | Yok | 1,6689 R (gider varsayımıyla) |

Uyarılar, UTC zamanıyla:
- SOL 18 Ekim 20:00Z: bearish BOS 101,67, kapanış 100,78; giriş
  şartları tamamlanmadı veya retest penceresi kapandı
- SOL 24 Ekim 10:00Z (**13:00 TSİ**): bearish BOS 101,63,
  kapanış 101,38; 1H RSI 29,59 ile aşırı satım riski
- SOL 24 Ekim 15:00Z (**18:00 TSİ**): bearish BOS 101,05,
  kapanış 100,33; hızlı düşüşü kovalamak riskli, aynı bar giriş sayılmaz

24 Ekim 13:00 uyarısının **tamamlanmış tek kağıt üstü senaryosu**:
- Retest kapanışı sonrasında 15:00 TSİ *sonraki mum açılışında*
  varsayımsal giriş **101,46**
- Varsayımsal stop **102,0115**
- TP1 **100,9085**; TP2 **100,3570**; TP3 **99,8055**
- Geriye dönük fiyat yolunda TP3'e kadar ulaşmış; stop/TP aynı mum
  gerçekleşme belirsizliği için kod stop-önce varsayar
- Gider varsayımı sonrası **+1,6689 R**, yalnızca **bir örnek**
- **Bu sonuç canlı işlemi temsil etmez ve strateji başarı olasılığını
  tahmin etmez.** İstatistiksel kazanma oranı sunmak doğru değildir.

## Bilimsel sınırlamalar ve izlenecek yol

1. Sadece 300 saatlik veriyle istatistiksel iddia kurulamaz;
   hem yükseliş hem düşüş dönemlerini kapsayan farklı zaman aralıkları gerekir.
2. Test için kullanılan 6 saat retest, %20 hacim, ATR tamponu ve
   24 saat çıkış, *başarı kanıtı değil*, önceden tanımlanmış V3 varsayımlarıdır.
3. Alternatif maliyet ve slippage senaryoları ile aynı-mum belirsizliği
   ele alınmalı, veriler eğitim ve ileri-tarihli test olarak ayrılmalı.
4. Uzun geçmiş/çok sayıda bağımsız gerçekleşmiş örnek olmadan
   `main` dalına otomatik sinyal veya kullanıcıya 'teyitli giriş'
   aktarılmaz. Var olan saatlik rapor yalnızca yön ve erken uyarı sunar.
5. Güncel `/history` endpoint'i 1H için 14 günle sınırlı,
   çıktı son 300 mumla kesilir. Daha uzun test ayrı arşiv gerektirir;
   üretim Cloudflare Worker'a değiştirme yapılmamıştır.

Çalıştır:
```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 backtest_retest_v3.py \
  --hour history_1hour.json --four history_4hour.json \
  --daily history_daily.json --output v3_retest_backtest.json
```

Doğrulama: https://github.com/exchangecurrency11/BTC-SOL-ANALYS-S/actions/runs/40134243030
