# Thermal Printer Integration Guide

## Overview
Your billing system now supports thermal printing via USB or Bluetooth for 58mm thermal printers (like your Hoin printer). When users press the **Print** button, the bill will be printed on the thermal printer.

## USB vs Bluetooth - Recommendation

### ✅ **USB is RECOMMENDED** for the following reasons:

1. **Reliability**: USB provides stable, consistent connection without dropouts
2. **Speed**: Faster data transfer than Bluetooth
3. **No Pairing**: No need to pair devices or manage Bluetooth connections
4. **Power**: Can power the printer directly via USB
5. **Simpler Setup**: Easier to configure and troubleshoot
6. **No Interference**: Bluetooth can have issues in busy wireless environments

### Bluetooth Advantages (fewer):
- Wireless/portable setup
- Can connect from multiple devices

**For a point-of-sale kiosk where the printer stays in one place, USB is the clear winner.**

---

## Installation Steps

### 1. Install Required Libraries
```bash
pip install python-escpos pyusb
```

### 2. Connect Your Hoin Printer
1. Connect the printer to your computer via USB cable
2. Power on the printer
3. Windows will automatically detect it as a USB device

### 3. Install USB Drivers (Windows Only)

On Windows, you need to install libusb drivers:

1. **Download Zadig**: https://zadig.akeo.ie/
2. **Run Zadig as Administrator**
3. **Options → List All Devices**
4. **Select your thermal printer** from the dropdown
5. **Select 'WinUSB'** as the driver (use the arrows to select)
6. **Click 'Replace Driver'** or **'Install Driver'**

### 4. Find Your Printer's USB IDs

Run the setup utility to detect your printer:

```bash
python thermal_printer_setup.py
```

This will show you:
- Vendor ID (VID)
- Product ID (PID)
- Manufacturer name
- Product name

Example output:
```
✓ FOUND PRINTER:
  Vendor ID:     0x0fe6
  Product ID:    0x811e
  Manufacturer:  ICS Advent
  Product:       Hoin HOP-H58
```

### 5. Test the Connection

```bash
python thermal_printer_setup.py --test
```

This will:
- Attempt to connect to the printer
- Offer to print a test receipt
- Verify everything is working

---

## How It Works

### Automatic Connection
The application automatically tries to connect to the thermal printer when it starts:

1. Tries common Hoin printer IDs (0x0fe6:0x811e)
2. Tries other common thermal printer IDs
3. If found, connects and enables printing
4. If not found, printing is disabled (Email/Telegram still work)

### Print Button Behavior
When the user clicks **Print** after payment:

1. Checks if printer is connected
2. If not connected, attempts to reconnect
3. Formats the bill for 58mm thermal paper
4. Sends ESC/POS commands to print
5. Shows success/error message

### Receipt Format (58mm)
The thermal receipt includes:
- Store name and address
- GSTIN number
- Tax Invoice header
- Bill number and date
- Payment ID
- Item list with HSN codes
- Quantities, rates, and totals
- GST breakdown (CGST/SGST)
- Grand total
- Thank you message

---

## Configuration

### Auto-Detection (Default)
The system automatically tries these printer IDs:
- `0x0fe6:0x811e` - Hoin HOP-H58
- `0x0416:0x5011` - Generic ESC/POS
- `0x04b8:0x0e15` - Epson TM-T20

### Manual Configuration (Optional)
If auto-detection doesn't work, you can specify the IDs in your `.env` file:

```env
THERMAL_PRINTER_VID=0x0fe6
THERMAL_PRINTER_PID=0x811e
```

Then modify `thermal_printer.py` to read these values.

---

## Troubleshooting

### Printer Not Detected

**Problem**: "No thermal printer found"

**Solutions**:
1. Check USB cable is connected
2. Check printer is powered on
3. Try a different USB port
4. Install WinUSB driver using Zadig (Windows)
5. Run `python thermal_printer_setup.py` to verify

### Print Failed

**Problem**: "Failed to print receipt"

**Solutions**:
1. Check printer has paper loaded
2. Check paper is loaded correctly (thermal side facing print head)
3. Check printer is not in error state (paper jam, cover open)
4. Restart the printer
5. Reconnect USB cable

### Printer Prints Garbage

**Problem**: Random characters or symbols printed

**Solutions**:
1. Your printer may not support ESC/POS commands
2. Check printer model compatibility
3. Try a different printer driver in Zadig

### USB Access Denied (Windows)

**Problem**: "Access denied" or "Permission error"

**Solutions**:
1. Install WinUSB driver using Zadig
2. Run the application as Administrator (not recommended for production)
3. Check Windows Device Manager for driver issues

### Bluetooth Connection (Alternative)

If you prefer Bluetooth:

1. Pair the printer with your computer via Bluetooth settings
2. Note the COM port assigned (e.g., COM5)
3. Modify the code to use Serial connection:

```python
# In _connect_thermal_printer method
if self.thermal_printer.connect_serial('COM5', 9600):
    print("[Thermal Printer] Connected via Bluetooth")
```

---

## Code Structure

### Files Added/Modified

1. **`thermal_printer.py`** (NEW)
   - ThermalPrinter class
   - USB/Serial connection methods
   - Receipt formatting for 58mm paper
   - ESC/POS command generation

2. **`thermal_printer_setup.py`** (NEW)
   - USB device scanner
   - Printer detection utility
   - Connection tester

3. **`ui_main.py`** (MODIFIED)
   - Import thermal printer module
   - Initialize printer in `__init__`
   - Connect print button to `print_thermal_receipt`
   - Auto-connect on startup
   - Disconnect on close

4. **`requirements.txt`** (MODIFIED)
   - Added `python-escpos>=3.0`
   - Added `pyusb>=1.2.1`

---

## Testing Checklist

- [ ] Install dependencies: `pip install python-escpos pyusb`
- [ ] Install WinUSB driver using Zadig (Windows)
- [ ] Run `python thermal_printer_setup.py` to detect printer
- [ ] Run `python thermal_printer_setup.py --test` to test connection
- [ ] Start your application
- [ ] Check console for "[Thermal Printer] Successfully connected via USB"
- [ ] Complete a test transaction
- [ ] Click **Print** button
- [ ] Verify receipt prints correctly
- [ ] Check all items, totals, and GST calculations

---

## Common Hoin Printer Models

| Model | VID | PID | Notes |
|-------|-----|-----|-------|
| HOP-H58 | 0x0fe6 | 0x811e | Most common |
| HOP-E58 | 0x0fe6 | 0x811e | USB + Ethernet |
| Generic ESC/POS | 0x0416 | 0x5011 | Fallback |

---

## Support

If you encounter issues:

1. Run the diagnostic: `python thermal_printer_setup.py`
2. Check the console output for error messages
3. Verify USB drivers are installed correctly
4. Test with a different USB cable/port
5. Ensure printer firmware is up to date

---

## Summary

✅ **USB is the recommended connection method** for reliability and simplicity.

✅ **The integration is complete** - just install drivers and test!

✅ **Print button now works** - automatically formats and prints bills on 58mm thermal paper.

✅ **Fallback options** - Email and Telegram still work if printer is unavailable.
