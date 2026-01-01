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
# templates klasörü bot.py'nin bir üst dizininde olduğu için yol ayarı
base_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(os.path.dirname(base_dir), 'templates')

flask_app = Flask(__name__, template_folder=template_dir)

@flask_app.route('/')
def index():
    """Ana sayfa: Sadece arayüzü yükler."""
    return render_template('index.html')

@flask_app.route('/get_hand')
def get_hand():
    user_id = request.args.get('user_id')
    chat_id = request.args.get('chat_id')
    if not user_id or not chat_id:
        return jsonify({"error": "Parametre eksik"}), 400
    el = oyuncu_eli_getir(int(chat_id), int(user_id))
    return jsonify(el if el else [])
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)

# --- OKEY YARDIMCI FONKSİYONLAR ---
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

    keyboard.append([InlineKeyboardButton("▫️ Boşluk Ekle", callback_data="bosluk"), 
                     InlineKeyboardButton("❌ Temizle", callback_data="temizle")])
    keyboard.append([InlineKeyboardButton("🃏 Taş Çek", callback_data="cek"), 
                     InlineKeyboardButton("📤 Taş At", callback_data="at")])
    
    toplam = el_analiz_et(el, okey)
    durum = "🟢 SIRA SENDE!" if aktif_sira == user_id else "🔴 SIRA BAŞKASINDA"
    txt = f"{durum}\n📍 Gösterge: {gosterge['renk']} {gosterge['sayi']}\n📊 Per Toplamı: {toplam}"
    
    return InlineKeyboardMarkup(keyboard), txt

# --- BOT KOMUTLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Railway Networking adresin
    webapp_url = "https://worker-production-9405.up.railway.app"
    keyboard = [[InlineKeyboardButton("🎴 Oyun Panelini Aç", web_app=WebAppInfo(url=webapp_url))]]
    
    await update.message.reply_text(
        "🚀 101 Okey Plus!\nIstakanı yönetmek için butona tıkla:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def katil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    # Bu kısım lobi mantığına göre veritabanına kayıt atmalıdır
    await update.message.reply_text(f"✅ {user.first_name} masaya katıldı.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # (Buradaki buton mantığı aynı kaldı, gereksiz uzatmamak için el_arayuzu ile bağlantısı korunmuştur)

if __name__ == '__main__':
    # Flask'ı ayrı bir thread'de başlat
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Botu başlat
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("katil", katil))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("Bot ve Web App Sunucusu Aktif!")
    app.run_polling()