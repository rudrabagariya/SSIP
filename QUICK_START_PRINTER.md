# Quick Start Guide - Thermal Printer

## 1. Install Dependencies
```bash
pip install python-escpos pyusb
```

## 2. Install USB Driver (Windows Only)
- Download Zadig: https://zadig.akeo.ie/
- Run as Administrator
- Options → List All Devices
- Select your thermal printer
- Install WinUSB driver

## 3. Detect Your Printer
```bash
python thermal_printer_setup.py
```

## 4. Test Connection
```bash
python thermal_printer_setup.py --test
```

## 5. Run Your Application
The print button will now work automatically!

---

## USB vs Bluetooth

**✅ USE USB** (Recommended)
- More reliable
- Faster
- No pairing needed
- Simpler setup

**Bluetooth** (Optional)
- Wireless
- Requires pairing
- May have connection issues

---

## Troubleshooting

**Printer not found?**
1. Check USB cable
2. Check power
3. Install WinUSB driver (Zadig)

**Print failed?**
1. Check paper is loaded
2. Check printer is not in error
3. Restart printer

**Need help?**
See THERMAL_PRINTER_GUIDE.md for detailed instructions
        # Run async setup
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(set_bot_username())
        
        # Add handlers
        application.add_handler(CommandHandler("start", start_command))
        
        # Start polling - use run_polling without signal handlers
        # This is needed because on Linux, set_wakeup_fd only works in main thread
        print("[Telegram] Starting bot polling...")
        loop.run_until_complete(application.initialize())
        loop.run_until_complete(application.start())
        loop.run_until_complete(application.updater.start_polling(allowed_updates=Update.ALL_TYPES))
        loop.run_forever()