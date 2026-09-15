"""
Thermal Printer Setup Utility
Run this script to find your Hoin thermal printer's USB IDs and test the connection
"""

import sys

def find_printers():
    """Scan for USB thermal printers."""
    print("=" * 60)
    print("THERMAL PRINTER SETUP UTILITY")
    print("=" * 60)
    print()
    
    # Check if required libraries are installed
    try:
        import usb.core
        print("✓ pyusb is installed")
    except ImportError:
        print("✗ pyusb is NOT installed")
        print("  Install with: pip install pyusb")
        return
    
    try:
        from escpos.printer import Usb
        print("✓ python-escpos is installed")
    except ImportError:
        print("✗ python-escpos is NOT installed")
        print("  Install with: pip install python-escpos")
        return
    
    print()
    print("Scanning for USB devices...")
    print("-" * 60)
    
    # Common thermal printer class codes
    PRINTER_CLASS = 7
    found_printers = []
    
    try:
        devices = list(usb.core.find(find_all=True))
        print(f"Found {len(devices)} USB devices total")
        print()
        
        for device in devices:
            try:
                # Check if it's a printer
                is_printer = False
                
                if device.bDeviceClass == PRINTER_CLASS:
                    is_printer = True
                    reason = "Printer class device"
                elif hasattr(device, 'idVendor'):
                    # Check against known thermal printer vendors
                    known_vendors = {
                        0x0fe6: "ICS Advent (Hoin)",
                        0x0416: "Winbond Electronics",
                        0x04b8: "Seiko Epson",
                        0x0519: "Star Micronics",
                        0x154f: "Wincor Nixdorf",
                    }
                    
                    if device.idVendor in known_vendors:
                        is_printer = True
                        reason = f"Known vendor: {known_vendors[device.idVendor]}"
                
                if is_printer:
                    vendor_id = device.idVendor
                    product_id = device.idProduct
                    
                    # Try to get product string
                    try:
                        product_name = usb.util.get_string(device, device.iProduct)
                    except:
                        product_name = "Unknown"
                    
                    # Try to get manufacturer string
                    try:
                        manufacturer = usb.util.get_string(device, device.iManufacturer)
                    except:
                        manufacturer = "Unknown"
                    
                    print(f"✓ FOUND PRINTER:")
                    print(f"  Vendor ID:     0x{vendor_id:04x}")
                    print(f"  Product ID:    0x{product_id:04x}")
                    print(f"  Manufacturer:  {manufacturer}")
                    print(f"  Product:       {product_name}")
                    print(f"  Reason:        {reason}")
                    print()
                    
                    found_printers.append((vendor_id, product_id, manufacturer, product_name))
                    
            except Exception as e:
                # Skip devices we can't access
                continue
        
        if not found_printers:
            print("✗ No thermal printers found")
            print()
            print("Troubleshooting:")
            print("  1. Make sure the printer is connected via USB")
            print("  2. Make sure the printer is powered on")
            print("  3. Try a different USB port")
            print("  4. On Windows, you may need to install libusb drivers")
            print("     Download Zadig: https://zadig.akeo.ie/")
            print("     Use it to install WinUSB driver for your printer")
        else:
            print("=" * 60)
            print("CONFIGURATION")
            print("=" * 60)
            print()
            print("To use the printer in your application, you can either:")
            print()
            print("1. AUTO-DETECT (Recommended):")
            print("   The application will automatically try common printer IDs")
            print()
            print("2. MANUAL CONFIGURATION:")
            print("   If auto-detect doesn't work, add this to your .env file:")
            print()
            for vid, pid, mfr, prod in found_printers:
                print(f"   THERMAL_PRINTER_VID=0x{vid:04x}")
                print(f"   THERMAL_PRINTER_PID=0x{pid:04x}")
                print()
        
    except Exception as e:
        print(f"Error scanning USB devices: {e}")
        print()
        print("On Windows, you may need to install libusb drivers:")
        print("  1. Download Zadig: https://zadig.akeo.ie/")
        print("  2. Run Zadig as Administrator")
        print("  3. Options → List All Devices")
        print("  4. Select your thermal printer from the dropdown")
        print("  5. Select 'WinUSB' as the driver")
        print("  6. Click 'Replace Driver' or 'Install Driver'")
    
    print()
    print("=" * 60)


def test_connection():
    """Test connection to thermal printer."""
    print()
    print("=" * 60)
    print("TESTING PRINTER CONNECTION")
    print("=" * 60)
    print()
    
    try:
        from thermal_printer import ThermalPrinter
        
        printer = ThermalPrinter()
        
        print("Attempting to connect via USB...")
        if printer.connect_usb():
            print("✓ Successfully connected to thermal printer!")
            print()
            
            # Ask if user wants to print a test receipt
            response = input("Print a test receipt? (y/n): ").strip().lower()
            if response == 'y':
                print("Printing test receipt...")
                
                # Test data
                test_payment = {
                    'id': 'TEST_' + '1234567890',
                }
                test_cart = [
                    {'name': 'Test Item 1', 'qty': 2, 'price': 50.00, 'gst_percent': 5, 'hsn_code': '1234'},
                    {'name': 'Test Item 2', 'qty': 1, 'price': 100.00, 'gst_percent': 12, 'hsn_code': '5678'},
                ]
                test_total = 200.00
                test_settings = {
                    'store_name': 'Test Store',
                    'store_address': '123 Test Street, Test City',
                    'store_gstin': '29ABCDE1234F1Z5',
                }
                
                printer.print_receipt(test_payment, test_cart, test_total, test_settings)
                print("✓ Test receipt printed successfully!")
            
            printer.disconnect()
        else:
            print("✗ Could not connect to thermal printer")
            print("  Make sure the printer is connected and powered on")
            
    except ImportError as e:
        print(f"✗ Missing library: {e}")
        print("  Run: pip install -r requirements.txt")
    except Exception as e:
        print(f"✗ Error: {e}")
    
    print()


if __name__ == "__main__":
    find_printers()
    
    # Ask if user wants to test connection
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        test_connection()
    else:
        print()
        print("To test the connection, run:")
        print("  python thermal_printer_setup.py --test")
        print()
