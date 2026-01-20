import os
import random
import threading
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from database import get_connection
from database import deste_olustur
from itertools import combinations
# Veritabanı fonksiyonları
from database import (
    oyunu_baslat_db, sira_kimde, sirayi_degistir, 
    oyuncu_eli_getir, oyuncu_eli_guncelle, tas_cek_db, 
    okey_belirle, oyun_verisi_getir, el_analiz_et
)

load_dotenv()
TOKEN = "8238405925:AAG8ak1cXItdGW4e5RAK4NXGxX8lXeQBWDs"

# --- FLASK DOSYA YOLU AYARI ---
# templates klasörü API'nin dışında, ana dizinde olduğu için yolu dinamik buluyoruz
current_dir = os.path.dirname(os.path.abspath(__file__)) # /app/API
root_dir = os.path.dirname(current_dir) # /app
template_path = os.path.join(root_dir, 'templates')

flask_app = Flask(__name__, template_folder=template_path)

# --- YARDIMCI FONKSİYONLAR ---



def per_gecerli_mi(grup):
    """
    101 Okey:
    - Joker SADECE gerçek okeydir (isOkey=True)
    - Sahte okey (isFakeOkey=True) joker değildir
    """
    if not grup or len(grup) < 3:
        return False

    # sadece sağlam dict taşlar
    grup = [t for t in grup if isinstance(t, dict)]
    if len(grup) < 3:
        return False

    jokerler = [t for t in grup if t.get("isOkey")]
    normal = [t for t in grup if not t.get("isOkey")]

    joker_sayisi = len(jokerler)
    if len(normal) == 0:
        return False

    # 🔥 güvenlik: renk/sayi eksikse invalid
    for t in normal:
        if "renk" not in t or "sayi" not in t:
            return False
        if t["renk"] is None or t["sayi"] is None:
            return False

    # Grup per
    sayilar = {t["sayi"] for t in normal}
    if len(sayilar) == 1:
        renkler = [t["renk"] for t in normal]
        if len(set(renkler)) != len(renkler):
            return False
        return True

    # Seri per
    renkler = {t["renk"] for t in normal}
    if len(renkler) != 1:
        return False

    sayilar = sorted(t["sayi"] for t in normal)
    eksik = 0

    for i in range(1, len(sayilar)):
        fark = sayilar[i] - sayilar[i - 1]
        if fark == 0:
            return False
        if fark > 1:
            eksik += (fark - 1)

    return eksik <= joker_sayisi


def per_analiz_et_mantigi(taslar):
    """
    Tüm eldeki taşları analiz eder, en yüksek puanlı per kombinasyonlarını bulur
    ve taşları perler arasına boşluk koyarak dizer.
    """
    n = len(taslar)
    adaylar = []

    # 1. ADIM: Tüm olası per adaylarını (3'lüden 13'lüye kadar) bul
    # 101 Okey kurallarına göre (per_gecerli_mi fonksiyonunu kullanarak)
    for k in range(3, min(14, n + 1)):
        for comb in combinations(taslar, k):
            per = list(comb)
            if per_gecerli_mi(per):
                puan = per_puan_hesapla(per)
                if puan > 0:
                    adaylar.append((per, puan))

    # Puanı yüksek olan adayları başa al (Backtracking hızı için)
    adaylar.sort(key=lambda x: x[1], reverse=True)

    best_score = 0
    best_solution = []

    # 2. ADIM: Backtracking (Geriye Dönük İzleme) ile çakışmayan en iyi seti bul
    def backtrack(idx, used_ids, current_solution, current_score):
        nonlocal best_score, best_solution
        
        # Eğer mevcut puan daha iyiyse kaydet
        if current_score > best_score:
            best_score = current_score
            best_solution = current_solution[:]

        for j in range(idx, len(adaylar)):
            per, puan = adaylar[j]
            # Taşın ID'sini kullanarak aynı fiziksel taşın birden fazla perde girmesini önle
            per_ids = [id(t) for t in per]
            
            if any(x in used_ids for x in per_ids):
                continue

            # Taşı kullanıldı olarak işaretle
            for x in per_ids:
                used_ids.add(x)
            current_solution.append(per)

            # Bir sonraki adayları dene
            backtrack(j + 1, used_ids, current_solution, current_score + puan)

            # Geri al (Backtrack)
            current_solution.pop()
            for x in per_ids:
                used_ids.remove(x)

    # Algoritmayı başlat
    backtrack(0, set(), [], 0)

    # 3. ADIM: Sonuç Listesini Oluşturma (İstaka Dizilimi)
    BOS = {"bos": True}
    yeni_el = []
    final_used_ids = set()

    # Perleri aralarına boşluk koyarak ekle
    for per in best_solution:
        yeni_el.extend(per)
        for t in per:
            final_used_ids.add(id(t))
        yeni_el.append(BOS) # Per bitince boşluk bırak

    # Perlere girmeyen "boşta kalan" taşları sona ekle
    kalanlar = [t for t in taslar if id(t) not in final_used_ids]
    yeni_el.extend(kalanlar)

    return yeni_el, best_score
def per_puan_hesapla(per):
    """
    Basit ve tutarlı puan hesabı:
    - Grup per: len(per) * sayı
    - Seri per: serinin sayıları toplamı (joker boşluğu doldurur)
    Joker sadece isOkey.
    """
    if not per_gecerli_mi(per):
        return 0

    jokerler = [t for t in per if t.get("isOkey")]
    normal = [t for t in per if not t.get("isOkey")]

    if not normal:
        return 0

    sayilar_set = {t["sayi"] for t in normal}
    # Grup per
    if len(sayilar_set) == 1:
        return len(per) * normal[0]["sayi"]

    # Seri per
    normal_sayilar = sorted(t["sayi"] for t in normal)
    start = normal_sayilar[0]
    end = normal_sayilar[-1]

    # Jokerler boşluk doldurur → seri uzunluğunu per uzunluğuna tamamla
    seri_len = end - start + 1
    if seri_len < len(per):
        end += (len(per) - seri_len)

    return sum(range(start, end + 1))


def okey_belirle(gosterge):
    # Gösterge 13 ise okey 1 olur
    if gosterge["sayi"] == 13:
        sayi = 1
    else:
        sayi = gosterge["sayi"] + 1

    return {
        "renk": gosterge["renk"],
        "sayi": sayi
    }

def oyuncu_daha_once_acti_mi(chat_id, user_id):
    oyun = oyun_verisi_getir(chat_id)
    if not oyun:
        return False

    # oyun tuple geliyorsa → henüz açma takibi yok
    if isinstance(oyun, tuple):
        return False

    # dict ise (ileride eklenecek)
    return user_id in oyun.get("acmis_oyuncular", [])



# --- FLASK ROTALARI ---
@flask_app.route('/discard_tile', methods=['POST'])
def discard_tile():
    data = request.json
    chat_id = int(data['chat_id'])
    user_id = int(data['user_id'])
    index = int(data['index'])

    from database import tas_at_db

    tas = tas_at_db(chat_id, user_id, index)

    if tas:
        return jsonify({"success": True, "tas": tas})

    return jsonify({"success": False})


@flask_app.route('/draw_tile', methods=['POST'])
def draw_tile():
    data = request.json or {}

    # Gerekli veriler
    try:
        chat_id = int(data.get('chat_id'))
        user_id = int(data.get('user_id'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Geçersiz chat_id/user_id"}), 400

    oyun = oyun_verisi_getir(chat_id)
    if not oyun:
        return jsonify({"success": False, "error": "Oyun bulunamadı"}), 404

    # Oyuncu zaten çektiyse tekrar çekemez
    if oyun.get("cekildi"):
        return jsonify({"success": False, "error": "Önce taş atmalısın"}), 400

    tas = tas_cek_db(chat_id, user_id)

    if not tas:
        return jsonify({"success": False, "error": "Destede taş kalmadı"}), 400

    # normalize fonksiyonun yoksa direkt tas gönder
    # (UI zaten renkleri render ediyor)
    return jsonify({"success": True, "tas": tas})

@flask_app.route('/')
def index():
    return render_template('index.html')



@flask_app.route("/get_hand", methods=["GET"])
def get_hand():
    user_id = request.args.get("user_id", type=int)
    chat_id = request.args.get("chat_id", type=int)

    if not user_id or not chat_id:
        return jsonify({"error": "Eksik parametre"}), 400

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT players, gosterge, okey FROM games WHERE chat_id = %s", (chat_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({"error": "Oyun bulunamadı"}), 404

    players, gosterge, okey = row
    el = players.get(str(user_id), [])

    yeni_el = []
    for tas in el:
        if not tas:
            yeni_el.append(None)
            continue

        # 1. OKEY KONTROLÜ: Rengi ve sayısı okey ile aynı olan normal taş
        is_okey = (
            okey and 
            tas.get("renk") == okey.get("renk") and 
            tas.get("sayi") == okey.get("sayi") and 
            not tas.get("isFakeOkey")
        )

        # 2. SAHTE OKEY KONTROLÜ: Direkt veritabanındaki flag'e bakıyoruz
        is_fake = tas.get("isFakeOkey", False)

        tas["isOkey"] = is_okey
        tas["isFakeOkey"] = is_fake
        yeni_el.append(tas)

    return jsonify({
        "el": yeni_el,
        "gosterge": gosterge,
        "okey": okey
    })



@flask_app.route('/save_hand', methods=['POST'])
def save_hand():
    data = request.json or {}
    el = data.get('el', [])

    temiz_el = []
    for tas in el:
        if tas is None:
            temiz_el.append({"bos": True})
            continue

        if isinstance(tas, dict) and tas.get("bos") is True:
            temiz_el.append({"bos": True})
            continue

        t2 = renk_normalize_et(tas)
        if t2 and "renk" in t2 and "sayi" in t2:
            temiz_el.append(t2)
        else:
            temiz_el.append({"bos": True})

    oyuncu_eli_guncelle(int(data['chat_id']), int(data['user_id']), temiz_el)
    return jsonify({"success": True})



@flask_app.route('/auto_sort', methods=['POST'])
def auto_sort():
    data = request.json or {}
    chat_id = int(data.get("chat_id"))
    user_id = int(data.get("user_id"))

    el = oyuncu_eli_getir(chat_id, user_id) #
    if not el:
        return jsonify({"success": False, "error": "El boş"})

    # 1. Analiz için sadece gerçek taşları ayıkla
    taslar = []
    for t in el:
        if t and isinstance(t, dict) and not t.get("bos"):
            normalized = renk_normalize_et(t)
            if not normalized.get("bos"):
                taslar.append(normalized)

    # 2. Algoritmayı çalıştır
    yeni_el_listesi, puan = per_analiz_et_mantigi(taslar) #

    # 3. UI için listeyi temizle ve eksikleri "bos" ile doldur
    final_el = []
    for t in yeni_el_listesi:
        final_el.append(renk_normalize_et(t))

    # 4. Orijinal istaka uzunluğunu koru (Genelde 30 slot)
    ISTAKA_BOYUTU = 30 
    if len(final_el) < ISTAKA_BOYUTU:
        final_el.extend([{"bos": True}] * (ISTAKA_BOYUTU - len(final_el)))
    else:
        final_el = final_el[:ISTAKA_BOYUTU]

    # Veritabanını güncelle
    oyuncu_eli_guncelle(chat_id, user_id, final_el) #

    return jsonify({
        "success": True, 
        "yeni_el": final_el, 
        "puan": puan
    })


@flask_app.route('/can_open', methods=['POST'])
def can_open():
    data = request.json
    puan = data.get("puan", 0)

    return jsonify({
        "can_open": puan >= 101,
        "puan": puan
    })



def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)

# --- BOT KOMUTLARI ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    webapp_url = f"https://worker-production-9405.up.railway.app/?chat_id={chat_id}"

    keyboard = [[
        InlineKeyboardButton(
            "🎴 Oyun Panelini Aç",
            web_app=WebAppInfo(url=webapp_url)
        )
    ]]

    await update.message.reply_text(
        "🚀 101 Okey Plus Paneline Hoş Geldin!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
def renk_normalize_et(tas):
    if not tas:
        return {"bos": True}
    
    # Eğer zaten boş işaretliyse dokunma
    if isinstance(tas, dict) and tas.get("bos"):
        return {"bos": True}

    # Temel veri kontrolü
    if not isinstance(tas, dict) or 'sayi' not in tas or 'renk' not in tas:
        return {"bos": True}

    # Sayıyı garantiye al
    try:
        tas["sayi"] = int(tas["sayi"])
    except (ValueError, TypeError):
        return {"bos": True}

    # Renk isimlerini standartlaştır (JS tarafındaki CSS sınıflarıyla uyum için)
    renk_raw = str(tas.get('renk', '')).strip().lower()
    
    # Türkçe karakter dönüşümü
    tr_map = str.maketrans("ıişğüöç", "iisguoc")
    renk_raw = renk_raw.translate(tr_map)

    if 'kirmizi' in renk_raw or 'red' in renk_raw:
        tas['renk'] = 'kirmizi'
    elif 'mavi' in renk_raw or 'blue' in renk_raw:
        tas['renk'] = 'mavi'
    elif 'sari' in renk_raw or 'yellow' in renk_raw:
        tas['renk'] = 'sari'
    elif 'siyah' in renk_raw or 'black' in renk_raw:
        tas['renk'] = 'siyah'
    
    # Bayrakları (flags) garanti altına al
    tas.setdefault("isOkey", False)
    tas.setdefault("isFakeOkey", False)
    
    return tas

def tum_per_adaylarini_bul(el):
    """
    Eldeki tüm geçerli perleri (3-4 taşlık grup veya seri) üretir.
    Joker sadece isOkey=True olan taşlardır.
    """
    adaylar = []

    # 3 ve 4 uzunlukta tüm kombinasyonları dene
    from itertools import combinations

    for k in (3, 4, 5, 6, 7, 8):  # seri daha uzun olabileceği için
        for comb in combinations(el, k):
            grup = list(comb)
            if per_gecerli_mi(grup):
                adaylar.append(grup)

    return adaylar
def max_puanli_per_kombinasyonu(el):
    adaylar = tum_per_adaylarini_bul(el)

    # Her perin puanını hesapla
    perler = [(per, per_puan_hesapla(per)) for per in adaylar]
    perler.sort(key=lambda x: x[1], reverse=True)  # yüksek puanlıları öne al

    best_score = 0
    best_solution = []

    def backtrack(i, used_ids, current, score):
        nonlocal best_score, best_solution

        if score > best_score:
            best_score = score
            best_solution = current[:]

        if i >= len(perler):
            return

        for j in range(i, len(perler)):
            per, puan = perler[j]

            ids = [id(t) for t in per]
            if any(x in used_ids for x in ids):
                continue

            for x in ids:
                used_ids.add(x)

            current.append(per)
            backtrack(j + 1, used_ids, current, score + puan)

            current.pop()
            for x in ids:
                used_ids.remove(x)

    backtrack(0, set(), [], 0)
    return best_solution, best_score


async def katil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    try:
        # 1️⃣ DESTEYİ OLUŞTUR
        deste = deste_olustur()

        # 2️⃣ GÖSTERGEYİ ÇEK
        gosterge = deste.pop()

        # 3️⃣ OKEYİ BELİRLE
        okey_tas = {
            "renk": gosterge["renk"],
            "sayi": gosterge["sayi"] + 1 if gosterge["sayi"] < 13 else 1
        }

        # 4️⃣ SAHTE OKEYLERE KİMLİK VER
        for tas in deste:
            if tas.get("isFakeOkey"):
                continue
            if tas["renk"] == okey_tas["renk"] and tas["sayi"] == okey_tas["sayi"]:
                tas["isOkey"] = True

        # 5️⃣ OYUNCU ELİ
        hand = [deste.pop() for _ in range(22)]

        oyuncular = [{
            "id": user.id,
            "name": user.first_name,
            "hand": hand
        }]

        oyunu_baslat_db(
            chat_id=chat_id,
            oyuncular=oyuncular,
            deste=deste,
            gosterge=gosterge,
            okey=okey_tas
        )

        await update.message.reply_text("✅ Oyun başlatıldı!")

    except Exception as e:
        print("KATIL HATASI:", e)
        await update.message.reply_text("❌ Oyun başlatılırken hata oluştu.")



if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    if os.getenv("RUN_TELEGRAM_BOT", "true") == "true":
      app = ApplicationBuilder().token(TOKEN).build()
      app.add_handler(CommandHandler("start", start))
      app.add_handler(CommandHandler("katil", katil))
      app.run_polling()