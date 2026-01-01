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

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)

# --- BOT KOMUTLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Kendi Railway URL'niz
    webapp_url = "https://worker-production-9405.up.railway.app"
    keyboard = [[InlineKeyboardButton("🎴 Oyun Panelini Aç", web_app=WebAppInfo(url=webapp_url))]]
    
    await update.message.reply_text(
        "🚀 101 Okey Plus Paneline Hoş Geldin!\nIstakanı yönetmek için butona tıkla:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(lambda u, c: None)) # Boş handler
    
    print("Bot ve Web App Sunucusu Aktif!")
    app.run_polling()