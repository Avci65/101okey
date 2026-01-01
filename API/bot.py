import os
import random
import threading
from dotenv import load_dotenv
from flask import Flask, render_template
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from flask import jsonify, request
# Veritabanı fonksiyonları (Aynı klasörde oldukları varsayılıyor)
from database import (
    oyunu_baslat_db, sira_kimde, sirayi_degistir, 
    oyuncu_eli_getir, oyuncu_eli_guncelle, tas_cek_db, 
    el_analiz_et, okey_belirle, oyun_verisi_getir
)

load_dotenv()
TOKEN = "8238405925:AAG8ak1cXItdGW4e5RAK4NXGxX8lXeQBWDs"

# --- FLASK VE TEMPLATE AYARLARI ---
# bot.py'nin bulunduğu dizini alıyoruz (API klasörü)
base_dir = os.path.dirname(os.path.abspath(__file__))
# templates klasörü bot.py ile aynı yerde değil, bir üst dizinde
template_dir = os.path.join(os.path.dirname(base_dir), 'templates')

flask_app = Flask(__name__, template_folder=template_dir)

@flask_app.route('/')
def get_hand():
    user_id = request.args.get('user_id')
    chat_id = request.args.get('chat_id')
    if not user_id or not chat_id:
        return jsonify({"error": "Eksik parametre"}), 400
    
    # Veritabanından gerçek eli çekiyoruz
    el = oyuncu_eli_getir(int(chat_id), int(user_id))
    return jsonify(el if el else [])
def index():
    # Bu satır artık templates/index.html dosyasını bulabilecek
    return render_template('index.html')

def run_flask():
    # Railway 8080 portunu beklediği için varsayılanı 8080 yaptık
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)

# --- OKEY MANTIĞI VE YARDIMCI FONKSİYONLAR ---
def deste_olustur():
    renkler = ['Kırmızı', 'Mavi', 'Siyah', 'Sarı']
    deste = [{'renk': r, 'sayi': s} for r in renkler for s in range(1, 14)] * 2
    deste.extend([{'renk': 'Sahte', 'sayi': 0}] * 2)
    random.shuffle(deste)
    return deste

def el_arayuzu(el, chat_id, user_id, kaynak_idx=None):
    res = oyun_verisi_getir(chat_id)
    gosterge = res[0] if res else None
    okey = okey_belirle(gosterge)
    aktif_sira = sira_kimde(chat_id)
    
    emojiler = {"Kırmızı": "🟥", "Mavi": "🟦", "Siyah": "⬛", "Sarı": "🟨", "Sahte": "🃏", "Boş": "▫️"}
    keyboard = []
    
    row = []
    for i, tas in enumerate(el):
        if tas is None:
            label = "✨" if i == kaynak_idx else emojiler["Boş"]
        else:
            is_okey = okey and tas['renk'] == okey['renk'] and tas['sayi'] == okey['sayi']
            prefix = "⭐" if is_okey else emojiler.get(tas['renk'], '⚪')
            if i == kaynak_idx: prefix = "🎯"
            label = f"{prefix}{tas['sayi'] if tas['sayi'] != 0 else ''}"
        
        row.append(InlineKeyboardButton(label, callback_data=f"sec_{i}"))
        if len(row) == 7:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)

    keyboard.append([InlineKeyboardButton("➖➖➖➖➖ ISTAKA ➖➖➖➖➖", callback_data="none")])
    keyboard.append([
        InlineKeyboardButton("▫️ Boşluk Ekle", callback_data="bosluk"), 
        InlineKeyboardButton("❌ Temizle", callback_data="temizle")
    ])
    keyboard.append([
        InlineKeyboardButton("🃏 Taş Çek", callback_data="cek"), 
        InlineKeyboardButton("📤 Taş At", callback_data="at")
    ])
    
    toplam = el_analiz_et(el, okey)
    durum = "🟢 SIRA SENDE!" if aktif_sira == user_id else "🔴 SIRA BAŞKASINDA"
    okey_bilgi = f"📍 Gösterge: {gosterge['renk']} {gosterge['sayi']} | 🃏 OKEY: {okey['renk']} {okey['sayi']}"
    txt = f"{durum}\n{okey_bilgi}\n📊 Per Toplamı: {toplam}"
    
    return InlineKeyboardMarkup(keyboard), txt

# --- BOT KOMUTLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # En son oluşturduğun aktif Railway URL'si
    webapp_url = "https://worker-production-9405.up.railway.app"
    
    keyboard = [[InlineKeyboardButton("🎴 Oyunu Başlat (Panel)", web_app=WebAppInfo(url=webapp_url))]]
    
    await update.message.reply_text(
        "🚀 101 Okey Plus Paneline Hoş Geldin!\n\nIstakanı yönetmek için butona tıkla:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

lobi = []

async def katil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global lobi
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not any(p['id'] == user.id for p in lobi):
        lobi.append({'id': user.id, 'name': user.first_name})
    await update.message.reply_text(f"✅ {user.first_name} masaya katıldı. ({len(lobi)}/4)")
    
    if len(lobi) == 1:
        deste = deste_olustur()
        gosterge = deste.pop()
        for i, p in enumerate(lobi):
            p['hand'] = [deste.pop() for _ in range(22 if i == 0 else 21)]
        oyunu_baslat_db(chat_id, lobi, deste, gosterge)
        await update.message.reply_text("🚀 Oyun Başladı! /start ile paneli açabilirsiniz.")
        lobi = []

async def el_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    el = oyuncu_eli_getir(chat_id, user_id)
    if el:
        markup, txt = el_arayuzu(el, chat_id, user_id)
        await update.message.reply_text(txt, reply_markup=markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    el = oyuncu_eli_getir(chat_id, user_id)
    aktif_sira = sira_kimde(chat_id)

    if query.data.startswith("sec_") or query.data in ["bosluk", "temizle"]:
        if query.data.startswith("sec_"):
            target_idx = int(query.data.split("_")[1])
            source_idx = context.user_data.get('kaynak_idx')
            if source_idx is None:
                context.user_data['kaynak_idx'] = target_idx
            else:
                el[source_idx], el[target_idx] = el[target_idx], el[source_idx]
                oyuncu_eli_guncelle(chat_id, user_id, el)
                context.user_data['kaynak_idx'] = None
        elif query.data == "bosluk":
            el.append(None)
            oyuncu_eli_guncelle(chat_id, user_id, el)
        elif query.data == "temizle":
            el = [t for t in el if t is not None]
            oyuncu_eli_guncelle(chat_id, user_id, el)
        
        markup, txt = el_arayuzu(el, chat_id, user_id, context.user_data.get('kaynak_idx'))
        await query.edit_message_text(text=txt, reply_markup=markup)
        return

    if user_id != aktif_sira:
        await context.bot.send_message(chat_id=user_id, text="⚠️ Sıra sende değil!")
        return

    if query.data == "cek":
        if len([t for t in el if t]) >= 22:
            await context.bot.send_message(chat_id=user_id, text="⚠️ Elin dolu!")
            return
        cekilen, yeni_el = tas_cek_db(chat_id, user_id)
        context.user_data['tas_cekti'] = True
        markup, txt = el_arayuzu(yeni_el, chat_id, user_id)
        await query.edit_message_text(text=f"🎴 Taş çekildi: {cekilen['renk']} {cekilen['sayi']}\n{txt}", reply_markup=markup)

    elif query.data == "at":
        tas_cekti_mi = context.user_data.get('tas_cekti', False)
        if len(el) < 22 and not tas_cekti_mi:
            await context.bot.send_message(chat_id=user_id, text="⚠️ Önce taş çekmelisin!")
            return
        source_idx = context.user_data.get('kaynak_idx')
        if source_idx is None or el[source_idx] is None:
            await context.bot.send_message(chat_id=user_id, text="⚠️ Atmak için taş seç!")
            return
        
        atilan = el.pop(source_idx)
        temiz_el = [t for t in el if t is not None]
        oyuncu_eli_guncelle(chat_id, user_id, temiz_el)
        sirayi_degistir(chat_id)
        context.user_data['tas_cekti'] = False
        context.user_data['kaynak_idx'] = None
        
        markup, txt = el_arayuzu(temiz_el, chat_id, user_id)
        await query.edit_message_text(text=f"✅ {atilan['renk']} {atilan['sayi']} attın. Sıra geçti!\n{txt}", reply_markup=markup)

if __name__ == '__main__':
    # Flask sunucusunu ayrı kolda başlatıyoruz
    threading.Thread(target=run_flask).start()
    
    # Botu başlatıyoruz
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("katil", katil))
    app.add_handler(CommandHandler("el", el_komutu))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("Bot ve Web App Sunucusu Aktif!")
    app.run_polling()
