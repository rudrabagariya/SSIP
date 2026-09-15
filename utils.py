"""
Utility functions for Smart Checkout Kiosk
"""
from datetime import datetime

def format_amount_server(amount_paise: int, lang: str) -> str:
    """Format amount for server-side rendering"""
    amount_inr = amount_paise / 100.0
    text = f"₹{amount_inr:.2f}"
    if lang == 'hi':
        return text.translate(str.maketrans('0123456789', '०१२३४५६७८९'))
    return text

def to_devanagari_digits(s: str) -> str:
    """Convert digits to Devanagari"""
    mapping = str.maketrans('0123456789', '०१२३४५६७८९')
    return s.translate(mapping)

def to_gujarati_digits(s: str) -> str:
    """Convert digits to Gujarati"""
    mapping = str.maketrans('0123456789', '૦૧૨૩૪૫૬૭૮૯')
    return s.translate(mapping)

def generate_receipt_text(payment_data, cart_data, total, store_name):
    """Standalone function to generate receipt text for Telegram"""
    now_str = datetime.now().strftime('%d-%b-%Y %I:%M %p')
    payment_id = payment_data.get('id', 'N/A')
    
    lines = [
        f"🧾 {store_name} 🧾",
        f"================================",
        f"📅 Date: {now_str}",
        f"🆔 Bill No: {payment_id[-8:]}",
        f"💳 Payment ID: {payment_id}",
        f"================================",
        "Items:",
    ]

    for item in cart_data:
        lines.append(f"• {item['name']} x {item['qty']} = ₹{item['price'] * item['qty']:.2f}")

    lines.append(f"================================")
    lines.append(f"💰 TOTAL: ₹{total:.2f}")
    lines.append(f"================================")
    lines.append("Thank you for shopping with us! 🙏")
    
    return "\n".join(lines)
