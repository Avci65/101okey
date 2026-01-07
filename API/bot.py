import os
import random
import threading
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from database import get_connection

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
    """Bir taş grubunun 101 kurallarına göre per olup olmadığını denetler."""
    if any(t["renk"] == "sahte" for t in grup):
     return True
    if len(grup) < 3: 
        return False
    
    # 1. Seri Per Kontrolü (Aynı renk, ardışık sayılar: örn. Mavi 1-2-3)
    is_seri = all(t['renk'] == grup[0]['renk'] for t in grup) and \
              all(grup[i]['sayi'] == grup[i-1]['sayi'] + 1 for i in range(1, len(grup)))
    
    if is_seri:
        return True

    # 2. Grup Per Kontrolü (Aynı sayı, farklı renkler: örn. Siyah 5 - Mavi 5 - Kırmızı 5)
    renkler = [t['renk'] for t in grup]
    is_grup = all(t['sayi'] == grup[0]['sayi'] for t in grup) and \
              len(set(renkler)) == len(renkler)
              
    return is_grup

def per_analiz_et_mantigi(taslar):
    """Taşları en yüksek puanı alacak şekilde dizer ve puanı hesaplar."""
    renkler = {}
    sayilar = {}
    
    # Taşları renklerine ve sayılarına göre gruplandır
    for t in taslar:
        r, s = t['renk'], t['sayi']
        if r not in renkler: renkler[r] = []
        renkler[r].append(t)
        if s not in sayilar: sayilar[s] = []
        sayilar[s].append(t)

    final_dizilim = []
    kullanilan_tas_keyleri = set()

    # ÖNCE SERİ PERLERİ BUL (Genelde daha çok puan getirir)
    for r in renkler:
        liste = sorted(renkler[r], key=lambda x: x['sayi'])
        gecici_per = []
        for i in range(len(liste)):
            if not gecici_per or liste[i]['sayi'] == gecici_per[-1]['sayi'] + 1:
                gecici_per.append(liste[i])
            else:
                if len(gecici_per) >= 3:
                    final_dizilim.append(list(gecici_per))
                    for p in gecici_per: kullanilan_tas_keyleri.add(f"{p['renk']}-{p['sayi']}")
                gecici_per = [liste[i]]
        if len(gecici_per) >= 3:
            final_dizilim.append(list(gecici_per))
            for p in gecici_per: kullanilan_tas_keyleri.add(f"{p['renk']}-{p['sayi']}")

    # SONRA GRUP PERLERİ BUL (Kullanılmayan taşlardan)
    for s in sayilar:
        liste = sayilar[s]
        benzersiz_grup = []
        gorulen_renkler = set()
        for t in liste:
            key = f"{t['renk']}-{t['sayi']}"
            if t['renk'] not in gorulen_renkler and key not in kullanilan_tas_keyleri:
                benzersiz_grup.append(t)
                gorulen_renkler.add(t['renk'])
        
        if len(benzersiz_grup) >= 3:
            final_dizilim.append(benzersiz_grup)
            for p in benzersiz_grup: kullanilan_tas_keyleri.add(f"{p['renk']}-{p['sayi']}")

    # ISTAKAYI OLUŞTUR VE PUANI HESAPLA
    sonuc_istaka = []
    toplam_puan = 0
    
    for per in final_dizilim:
        # Sadece kurallara uyan perlerin puanını topla
        if per_gecerli_mi(per):
            toplam_puan += sum(t['sayi'] for t in per)
        
        sonuc_istaka.extend(per)
        sonuc_istaka.append(None) # Her perden sonra boşluk bırak

    # PER OLMAYAN TAŞLARI SONA EKLE
    kalanlar = [t for t in taslar if f"{t['renk']}-{t['sayi']}" not in kullanilan_tas_keyleri]
    sonuc_istaka.extend(kalanlar)
    
    # 30 SLOTLUK ISTAKAYA TAMAMLA
    while len(sonuc_istaka) < 30:
        sonuc_istaka.append(None)
        
    return sonuc_istaka[:30], toplam_puan

def deste_olustur(okey_tas):
    """
    106 taş üretir:
    - 4 renk × 13 sayı × 2 = 104
    - 2 adet sahte okey (okey taşının aynısı, is_fake_okey=True)
    """

    renkler = ["kirmizi", "mavi", "siyah", "sari"]
    deste = []

    # Normal taşlar
    for renk in renkler:
        for sayi in range(1, 14):
            for _ in range(2):
                deste.append({
                    "renk": renk,
                    "sayi": sayi,
                    "is_okey": False,
                    "is_fake_okey": False
                })

    # 2 adet SAHTE OKEY (okey taşının aynısı)
    for _ in range(2):
        deste.append({
            "renk": okey_tas["renk"],
            "sayi": okey_tas["sayi"],
            "is_okey": False,
            "is_fake_okey": True
        })

    random.shuffle(deste)
    return deste


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
    # Oyuncu zaten çektiyse tekrar çekemez
    if oyun_verisi_getir(chat_id).get("cekildi"):
     return jsonify({"success": False, "error": "Önce taş atmalısın"})

    data = request.json
    chat_id, user_id = data['chat_id'], data['user_id']
    
    # Veritabanından sıradaki taşı çek
    tas = tas_cek_db(int(chat_id), int(user_id))
    
    if tas:
        return jsonify({"success": True, "tas": renk_normalize_et(tas)})
    return jsonify({"success": False, "error": "Deste bitti veya sıra sende değil!"})
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

    cur.execute("""
        SELECT players, gosterge, okey
        FROM games
        WHERE chat_id = %s
    """, (chat_id,))

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({"error": "Oyun bulunamadı"}), 404

    players, gosterge, okey = row

    # Oyuncunun eli
    el = players.get(str(user_id), [])

    # 🟡 GÖSTERGE
    gosterge_tas = {
        "renk": gosterge["renk"],
        "sayi": gosterge["sayi"]
    } if gosterge else None

    # ⭐ GERÇEK OKEY
    okey_tas = {
        "renk": okey["renk"],
        "sayi": okey["sayi"],
        "isOkey": True
    } if okey else None

    # 🎭 EL İÇİNDE OKEY & SAHTE OKEY İŞARETLEME
    yeni_el = []
    for tas in el:
        if not tas:
            yeni_el.append(None)
            continue

        # GERÇEK OKEY
        if (
            okey
            and tas["renk"] == okey["renk"]
            and tas["sayi"] == okey["sayi"]
            and not tas.get("isFakeOkey", False)
        ):
            tas["isOkey"] = True
            tas["isFakeOkey"] = False

        # SAHTE OKEY
        elif tas.get("isFakeOkey", False):
            tas["isOkey"] = False
            tas["isFakeOkey"] = True

        else:
            tas["isOkey"] = False
            tas["isFakeOkey"] = False

        yeni_el.append(tas)

    return jsonify({
        "el": yeni_el,
        "gosterge": gosterge_tas,
        "okey": okey_tas
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


async def katil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    try:
        # 1️⃣ DESTEYİ OLUŞTUR
        deste = deste_olustur()

        # 2️⃣ GÖSTERGEYİ ÇEK
        gosterge = deste.pop()

        # 3️⃣ OKEYİ BELİRLE
        okey = okey_belirle(gosterge)

        # 4️⃣ GERÇEK OKEY TAŞLARINI İŞARETLE
        for tas in deste:
            if tas["renk"] == okey["renk"] and tas["sayi"] == okey["sayi"]:
                tas["isOkey"] = True

        # 5️⃣ ELİ DAĞIT (22 TAŞ)
        hand = [deste.pop() for _ in range(22)]

        oyuncular = [{
            "id": user.id,
            "name": user.first_name,
            "hand": hand
        }]

        # 6️⃣ VERİTABANINA KAYDET
        oyunu_baslat_db(
            chat_id=chat_id,
            oyuncular=oyuncular,
            deste=deste,
            gosterge=gosterge,
            okey=okey
        )

        await update.message.reply_text(
            f"✅ {user.first_name}, oyun başlatıldı!\n"
            f"🎯 Gösterge: {gosterge['renk']} {gosterge['sayi']}\n"
            f"🟡 Okey: {okey['renk']} {okey['sayi']}"
        )

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