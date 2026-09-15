"""
Thermal Printer Module for 58mm ESC/POS Printers
Supports USB connection using python-escpos library
"""

try:
    from escpos.printer import Usb, Serial, Network, Win32Raw
    from escpos.exceptions import USBNotFoundError
    ESCPOS_AVAILABLE = True
except ImportError:
    ESCPOS_AVAILABLE = False
    print("[Thermal Printer] python-escpos not installed. Run: pip install python-escpos")

try:
    import win32print
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False

from datetime import datetime
from collections import defaultdict


class ThermalPrinter:
    """Wrapper class for thermal printer operations."""
    
    def __init__(self):
        self.printer = None
        self.connected = False
        self.connection_type = None  # 'usb', 'serial', 'windows'
        
    def connect_windows_printer(self, printer_name=None):
        """
        Connect to thermal printer via Windows printer driver (official Hoin drivers).
        This is the RECOMMENDED method if you have official Hoin drivers installed.
        
        Args:
            printer_name: Name of the printer in Windows (e.g., 'POS58 Printer')
                         If None, will try to auto-detect common thermal printer names
            
        Returns:
            bool: True if connected successfully
        """
        if not ESCPOS_AVAILABLE:
            raise RuntimeError("python-escpos library not installed")
        
        try:
            # If no printer name specified, try to find it
            if printer_name is None:
                printer_name = self._find_windows_printer()
                if not printer_name:
                    print("[Thermal Printer] No thermal printer found in Windows")
                    return False
            
            # Connect using Win32Raw (works with Windows printer drivers)
            self.printer = Win32Raw(printer_name)
            self.connected = True
            self.connection_type = 'windows'
            print(f"[Thermal Printer] Connected to Windows printer: {printer_name}")
            return True
            
        except Exception as e:
            print(f"[Thermal Printer] Windows printer connection failed: {e}")
            self.connected = False
            return False
    
    def _find_windows_printer(self):
        """Find thermal printer in Windows printer list."""
        try:
            if WIN32_AVAILABLE:
                # Get list of all printers
                printers = [printer[2] for printer in win32print.EnumPrinters(2)]
                
                # Common thermal printer names
                thermal_keywords = ['POS58', 'POS-58', 'Hoin', 'HOP', 'Thermal', 'Receipt', 'ESC/POS']
                
                for printer in printers:
                    for keyword in thermal_keywords:
                        if keyword.lower() in printer.lower():
                            print(f"[Thermal Printer] Found: {printer}")
                            return printer
            
            return None
        except Exception as e:
            print(f"[Thermal Printer] Error finding Windows printer: {e}")
            return None
    
    def connect_usb(self, vendor_id=None, product_id=None):
        """
        Connect to thermal printer via raw USB (requires WinUSB driver).
        Only use this if you DON'T have official Hoin drivers installed.
        
        Args:
            vendor_id: USB Vendor ID (hex). If None, will try to auto-detect Hoin printer
            product_id: USB Product ID (hex). If None, will try to auto-detect
            
        Common Hoin printer IDs:
            - 0x0fe6:0x811e (Hoin HOP-H58)
            - 0x0416:0x5011 (Generic ESC/POS)
            
        Returns:
            bool: True if connected successfully
        """
        if not ESCPOS_AVAILABLE:
            raise RuntimeError("python-escpos library not installed")
            
        try:
            # Try common Hoin printer IDs first
            if vendor_id is None or product_id is None:
                common_ids = [
                    (0x0fe6, 0x811e),  # Hoin HOP-H58
                    (0x0416, 0x5011),  # Generic ESC/POS
                    (0x04b8, 0x0e15),  # Epson TM-T20
                ]
                
                for vid, pid in common_ids:
                    try:
                        self.printer = Usb(vid, pid)
                        self.connected = True
                        self.connection_type = 'usb'
                        print(f"[Thermal Printer] Connected via USB (VID: 0x{vid:04x}, PID: 0x{pid:04x})")
                        return True
                    except USBNotFoundError:
                        continue
                        
                raise USBNotFoundError("No thermal printer found. Please check connection.")
            else:
                self.printer = Usb(vendor_id, product_id)
                self.connected = True
                self.connection_type = 'usb'
                print(f"[Thermal Printer] Connected via USB (VID: 0x{vendor_id:04x}, PID: 0x{product_id:04x})")
                return True
                
        except Exception as e:
            print(f"[Thermal Printer] USB connection failed: {e}")
            self.connected = False
            return False
    
    def connect_serial(self, port='COM1', baudrate=9600):
        """
        Connect to thermal printer via Serial/Bluetooth.
        
        Args:
            port: Serial port (e.g., 'COM3' on Windows, '/dev/ttyUSB0' on Linux')
            baudrate: Baud rate (usually 9600 or 115200)
            
        Returns:
            bool: True if connected successfully
        """
        if not ESCPOS_AVAILABLE:
            raise RuntimeError("python-escpos library not installed")
            
        try:
            self.printer = Serial(port, baudrate=baudrate)
            self.connected = True
            self.connection_type = 'serial'
            print(f"[Thermal Printer] Connected via Serial ({port} @ {baudrate})")
            return True
        except Exception as e:
            print(f"[Thermal Printer] Serial connection failed: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """Disconnect from printer."""
        if self.printer:
            try:
                self.printer.close()
            except:
                pass
        self.connected = False
        self.printer = None
    
    def print_receipt(self, payment_data, cart_items, total, store_settings):
        """
        Print a formatted receipt on 58mm thermal paper.
        
        Args:
            payment_data: Dictionary with payment information
            cart_items: List of cart items
            total: Total amount
            store_settings: Dictionary with store information
        """
        if not self.connected or not self.printer:
            raise RuntimeError("Printer not connected")
        
        try:
            # Store information
            store_name = store_settings.get('store_name', 'Smart Store')
            store_address = store_settings.get('store_address', '')
            store_gstin = store_settings.get('store_gstin', '')
            
            # Payment information
            payment_id = payment_data.get('id', 'N/A')
            bill_no = payment_id[-8:] if len(payment_id) >= 8 else payment_id
            date_str = datetime.now().strftime('%d-%b-%Y %I:%M %p')
            
            # --- Header ---
            self.printer.set(align='center', bold=True, width=2, height=2)
            self.printer.text(f"{store_name}\n")
            
            self.printer.set(align='center', bold=False, width=1, height=1)
            if store_address:
                self.printer.text(f"{store_address}\n")
            if store_gstin:
                self.printer.text(f"GSTIN: {store_gstin}\n")
            
            self.printer.set(align='center', bold=True)
            self.printer.text("TAX INVOICE\n")
            self.printer.text("=" * 32 + "\n")
            
            # --- Bill Details ---
            self.printer.set(align='left', bold=False)
            self.printer.text(f"Bill No: {bill_no}\n")
            self.printer.text(f"Date: {date_str}\n")
            self.printer.text(f"Payment ID: {payment_id}\n")
            self.printer.text("=" * 32 + "\n")
            
            # --- Items Header ---
            self.printer.text("ITEM          QTY  RATE   TOTAL\n")
            self.printer.text("-" * 32 + "\n")
            
            # --- Calculate GST ---
            gst_breakup = defaultdict(lambda: {'taxable_amount': 0, 'cgst': 0, 'sgst': 0})
            total_taxable = 0
            total_cgst = 0
            total_sgst = 0
            
            # --- Items ---
            for item in cart_items:
                name = item['name'][:12]  # Truncate long names for 58mm paper
                qty = item['qty']
                price = item['price']
                gst_rate = item.get('gst_percent', 0)
                
                # Calculate taxable value
                taxable_per_unit = price / (1 + (gst_rate / 100.0))
                taxable_total = taxable_per_unit * qty
                item_total = price * qty
                
                # GST calculation
                gst_amount = item_total - taxable_total
                cgst = gst_amount / 2.0
                sgst = gst_amount / 2.0
                
                # Update breakup
                gst_breakup[gst_rate]['taxable_amount'] += taxable_total
                gst_breakup[gst_rate]['cgst'] += cgst
                gst_breakup[gst_rate]['sgst'] += sgst
                total_taxable += taxable_total
                total_cgst += cgst
                total_sgst += sgst
                
                # Print item line (formatted for 58mm)
                self.printer.text(f"{name:<12} {qty:>3} {price:>6.2f} {item_total:>6.2f}\n")
            
            # --- Totals ---
            self.printer.text("-" * 32 + "\n")
            self.printer.text(f"Sub Total:        Rs. {total_taxable:>8.2f}\n")
            self.printer.text(f"CGST:             Rs. {total_cgst:>8.2f}\n")
            self.printer.text(f"SGST:             Rs. {total_sgst:>8.2f}\n")
            self.printer.text("=" * 32 + "\n")
            
            self.printer.set(bold=True, width=2, height=2)
            self.printer.text(f"TOTAL: Rs.{total:>8.2f}\n")
            self.printer.set(bold=False, width=1, height=1)
            self.printer.text("=" * 32 + "\n")
            
            # --- GST Breakup ---
            if len(gst_breakup) > 0:
                self.printer.text("\nGST BREAKUP\n")
                self.printer.text("-" * 32 + "\n")
                self.printer.text("GST%  Taxable  CGST   SGST\n")
                
                for rate in sorted(gst_breakup.keys()):
                    data = gst_breakup[rate]
                    self.printer.text(
                        f"{rate:>4.1f} {data['taxable_amount']:>7.2f} "
                        f"{data['cgst']:>6.2f} {data['sgst']:>6.2f}\n"
                    )
                self.printer.text("-" * 32 + "\n")
            
            # --- Footer ---
            self.printer.set(align='center')
            self.printer.text("\nThank You! Visit Again!\n")
            self.printer.text("=" * 32 + "\n\n\n")
            
            # Cut paper (if supported)
            try:
                self.printer.cut()
            except:
                pass
            
            
            print("[Thermal Printer] Receipt printed successfully")
            return True
            
        except Exception as e:
            print(f"[Thermal Printer] Print failed: {e}")
            raise


def find_usb_printers():
    """
    Utility function to scan for USB thermal printers.
    Returns list of (vendor_id, product_id) tuples.
    """
    try:
        import usb.core
        devices = []
        
        # Common thermal printer class codes
        PRINTER_CLASS = 7
        
        for device in usb.core.find(find_all=True):
            try:
                if device.bDeviceClass == PRINTER_CLASS or \
                   (hasattr(device, 'idVendor') and device.idVendor in [0x0fe6, 0x0416, 0x04b8]):
                    devices.append((device.idVendor, device.idProduct))
                    print(f"Found printer: VID=0x{device.idVendor:04x}, PID=0x{device.idProduct:04x}")
            except:
                continue
                
        return devices
    except ImportError:
        print("pyusb not installed. Run: pip install pyusb")
        return []
    except Exception as e:
        print(f"Error scanning USB devices: {e}")
        return []
