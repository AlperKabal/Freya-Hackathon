# Öğrenme notları: Freya "Build the Builder"

Yaşar için, Faz 0 boyunca anlatılanların toplu hali (10 Ekim 2026). Kısaltmalar ilk geçtikleri yerde açık yazıldı.
Teknik ayrıntıların İngilizce kaydı [JOURNAL.md](JOURNAL.md) dosyasında, çalışma planı [DEV_AGENT_PROMPT.md](DEV_AGENT_PROMPT.md) dosyasında.

## İçindekiler

1. [Büyük resim: builder ve telefon ajanı](#1-büyük-resim-builder-ve-telefon-ajanı)
2. [Freya platformu: bir workflow nasıl çalışır](#2-freya-platformu-bir-workflow-nasıl-çalışır)
3. [Banka tarafı: 7 tool ve ledger](#3-banka-tarafı-7-tool-ve-ledger)
4. [Puanlama](#4-puanlama)
5. [Brief A ve B'nin özü](#5-brief-a-ve-bnin-özü)
6. [Base agent'ın anatomisi](#6-base-agentın-anatomisi)
7. [Baseline sonucu ve vaka analizi](#7-baseline-sonucu-ve-vaka-analizi)
8. [Bizim mimarimiz: hibrit builder](#8-bizim-mimarimiz-hibrit-builder)
9. [Self-test tuzağı](#9-self-test-tuzağı)
10. [Script'ler tek tek](#10-scriptler-tek-tek)
11. [Kitte bulunan sorunlar ve doğrulanan bilgiler](#11-kitte-bulunan-sorunlar-ve-doğrulanan-bilgiler)
12. [Komut kopya kağıdı](#12-komut-kopya-kağıdı)
13. [Faz 0 kapanışı ve açık soru](#13-faz-0-kapanışı-ve-açık-soru)

---

## 1. Büyük resim: builder ve telefon ajanı

İki ayrı program var. Karıştırmamak en önemli konu:

| | **Telefon ajanı** (phone agent) | **Builder** |
|---|---|---|
| Ne | Freya'da çalışan bir *workflow* (JSON, JavaScript Object Notation) | Bizim Python programımız |
| Kim yazar | Builder üretir | Biz yazarız |
| Ne yapar | Müşteriyle konuşur, bankanın tool'larını çağırır | Brief'i ve tool API (application programming interface) dosyasını okur, ajanı Freya'ya yükler |

Pazar 17:00 UTC (Coordinated Universal Time; Türkiye saatiyle 20:00) iki gizli brief gelir: biri temiz bir şartname,
diğeri ham banka materyali (e-posta, politika alıntısı, onu değiştiren bir memo, bir kod listesi). Builder'ı bunlar
üzerinde **elle müdahale olmadan** çalıştırırız. 20:00 UTC'de (23:00 TR) teslim kapanır.

Bu yüzden builder Brief A'yı ezberlememeli; brief'i **okuyup anlayan** bir program olmalı.
"Brief A'dan hiçbir değer `builder/` içine girmez" kuralının sebebi bu.

**Sert kurallar (ihlal = diskalifiye):**
- Builder'ın oluşturduğu ajan elle düzenlenmez.
- Gizli brief açıldıktan sonra yalnızca bug fix; gizli brief'ten hiçbir kural, değer, ad koda girmez.
- Ajanın modeli (`AGENT_LLM`) değiştirilmez. Builder istediği modeli kullanabilir.
- Workflow'a `agent_config` gönderilmez.
- Bir builder çalışması (self-test dahil) brief başına en fazla 30 dakika.
- Workflow yerinde güncellenir (`freya.save_workflow`), her çalışmada yenisi oluşturulmaz.

---

## 2. Freya platformu: bir workflow nasıl çalışır

**Workflow bir graf.** Her **node** konuşmanın bir adımı, **transition**'lar adımlar arasındaki oklar.

### Node tipleri

| Tip | Ne yapar | Konuşur mu |
|---|---|---|
| `conversation` | Model müşteriyle konuşur, `tools` çağırabilir | Evet |
| `api_request` | Girişte HTTP (HyperText Transfer Protocol) çağrısı yapar (`pre_actions`) | Hayır |
| `code` | Girişte Python çalıştırır, `vars` okur/yazar | Hayır |
| `end_call` | Telefonu kapatır | İsteğe bağlı veda |

`tools` yalnızca `conversation` node'larında, `pre_actions` yalnızca `api_request` ve `code` node'larında yaşar.
Yanlış yere koyarsan platform **hatasız ve sessizce** siler.

### Her müşteri cümlesinde üç ayrı LLM (large language model) çağrısı

```
müşteri mesajı → 1. EXTRACTION (değişken çıkar) → 2. ROUTING (node değiştir?) → 3. DIALOGUE (cevap yaz)
```

Üçü aynı prompt'u görmez. **Routing yalnızca transition açıklamalarını okur, `task_message`'ı hiç görmez.**
Yani `task_message`'a "kimlik doğrulanınca ödemeye geç" yazmanın routing'e etkisi sıfırdır.

### Deterministik ve semantik geçişler

- `equals`, `greater_than`, `is_set` gibi koşullar **kodda** değerlendirilir: model çağrısı yok, her seferinde aynı sonuç.
- `matches_intent` modelin yorumudur: bazen tutar, bazen tutmaz.

Bir müşteri ancak **3 koşunun 3'ünü** geçerse sayılıyor. %90 güvenilir bir adım üç koşuda yaklaşık %73'e iner
(0,9³). Bu yüzden mümkün olan her yerde deterministik yolu seçiyoruz. Müşterinin söylediğine göre dallanmak için önce
bir enum çıkarıp sonra `equals` ile dallanırız:

```json
{"name": "who_answered", "type": "string",
 "enum_values": ["customer", "other_person", "wrong_number", "deceased", "unclear"],
 "min_confidence": 0.7}
```

**Boolean tuzağı:** `true` değerleri string olarak gelir, bazen `"true"`, bazen `"True"`. `equals` string karşılaştırır.
İkisini birden test et ya da daha iyisi koddan string bayrak yaz (`"verified"`, `"rejected"`).

### Extraction (değişken çıkarma)

- Her alana `min_confidence` koy (örneğin 0.7). Varsayılan 0.95 değerleri **sessizce** atar.
- Tarihleri `type: "date"` olarak tanımla; yoksa model yılı tahmin eder.
- Yerleşik tarih kuralları "next week" gibi belirsiz ifadeleri somut bir tarihe çevirir. Brief belirsiz dönemler için
  "bir kez tam günü sor" diyorsa bunu ayrıca ele almak gerekir.

### Tool parametrelerinde "baking" (sabitleme)

Bir parametrenin `default` alanı `{{degisken}}` olsun. Node'a girildiği anda değişkenin değeri varsa parametre
**sabitlenir** ve model onu hiç görmez. Değişken boşsa parametreyi model doldurur. `const` asla sabitlemez, kullanma.

Sonuç: `customer_id`, `product_id`, doğrulanmış tutar ve tarih, `outcome`, `reason` gibi kritik değerleri önce
**kod** hesaplayıp değişkene yazar, sonra tool bunları sabitler. Model "p7" gibi bir id uyduramaz.

### Tool sonuçları değişkenlere kendiliğinden düşer

`<tool>_response.data.<alan>`, `<tool>_args.<alan>`, `<tool>_success_count`, `<tool>_failure_count`.
Mapping yazmadan bunlarla routing yapabilirsin.

### Post-hook (`post_process_code`)

Tool sonucu modele gitmeden önce çalışan küçük bir Python kodu. İki büyük hatayı çözer:
ajanın tool sonucundan sonra susması ve olumsuz bir sonucu (`verified: false`) görmezden gelmesi.

```python
try:
    result.pop('header', None)
    d = result.get('data')
    if isinstance(d, dict):
        d['what_to_do_next'] = 'Wrong answer. 2 tries left. Ask the same question again.'
except Exception:
    pass
```

### Code node

`node_type: "code"`, passthrough, `pre_actions` içinde `code_exec`. `vars` sözlüğünü okur ve yazar.
Bütün tarih ve tutar hesapları burada yapılır; modele bitmiş gerçekler metin olarak verilir.
Kurallar: kodda `{{` veya `}}` yazma, kod asla hata fırlatmasın (`try/except`), sonraki node'ların okuduğu her
değişkene bir yedek değer yaz.

### Passthrough node

Kullanıcıyı beklemeden yönlenir. **Mutlaka bir `always` transition ile bitmeli**, yoksa kilitlenir.

### Lifecycle tool

`config.alwaysRunsAt: ["end_of_call"]` olan bir tool, çağrı bittikten sonra motor tarafından çalıştırılır.
`close_call`'ın her zaman son çağrı olmasını garanti eder. Şartı: `{{outcome}}` ve `{{reason}}` o ana kadar **bizim
kodumuz** tarafından doldurulmuş olmalı. Boşsa bir model tahmin yürütür (baseline'da bunun ne kadar kötü olduğunu
gördük, bölüm 7).

### Publish

Bir update ancak publish edilince sayılır. `freya.save_workflow` publish eder; düz bir PUT etmez.

---

## 3. Banka tarafı: 7 tool ve ledger

[tools/openapi.json](../tools/openapi.json) yedi tool tanımlar:

| Tool | Ne yapar |
|---|---|
| `verify_identity` | Bir güvenlik cevabını kontrol eder. `verified`, `wrong_answers_left`, `all_verified`, `hint` döner |
| `get_account` | Gecikmiş ürünleri döner. Kimlik doğrulanmadan reddeder |
| `create_promise` | Ürün başına bir ödeme sözü kaydeder |
| `add_note` | Brief B: söz alınamayan ürünün sebebini kaydeder |
| `schedule_callback` | Geri arama planlar (`date`, `time` HH:MM) |
| `transfer_to_agent` | Çağrıyı bir kuyruğa devreder (`restructuring`, `general`, `support`) |
| `close_call` | Çağrıyı outcome ve reason ile kapatır. Her zaman son çağrı |

Bunlar sahte bir banka sunucusunda (mock) çalışır ve her çağrı bir **ledger**'a (kayıt defteri) yazılır.
Mock brief'i **uygulamaz**: tatil gününe söz istesen de kaydeder. Kuralları uygulamak tamamen bizim ajanın işi.

Gizli brief'lerde tool adları aynı kalır, **alanlar ve izin verilen değerler değişebilir**. Bu yüzden enum'lar
(outcome adları, kuyruklar, kimlik alanları) her zaman tool API dosyasından okunmalı.

---

## 4. Puanlama

1. Mock'ta her vaka için bir practice session açılır; mock `customer_id` dahil çağrı değişkenlerini döner.
2. Freya'da bir simülasyon başlar. Müşteriyi bir Gemini modeli oynar.
3. Çağrı bitince iki kontrol:
   - **Ledger kontrolü** (`score.py`): outcome ve reason, söz kayıtları, notlar, callback'ler, transferler **birebir**
     doğru mu; son çağrı `close_call` mı?
   - **Hakem modeli**: transkripti vakanın `checks` listesine göre okur (örnek: "'collections' kelimesi kimlik
     doğrulamadan önce söylenmedi").

Kısmi puan yok. Tek bir yanlış alan o koşuyu düşürür.

**Final:** 60 gizli müşteri (brief başına 30), 1 ila 3 ürün, birkaç farklı takvim günü. Her müşteri 3 kez koşar ve
yalnızca 3/3 geçerse sayılır. Eşitlikte: geçen vakalardaki toplam söz tutarı, sonra kısa build süresi, sonra erken
teslim.

**Önemli:** Pratikteki `checks` listesi kuralların tamamı değil, örnekler. Finalde hakem transkripti brief'in
tamamına göre okur.

---

## 5. Brief A ve B'nin özü

### Brief A (tek ürün, 47 kural)

Akış: açılış → doğru kişi mi? → (başkası açtıysa: hiçbir şey açıklamadan callback) → 2 güvenlik sorusu → borcu
söyle → bugün ödeyebilir mi? → ikna denemeleri → teyit → kayıt → kapanış.

En çok hata çıkacak yer **tarih hesabı**. `now = 2026-10-14` (Çarşamba) için, kodla doğrulandı:

| Hesap | Sonuç | Vaka |
|---|---|---|
| Geç band (8 ila 45 gün): bugünden sonraki 7. iş günü | 23 Ekim | PUB-04, PUB-13 |
| Erken band (1 ila 7 gün): 12. iş günü, 26 Ekim tatili atlanarak | 2 Kasım | PUB-13 |
| 1. ikna denemesi: bu haftanın son iş günü | 16 Ekim | PUB-06, PUB-10 |

Bu hesabı her müşteri cümlesinde modele yaptırırsak er geç yanlış yapar. Plan: `setup` adlı bir code node'unda bir
kez hesaplayıp modele hazır metin vermek ("Son tarih: 23 Ekim Cuma").

### Brief B (en fazla 3 ürün)

Brief A'nın üstüne: ürün başına ayrı band ve son tarih; ürün başına ayrı ikna sayacı; önce "hepsini bugün ödeyebilir
misiniz?", sonra ürün ürün; tek bir toplu teyit, sonra ürün başına `create_promise`; söz alınamayan her ürün için
`add_note`; transfer olursa hiç not yok; "promise kazanır, transfer hariç" kapanış önceliği.

---

## 6. Base agent'ın anatomisi

[examples/base-agent.json](../examples/base-agent.json): 2 node, 4 tool.

```
initial_node: identity ──(all_verified == true/True)──► collection
                                                              (çıkış yok)
workflow tools: close_call  [end_of_call lifecycle]
```

**`identity` node'u:**
- `on_enter` bir TTS (text-to-speech, metinden sese) satırı: "Hello, this is the digital assistant of Freya Bank. Am I
  speaking with {{title}} {{last_name}}?" Sabit olduğu için her seferinde aynı çıkar.
  Ama Brief A kural 1'in istediği "the call is recorded" kısmı **eksik**.
- `verify_identity`: `field` ve `answer` alanlarını model doldurur (`{{field}}` diye bir değişken olmadığı için
  sabitlenemez); `customer_id` sabitlenmiş.
- Geçiş iki yazımı birden test eder: `"true"` ve `"True"`.

**`end_call` bir tool olarak:** conversation node'unda `trigger_pattern: "Have a good day"` olan bir `end_call`
tool'u var. Model bu cümleyi söyleyince çağrı kendiliğinden kapanır. `trigger_timeout` 3 saniyelik bir pencere açar;
müşterinin cevabı `trigger_pattern_both` listesindeki bir ifadeyle eşleşirse kapanış iptal olmaz.
Kullanışlı ama riskli: model cümleyi yanlış anda söylerse çağrı yanlış anda kapanır.

**`collection` node'u:** `get_account` modelin çağırdığı bir tool (bizde `pre_actions` olacak). `create_promise`
alanlarını model doldurur; tarih kuralları için modelin elinde yalnızca `"Now: {{now}}"` var.

**`close_call` (lifecycle):** `{{outcome}}` değişkenini hiçbir yer doldurmuyor, değeri çağrı sonunda bir model
tahmin ediyor. Enum'da `paid` ve `transferred` de yok. `pre_process_code` outcome `promise` veya `paid` ise
`reason` alanını siliyor (bu doğru: `score.py` bu durumda reason'ın `None` olmasını bekliyor).

---

## 7. Baseline sonucu ve vaka analizi

**Base agent, Brief A: 0/10.** README "yaklaşık 2/13" diyordu. Medyan en yavaş tur 5 saniye, telefonu kapatan müşteri
yok; yani model yavaş değildi, puan gerçek. (Tek koşu yalnızca bir işarettir.)

### PUB-02: telefonu başkası açıyor

Beklenen: hiçbir şey açıklamadan yarın 11:00'e callback, `not_reached / callback`.

```
0.0s AGENT  Hello, this is the digital assistant of Freya Bank. Am I speaking with Ms Costa?
1.7s USER   No, this is her husband. What is this call about?
1.7s AGENT  I can explain after the security check. Am I speaking with Ms Costa?
3.1s USER   No, I told you I am her husband. I can pay for it myself if you tell me what it is.
3.2s AGENT  I am sorry, but I must verify the account holder's identity first. Goodbye, have a good day.
3.5s   [trigger_timeout_started]
4.4s USER   Thank you, goodbye.
6.5s   [call_ended]
9.8s   [call] close_call body={"reason": "unclear", "outcome": "not_reached", ...}
```

1. Açılışta "the call is recorded" eksik; `checks` listesinde olmadığı için hakem yakalamadı, finalde yakalayabilir.
2. Kişi "kocasıyım" dediği halde ajan aynı soruyu tekrar soruyor: `task_message` başkası açarsa ne yapılacağını
   anlatmıyor ve bu durumdan çıkacak bir **transition yok**.
3. Model doğaçlama bir çıkış yapıyor; "Have a good day" çağrıyı kapatıyor. İyi tarafı: borçtan bahsetmedi, kocanın
   ödeme teklifini kabul etmedi (kural 10).
4. `close_call` görüşmeden 3 saniye sonra çalışıyor (lifecycle). Outcome'u model tahmin ediyor: `unclear`. Doğrusu
   `callback`.

**Asıl ders:** Ledger `callbacks: [{2026-10-15, 11:00}]` bekliyor. Bunu yazabilecek tek şey `schedule_callback`, ve bu
tool workflow'da **hiç yok**. Hiçbir prompt bu vakayı geçiremezdi.

| Tür | Örnek | Prompt ile düzelir mi? |
|---|---|---|
| **Yapısal** | Tool yok, node yok, transition yok | **Hayır**, önce yapı değişmeli |
| **Davranışsal** | Cümleyi unutmak, yanlış tarihi kabul etmek | Kısmen; prompt'a bağlı her şey 3/3'te risk |

### PUB-08: "zaten ödedim"

İyi işleyenler:
- Model "twenty-eight April nineteen ninety-three" ifadesini doğru biçimde `1993-04-28`'e çevirdi.
- Geçiş `all_verified == 'true'` koşuluyla deterministik olarak tetiklendi.

Bozulan:
```
6.6s  USER   ... I actually paid it in the app this morning.
7.0s  AGENT  Our records still show a past due amount of 180 for your credit card. When will you be able to pay this?
10.5s AGENT  ... could you provide the date the payment should arrive? If not, I'll have to end the call.
13.1s USER   It should be there today since I paid it this morning
13.1s AGENT  Just to confirm, you are promising a payment of 180 for today, October 14th, 2026. Is that correct?
15.5s USER   Yes, I confirm.
16.0s   [call] create_promise ...
```

`collection` prompt'u modele tek bir hedef veriyor: "söz al". "Zaten ödedi" durumu hiç yazılmamış. Model, kapsanmayan
durumu hedefe doğru **büküyor** ve "bugün orada olmalı" cümlesini bir söze çeviriyor. Bu bir **honesty** ihlali.
Ayrıca baskı var ("If not, I'll have to end the call") ve borç kural 17'ye uygun söylenmedi ("collections team",
"card ending 5512", gecikme günü eksik).

**Kural:** Model, prompt'un kapsamadığı her durumu prompt'taki hedefe doğru büker. Çözüm daha uzun prompt değil;
"zaten ödedi" diyen müşteriyi `create_promise`'ın **hiç bulunmadığı** ayrı bir yola yönlendirmek.

### 10 vaka, dört kök sebep

| Vaka | Kök sebep | Çözen mekanizma |
|---|---|---|
| PUB-01 | SMS teyit cümlesi söylenmedi | `create_promise` post-hook'u + SPEC'ten zorunlu cümle |
| PUB-02 | `schedule_callback` yok, üçüncü kişi yolu yok | Yapı: `who_answered` enum → callback node'u, kodda doğrulama |
| PUB-03 | Outcome `(None, None)`; uygulama/şube söylenmedi; olmayan bir transferden bahsetti | Outcome koddan; `verify_identity` post-hook'u |
| PUB-04 | Müşterinin tarihi (6 Kasım) son tarihi (23 Ekim) aştı | Son tarih kodda; tarih sabitlenmeden önce kodda doğrulanır |
| PUB-05 | Destek ekibi teklif edilmedi; reason `refused` yerine `hardship` olmalıydı | Hardship çıkışı + `transfer_to_agent`; reason koddan |
| PUB-06 | "The rest stays overdue" cümlesi eksik | SPEC'ten prompt kuralı |
| PUB-07 | 26 Ekim tatili kabul edildi | İş günü kontrolü kodda |
| PUB-08 | "Zaten ödedim" söze döndü; `paid` enum'da yok | Intent enum → paid çıkışı; outcome enum'u tool API'den |
| PUB-09 | `transfer_to_agent` yok | Restructuring çıkışı, queue sabitlenmiş |
| PUB-10 | İlk hatadan sonra tekrar denemedi; outcome `(None, None)` | Bir kez tekrar dene (post-hook söyler); outcome koddan |

Özetle:

| Kök sebep | Vakalar |
|---|---|
| Yapı eksik (tool ya da yol yok) | 02, 05, 08, 09 |
| Hesabı model yapıyor | 04, 07 |
| Zorunlu cümle atlanıyor | 01, 06 |
| Durum takibi ve outcome modelde | 03, 10 |

---

## 8. Bizim mimarimiz: hibrit builder

**Yol 1: Her şeyi LLM yapsın** (örnek builder). Claude brief'i okur, JSON'u kendisi yazar, test eder, düzeltir.
Esnek ama her çalıştırmada farklı bir ajan çıkar; 30 dakika sınırı var; Pazar günü test edecek pratik müşteri yok.

**Yol 2: Hibrit** (bizim seçtiğimiz):

```
[1] ingest    brief dosyaları + openapi.json okunur
[2] extract   LLM: brief → SPEC (yapılandırılmış JSON). "Anlama" işini LLM yapar
[3] generate  BİZİM Python kodumuz: SPEC → workflow JSON. "İnşa" işi deterministik
[4] verify    lint + code snippet'lerini yerelde çalıştırma + dry run + chat smoke test
[5] save      freya.save_workflow, export, trace
```

**Neden?** LLM metin anlamakta güçlü ("bu memo şu kuralı değiştiriyor"). Her seferinde aynı ve hatasız 900 satırlık
JSON üretmekte zayıf. LLM'e yalnızca SPEC'i doldurtuyoruz; workflow'u önceden test ettiğimiz şablon kod üretiyor.
SPEC doğruysa ajan da doğru çıkar.

Basit bir SPEC parçası:

```json
{
  "business_days": {"weekdays": [0,1,2,3,4], "holidays": ["..."]},
  "bands": [
    {"min_days": 1, "max_days": 7, "deadline_business_days": 12, "attempts": 1},
    {"min_days": 8, "max_days": 45, "deadline_business_days": 7, "attempts": 2}
  ],
  "identity_questions": [{"field": "date_of_birth", "format": "YYYY-MM-DD"}]
}
```

Generator bu tabloda kaç satır olursa olsun çalışmalı: gizli brief'te 3 band, farklı kimlik soruları, kurumsal
müşteriler çıkabilir. Faz 2'de hayali bir üçüncü banka brief'iyle test edeceğiz.

Taslak workflow (test edilecek bir hipotez, kesin değil):
`setup` (code) → `opening` (TTS + `who_answered` enum) → `third_party` / `identity` → `load_account` (api_request)
→ `account_facts` (code) → `negotiate` → `confirm_and_record` → çıkışlar (paid, dispute, hardship, restructuring,
human, refusal); `close_call` lifecycle tool, outcome ve reason koddan sabitlenir.

---

## 9. Self-test tuzağı

`public-test-set.json` dosyasındaki 13 müşteri **yalnızca Brief A ve B için** var ve mock **bilinmeyen vaka
id'lerini reddediyor** (`{'ok': False, 'error': 'unknown practice case'}`, bizim testimiz). Builder gizli brief
üzerinde `run_cases.py` koşturursa ajanı Brief A'nın kurallarıyla test edip yanlış yöne "düzeltir". Örnek builder'ın
skill'i tam olarak bunu yapıyor.

Bizim son testimiz brief'ten bağımsız:
1. Statik kontroller: her yol `end_call`'a ulaşıyor mu, passthrough node'larda `always` var mı, `null` var mı, kodda
   `{{` var mı, tool alanları ve enum'lar tool API dosyasından mı?
2. Üretilen her Python snippet'ini farklı `now` değerleriyle yerelde çalıştırmak: Cuma günleri, tatil öncesi, ay sonu.
3. Dry run (`validate_workflow`).
4. Chat smoke test: açılış satırı, kimlikten önce açıklama yok, üçüncü kişi yolu.
5. Pratik vakalar yalnızca `--practice A` gibi açık bir bayrakla. Builder brief'in içeriğine bakıp "bu Brief A"
   diye tahmin etmez.

---

## 10. Script'ler tek tek

```
run_cases.py ──► freya.py   (Freya: persona, simülasyon, transkript)
     └────────► score.py   (Mock banka: session, ledger, puanlama)
agent_builder.py ──► Claude Agent SDK (+ eksik SKILL.md)
dev/show_call.py ──► freya.py
```

### 10.1 [freya.py](../freya.py): Freya'nın uzaktan kumandası

Yalnızca standart kütüphane (`urllib`), `pip install` gerekmez.

Anahtar, modül **import edildiği anda** okunur (`HEADERS` satırı). Python içindeyken `os.environ`'u sonradan
değiştirmenin etkisi yok; `source env.sh` Python'dan **önce** yapılmalı.

| Fonksiyon | Ne yapar | Kim kullanır |
|---|---|---|
| `api(method, path, body, **params)` | Ortak kapı: `?a=b` ekler, 120 sn zaman aşımı, HTTP hatasında cevabın ilk 1500 karakteriyle `RuntimeError`, `{data: {result}}` zarfını açar | Herkes |
| `workspace_id()` | Anahtarın gördüğü **ilk** workspace'i bulur, önbelleğe alır; `FREYA_WORKSPACE_ID` varsa onu kullanır | GET ve versiyon çağrıları |
| `create_workflow(name, wf)` | Yeni workflow + agent | `save_workflow` |
| `save_workflow(slot, wf)` | **Slot mantığı:** `.freya-agents.json`'da slot varsa update, yoksa create | Biz, builder |
| `validate_workflow(name, wf)` | `?dryRun=true`, hiçbir şey kaydetmez | verify aşaması |
| `update_workflow(id, wf)` | PUT → GET → model yanlışsa düzeltip tekrar PUT → en yeni versiyonu **publish** | `save_workflow` |
| `export_workflow(id, path)` | Platformdaki workflow'u dosyaya yazar. **Teslim edilecek dosya** | Pazar günü |
| `create_personas(list)` | Simüle müşterileri oluşturur | run_cases |
| `get_iteration(sim, it)` | Sonuçları 100'erli sayfalarla okuyup birleştirir | run_cases |
| `get_call(id)` | Transkript ve sistem olayları | show_call |
| `run_simulation(...)` | Simülasyonu başlatır; workspace meşgulse 30 sn'de bir tekrar dener; 10 sn'de bir durum sorar | run_cases |

- **Slot:** workspace en fazla 200 workflow tutar. `.freya-agents.json` **çalıştırıldığı klasöre** yazılır; komutları
  hep `build-the-builder` içinden çalıştır, yoksa yeni bir workflow oluşur.
- **Neden çift PUT?** Platform kendi `agent_config`'ini ekliyor ve oradaki model etkinliğin modeli olmayabilir.
  Simülasyon override alanlarıyla yine çalışır, ama chat testi ya da gerçek çağrı başlamaz. `freya.py` modeli düzeltip
  bir kez daha kaydeder. Biz `agent_config` göndermeyiz.
- **Neden publish?** PUT yalnızca taslak bir versiyon kaydeder; simülasyon yayınlanmış versiyonu kullanır.
- **Kod okuma dersi:** `run_simulation`'ın docstring'i iki değer dönüyor diyor, kod **üç** değer dönüyor
  (`sim_id, iteration_id, status`). Docstring ile kod çelişirse kod doğrudur.
- Simülasyondaki model rolleri: `assistant`, `routing`, `extraction` = `AGENT_LLM` (bizim ajan);
  `persona` ve `analysis` = Gemini (müşteri ve hakem).

| Ayar | Varsayılan | Not |
|---|---|---|
| `FREYA_API_KEY` | boş | Zorunlu |
| `FREYA_API_URL` | staging | Değiştirme |
| `FREYA_WORKSPACE_ID` | ilk workspace | Anahtar birden fazla workspace görüyorsa |
| `FREYA_SIM_CONCURRENCY` | `5` | Artırırsan koşu kısalır ama model yavaşlarsa müşteriler kapatabilir. Şimdilik 5 |
| `state_file` parametresi | `.freya-agents.json` | Slot dosyası |

**Dokunulmaz:** `AGENT_LLM` ve `FREYA_AGENT_PROVIDER` / `FREYA_AGENT_MODEL` (organizatörlere ait) ve dosyanın kendisi.

### 10.2 [tools/score.py](../tools/score.py): mock bankanın hakemi

**`http(path, body)`:** Adres `FREYA_BANK_HOST` (varsayılan mock). Her isteğe `x-team-key: FREYA_BANK_TEAM_KEY`
ekler; mock session'larını bu anahtarla ayırır, bu yüzden takımca aynı ve sabit olmalı. `body` varsa POST, yoksa GET.
HTTP hatasında fırlatmaz, hatanın JSON gövdesini döner.

**`score_ledger(case, ledger)`:**

| Kontrol | Dikkat |
|---|---|
| `(outcome, reason)` birebir | `promise` için reason **`None`** olmalı; `""` eşleşmez |
| Sözler `(product_id, round(amount,2), date)` | Sıra önemsiz, değerler birebir; 637.5 doğru, 637 yanlış |
| Notlar `(product_id, reason)` | Notun `text` alanı kontrol edilmiyor |
| Callback'ler `(date, time)` | `"11:00"` biçimi; `"11:00:00"` eşleşmez |
| Transferler | Yalnızca queue adları |
| Son tool çağrısı `close_call` mı | Lifecycle tool bunu garanti ediyor |
| Kimlikten önce `get_account`/`create_promise` | Mock reddetse bile çağrı yapılmışsa ihlal |
| Outcome `not_reached`/`no_contact`/`unreached` iken kimlik/hesap tool'u | Gizli brief'te farklı outcome adlarının ipucu |

CLI (command-line interface): `python tools/score.py PUB-08 <customer_id>` tek bir session'ı yeniden puanlar
(yalnızca ledger, hakem yok).

### 10.3 [tools/run_cases.py](../tools/run_cases.py): test koşucusu

| Bayrak | Ne yapar | Örnek |
|---|---|---|
| `agent_id` | Test edilecek **agent** id (workflow id değil) | `96ec991c-...` |
| `--brief A\|B` | Brief'e göre filtre | `--brief B` |
| `--only` | Virgülle ayrılmış vaka listesi | `--only PUB-04,PUB-07` |
| `--reps N` | Her vaka N kez; hepsi geçerse sayılır | `--reps 3` |
| `--style` | `pieces`, `corrects`, `talkative`, `asks_back`, `in_words` | `--style pieces` |
| `--out` | Sonuç JSON'u (call id'ler dahil) | `--out results/x.json` |
| `--cases` | Başka bir vaka dosyası | Kökteki eski dosyayı **verme** |
| `--rerun-if-slow N` | Medyan en yavaş tur > 10 sn ise 5 dk bekleyip tekrarlar | Organizatörler kullanıyor |

Akış:
1. **`persona_for`:** `family == "Third party"` ise müşteri "ben o kişi değilim" rolünü oynar. Değilse `identity`
   alanları cümleye çevrilir; `say` sözlüğünde `postcode`, `birth_year`, `company_number`, `founded_year` da var
   (gizli brief'te farklı kimlik soruları gelebilir ipucu). `successCriteria` vakanın `checks` listesidir.
   Persona kuralları: tarihler kelimeyle söylenir; müşteri yalnızca sorulana cevap verir; doğru read-back'e
   "Yes, I confirm." der; vedaya "Thank you, goodbye." der.
2. **Persona önbelleği:** prompt metninin SHA1 (Secure Hash Algorithm 1) özeti `.personas.json`'da. Metin değişirse
   yeni persona oluşturulur.
3. **`run_once`:** her vaka için mock'ta yeni session ve **temiz ledger**, yeni `customer_id`. PUB-10'daki
   `faults` ayarını mock vaka id'sine göre uygular. Tüm vakalar tek simülasyonda (5 paralel, çağrı başına en fazla
   420 sn). Ledger + hakem kararı birleştirilir. En yavaş tur: her müşteri mesajından sonraki ilk cevaba kadar süre.
4. **`--reps`:** her tekrar ayrı simülasyon, ayrı session. `--reps 3` tam olarak finalin kuralı.
5. **Kayıtlar:** `results/log.jsonl` (koşu başına bir satır, puanın geçmişi) ve `--out` (son tekrarın `rows`'u ve
   tüm tekrarların `all_rows`'u).

**İpucu:** Çıktı pipe'a (`| tee`) gidince Python satırları biriktirir ve log sona kadar boş görünür.
`python -u` ile her satır anında görünür.

### 10.4 [examples/agent_builder.py](../examples/agent_builder.py): örnek builder

"Her şeyi LLM yapsın" yaklaşımı; 50 satırlık kod, asıl bilgi `SKILL.md`'de.

| Ayar | Anlamı |
|---|---|
| `model` | `BUILDER_MODEL`, varsayılan `claude-opus-5-5` |
| `skills=["build-phone-agent"]` | `.claude/skills/` altındaki skill. **Repoda yok** |
| `setting_sources=["project"]` | Yalnızca bu klasörün `.claude/` ayarları. DEV_AGENT_PROMPT'u `CLAUDE.md` yapmamamızın sebebi: yoksa builder'ın her çalışmasında geliştirici talimatları da yüklenirdi |
| `allowed_tools` + `dontAsk` | Dosya okuma/yazma ve Bash, onay istemeden |
| `max_turns=150` | En fazla 150 adım |
| `BASH_DEFAULT_TIMEOUT_MS=900000` | Test koşusu 11 dk sürebildiği için 15 dk'ya kadar izin |

Her mesaj `traces/<zaman>.jsonl`'a yazılır (teslim edilecek trace). Sonda tur sayısı, süre ve maliyet yazdırılır.
Çalıştırmak için `pip install claude-agent-sdk` ve eksik `SKILL.md` gerekiyor. VS Code'daki "1" uyarısı bu paketin
kurulu olmamasından.

### 10.5 [dev/show_call.py](show_call.py): bizim transkript görüntüleyicimiz

```bash
python dev/show_call.py results/base-a.json PUB-02 > results/PUB-02.txt   # vaka id'siyle
python dev/show_call.py <call_id>                                          # call id'siyle
```

| Satır | Anlamı |
|---|---|
| `[node] a -> b` | Konuşma hangi adımda. Ajan yanlış bir şey dediyse önce o anki node'a ve `task_message`'a bak |
| `[call]` / `[done]` | Tool'a giden body ve dönen `data`. Hangi alanı kod sabitledi, hangisini model yazdı, burada görünür |
| `[route] a -> b` | Bir geçişin tetiklendiği an (yalnızca `matched=true` olanlar) |
| `[ERROR]` | Platform hatası |
| `endedReason` | `customer-ended-call` ise müşteri kapatmış; çoğu zaman ajan sustu demektir |

Bir geçişin **neden tetiklenmediğini** görmek için eşleşmeyen dalları ve `variable_table`'ı da yazdırmak gerekecek;
ihtiyaç olunca eklenecek.

### Yapılandırma özeti

| Ne | Nerede | Kural |
|---|---|---|
| Anahtarlar ve adresler | `env.sh` | Git'e asla girmez |
| Test seçenekleri | `run_cases.py` bayrakları | Serbest; öneri: `-u` + `--out` + `tee` |
| Slot adları | `save_workflow('yasar-...')` | `yasar-` önekiyle, takım arkadaşıyla çakışmasın |
| Ajan modeli | `AGENT_LLM` | **Dokunulmaz** |
| Kit dosyaları | `freya.py`, `tools/`, `examples/` | Değişmez; ekler `builder/` veya `dev/` içine |

---

## 11. Kitte bulunan sorunlar ve doğrulanan bilgiler

**Sorunlar:**
1. `.claude/skills/build-phone-agent/SKILL.md` repoda **yok** (gizli klasör olduğu için kopyalanırken düşmüş
   olabilir). Örnek builder onsuz çalışmaz.
2. Bu Windows makinesinde `python3` çalışmıyor (Windows Store kısayolu). Her yerde `python` kullan (3.14.6).
3. İki `public-test-set.json` var. Kökteki eski ve `identity` bloğu yok (13 vakanın hiçbirinde); onun dışında
   aynı. `run_cases.py` doğru olanı (`build-the-builder/` içindekini) zaten varsayılan olarak okuyor.
4. `env.example` `.gitignore`'da **değil**; gerçek anahtar oraya yazılırsa commit'e girer.

**Doğrulanan platform bilgileri (bizim denemelerimiz):**
- Mock bilinmeyen vaka id'lerini reddediyor.
- `base-agent.json` içindeki iki `null` değer create sırasında reddedilmedi (dokümanda "null olmaz" yazıyor).
  Biz yine de `null` üretmeyeceğiz.
- Lifecycle `close_call`'da boş kalan `{{outcome}}` değerini bir model tahmin ediyor; PUB-03 ve PUB-10'da tahmin
  bile yapılamadı ve ledger `(None, None)` gösterdi.
- Lifecycle tool üzerindeki `pre_process_code` çalışıyor (PUB-08'de `reason` silindi).
- `end_call` tool'u `trigger_pattern` ile kapattığında `endedReason` = `assistant-ended-call`; `close_call` yaklaşık
  3 sn sonra çalışıyor.

**Karşılaşılan hata ve çözümü:**
- `401 Invalid API key`: `env.sh` içindeki değer hâlâ şablondaki örnekti (`fak_your_key_here`, 17 karakter).
  Dosyayı kaydet, `source env.sh` komutunu **yeniden** çalıştır.

---

## 12. Komut kopya kağıdı

Hepsi Git Bash'te, `build-the-builder` klasöründe:

```bash
source env.sh

# Bir workflow'u slot'a yükle (ilk seferde create, sonra update + publish)
python -c "import freya,json; print(freya.save_workflow('yasar-base', json.load(open('examples/base-agent.json'))))"

# Test koşuları (önce takım arkadaşına sor: aynı anda tek simülasyon)
mkdir -p results
python -u tools/run_cases.py <agent_id> --brief A --out results/<ad>.json | tee results/<ad>.log
python -u tools/run_cases.py <agent_id> --brief A --reps 3 --out results/<ad>.json | tee results/<ad>.log
python -u tools/run_cases.py <agent_id> --brief A --style pieces --out results/<ad>.json | tee results/<ad>.log
python -u tools/run_cases.py <agent_id> --brief B --only PUB-12 --out results/<ad>.json | tee results/<ad>.log

# Transkript
python dev/show_call.py results/<ad>.json PUB-02 > results/PUB-02.txt

# Mock'a doğrudan soru
python -c "import sys; sys.path.insert(0,'tools'); from score import http; print(http('/v1/practice/sessions', {'case': 'PUB-01'}))"

# Commit öncesi anahtar taraması
git diff --cached | grep -iE "fak_|sk-ant|api_key"
```

Bizim slot'umuz: `yasar-base` → agent_id `96ec991c-9aaf-4c2b-b5aa-7635acc439a4`.

---

## 13. Faz 0 kapanışı ve açık soru

**Özet:**
1. Branch `yasar/hybrid-builder`, `.gitignore` ve journal kuruldu. Commit'lerde Claude satırı yok; branch yerelde.
2. Base agent `yasar-base` slot'unda; Brief A'da **0/10**, model hızlıydı, puan gerçek.
3. Mock bilinmeyen vaka id'lerini reddediyor → gizli brief'te self-test brief'ten bağımsız olmalı.
4. Lifecycle `close_call`'da boş kalan değişkeni model tahmin ediyor ve bazen boş bırakıyor → outcome'u kod yazmalı.
5. Yapısal hatalar prompt'la düzelmez.
6. Eksik: örnek builder'ın skoru (`SKILL.md` lazım). Tüm 13 vakalık koşu (`base-all`) sonuçları bekleniyor.

**Faz sorusu (cevabını bekliyor):**

> PUB-08'i düzeltmek için iki küçük değişiklik yaptığımızı düşün: `close_call` enum'una `paid` ekliyoruz ve
> `collection` prompt'una "müşteri zaten ödediğini söylerse söz alma, ödemenin görünmesinin bir iş günü sürebileceğini
> söyle" cümlesini yazıyoruz. Bu vaka artık **3 koşunun 3'ünü de** güvenle geçer mi? Hangi iki karar hâlâ modelin
> elinde kalır?

Sıradaki: Faz 1, kural matrisi (Brief A ve B'nin her kuralı → onu test eden vaka → onu uygulayan mekanizma).
