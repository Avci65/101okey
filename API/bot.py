import os
import random
import threading
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from database import get_connection
from database import deste_olustur
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
    101 Okey kuralı:
    - Joker sadece GERÇEK OKEY taşıdır (isOkey=True)
    - Sahte okey (isFakeOkey=True) joker değildir
    """
    if not grup or len(grup) < 3:
        return False

    # Joker sadece isOkey
    jokerler = [t for t in grup if t and t.get("isOkey")]
    normal = [t for t in grup if t and not t.get("isOkey")]

    joker_sayisi = len(jokerler)

    # Tüm taşlar joker olamaz (mantıksız)
    if len(normal) == 0:
        return False

    # RENK veya SAYI eksikse per olmaz
    if any(("renk" not in t or "sayi" not in t) for t in normal):
        return False

    # GRUP PER: aynı sayı, farklı renk
    sayilar = {t["sayi"] for t in normal}
    if len(sayilar) == 1:
        renkler = [t["renk"] for t in normal]
        # aynı renkten tekrar olamaz
        if len(set(renkler)) != len(renkler):
            return False
        return True

    # SERİ PER: aynı renk, ardışık sayılar (joker boşluk doldurabilir)
    renkler = {t["renk"] for t in normal}
    if len(renkler) != 1:
        return False

    sirali = sorted([t["sayi"] for t in normal])
    eksik = 0
    for i in range(1, len(sirali)):
        fark = sirali[i] - sirali[i - 1]
        if fark == 0:
            return False  # aynı sayı tekrar olamaz
        if fark > 1:
            eksik += (fark - 1)

    return eksik <= joker_sayisi


def per_analiz_et_mantigi(taslar):
    """Taşları okeyi kullanarak en yüksek puanı alacak şekilde dizer."""
    jokerler = [t for t in taslar if t.get("isOkey") or t.get("isFakeOkey")]
    normal_taslar = [t for t in taslar if not (t.get("isOkey") or t.get("isFakeOkey"))]
    
    kullanilan_id = set() # Hangi taşlar perlere dahil edildi?
    final_perler = []

    # --- A. SERİ PERLERİ BUL (Öncelikli) ---
    renkler = ["kirmizi", "mavi", "siyah", "sari"]
    for r in renkler:
        renk_grubu = sorted([t for t in normal_taslar if t['renk'] == r], key=lambda x: x['sayi'])
        i = 0
        while i < len(renk_grubu):
            gecici_per = [renk_grubu[i]]
            j = i + 1
            while j < len(renk_grubu):
                # Ardışık mı yoksa arada jokerle dolacak boşluk mu var?
                fark = renk_grubu[j]['sayi'] - gecici_per[-1]['sayi']
                if fark == 1:
                    gecici_per.append(renk_grubu[j])
                    j += 1
                elif 1 < fark <= (len(jokerler) + 1): # Boşluk jokerle dolabilir mi?
                    # Bu basitleştirilmiş bir yaklaşımdır
                    gecici_per.append(renk_grubu[j])
                    j += 1
                else:
                    break
            
            if len(gecici_per) >= 2: # En az 2 taş varsa jokerle 3'e tamamlanabilir
                if len(gecici_per) >= 3 or len(jokerler) > 0:
                    # Per geçerli mi kontrol et
                    # (Not: Burada jokerleri geçici olarak ekleyip test etmek gerekebilir)
                    final_perler.append(gecici_per)
                    for t in gecici_per: kullanilan_id.add(id(t))
                    i = j
                else: i += 1
            else: i += 1

    # --- B. GRUP PERLERİ BUL (Kalanlardan) ---
    kalan_taslar = [t for t in normal_taslar if id(t) not in kullanilan_id]
    for s in range(1, 14):
        ayni_sayilar = [t for t in kalan_taslar if t['sayi'] == s]
        # Renkleri benzersiz yap
        benzersiz_grup = []
        gorulen_renkler = set()
        for t in ayni_sayilar:
            if t['renk'] not in gorulen_renkler:
                benzersiz_grup.append(t)
                gorulen_renkler.add(t['renk'])
        
        if len(benzersiz_grup) >= 3 or (len(benzersiz_grup) >= 2 and len(jokerler) > 0):
            final_perler.append(benzersiz_grup)
            for t in benzersiz_grup: kullanilan_id.add(id(t))

    # --- C. JOKERLERİ DAĞIT VE ISTAKAYI OLUŞTUR ---
    istaka = []
    kullanilan_joker_sayisi = 0
    toplam_puan = 0

    for per in final_perler:
        # Per 2 taşlıysa 1 joker ekle
        if len(per) == 2 and kullanilan_joker_sayisi < len(jokerler):
            per.append(jokerler[kullanilan_joker_sayisi])
            kullanilan_joker_sayisi += 1
        
        # Puan hesapla
        if per_gecerli_mi(per):
            # Okeyli perlerde puan hesabı: Joker girdiği yerdeki taşın değerini alır
            puan = sum(t['sayi'] for t in per if not (t.get("isOkey") or t.get("isFakeOkey")))
            # Basit puan hesabı: Joker ortalama bir değer alır veya per mantığına göre eklenir
            toplam_puan += puan 
        
        istaka.extend(per)
        istaka.append(None) # Perler arası boşluk

    # Kalan her şeyi sona ekle
    kalanlar = [t for t in taslar if id(t) not in kullanilan_id and not (t.get("isOkey") or t.get("isFakeOkey"))]
    # Kullanılmayan jokerleri de ekle
    if kullanilan_joker_sayisi < len(jokerler):
        kalanlar.extend(jokerler[kullanilan_joker_sayisi:])
        
    istaka.extend(kalanlar)
    
    # 30'a tamamla
    while len(istaka) < 30:
        istaka.append(None)
        
    return istaka[:30], toplam_puan
def per_puan_hesapla(grup):
    """
    101 Okey puan:
    - Grup per: taş sayısı * sayı
    - Seri per: taşların sayıları toplamı (joker boşluk doldurur)
    Joker sadece gerçek okeydir.
    """
    if not per_gecerli_mi(grup):
        return 0

    jokerler = [t for t in grup if t and t.get("isOkey")]
    normal = [t for t in grup if t and not t.get("isOkey")]

    joker_sayisi = len(jokerler)
    if len(normal) == 0:
        return 0

    # GRUP PER
    sayilar = {t["sayi"] for t in normal}
    if len(sayilar) == 1:
        return len(grup) * normal[0]["sayi"]

    # SERİ PER
    normal_sayilar = sorted([t["sayi"] for t in normal])
    start = normal_sayilar[0]
    end = normal_sayilar[-1]

    # Aradaki boşlukları joker dolduruyor farz edilir
    toplam_uzunluk = (end - start + 1)

    # seri uzunluğu grup uzunluğu olmalı: joker ile tamamla
    if toplam_uzunluk < len(grup):
        end += (len(grup) - toplam_uzunluk)

    # start..end arası toplam
    seri_toplam = sum(range(start, end + 1))
    return seri_toplam


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
    data = request.json
    temiz_el = [renk_normalize_et(tas) for tas in data.get('el', [])]
    oyuncu_eli_guncelle(int(data['chat_id']), int(data['user_id']), temiz_el)
    return jsonify({"success": True})

@flask_app.route('/auto_sort', methods=['POST'])
def auto_sort():
    data = request.json

    el = oyuncu_eli_getir(int(data['chat_id']), int(data['user_id']))
    if not el:
        return jsonify({"success": False, "error": "El boş"})

    taslar = [renk_normalize_et(t) for t in el if t is not None]
    taslar = [t for t in taslar if t is not None]

    yeni_el, puan = per_analiz_et_mantigi(taslar)

    # 🔥 RENK GARANTİSİ
    yeni_el = [renk_normalize_et(t) for t in yeni_el]

    oyuncu_eli_guncelle(int(data['chat_id']), int(data['user_id']), yeni_el)

    return jsonify({
        "success": True,
        "yeni_el": yeni_el,
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
        return None

    if 'renk' not in tas or 'sayi' not in tas:
        return None  # bozuk taşı tamamen at

    renk = str(tas['renk']).lower()

    if 'kirmizi' in renk or 'kırmızı' in renk or 'red' in renk:
        tas['renk'] = 'kirmizi'
    elif 'mavi' in renk or 'blue' in renk:
        tas['renk'] = 'mavi'
    elif 'sari' in renk or 'yellow' in renk:
        tas['renk'] = 'sari'
    elif 'siyah' in renk or 'black' in renk:
        tas['renk'] = 'siyah'
    else:
        return None  # sahte / bozuk

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