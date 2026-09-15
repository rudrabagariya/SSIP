"""
Quick Test Script for Hoin Thermal Printer with Official Drivers
Run this to verify your printer is working with Windows drivers
"""

from thermal_printer import ThermalPrinter

def test_windows_printer():
    print("=" * 60)
    print("TESTING HOIN THERMAL PRINTER (Windows Driver)")
    print("=" * 60)
    print()
    
    printer = ThermalPrinter()
    
    # Try to connect via Windows printer
    print("Attempting to connect to Windows printer...")
    if printer.connect_windows_printer():
        print("✓ Successfully connected!")
        print(f"  Connection type: {printer.connection_type}")
        print()
        
        # Ask if user wants to print test
        response = input("Print a test receipt? (y/n): ").strip().lower()
        if response == 'y':
            print("Printing test receipt...")
            
            test_payment = {'id': 'TEST_12345678'}
            test_cart = [
                {'name': 'Test Item 1', 'qty': 2, 'price': 50.00, 'gst_percent': 5, 'hsn_code': '1234'},
                {'name': 'Test Item 2', 'qty': 1, 'price': 100.00, 'gst_percent': 12, 'hsn_code': '5678'},
            ]
            test_total = 200.00
            test_settings = {
                'store_name': 'Test Store',
                'store_address': '123 Test Street',
                'store_gstin': '29ABCDE1234F1Z5',
            }
            
            try:
                printer.print_receipt(test_payment, test_cart, test_total, test_settings)
                print("✓ Test receipt printed successfully!")
            except Exception as e:
                print(f"✗ Print failed: {e}")
        
        printer.disconnect()
    else:
        print("✗ Could not connect to printer")
        print()
        print("Troubleshooting:")
        print("  1. Make sure official Hoin drivers are installed")
        print("  2. Check printer is connected and powered on")
        print("  3. Verify printer appears in Windows Devices and Printers")
        print("  4. Try printing a test page from Windows to verify driver works")
    
    print()
    print("=" * 60)

if __name__ == "__main__":
    test_windows_printer()
