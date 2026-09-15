"""
Telegram bot for sending receipts
"""
import asyncio
import config
from utils import generate_receipt_text

def run_telegram_bot():
    """Run Telegram bot in polling mode to handle receipt requests"""
    if not config.TELEGRAM_BOT_TOKEN:
        print("[Telegram] Bot token not configured. Skipping bot initialization.")
        return
    
    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes
        
        async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle /start command and receipt requests"""
            args = context.args
            
            if args and args[0].startswith('receipt_'):
                transaction_id = args[0].replace('receipt_', '')
                
                receipt_data = config.PENDING_RECEIPTS.get(transaction_id)
                
                if not receipt_data:
                    await update.message.reply_text(
                        "❌ Receipt not found or expired. Please request a new one from the kiosk."
                    )
                    return
                
                try:
                    receipt_text = generate_receipt_text(
                        receipt_data['payment'],
                        receipt_data['cart'],
                        receipt_data['total'],
                        receipt_data['store_name']
                    )
                    
                    await update.message.reply_text(receipt_text)
                    
                    del config.PENDING_RECEIPTS[transaction_id]
                    
                except Exception as e:
                    print(f"[Telegram] Error sending receipt: {e}")
                    await update.message.reply_text(
                        "❌ Error sending receipt. Please try again or contact support."
                    )
            else:
                await update.message.reply_text(
                    "👋 Welcome! Scan the QR code at the kiosk to receive your receipt."
                )
        
        application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        
        async def set_bot_username():
            bot = await application.bot.get_me()
            config.TELEGRAM_BOT_USERNAME = bot.username
            print(f"[Telegram] Bot started: @{config.TELEGRAM_BOT_USERNAME}")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(set_bot_username())
        
        application.add_handler(CommandHandler("start", start_command))
        
        # Use manual polling instead of run_polling()
        # run_polling() calls signal.set_wakeup_fd() which crashes on Linux
        # when running in a non-main thread
        print("[Telegram] Starting bot polling...")
        loop.run_until_complete(application.initialize())
        loop.run_until_complete(application.start())
        loop.run_until_complete(application.updater.start_polling(allowed_updates=Update.ALL_TYPES))
        loop.run_forever()
        
    except ImportError:
        print("[Telegram] python-telegram-bot not installed. Run: pip install python-telegram-bot")
    except Exception as e:
        print(f"[Telegram] Bot error: {e}")
