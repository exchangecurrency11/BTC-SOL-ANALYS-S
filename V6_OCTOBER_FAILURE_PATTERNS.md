# V6: BTC/SOL BOS–Retest Arıza Desenleri (30 Ekim 2026)

## Çalışma durumu

**Deneysel dala ait geçmiş kağıt işlem analizi; canlı işleme bağlı DEĞİL.**
[Başarılı GitHub Actions çalışması](https://github.com/exchangecurrency11/BTC-SOL-ANALYS-S/actions/runs/41117088756)

- Kaynak: Binance resmi `data.binance.vision` **USD-M Futures** 1H ZIP dosyaları.
- Mevcut 24 ay: Ekim 2024 – Eylül 2026 (BTC ve SOL için 48 aylık ZIP).
- **Eklenen Ekim:** 1–27 Ekim 2026, iki parite × 27 = **54 günlük ZIP**.
- **28 Ekim 2026 günlük dosyası 30 Ekim 19:39 UTC itibarıyla HTTP 404**; eksik günü doldurmadık ve 29 Ekim'i de eklemedik.
- Sembol başına **18.168 tamamlanmış 1H**, **4.542 adet 4H**, **757 günlük** mum.
- ZIP başına SHA-256 doğrulaması, tüm 1H zaman çizelgesi eksiksiz. 4H/1D, **aynı Binance 1H mumlarından** türetildi.
- Eski dönemin sinyal ve hipotetik işlem kayıtları yeniden oynatıldığında **BTC 62 uyarı/18 işlem ve SOL 74 uyarı/31 işlem birebir aynı kaldı**.
- **49/49 otomatik test başarılı**.

## Sonuçlar (tamamlanmış varsayımsal işlemler)

| Gözlem | BTC | SOL |
|---|---:|---:|
| Erken BOS uyarısı | 62 | 79 |
| Retest ve sonraki açılış şartını karşılayan sonuçlanmış işlem | 18 | 33 |
| Net R pozitif işlemler | 7 | 14 |
| Net R negatif veya sıfır işlemler | 11 | 19 |
| TP1 görülmeden stop | 9 | 13 |
| İlk iki yıllık ortalama R, maliyetli | −0,0820 | +0,0831 |
| Ekim 1–27 ek dönemde işlem | 0 | 2 |
| Ekim 1–27 ek dönemde kazanan işlem | 0 | 1 |
| Ekim 1–27 ek dönemde ortalama R | yok | +0,304 |

Kullandığımız R: varsayımsal stop mesafesi biriminde sonuç; 9 baz puan/yön ücret + kayma **varsayımı**, gerçek borsa maliyeti değil. Fonlama, gerçek dolum, aralıklı fiyat ve emir defteri maliyetleri modellenmedi.

## Daha önce oluşmuş işlemlerde tanımlayıcı alt grup karşılaştırmaları

| Hipotez için gözlem | Örnek | Kazanan / Toplam | Ortalama R |
|---|---|---:|---:|
| BTC, stop mesafesi girişin %1'inden dar | %1 altı | 1/9 | −0,873 |
| BTC, stop mesafesi %1–4 | %1–4 | 6/9 | +0,709 |
| SOL, SHORT | SHORT | 6/17 | −0,151 |
| SOL, LONG | LONG | 8/16 | +0,360 |
| SOL, uyarıdaki hacim değişimi %20–49 | Düşük hacim | 1/4 | −0,195 |
| SOL, uyarıdaki hacim değişimi %50–99 | Orta hacim | 2/7 | −0,216 |
| SOL, uyarıdaki hacim değişimi en az %100 | Yüksek hacim | 11/22 | +0,249 |
| SOL, aşırı RSI (SHORT için <=30, LONG için >=70) | Aşırı | 7/17 | +0,046 |
| SOL, aşırı RSI yok | Normal | 7/16 | +0,150 |

### Ne ÇIKARAMAYIZ?

Bu farklar **nedensellik kanıtı değildir**. Çok küçük ve birbirine bağımlı alt grupların tarihsel *betimlemesi*dir. Bir işlemi RSI/stop/hacim filtresiyle elemek stratejinin daha sonraki işlemlerini de değiştireceği için tabloda kalan kârlı işlemlerin ortalaması **yeni strateji getirisi sayılamaz**. Daha önce görülen 2026 Nisan-Eylül dönemi artık tamamen bağımsız tutulan holdout değildir. Yalnızca 2 Ekim işlemiyle gelecekteki kazanç ihtimali hesaplanamaz.

### Gelecek deney hipotezleri (henüz uygulanmadı)

1. BTC'de **%1'den dar stop** durumunda gereksiz retest girişleri olabilir. Ayrı kronolojik paper replay ve yeni, henüz görülmemiş dönem gerekir.
2. SOL SHORT ve düşük hacimli BOS sinyalleri daha çok tersine dönebilir. Bunun sebep olup olmadığı test edilmedi.
3. RSI aşırılığı zararları tek başına açıklamıyor; RSI'ı körlemesine dışlayıcı yapmak bazı kârlı işlemleri de eler.
4. Ekim 28 ve sonrası gelecekte arşivde yayımlanınca, aynı yöntemle **önce arşiv dosyası varlığını kontrol ederek** birleştirilebilir. Güncel 1H Coinalyze akışı bağımsızdır.

**Canlı görevlerde, main dalında, Cloudflare Worker'da, 1H/4H bildirimlerinde veya borsada değişiklik YOK.** Bu test sadece dar tanımlı V4 BOS–retest stratejisine aittir; canlı 1H uyarılarındaki CHoCH / OB durumlarının tamamını ölçmez.
