"""
Flask server for Razorpay payment processing
"""
import json
import sqlite3
from datetime import datetime, timezone
from flask import Flask, request, render_template_string, jsonify
import razorpay

from config import (
    RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, FLASK_PORT, 
    DB_PATH, STORE_NAME, ORDER_CACHE, PENDING_RECEIPTS
)
from database import get_setting_value, save_transaction_to_csv
from utils import format_amount_server

# Initialize Razorpay client
client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# Configure timeout for Razorpay client
if hasattr(client, 'session'):
    from requests.adapters import HTTPAdapter
    adapter = HTTPAdapter()
    client.session.mount('http://', adapter)
    client.session.mount('https://', adapter)
    
    original_request = client.session.request
    def request_with_timeout(*args, **kwargs):
        kwargs.setdefault('timeout', 10)
        return original_request(*args, **kwargs)
    client.session.request = request_with_timeout
    
    # Fix CA bundle for PyInstaller
    import sys
    if getattr(sys, 'frozen', False):
        try:
            import certifi
            client.session.verify = certifi.where()
            print(f"[DEBUG] Set Razorpay client session verify to: {certifi.where()}")
        except Exception as e:
            print(f"Warning: Could not set CA bundle for Razorpay session: {e}")

# Flask app
flask_app = Flask(__name__)

# HTML Templates
CHECKOUT_PAGE = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>{{ labels.title }}</title>
    <script>
      document.addEventListener('DOMContentLoaded', function() {
        const inputs = document.querySelectorAll('input, textarea, select');
        inputs.forEach(input => {
          input.setAttribute('autocomplete', 'off');
          input.setAttribute('autocorrect', 'off');
          input.setAttribute('autocapitalize', 'off');
          input.setAttribute('spellcheck', 'false');
        });
      });
      
      localStorage.clear();
      sessionStorage.clear();
      
      if (window.indexedDB) {
        const dbs = ['razorpay', 'checkout', 'payments'];
        dbs.forEach(dbName => {
          try {
            indexedDB.deleteDatabase(dbName);
          } catch(e) {}
        });
      }
      
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', disableAutofill);
      } else {
        disableAutofill();
      }
      
      function disableAutofill() {
        const allInputs = document.querySelectorAll('input');
        allInputs.forEach(input => {
          input.setAttribute('autocomplete', 'off');
          input.value = '';
        });
      }
    </script>
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <style>
      body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
        padding: 20px;
        background: #f8f9fa;
        color: #333;
        max-width: 500px;
        margin: 0 auto;
      }
      .container {
        background: white;
        border-radius: 12px;
        padding: 25px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
      }
      h3 {
        margin-top: 0;
        color: #2c3e50;
      }
      #pay {
        background: #5469d4;
        color: white;
        border: none;
        padding: 12px 24px;
        border-radius: 6px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        width: 100%;
        transition: background 0.2s;
      }
      #pay:hover {
        background: #4457b4;
      }
      .amount {
        font-size: 24px;
        font-weight: bold;
        color: #27ae60;
        margin: 10px 0;
      }
      input:-webkit-autofill,
      input:-webkit-autofill:hover,
      input:-webkit-autofill:focus,
      input:-webkit-autofill:active {
        -webkit-box-shadow: 0 0 0 30px white inset !important;
      }
    </style>
  </head>
  <body>
    <div class="container">
      <h3>{{ labels.complete_payment }}</h3>
      <p>{{ labels.order }}: <strong>{{ order_id }}</strong></p>
      <p>{{ labels.amount }}: <span class="amount">{{ amount_text }}</span></p>
      <button id="pay">{{ labels.pay_now }}</button>
    </div>
    <script>
      document.getElementById('pay').click();
      
      document.getElementById('pay').onclick = async function(){
        var options = {
          "key": "{{ key_id }}",
          "amount": {{ amount }},
          "currency": "INR",
          "name": "{{ store_name }}",
          "description": "{{ labels.checkout_desc }}",
          "order_id": "{{ order_id }}",
          "modal": {
            "ondismiss": function() {
              window.location = "/fail";
            }
          },
          "handler": function (response){
            var form = new FormData();
            form.append('razorpay_payment_id', response.razorpay_payment_id);
            form.append('razorpay_order_id', response.razorpay_order_id);
            form.append('razorpay_signature', response.razorpay_signature);
            fetch("/verify", {method:'POST', body: form})
              .then(r=>r.json())
              .then(j=>{
                if(j.status && j.status === 'ok'){
                  window.location = "/status/" + response.razorpay_payment_id;
                } else {
                  document.body.innerHTML += "<p style='color:red'>"+"{{ labels.verify_failed }}"+": "+JSON.stringify(j)+"</p>";
                }
              })
              .catch(e=> { document.body.innerHTML += "<p style='color:red'>Error: "+e+"</p>"; });
          }
        };
        var rzp = new Razorpay(options);
        rzp.on('payment.failed', function (response){
          window.location = "/fail";
        });
        rzp.open();
      }
    </script>
  </body>
</html>
"""

STATUS_PAGE = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>{{ labels.title }}</title>
    <style>
      body { font-family: Arial, sans-serif; padding: 20px; text-align: center; }
      .success { color: #28a745; font-size: 24px; font-weight: bold;}
      .failure { color: #dc3545; font-size: 24px; font-weight: bold;}
      .container { max-width: 400px; margin: auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px;}
    </style>
  </head>
  <body>
    <div class="container">
        <h3>{{ labels.payment_status }}</h3>
        <p class="{{ 'success' if payment.status == 'captured' else 'failure' }}">
          {{ labels.success if payment.status == 'captured' else labels.failed }}
        </p>
        <p>{{ labels.id }}: {{ payment.id }}</p>
        <p>{{ labels.amount }}: {{ amount_text }}</p>
        <p>{{ labels.auto_close }}</p>
        <script>setTimeout(() => window.close(), 3000);</script>
    </div>
  </body>
</html>
"""

def get_labels(lang):
    """Get localized labels for payment pages"""
    if lang == 'hi':
        return {
            'title': 'भुगतान',
            'complete_payment': 'भुगतान पूरा करें',
            'order': 'ऑर्डर',
            'amount': 'राशि',
            'pay_now': 'अभी भुगतान करें',
            'checkout_desc': 'चेकआउट भुगतान',
            'verify_failed': 'सत्यापन विफल',
            'payment_status': 'भुगतान स्थिति',
            'success': 'भुगतान सफल',
            'failed': 'भुगतान असफल',
            'id': 'आईडी',
            'auto_close': 'यह विंडो स्वचालित रूप से बंद हो जाएगी।'
        }
    if lang == 'gu':
        return {
            'title': 'ચુકવણી',
            'complete_payment': 'ચુકવણી પૂર્ણ કરો',
            'order': 'ઓર્ડર',
            'amount': 'રકમ',
            'pay_now': 'હમણાં ચૂકવો',
            'checkout_desc': 'ચેકઆઉટ ચુકવણી',
            'verify_failed': 'ચકાસણી નિષ્ફળ',
            'payment_status': 'ચુકવણીની સ્થિતિ',
            'success': 'ચુકવણી સફળ',
            'failed': 'ચુકવણી નિષ્ફળ',
            'id': 'આઈડી',
            'auto_close': 'આ વિન્ડો આપમેળે બંધ થઈ જશે.'
        }
    return {
        'title': 'Razorpay Checkout',
        'complete_payment': 'Complete Payment',
        'order': 'Order',
        'amount': 'Amount',
        'pay_now': 'Pay Now',
        'checkout_desc': 'Checkout Payment',
        'verify_failed': 'Verification failed',
        'payment_status': 'Payment Status',
        'success': 'Payment Successful',
        'failed': 'Payment Failed',
        'id': 'ID',
        'auto_close': 'This window will close automatically.'
    }

@flask_app.route('/checkout/<order_id>')
def checkout(order_id):
    """Checkout page route"""
    order_data = ORDER_CACHE.get(order_id)
    if not order_data:
        return "Order not found", 404
    
    # Extract order from the cached data structure
    order = order_data.get('order') if isinstance(order_data, dict) else order_data
    
    lang = get_setting_value('language', 'en')
    labels = get_labels(lang)
    amount_text = format_amount_server(order['amount'], lang)
    return render_template_string(CHECKOUT_PAGE, order_id=order_id, 
                                 amount=order['amount'], amount_text=amount_text, key_id=RAZORPAY_KEY_ID,
                                 store_name=STORE_NAME, labels=labels)

@flask_app.route('/verify', methods=['POST'])
def verify_payment():
    """Verify payment signature"""
    data = request.form.to_dict()
    required = ("razorpay_payment_id", "razorpay_order_id", "razorpay_signature")
    if not all(k in data for k in required):
        return jsonify({"error": "missing params"}), 400

    try:
        client.utility.verify_payment_signature(data)
        payment = client.payment.fetch(data["razorpay_payment_id"])

        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR IGNORE INTO transactions (date, amount, status, razorpay_id, raw_json)
                VALUES (?, ?, ?, ?, ?)
            """, (datetime.now(timezone.utc).isoformat(), payment.get("amount"), payment.get("status"), payment.get("id"), json.dumps(payment)))
            conn.commit()

        # Save transaction to CSV with sold items
        order_data = ORDER_CACHE.get(data["razorpay_order_id"])
        if order_data and isinstance(order_data, dict) and 'cart' in order_data:
            try:
                save_transaction_to_csv(
                    cart=order_data['cart'],
                    total_amount=order_data['total'],
                    payment_id=payment.get("id"),
                    payment_status=payment.get("status")
                )
            except Exception as csv_error:
                print(f"Warning: Failed to save transaction to CSV: {csv_error}")

        return jsonify({"status": "ok", "payment": payment})

    except Exception as e:
        print("Verification/DB error:", e)
        return jsonify({"error": "signature verification failed or DB error", "detail": str(e)}), 400

@flask_app.route('/status/<payment_id>')
def show_status(payment_id):
    """Show payment status"""
    try:
        payment = client.payment.fetch(payment_id)
    except Exception as e:
        return f"Could not fetch payment: {e}", 404
    lang = get_setting_value('language', 'en')
    labels = get_labels(lang)
    amount_text = format_amount_server(payment.get('amount', 0), lang)
    return render_template_string(STATUS_PAGE, payment=payment, labels=labels, amount_text=amount_text)

@flask_app.route('/fail')
def payment_failed_signal():
    """Payment failed/cancelled page"""
    return "<html><body><h3>Payment failed or cancelled.</h3></body></html>", 200

@flask_app.route('/telegram/receipt/<transaction_id>')
def get_telegram_receipt(transaction_id):
    """API endpoint to retrieve receipt data for Telegram bot"""
    receipt_data = PENDING_RECEIPTS.get(transaction_id)
    if not receipt_data:
        return jsonify({"error": "Receipt not found or expired"}), 404
    return jsonify(receipt_data)

def run_flask():
    """Run Flask server"""
    flask_app.run(host='127.0.0.1', port=FLASK_PORT, debug=False, use_reloader=False)
