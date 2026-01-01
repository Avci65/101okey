import os
import random
import threading
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

# Veritabanı fonksiyonları
from database import (
    oyunu_baslat_db, sira_kimde, sirayi_degistir, 
    oyuncu_eli_getir, oyuncu_eli_guncelle, tas_cek_db, 
    okey_belirle, oyun_verisi_getir, el_analiz_et
)

load_dotenv()
TOKEN = "8238405925:AAG8ak1cXItdGW4e5RAK4NXGxX8lXeQBWDs"

# --- FLASK AYARLARI ---
base_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(os.path.dirname(base_dir), 'templates')

flask_app = Flask(__name__, template_folder=template_dir)

@flask_app.route('/')
def index():
    return render_template('index.html')

@flask_app.route('/get_hand')
def get_hand():
    user_id = request.args.get('user_id')
    chat_id = request.args.get('chat_id')
    
    # 'undefined' hatasını engelleyen kontrol
    if not user_id or user_id == 'undefined' or not chat_id or chat_id == 'undefined':
        return jsonify({"error": "Gecersiz veya eksik parametre"}), 400
    
    try:
        # Veritabanından gerçek eli çekiyoruz
        el = oyuncu_eli_getir(int(chat_id), int(user_id))
        return jsonify(el if el else [])
    except ValueError:
        return jsonify({"error": "ID bilgileri sayisal olmali"}), 400
@flask_app.route('/save_hand', methods=['POST'])
def save_hand():
    data = request.json
    user_id = data.get('user_id')
    chat_id = data.get('chat_id')
    yeni_el = data.get('el')
    
    if not user_id or not chat_id or yeni_el is None:
        return jsonify({"success": False}), 400
        
    try:
        # Kaydederken de veriyi temizleyerek veritabanına gönderiyoruz
        temiz_el = [renk_normalize_et(tas) for tas in yeni_el]
        oyuncu_eli_guncelle(int(chat_id), int(user_id), temiz_el)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
@flask_app.route('/auto_sort', methods=['POST'])
def per_analiz_et(taslar):
    # Bu fonksiyon eldeki en iyi per kombinasyonlarını bulur
    seri_perler = []
    grup_perler = []
    
    # Renklere göre ayır (Seri perler için)
    renkler = {}
    for t in taslar:
        r = t['renk']
        if r not in renkler: renkler[r] = []
        renkler[r].append(t)
    
    # Sayılara göre ayır (Grup perler için)
    sayilar = {}
    for t in taslar:
        s = t['sayi']
        if s not in sayilar: sayilar[s] = []
        sayilar[s].append(t)

    # 1. Seri Perleri Bul (Örn: Mavi 1-2-3)
    final_dizilim = []
    kullanilan_taslar = set()

    for r in renkler:
        liste = sorted(renkler[r], key=lambda x: x['sayi'])
        gecici_per = []
        for i in range(len(liste)):
            if not gecici_per or liste[i]['sayi'] == gecici_per[-1]['sayi'] + 1:
                gecici_per.append(liste[i])
            else:
                if len(gecici_per) >= 3:
                    final_dizilim.append(gecici_per)
                    for p in gecici_per: kullanilan_taslar.add(f"{p['renk']}-{p['sayi']}")
                gecici_per = [liste[i]]
        if len(gecici_per) >= 3:
            final_dizilim.append(gecici_per)
            for p in gecici_per: kullanilan_taslar.add(f"{p['renk']}-{p['sayi']}")

    # 2. Grup Perleri Bul (Örn: Siyah 5 - Mavi 5 - Kırmızı 5)
    for s in sayilar:
        liste = sayilar[s]
        # Aynı renkten taşları filtrele
        benzersiz_renkler = []
        gorulen_renkler = set()
        for t in liste:
            if t['renk'] not in gorulen_renkler and f"{t['renk']}-{t['sayi']}" not in kullanilan_taslar:
                benzersiz_renkler.append(t)
                gorulen_renkler.add(t['renk'])
        
        if len(benzersiz_renkler) >= 3:
            final_dizilim.append(benzersiz_renkler)
            for p in benzersiz_renkler: kullanilan_taslar.add(f"{p['renk']}-{p['sayi']}")

    # Perleri yan yana koy, aralarına birer boşluk (None) ekle
    sonuc_istaka = []
    toplam_puan = 0
    for per in final_dizilim:
        sonuc_istaka.extend(per)
        sonuc_istaka.append(None) # Perler arası boşluk
        toplam_puan += sum(t['sayi'] for t in per)

    # Kalan boş taşları en sona ekle
    kalanlar = [t for t in taslar if f"{t['renk']}-{t['sayi']}" not in kullanilan_taslar]
    sonuc_istaka.extend(kalanlar)
    
    # 30'a tamamla
    while len(sonuc_istaka) < 30:
        sonuc_istaka.append(None)
        
    return sonuc_istaka[:30], toplam_puan

@flask_app.route('/auto_sort', methods=['POST'])
def auto_sort():
    data = request.json
    el = oyuncu_eli_getir(data['chat_id'], data['user_id'])
    taslar = [t for t in el if t is not None]
    
    yeni_el, puan = per_analiz_et(taslar)
    oyuncu_eli_guncelle(data['chat_id'], data['user_id'], yeni_el)
    
    return jsonify({"success": True, "yeni_el": yeni_el, "puan": puan})
def auto_sort():
    data = request.json
    user_id = data.get('user_id')
    chat_id = data.get('chat_id')
    
    if not user_id or not chat_id:
        return jsonify({"success": False}), 400
        
    try:
        # Mevcut eli veritabanından çek
        el = oyuncu_eli_getir(int(chat_id), int(user_id))
        if not el:
            return jsonify({"success": False, "error": "El bulunamadı"}), 404

        # None (boşluk) olanları temizle ve sadece taşları al
        taslar = [t for t in el if t is not None]
        
        # Basit bir dizme mantığı: Önce renge, sonra sayıya göre sırala
        # (Daha gelişmiş 'per' algılama algoritması buraya eklenebilir)
        sirali_taslar = sorted(taslar, key=lambda x: (x['renk'], x['sayi']))
        
        # 30 slotluk yeni ıstakayı oluştur
        yeni_istaka = [None] * 30
        for i, tas in enumerate(sirali_taslar):
            if i < 30:
                yeni_istaka[i] = tas
        
        # Veritabanını güncelle
        oyuncu_eli_guncelle(int(chat_id), int(user_id), yeni_istaka)
        
        return jsonify({"success": True, "yeni_el": yeni_istaka})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
def deste_olustur():
    # Okey renklerini tanımlıyoruz
    renkler = ['Kırmızı', 'Mavi', 'Siyah', 'Sarı']
    # Her renkten 1-13 arası taşlardan 2'şer set oluşturuyoruz (Toplam 104 taş)
    deste = [{'renk': r, 'sayi': s} for r in renkler for s in range(1, 14)] * 2
    # 2 adet Sahte Okey ekliyoruz
    deste.extend([{'renk': 'Sahte', 'sayi': 0}] * 2)
    # Taşları karıştırıyoruz
    random.shuffle(deste)
    return deste
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)
def renk_normalize_et(tas):
    if not tas:
        return None
    
    renk = tas.get('renk', '').lower()
    # Türkçe karakter ve büyük harf sorunlarını sunucu tarafında çözüyoruz
    if 'kirmizi' in renk or 'kırmızı' in renk or 'red' in renk:
        tas['renk'] = 'kirmizi'
    elif 'mavi' in renk or 'blue' in renk:
        tas['renk'] = 'mavi'
    elif 'sari' in renk or 'sarı' in renk or 'yellow' in renk:
        tas['renk'] = 'sari'
    elif 'siyah' in renk or 'black' in renk:
        tas['renk'] = 'siyah'
    
    return tas

# --- BOT KOMUTLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Kendi Railway URL'niz
    webapp_url = "https://worker-production-9405.up.railway.app"
    keyboard = [[InlineKeyboardButton("🎴 Oyun Panelini Aç", web_app=WebAppInfo(url=webapp_url))]]
    
    await update.message.reply_text(
        "🚀 101 Okey Plus Paneline Hoş Geldin!\nIstakanı yönetmek için butona tıkla:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
async def katil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # 1. Kullanıcıyı lobiye ekle veya doğrudan oyunu başlat
    # Not: Basitlik adına tek kişi katıldığında oyunu başlatıyoruz
    deste = deste_olustur()
    gosterge = deste.pop()
    
    # Oyuncu listesini hazırla
    oyuncular = [{'id': user.id, 'name': user.first_name}]
    
    # Her oyuncuya taşlarını dağıt (ilk oyuncuya 22, diğerlerine 21)
    # Burada tek oyuncu olduğu için direkt 22 taş veriyoruz
    hand = [deste.pop() for _ in range(22)]
    oyuncular[0]['hand'] = hand
    
    try:
        # 2. Veritabanında oyunu ve eli oluştur
        oyunu_baslat_db(chat_id, oyuncular, deste, gosterge)
        
        # 3. Kullanıcıya başarı mesajı gönder
        await update.message.reply_text(
            f"✅ {user.first_name}, masaya katıldın ve oyun başlatıldı!\n"
            f"🎴 Taşların dağıtıldı. Şimdi panelden 'Yenile' butonuna basabilirsin."
        )
    except Exception as e:
        print(f"Hata oluştu: {e}")
        await update.message.reply_text("❌ Oyun başlatılırken bir hata oluştu.")

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(lambda u, c: None)) # Boş handler
    # Mevcut CommandHandler satırlarının yanına ekle:
    app.add_handler(CommandHandler("katil", katil))
    
    print("Bot ve Web App Sunucusu Aktif!")
    app.run_polling()