"""
Database operations for Smart Checkout Kiosk
"""
import sqlite3
import csv
import os
from datetime import datetime
from config import DB_PATH, STORE_NAME, STORE_UPI_ID

def init_db():
    """Initialize database with required tables"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Note: Products table is created fresh only if it doesn't exist (no DROP)
    # Products table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT UNIQUE, 
            name TEXT, 
            price REAL,
            gst_percent REAL,
            hsn_code TEXT,
            weight_grams REAL,
            quantity INTEGER
        )""")
    
    # Transactions table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, amount INTEGER, status TEXT, razorpay_id TEXT, raw_json TEXT
        )""")
    
    # Settings table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE, value TEXT
        )""")
    
    # Always reload and sync products table from products.csv on startup
    csv_file = os.path.join(os.path.dirname(__file__), "products.csv")
    products_from_csv = load_products_from_csv(csv_file)
    if products_from_csv:
        cur.execute("DELETE FROM products")
        product_list_for_db = [
            (barcode, info['name'], info['price'], info['gst_percent'], 
             info['hsn_code'], info.get('weight_grams', 0), info.get('quantity', 0))
            for barcode, info in products_from_csv.items()
        ]
        cur.executemany(
            "INSERT INTO products (barcode, name, price, gst_percent, hsn_code, weight_grams, quantity) VALUES (?, ?, ?, ?, ?, ?, ?)", 
            product_list_for_db
        )
        print(f"✅ Synced {len(product_list_for_db)} products from '{csv_file}' into SQLite database.")
    
    # Initialize settings if empty
    if cur.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
        settings = [
            ('store_name', STORE_NAME), 
            ('upi_id', STORE_UPI_ID),
            ('razorpay_enabled', 'true'), 
            ('upi_qr_enabled', 'true'),
            ('language', 'en'), 
            ('theme', 'light'),
            ('store_address', '123 Smart Plaza, Near Circuit House, Vadodara, Gujarat 390007'),
            ('store_gstin', '24ABCDE1234F1Z5')
        ]
        cur.executemany("INSERT INTO settings (key, value) VALUES (?, ?)", settings)
    
    conn.commit()
    conn.close()

def load_products_from_csv(filename=None):
    """Load products from CSV file"""
    if filename is None:
        filename = os.path.join(os.path.dirname(__file__), "products.csv")
    products = {}
    try:
        with open(filename, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                barcode = row['barcode']
                products[barcode] = {
                    'name': row['name'],
                    'price': float(row['price']),
                    'gst_percent': float(row.get('gst_percent', 0)),
                    'hsn_code': row.get('hsn_code', ''),
                    'weight_grams': float(row.get('weight_grams', 0)),
                    'quantity': int(row.get('quantity', 0))
                }
    except FileNotFoundError:
        print(f"CSV file {filename} not found. Starting with empty products.")
    except Exception as e:
        print(f"Error loading CSV: {e}")
    return products

# load_products_from_csv_with_quantity was identical to load_products_from_csv — removed.
# Use load_products_from_csv() everywhere instead.

def save_products_to_csv(products, filename=None):
    """Save products with inventory data to CSV file"""
    if filename is None:
        filename = os.path.join(os.path.dirname(__file__), "products.csv")
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['barcode', 'name', 'price', 'gst_percent', 'hsn_code', 'weight_grams', 'quantity']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for barcode, info in products.items():
                writer.writerow({
                    'barcode': barcode,
                    'name': info['name'],
                    'price': info['price'],
                    'gst_percent': info.get('gst_percent', 0),
                    'hsn_code': info.get('hsn_code', ''),
                    'weight_grams': info.get('weight_grams', 0),
                    'quantity': info.get('quantity', 0)
                })
        print("✅ Products saved to CSV file")
    except Exception as e:
        print(f"Error saving to CSV: {e}")

def update_inventory_in_csv(cart, filename="products.csv"):
    """Update inventory quantities in CSV file after a successful purchase"""
    try:
        products = load_products_from_csv(filename)
        
        for item in cart:
            barcode = item['barcode']
            if barcode in products:
                products[barcode]['quantity'] -= item['qty']
                if products[barcode]['quantity'] < 0:
                    products[barcode]['quantity'] = 0
                    print(f"⚠️ Warning: Negative quantity for product {barcode} ({products[barcode]['name']}), reset to 0")
        
        save_products_to_csv(products, filename)
        print("✅ Inventory updated in CSV file")
        return True
    except Exception as e:
        print(f"❌ Error updating inventory: {e}")
        return False

def update_inventory_in_database(cart):
    """Update inventory quantities in database after a successful purchase"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            for item in cart:
                barcode = item['barcode']
                qty_purchased = item['qty']
                
                row = cur.execute("SELECT quantity FROM products WHERE barcode=?", (barcode,)).fetchone()
                if row:
                    current_qty = row[0] if row[0] is not None else 0
                    new_qty = max(0, current_qty - qty_purchased)
                    
                    cur.execute("UPDATE products SET quantity=? WHERE barcode=?", (new_qty, barcode))
                    print(f"✅ Updated {barcode}: {current_qty} → {new_qty}")
            
            conn.commit()
        print("✅ Inventory updated in database")
        return True
    except Exception as e:
        print(f"❌ Error updating database inventory: {e}")
        return False

def get_setting_value(key, default=None):
    """Get a setting value from database"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row[0] if row else default
    except Exception:
        return default

def save_transaction_to_csv(cart, total_amount, payment_id, payment_status, filename="transactions.csv"):
    """
    Save transaction history with all sold items to CSV file
    
    Args:
        cart: List of items in the cart (each item is a dict with barcode, name, price, qty, gst_percent, hsn_code)
        total_amount: Total transaction amount
        payment_id: Razorpay payment ID or transaction reference
        payment_status: Payment status (e.g., 'captured', 'failed')
        filename: CSV file name (default: transactions.csv)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Check if file exists to determine if we need to write headers
        file_exists = os.path.isfile(filename)
        
        # Get current timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Open file in append mode
        with open(filename, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'transaction_date', 
                'transaction_time',
                'payment_id', 
                'payment_status',
                'item_barcode',
                'item_name', 
                'item_price', 
                'item_quantity',
                'item_subtotal',
                'item_gst_percent',
                'item_hsn_code',
                'transaction_total'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            # Write header if file is new
            if not file_exists:
                writer.writeheader()
            
            # Write each item in the cart as a separate row
            for item in cart:
                item_subtotal = item['price'] * item['qty']
                writer.writerow({
                    'transaction_date': timestamp.split()[0],
                    'transaction_time': timestamp.split()[1],
                    'payment_id': payment_id,
                    'payment_status': payment_status,
                    'item_barcode': item['barcode'],
                    'item_name': item['name'],
                    'item_price': f"{item['price']:.2f}",
                    'item_quantity': item['qty'],
                    'item_subtotal': f"{item_subtotal:.2f}",
                    'item_gst_percent': item.get('gst_percent', 0),
                    'item_hsn_code': item.get('hsn_code', ''),
                    'transaction_total': f"{total_amount:.2f}"
                })
        
        print(f"✅ Transaction saved to {filename} - Payment ID: {payment_id}, Total: ₹{total_amount:.2f}, Items: {len(cart)}")
        return True
        
    except Exception as e:
        print(f"❌ Error saving transaction to CSV: {e}")
        return False

def load_transactions_from_csv(filename="transactions.csv"):
    """
    Load all transactions from CSV file
    
    Args:
        filename: CSV file name (default: transactions.csv)
    
    Returns:
        list: List of transaction dictionaries
    """
    transactions = []
    try:
        if not os.path.isfile(filename):
            print(f"Transaction file {filename} not found.")
            return transactions
            
        with open(filename, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                transactions.append(row)
        
        print(f"✅ Loaded {len(transactions)} transaction records from {filename}")
        return transactions
        
    except Exception as e:
        print(f"❌ Error loading transactions from CSV: {e}")
        return transactions

