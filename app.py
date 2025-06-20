from flask import Flask, render_template, request, redirect, session, url_for, send_file, Response, flash,jsonify,send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
from models import (
    get_user, get_sales, get_products, add_sale, get_user_inventory,
    add_salesperson_stock_bulk, approve_request, reject_request, get_pending_requests_for_user,
    initialize_salesperson_inventory, get_db, get_customers_for_business, generate_batch_number, get_date_range
)
from models import initialize_database
initialize_database()

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import random
import string
import csv
import io
from math import ceil
import psycopg2.extras

app = Flask(__name__)
app.secret_key = 'your-secret-key'

def generate_random_password(length=4):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

@app.route('/')
def home():
    return redirect('/login')

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route("/offline")
def offline_page():
    return send_from_directory("static", "offline.html")

@app.route("/offline_sales_form")
def offline_sales_form():
    return send_from_directory("static", "offline_sales_form.html")


@app.route('/create_super_admin', methods=['GET', 'POST'])
def create_super_admin():
    from werkzeug.security import generate_password_hash
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db()
        cur = conn.cursor()

        # Check if already exists
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            return "Super admin already exists."

        password_hash = generate_password_hash(password)
        cur.execute("""
            INSERT INTO users (username, password, role, is_active)
            VALUES (%s, %s, 'super_admin', TRUE)
        """, (username, password_hash))

        conn.commit()
        return redirect('/login')

    return render_template('setup_superadmin.html')


@app.route('/register_owner', methods=['GET', 'POST'])
def register_owner():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        fullname = request.form['fullname']
        business_name = request.form['business_name']
        business_type = request.form['business_type']
        phone = request.form['phone'] 

        conn = get_db()
        cur = conn.cursor()

        try:
            # Check if username already exists
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                return render_template("register_owner.html", error="Account already exists. Please log in.")

            # Optional: Check if business already exists
            cur.execute("SELECT id FROM businesses WHERE name = %s AND phone = %s", (business_name, phone))
            existing_business = cur.fetchone()
            if existing_business:
                return render_template("register_owner.html", error="This business is already registered. Please log in.")

            # Step 1: Create the business
            cur.execute(
                "INSERT INTO businesses (name, type, phone, is_active) VALUES (%s, %s, %s, TRUE) RETURNING id",
                (business_name, business_type, phone)
            )
            business = cur.fetchone()
            if business is None:
                conn.rollback()
                return "Business creation failed", 500

            business_id = business['id']

            # Step 2: Create the owner user
            password_hash = generate_password_hash(password)
            cur.execute(
                "INSERT INTO users (username, password, role, business_id, is_active) VALUES (%s, %s, 'owner', %s, TRUE)",
                (username, password_hash, business_id)
            )

            conn.commit()
            return redirect('/login')

        except Exception as e:
            conn.rollback()
            print("ERROR:", e)
            return f"An error occurred: {e}", 500

    return render_template('register_owner.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db()
        cur = conn.cursor()

        # Fetch user info and join with business (if applicable)
        cur.execute('''
            SELECT u.*, b.is_active AS business_active
            FROM users u
            LEFT JOIN businesses b ON u.business_id = b.id
            WHERE u.username = %s
        ''', (username,))
        user = cur.fetchone()

        # Validate credentials
        if user and check_password_hash(user['password'], password):
            # Block inactive users
            if not user['is_active']:
                return render_template('login.html', error='Your user account is inactive.')

            # Block inactive business (but allow super_admin to log in)
            if user['role'] != 'super_admin' and not user['business_active']:
                return render_template('login.html', error='Your business has been deactivated.')

            # Set session
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['business_id'] = user['business_id']

            # Role-based redirect
            if user['role'] == 'super_admin':
                return redirect('/admin_dashboard')
            elif user['role'] == 'owner':
                return redirect('/dashboard')
            else:
                return redirect('/dashboard')

        else:
            return render_template('login.html', error='Invalid credentials.')

    return render_template('login.html')


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        phone = request.form.get('phone')

        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT id FROM businesses WHERE phone = %s", (phone,))
        business = cur.fetchone()

        if not business:
            flash("❌ No business registered with that phone number.", "danger")
            return redirect('/forgot_password')

        # ✅ Generate and store OTP
        otp = str(random.randint(100000, 999999))
        expiry = datetime.utcnow() + timedelta(minutes=5)

        cur.execute("""
            UPDATE businesses
            SET reset_token = %s, token_expiry = %s
            WHERE id = %s
        """, (otp, expiry, business['id']))
        conn.commit()

        session['reset_business_id'] = business['id']
        cur.close()
        conn.close()

        # For now, show OTP on screen (replace with SMS integration)
        flash(f"✅ OTP sent to {phone}: {otp}", "success")
        return redirect('/verify_otp')

    return render_template('forgot_password.html')

@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    if 'reset_business_id' not in session:
        return redirect('/forgot_password')

    if request.method == 'POST':
        entered_otp = request.form.get('otp')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT reset_token, token_expiry FROM businesses WHERE id = %s", 
                    (session['reset_business_id'],))
        business = cur.fetchone()

        if not business:
            flash("Business not found.", "danger")
            return redirect('/forgot_password')

        if datetime.utcnow() > business['token_expiry']:
            flash("OTP expired. Try again.", "danger")
            return redirect('/forgot_password')

        if business['reset_token'] != entered_otp:
            flash("Incorrect OTP.", "danger")
            return redirect('/verify_otp')

        if new_password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect('/verify_otp')

        hashed = generate_password_hash(new_password)

        cur.execute("""
            UPDATE businesses
            SET password_hash = %s, reset_token = NULL, token_expiry = NULL
            WHERE id = %s
        """, (hashed, session['reset_business_id']))
        conn.commit()
        cur.close()
        conn.close()

        session.pop('reset_business_id', None)
        flash("✅ Password reset successful.", "success")
        return redirect('/login')

    return render_template('verify_otp.html')


@app.route('/set_business_password', methods=['GET', 'POST'])
def set_business_password():
    business_id = session.get('otp_business_id')
    if not business_id:
        flash("⚠️ Session expired or invalid access.", "danger")
        return redirect('/login')

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if new_password != confirm_password:
            flash("❌ Passwords do not match.", "danger")
            return redirect(request.url)

        hashed = generate_password_hash(new_password)

        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE businesses SET password_hash = %s WHERE id = %s", (hashed, business_id))
        conn.commit()
        cur.close()
        conn.close()

        session.pop('otp_business_id', None)

        flash("✅ Password set successfully. You can now log in.", "success")
        return redirect('/login')

    return render_template('reset_password.html')

@app.route('/setup_superadmin', methods=['GET', 'POST'])
def setup_superadmin():
    conn = get_db()
    cur = conn.cursor()

    # Check if users already exist
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]

    if count > 0:
        return "Super admin already exists. Setup is locked.", 403

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_pw = generate_password_hash(password)

        cur.execute('''
            INSERT INTO users (username, password, role, business_id, is_active)
            VALUES (%s, %s, 'super_admin', NULL, TRUE)
        ''', (username, hashed_pw))

        conn.commit()
        return redirect('/login')

    return render_template('setup_superadmin.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()
    user_id = session['user_id']
    role = session['role']

    if role == 'owner':
        # Get business_id for owner
        cur.execute("SELECT business_id FROM users WHERE id = %s", (user_id,))
        business = cur.fetchone()
        if not business:
            return "Business not found", 400
        business_id = business['business_id']
        session['business_id'] = business_id

        # Count branches (users in the same business)
        cur.execute("SELECT COUNT(*) AS branch_count FROM users WHERE business_id = %s", (business_id,))
        result = cur.fetchone()
        session['branch_count'] = result['branch_count'] if result else 0


        # Fetch owner dashboard data
        cur.execute("""
            SELECT 
                s.batch_no AS batch_number,
                MIN(s.date) AS date,
                u.username AS salesperson_name,
                s.payment_method,
                SUM(s.quantity) AS total_quantity,
                SUM(s.quantity * s.price) AS total_price
            FROM sales s
            JOIN users u ON s.salesperson_id = u.id
            JOIN products p ON s.product_id = p.id
            WHERE p.business_id = %s
            GROUP BY s.batch_no, u.username, s.payment_method
            ORDER BY MIN(s.date) DESC
            LIMIT 15
        """, (business_id,))
        sales = cur.fetchall()

        for sale in sales:
            if sale['date']:
                sale['date'] = sale['date'].replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Africa/Kampala"))

        return render_template('dashboard_owner.html', sales=sales)

    else:
        # For salesperson: get sales + inventory
        cur.execute("""
            SELECT 
                s.batch_no AS batch_number,
                MIN(s.date) AS date,
                s.payment_method,
                SUM(s.quantity) AS total_quantity,
                SUM(s.quantity * s.price) AS total_price
            FROM sales s
            JOIN products p ON s.product_id = p.id
            WHERE s.salesperson_id = %s
            GROUP BY s.batch_no, s.payment_method
            ORDER BY MIN(s.date) DESC
            LIMIT 15
        """, (user_id,))
        sales = cur.fetchall()

        for sale in sales:
            if sale['date']:
                sale['date'] = sale['date'].replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Africa/Kampala"))
        # Get inventory
        cur.execute('''
            SELECT ui.*, 
                   p.name AS product_name, 
                   p.category
            FROM user_inventory ui
            JOIN products p ON ui.product_id = p.id
            WHERE ui.user_id = %s
        ''', (user_id,))
        inventory = cur.fetchall()

        # Count users in the business
        cur.execute("SELECT business_id FROM users WHERE id = %s", (user_id,))
        business_id = cur.fetchone()['business_id']
        session['business_id'] = business_id

        # Count branches (users in the same business)
        cur.execute("SELECT COUNT(*) AS branch_count FROM users WHERE business_id = %s", (business_id,))
        result = cur.fetchone()
        session['branch_count'] = result['branch_count'] if result and 'branch_count' in result else 0


        return render_template('dashboard_sales.html', inventory=inventory, sales=sales, username=session['username'])

@app.route('/switch_role', methods=['POST'])
def switch_role():
    if 'user_id' not in session or 'role' not in session:
        flash("Session expired. Please log in again.")
        return redirect('/login')

    user_id = session['user_id']
    current_role = session['role']
    business_id = session.get('business_id')
    branch_count = session.get('branch_count', 0)

    if branch_count != 1:
        flash("Cannot switch roles when multiple users exist.")
        return redirect('/dashboard')

    # Toggle the role
    new_role = 'salesperson' if current_role == 'owner' else 'owner'

    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET role = %s WHERE id = %s", (new_role, user_id))
    conn.commit()

    # Update session
    session['role'] = new_role
    flash(f"Switched role to {new_role.capitalize()}.")

    return redirect('/dashboard')

@app.route('/record_sale', methods=['GET'])
def record_sale():
    if 'user_id' not in session or session['role'] != 'salesperson':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    user_id = session['user_id']

    # Get the salesperson's inventory
    inventory = get_user_inventory(user_id)

    # Get distinct categories (if needed for product filtering)
    cur.execute("""
        SELECT DISTINCT category 
        FROM products 
        WHERE category IS NOT NULL 
        ORDER BY category
    """)
    categories = [row['category'] for row in cur.fetchall()]

    # Get the salesperson's business ID
    cur.execute("SELECT business_id FROM users WHERE id = %s", (user_id,))
    result = cur.fetchone()
    business_id = result['business_id'] if result else None

    # ✅ Only fetch active customers from the same business
    customers = []
    if business_id:
        cur.execute("""
            SELECT id, name 
            FROM customers 
            WHERE business_id = %s AND is_active = TRUE 
            ORDER BY name
        """, (business_id,))
        customers = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("record_sale.html", 
                           products=inventory, 
                           categories=categories, 
                           customers=customers)


@app.route('/submit_sale', methods=['POST'])
def submit_sale():
    if 'user_id' not in session or session['role'] != 'salesperson':
        return jsonify({"error": "Unauthorized"}), 403

    try:
        data = request.get_json()  # ✅ Properly parse JSON request
        cart_data = data.get('cart_data')
        payment_method = data.get('payment_method')
        customer_id = data.get('customer_id') or None
        due_date = data.get('due_date') or None

        if not cart_data or not payment_method:
            return "Missing sale data or payment method", 400

        items = json.loads(cart_data)
        user_id = session['user_id']

        conn = get_db()
        cur = conn.cursor()

        try:
            # Get user info
            cur.execute("SELECT username, business_id FROM users WHERE id = %s", (user_id,))
            user_row = cur.fetchone()
            if not user_row:
                raise ValueError("❌ User not found.")
            username = user_row['username']
            business_id = user_row['business_id']

            # Generate batch number
            initials = ''.join(part[0] for part in username.strip().split()).upper()
            date_str = datetime.now().strftime("%Y%m%d")
            cur.execute("SELECT COUNT(DISTINCT batch_no) FROM sales WHERE batch_no LIKE %s", (f"{initials}_{date_str}_%",))
            count_row = cur.fetchone()
            count = list(count_row.values())[0] + 1 if count_row else 1
            batch_no = f"{initials}_{date_str}_{count:03d}"

            for item in items:
                product_id = int(item['productId'])
                quantity = int(item['quantity'])
                price = float(item['price'])

                # Verify product belongs to business
                cur.execute("SELECT id FROM products WHERE id = %s AND business_id = %s", (product_id, business_id))
                if not cur.fetchone():
                    raise ValueError("❌ Product not authorized for this business")

                # Update inventory
                cur.execute("""
                    UPDATE user_inventory
                    SET quantity = quantity - %s
                    WHERE user_id = %s AND product_id = %s
                """, (quantity, user_id, product_id))

                amount_paid = quantity * price if payment_method == 'Cash' else 0
                payment_status = 'paid' if payment_method == 'Cash' else 'unpaid'

                # Insert sale
                if payment_method == 'Cash':
                    cur.execute("""
                        INSERT INTO sales (
                            product_id, quantity, salesperson_id, price, payment_method,
                            date, amount_paid, payment_status, business_id, batch_no
                        ) VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        product_id, quantity, user_id, price, payment_method,
                        amount_paid, payment_status, business_id, batch_no
                    ))
                else:
                    if not customer_id:
                        raise ValueError("❌ Credit sale missing customer.")
                    cur.execute("""
                        INSERT INTO sales (
                            product_id, quantity, salesperson_id, price, payment_method,
                            date, amount_paid, payment_status, business_id, customer_id, batch_no
                        ) VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        product_id, quantity, user_id, price, payment_method,
                        amount_paid, payment_status, business_id, int(customer_id), batch_no
                    ))

                sale_row = cur.fetchone()
                if not sale_row:
                    raise ValueError("❌ Failed to fetch inserted sale ID.")
                sale_id = sale_row['id']

                # Handle credit
                if payment_method == 'Credit' and customer_id:
                    total_amount = quantity * price
                    cur.execute("""
                        INSERT INTO credit_sales (
                            sale_id, customer_id, amount, balance, due_date, status
                        ) VALUES (%s, %s, %s, %s, %s, 'unpaid')
                    """, (
                        sale_id, int(customer_id), total_amount, total_amount, due_date
                    ))

            conn.commit()
            return jsonify({"success": True, "batch_no": batch_no})

        except Exception as e:
            conn.rollback()
            import traceback
            print("❌ Sale Submission Error:", traceback.format_exc())
            return str(e), 400

        finally:
            cur.close()
            conn.close()

    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/batch_sales/<batch_no>')
def batch_sales(batch_no):
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()
    business_id = session.get('business_id')

    # Fetch sales with related product and customer info
    cur.execute("""
        SELECT s.*, 
               p.name AS product_name,
               c.name AS customer_name
        FROM sales s
        JOIN products p ON s.product_id = p.id
        LEFT JOIN customers c ON s.customer_id = c.id
        WHERE s.batch_no = %s AND s.business_id = %s
        ORDER BY s.date
    """, (batch_no, business_id))

    rows = cur.fetchall()

    sales = []
    for s in rows:
        # For each sale, calculate how much has been returned (exclude self-return lines)
        if not s['is_return']:
            cur.execute("""
                SELECT COALESCE(SUM(quantity), 0) AS returned_quantity
                FROM sales
                WHERE is_return = TRUE AND original_sale_id = %s
            """, (s['id'],))
            returned = cur.fetchone()['returned_quantity']
        else:
            returned = s['quantity']  # return rows just show own quantity

        s['returned_quantity'] = returned
        sales.append(s)

    cur.close()
    conn.close()

    return render_template('batch_sales.html', sales=sales, batch_number=batch_no)

@app.route('/print_receipt/<batch_no>')
def print_receipt(batch_no):
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    user_id = session['user_id']
    business_id = session.get('business_id')

    # 🔄 Get all sales for the batch (including returns)
    cur.execute("""
        SELECT s.*, p.name AS product_name
        FROM sales s
        JOIN products p ON s.product_id = p.id
        WHERE s.batch_no = %s AND s.business_id = %s
        ORDER BY s.date
    """, (batch_no, business_id))
    sales = cur.fetchall()

    # 🧮 Summarize products
    product_summary = {}
    grand_total = 0
    for s in sales:
        name = s['product_name']
        qty = s['quantity']
        price = s['price']
        if name not in product_summary:
            product_summary[name] = {'quantity': 0, 'price': price, 'total': 0}
        product_summary[name]['quantity'] += qty
        product_summary[name]['total'] += qty * price

    # 🚫 Remove fully returned items
    clean_summary = {}
    for name, data in product_summary.items():
        if data['quantity'] > 0:
            clean_summary[name] = data
            grand_total += data['total']

    # 🏷️ Get business name and phone
    cur.execute("SELECT name, phone FROM businesses WHERE id = %s", (business_id,))
    business_row = cur.fetchone()
    business_name = business_row['name']
    business_phone = business_row['phone']

    # 👤 Use salesperson username as branch name
    if sales:
        salesperson_id = sales[0]['salesperson_id']
        cur.execute("SELECT username FROM users WHERE id = %s", (salesperson_id,))
        branch_row = cur.fetchone()
        branch_name = branch_row['username'] if branch_row else "Unknown"
    else:
        branch_name = "Unknown"

    cur.close()
    conn.close()

    return render_template(
        'receipt.html',
        sales=sales,
        batch_number=batch_no,
        business_name=business_name,
        business_phone=business_phone,
        branch_name=branch_name,
        product_summary=clean_summary,
        grand_total=grand_total
    )


@app.route("/record_expense", methods=["GET", "POST"])
def record_expense():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Get business_id of logged-in user
    cur.execute("SELECT business_id FROM users WHERE id = %s", (user_id,))
    result = cur.fetchone()
    if not result:
        flash("❌ User not associated with a business.", "danger")
        return redirect("/dashboard")

    business_id = result["business_id"]

    # ✅ Only fetch salespersons under the same business
    cur.execute("""
        SELECT username FROM users 
        WHERE business_id = %s AND role = 'salesperson'
    """, (business_id,))
    staff_list = [row["username"] for row in cur.fetchall()]

    if request.method == "POST":
        # Handle JSON request (offline sync) or HTML form
        if request.is_json:
            data = request.get_json()
            staff_name = data.get("staff_name")
            item = data.get("item")
            amount = data.get("amount")
            comment = data.get("comment")
            timestamp = data.get("timestamp")  # Optional, unused here
        else:
            staff_name = request.form["staff_name"]
            item = request.form["item"]
            amount = request.form["amount"]
            comment = request.form["comment"]
            timestamp = None  # Not used in form
            submitted_by = session.get("username")

        # Get staff_id from username
        cur.execute("""
            SELECT id FROM users 
            WHERE username = %s AND business_id = %s AND role = 'salesperson'
        """, (staff_name, business_id))
        staff_result = cur.fetchone()

        if not staff_result:
            if request.is_json:
                return jsonify({"error": "Staff member not found."}), 400
            flash("❌ Staff member not found or not authorized.", "danger")
            return redirect("/dashboard")

        staff_id = staff_result["id"]
        submitted_by = session.get("username") if not request.is_json else staff_name

        # Insert expense
        cur.execute("""
            INSERT INTO expenses (business_id, staff_id, staff_name, item, amount, comment, username)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (business_id, staff_id, staff_name, item, amount, comment, submitted_by))
        conn.commit()

        if request.is_json:
            return jsonify({"status": "success"}), 200

        flash("✅ Expense recorded successfully.", "success")
        return redirect("/dashboard")

    return render_template("record_expense.html", staff_list=staff_list)

@app.route("/view_expenses")
def view_expenses():
    if "user_id" not in session:
        return redirect("/login")

    business_id = session.get("business_id")
    page = int(request.args.get("page", 1))
    per_page = 10
    offset = (page - 1) * per_page

    conn = get_db()
    cur = conn.cursor()

    # Fetch paginated expenses
    cur.execute("""
        SELECT * FROM expenses
        WHERE business_id = %s
        ORDER BY date DESC
        LIMIT %s OFFSET %s
    """, (business_id, per_page, offset))
    expenses = cur.fetchall()

    # Fetch total expense count
    cur.execute("SELECT COUNT(*) AS count FROM expenses WHERE business_id = %s", (business_id,))
    row = cur.fetchone()
    total = row["count"] if row and row["count"] is not None else 0

    has_next = (offset + per_page) < total

    return render_template("view_expenses.html", expenses=expenses, page=page, has_next=has_next)


@app.route('/transactions')
def transactions():
    if 'user_id' not in session:
        return redirect('/login')

    import psycopg2.extras
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    user_id = session['user_id']
    role = session['role']
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    payment_method = request.args.get('payment_method')
    page = int(request.args.get('page', 1))
    per_page = 10
    offset = (page - 1) * per_page

    filters = []
    params = []

    if role == 'salesperson':
        filters.append("salesperson_id = %s")
        params.append(user_id)
    elif role == 'owner':
        cur.execute("SELECT business_id FROM users WHERE id = %s", (user_id,))
        business_row = cur.fetchone()
        if not business_row or not business_row['business_id']:
            return "❌ Business not found", 400
        business_id = business_row['business_id']
        filters.append("product_id IN (SELECT id FROM products WHERE business_id = %s)")
        params.append(business_id)
    else:
        return "❌ Unauthorized", 403

    if start_date:
        filters.append("DATE(date) >= %s")
        params.append(start_date)
    if end_date:
        filters.append("DATE(date) <= %s")
        params.append(end_date)
    if payment_method:
        filters.append("payment_method = %s")
        params.append(payment_method)

    filter_query = " AND ".join(filters)

    # Total count for pagination
    cur.execute(f"""
        SELECT COUNT(DISTINCT batch_no) FROM sales
        WHERE {filter_query}
    """, tuple(params))
    total_batches = cur.fetchone()[0]
    total_pages = (total_batches + per_page - 1) // per_page

    # Paginated batch-level sales summary
    cur.execute(f"""
        SELECT 
            DATE(date) AS date,
            batch_no AS batch_number,
            payment_method,
            SUM(quantity) AS total_quantity,
            SUM(price * quantity) AS total_price
        FROM sales
        WHERE {filter_query}
        GROUP BY batch_no, DATE(date), payment_method
        ORDER BY DATE(date) DESC
        LIMIT {per_page} OFFSET {offset}
    """, tuple(params))
    sales = cur.fetchall()

    # Total Cash Sales
    cur.execute(f"""
        SELECT SUM(price * quantity) FROM sales
        WHERE {filter_query} AND payment_method = 'Cash'
    """, tuple(params))
    total_cash_sales = cur.fetchone()[0] or 0

    # Total Credit Sales
    cur.execute(f"""
        SELECT SUM(price * quantity) FROM sales
        WHERE {filter_query} AND payment_method = 'Credit'
    """, tuple(params))
    total_credit_sales = cur.fetchone()[0] or 0

    cur.close()
    conn.close()

    return render_template('transactions.html',
        sales=sales,
        total_cash_sales=total_cash_sales,
        total_credit_sales=total_credit_sales,
        start_date=start_date,
        end_date=end_date,
        payment_method=payment_method,
        page=page,
        total_pages=total_pages
    )

@app.route('/products', methods=['GET', 'POST'])
def products():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    # Get business ID for current owner
    cur.execute("SELECT business_id FROM users WHERE id = %s", (session['user_id'],))
    business = cur.fetchone()
    if not business:
        conn.close()
        return "Business not found", 400
    business_id = business['business_id']

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        if form_type == 'manual_entry':
            category = request.form['category']
            name = request.form['name']
            buying_price = float(request.form['buying_price'])
            agent_price = float(request.form['agent_price'])
            wholesale_price = float(request.form['wholesale_price'])
            retail_price = float(request.form['retail_price'])

            # Check if product already exists
            cur.execute("""
                SELECT id FROM products
                WHERE name = %s AND category = %s AND business_id = %s
            """, (name, category, business_id))
            existing = cur.fetchone()

            if existing:
                # Just update the prices — no quantity update
                cur.execute("""
                    UPDATE products
                    SET buying_price = %s,
                        agent_price = %s,
                        wholesale_price = %s,
                        retail_price = %s
                    WHERE id = %s
                """, (
                    buying_price,
                    agent_price,
                    wholesale_price,
                    retail_price,
                    existing['id']
                ))
            else:
                # Insert new product without quantity
                cur.execute("""
                    INSERT INTO products (
                        category, name, buying_price, agent_price,
                        wholesale_price, retail_price, business_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    category, name, buying_price, agent_price,
                    wholesale_price, retail_price, business_id
                ))

            conn.commit()

        elif form_type == 'csv_upload':
            file = request.files.get('file')
            if not file or not file.filename.endswith('.csv'):
                return "Please upload a valid CSV file", 400

            import csv
            reader = csv.DictReader(file.read().decode('utf-8').splitlines())
            reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]

            for row in reader:
                row = {k.strip().lower(): v.strip() for k, v in row.items()}
                try:
                    cur.execute("""
                        SELECT id FROM products 
                        WHERE name = %s AND category = %s AND business_id = %s
                    """, (row['product name'], row['category'], business_id))
                    existing = cur.fetchone()

                    if existing:
                        cur.execute("""
                            UPDATE products
                            SET buying_price = %s,
                                agent_price = %s,
                                wholesale_price = %s,
                                retail_price = %s
                            WHERE id = %s
                        """, (
                            float(row['buying price']),
                            float(row['agent price']),
                            float(row['wholesale price']),
                            float(row['retail price']),
                            existing['id']
                        ))
                    else:
                        cur.execute("""
                            INSERT INTO products (
                                category, name, buying_price, agent_price,
                                wholesale_price, retail_price, business_id
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (
                            row['category'],
                            row['product name'],
                            float(row['buying price']),
                            float(row['agent price']),
                            float(row['wholesale price']),
                            float(row['retail price']),
                            business_id
                        ))
                except Exception as e:
                    conn.rollback()
                    return f"Error in row: {row} — {str(e)}", 400
            conn.commit()

    # Filter logic
    selected_category = request.args.get('category', '')
    selected_product = request.args.get('product', '')

    query = "SELECT * FROM products WHERE business_id = %s"
    params = [business_id]

    if selected_category:
        query += " AND category = %s"
        params.append(selected_category)
    if selected_product:
        query += " AND name = %s"
        params.append(selected_product)

    cur.execute(query, params)
    products = cur.fetchall()

    cur.execute("SELECT DISTINCT category FROM products WHERE business_id = %s", (business_id,))
    categories = [row['category'] for row in cur.fetchall()]

    conn.close()
    return render_template('products.html',
                           products=products,
                           categories=categories,
                           selected_category=selected_category,
                           selected_product=selected_product)

@app.route('/add_products')
def add_products():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')
    return render_template('add_products.html')  # This will hold the form only

#SUM OF ALL SALESPERSON STOCKS
@app.route('/owner_inventory')
def owner_inventory():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    # Get the owner's business_id
    cur.execute("SELECT business_id FROM users WHERE id = %s", (session['user_id'],))
    business = cur.fetchone()
    if not business:
        return "Business not found", 400
    business_id = business['business_id']

    # Filters
    selected_branch = request.args.get('branch')

    # Inventory query with UI ID
    query = """
        SELECT 
            p.name AS product_name,
            p.category,
            u.username AS branch,
            ui.quantity,
            p.buying_price,
            ui.id AS ui_id
        FROM user_inventory ui
        JOIN users u ON ui.user_id = u.id
        JOIN products p ON ui.product_id = p.id
        WHERE u.role = 'salesperson'
          AND p.business_id = %s
    """
    params = [business_id]

    if selected_branch:
        query += " AND u.username = %s"
        params.append(selected_branch)

    query += " ORDER BY p.category, p.name, u.username"
    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    # Get all branches for filter dropdown
    cur.execute("SELECT DISTINCT username FROM users WHERE role = 'salesperson' AND business_id = %s", (business_id,))
    all_branches = sorted(row['username'] for row in cur.fetchall())

    conn.close()

    # Organize into product-branch table and calculate totals
    from collections import defaultdict
    table = defaultdict(lambda: defaultdict(int))  # table[product][branch] = qty
    totals = defaultdict(int)
    total_stock = 0
    total_worth = 0
    inventory_ids = {}  # (product_label, branch) -> ui_id

    for row in rows:
        label = f"{row['category']} - {row['product_name']}"
        qty = row['quantity']
        price = row['buying_price'] or 0
        branch = row['branch']

        table[label][branch] += qty
        totals[label] += qty

        total_stock += qty
        total_worth += qty * price

        inventory_ids[(label, branch)] = row['ui_id'] if 'ui_id' in row else None

    return render_template(
        "owner_inventory.html",
        table=table,
        branches=all_branches,
        totals=totals,
        total_stock=total_stock,
        total_worth=total_worth,
        selected_branch=selected_branch,
        inventory_ids=inventory_ids
    )

# EDIT SALES PERSON STOCKS IN THEIR INVENTORY
@app.route('/owner_inventory/edit/<int:inventory_id>', methods=['GET', 'POST'])
def edit_inventory_page(inventory_id):
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    # Get business ID of the owner
    cur.execute("SELECT business_id FROM users WHERE id = %s", (session['user_id'],))
    owner = cur.fetchone()
    if not owner:
        flash("Owner not found", "danger")
        return redirect(url_for('owner_inventory'))

    business_id = owner['business_id']

    # Check inventory record and ensure it's part of owner's business
    cur.execute("""
        SELECT ui.id, ui.quantity, p.name AS product_name, p.category, u.username AS branch
        FROM user_inventory ui
        JOIN users u ON ui.user_id = u.id
        JOIN products p ON ui.product_id = p.id
        WHERE ui.id = %s AND p.business_id = %s
    """, (inventory_id, business_id))
    record = cur.fetchone()

    if not record:
        conn.close()
        flash("Inventory record not found or unauthorized", "danger")
        return redirect(url_for('owner_inventory'))

    # On POST, update quantity
    if request.method == 'POST':
        try:
            new_qty = int(request.form['new_quantity'])
            if new_qty < 0:
                flash("Quantity must be non-negative", "warning")
                return render_template('edit_inventory.html', inventory=record)

            cur.execute("UPDATE user_inventory SET quantity = %s WHERE id = %s", (new_qty, inventory_id))
            conn.commit()
            flash("Inventory quantity updated successfully", "success")
            return redirect(url_for('owner_inventory'))
        except ValueError:
            flash("Invalid quantity format", "warning")

    conn.close()
    return render_template('edit_inventory.html', inventory=record)

# OWNERS EDIT THE PRODUCT TABLE AT OWNERS LEVEL
@app.route('/edit_product/<int:id>', methods=['GET', 'POST'])
def edit_product(id):
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    business_id = session['business_id']

    if request.method == 'POST':
        category = request.form['category']
        name = request.form['name']
        buying_price = float(request.form['buying_price'])
        agent_price = float(request.form['agent_price'])
        wholesale_price = float(request.form['wholesale_price'])
        retail_price = float(request.form['retail_price'])

        cur.execute('''
            UPDATE products
            SET category = %s, name = %s, buying_price = %s,
                agent_price = %s, wholesale_price = %s, retail_price = %s
            WHERE id = %s AND business_id = %s
        ''', (category, name, buying_price,
              agent_price, wholesale_price, retail_price, id, business_id))
        conn.commit()
        return redirect('/products')

    cur.execute("SELECT * FROM products WHERE id = %s AND business_id = %s", (id, business_id))
    product = cur.fetchone()
    if not product:
        return "Product not found or access denied", 404

    return render_template('edit_product.html', product=product)

@app.route('/restock_product/<int:id>', methods=['POST'])
def restock_product(id):
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    # Validate ownership
    cur.execute("SELECT id FROM products WHERE id = %s AND business_id = %s", (id, session['business_id']))
    product = cur.fetchone()
    if not product:
        return "Unauthorized or product not found", 403

    restock_qty = int(request.form['restock_qty'])

    cur.execute('''
        UPDATE products
        SET quantity_available = quantity_available + %s
        WHERE id = %s
    ''', (restock_qty, id))

    conn.commit()
    return redirect('/products')

@app.route('/delete_product/<int:id>', methods=['POST'])
def delete_product(id):
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    # Verify ownership
    cur.execute("SELECT id FROM products WHERE id = %s AND business_id = %s", (id, session['business_id']))
    product = cur.fetchone()
    if not product:
        return "Unauthorized or product not found", 403

    cur.execute("DELETE FROM products WHERE id = %s", (id,))
    conn.commit()
    return redirect('/products')

@app.route('/users', methods=['GET', 'POST'])
def manage_users():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    owner_id = session['user_id']
    cur.execute("SELECT business_id FROM users WHERE id = %s", (owner_id,))
    owner = cur.fetchone()

    if not owner or not owner['business_id']:
        return "❌ Owner does not have a business assigned", 400

    business_id = owner['business_id']

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = 'salesperson'
        password_hash = generate_password_hash(password)

        cur.execute("""
            INSERT INTO users (id, username, password, role, business_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (id, username, password_hash, role, business_id))
        new_user_id = cur.fetchone()['id']
        conn.commit()

        initialize_salesperson_inventory(new_user_id)

    cur.execute("""
        SELECT id, username, role, is_active FROM users
        WHERE role = 'salesperson' AND business_id = %s
    """, (business_id,))
    users = cur.fetchall()

    for user in users:
        user['is_active'] = bool(user['is_active'])  # Ensure correct Boolean logic

    return render_template('users.html', users=users)

@app.route('/delete_user', methods=['POST'])
def delete_user():

    user_id = request.form.get('user_id')

    if not user_id:
        flash("❌ No user ID provided.", "error")
        return redirect('/users')  # Make sure this matches the template page URL

    try:
        user_id = int(user_id)
    except ValueError:
        flash("❌ Invalid user ID format.", "error")
        return redirect('/users')

    conn = get_db()
    cur = conn.cursor()

    # Check if the user has any recorded sales
    cur.execute("SELECT COUNT(*) AS sale_count FROM sales WHERE salesperson_id = %s", (user_id,))
    result = cur.fetchone()

    if result and result['sale_count'] > 0:
        # Deactivate instead of delete
        cur.execute("UPDATE users SET is_active = FALSE WHERE id = %s", (user_id,))
        flash("🔒 User has recorded sales and was deactivated.", "warning")
    else:
        # Delete from user_inventory first
        cur.execute("DELETE FROM user_inventory WHERE user_id = %s", (user_id,))
        # Then delete from users
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        flash("🗑️ User permanently deleted (no sales found).", "success")

    conn.commit()
    cur.close()
    conn.close()
    return redirect('/users')  # Ensure this matches the correct redirect target

@app.route('/reset_password', methods=['POST'])
def reset_password():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    user_id = int(request.form['user_id'])
    new_password = generate_random_password()
    password_hash = generate_password_hash(new_password)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET password = %s WHERE id = %s AND role = 'salesperson'", (password_hash, user_id))
    conn.commit()

    return render_template('reset_success.html', password=new_password)

@app.route('/review_requests', methods=['GET', 'POST'])
def review_requests():
    if 'user_id' not in session or session['role'] != 'salesperson':
        return redirect('/login')

    user_id = session['user_id']

    if request.method == 'POST':
        request_id = int(request.form['request_id'])
        action = request.form.get('action')

        if action == 'approve':
            result = approve_request(request_id, user_id)

            if result == "insufficient_stock":
                session['popup_message'] = "⚠️ You do not have enough stock to approve this request."
                return redirect('/review_requests')

        elif action == 'reject':
            reason = request.form.get('rejection_reason', '')
            reject_request(request_id, user_id, reason)

        return redirect('/review_requests')

    # Fetch only pending requests sent to this salesperson
    requests = get_pending_requests_for_user(user_id)

    # Pop message from session if exists
    popup_message = session.pop('popup_message', None)

    return render_template('review_requests.html', requests=requests, popup_message=popup_message)


@app.route('/export_products')
def export_products():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT business_id FROM users WHERE id = %s", (session['user_id'],))
    business = cur.fetchone()
    if not business:
        return "Business not found", 400
    business_id = business['business_id']

    cur.execute('''
        SELECT category, name, quantity_available,
               buying_price, agent_price, wholesale_price, retail_price
        FROM products
        WHERE business_id = %s
    ''', (business_id,))
    products = cur.fetchall()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["Category", "Product Name", "Quantity Available",
                 "Buying Price", "Agent Price", "Wholesale Price", "Retail Price"])
    for p in products:
        cw.writerow([
            p["category"], p["name"], p["quantity_available"],
            p["buying_price"], p["agent_price"], p["wholesale_price"], p["retail_price"]
        ])

    headers = {
        "Content-Disposition": "attachment; filename=products.csv",
        "Content-Type": "text/csv"
    }

    return Response(si.getvalue(), mimetype="text/csv", headers=headers)

@app.route('/request_stock', methods=['GET', 'POST'])
def request_stock():
    if 'user_id' not in session or session['role'] != 'salesperson':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    current_user_id = session['user_id']

    # ✅ Get business_id of logged-in user
    cur.execute("SELECT business_id FROM users WHERE id = %s", (current_user_id,))
    biz_result = cur.fetchone()
    if not biz_result or not biz_result['business_id']:
        flash("❌ Your account is not linked to a business.", "danger")
        return redirect('/dashboard')
    business_id = biz_result['business_id']

    # ✅ Fetch logged-in salesperson's inventory
    cur.execute('''
        SELECT ui.product_id, ui.quantity, p.name AS product_name, p.buying_price
        FROM user_inventory ui
        JOIN products p ON ui.product_id = p.id
        WHERE ui.user_id = %s
    ''', (current_user_id,))
    inventory = cur.fetchall()

    # ✅ Get other salespersons in the same business (excluding self)
    cur.execute('''
        SELECT id, username FROM users
        WHERE role = 'salesperson' AND id != %s AND business_id = %s
    ''', (current_user_id, business_id))
    recipients = cur.fetchall()

    # 🔁 Handle stock request form submission
    if request.method == 'POST':
        requester_name = request.form.get('requester_name')
        recipient_id = int(request.form.get('recipient_id'))
        cart_data = request.form.get('cart_data')

        try:
            cart = json.loads(cart_data)
        except Exception as e:
            flash(f"❌ Invalid cart data: {e}", "danger")
            return redirect('/request_stock')

        for item in cart:
            product_name = item['name']
            quantity = int(item['quantity'])

            cur.execute("SELECT id, buying_price FROM products WHERE name = %s AND business_id = %s",
                        (product_name, business_id))
            result = cur.fetchone()
            if not result:
                continue  # Skip items not found

            product_id = result['id']
            buying_price = result['buying_price']
            total_value = quantity * buying_price

            # Insert into stock_requests table
            cur.execute('''
                INSERT INTO stock_requests (
                    product_id, requester_id, recipient_id, quantity, requester_name, status
                ) VALUES (%s, %s, %s, %s, %s, 'pending')
            ''', (product_id, current_user_id, recipient_id, quantity, requester_name))

            # Insert into distribution_log table
            cur.execute('''
                INSERT INTO distribution_log (
                    product_id, salesperson_id, receiver_id, quantity, status, total
                ) VALUES (%s, %s, %s, %s, 'pending', %s)
            ''', (product_id, current_user_id, recipient_id, quantity, total_value))

        conn.commit()
        flash("✅ Stock request submitted successfully.", "success")
        return redirect('/dashboard')

    return render_template('request_stock.html',
                           inventory=inventory,
                           recipients=recipients)

@app.route('/my_inventory')
def my_inventory():
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    user_id = session['user_id']

    # Get user's business ID
    cur.execute("SELECT business_id FROM users WHERE id = %s", (user_id,))
    business_row = cur.fetchone()
    if not business_row:
        return "Business not found", 400
    business_id = business_row['business_id']

    # Handle filters
    selected_category = request.args.get('category')
    search_term = request.args.get('search', '').strip().lower()

    # Get inventory for the logged-in user
    cur.execute("""
        SELECT ui.*, p.name AS product_name, p.category,
               p.buying_price, p.agent_price, p.wholesale_price, p.retail_price
        FROM user_inventory ui
        JOIN products p ON ui.product_id = p.id
        WHERE ui.user_id = %s
    """, (user_id,))
    inventory = cur.fetchall()

    # Apply category and search filters
    if selected_category:
        inventory = [item for item in inventory if item['category'] == selected_category]
    if search_term:
        inventory = [item for item in inventory if search_term in item['product_name'].lower()]

    # Summary: total stock and inventory worth
    total_stock_qty = sum(item['quantity'] for item in inventory)
    total_stock_value = sum(item['quantity'] * (item['buying_price'] or 0) for item in inventory)

    # Categories for filter dropdown
    cur.execute("""
        SELECT DISTINCT category FROM products
        WHERE business_id = %s
        ORDER BY category ASC
    """, (business_id,))
    categories = [row['category'] for row in cur.fetchall() if row['category']]

    return render_template(
        "my_inventory.html",
        inventory=inventory,
        categories=categories,
        selected_category=selected_category,
        search_term=search_term,
        total_stock=total_stock_qty,
        total_worth=total_stock_value
    )

@app.route('/report', methods=['GET', 'POST'])
def report():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    business_id = session['business_id']
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT username FROM users WHERE business_id = %s AND role != 'owner'", (business_id,))
    salespeople = [r['username'] for r in cur.fetchall()]

    page = int(request.args.get('page', 1))
    per_page = 10
    offset = (page - 1) * per_page
    current_page = page
    total_pages = 1

    if request.method == 'POST':
        quick_range = request.form.get('quick_range')
        if quick_range:
            start_date, end_date = get_date_range(quick_range)
        else:
            start_date = request.form.get('start_date')
            end_date = request.form.get('end_date')
        salesperson = request.form.get('salesperson')
        payment_method = request.form.get('payment_method')
    else:
        quick_range = None
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        salesperson = request.args.get('salesperson')
        payment_method = request.args.get('payment_method')

    report_query = '''
        SELECT u.username AS salesperson,
               s.payment_method,
               COUNT(s.id) AS sales_count,
               SUM(s.quantity) AS total_qty,
               SUM(s.quantity * p.buying_price) AS total_buying_price,
               SUM(s.quantity * s.price) AS total_selling_price,
               SUM((s.quantity * s.price) - (s.quantity * p.buying_price)) AS profit
        FROM sales s
        JOIN users u ON s.salesperson_id = u.id
        JOIN products p ON s.product_id = p.id
        WHERE p.business_id = %s
    '''
    report_params = [business_id]

    if start_date:
        report_query += ' AND date(s.date) >= date(%s)'
        report_params.append(start_date)
    if end_date:
        report_query += ' AND date(s.date) <= date(%s)'
        report_params.append(end_date)
    if salesperson:
        report_query += ' AND u.username = %s'
        report_params.append(salesperson)
    if payment_method:
        report_query += ' AND s.payment_method = %s'
        report_params.append(payment_method)

    report_query += ' GROUP BY u.username, s.payment_method ORDER BY total_selling_price DESC'
    cur.execute(report_query, report_params)
    report_data = cur.fetchall()

    expense_query = '''
        SELECT SUM(e.amount) AS total_expense
        FROM expenses e
        LEFT JOIN users u ON e.staff_id = u.id
        WHERE e.business_id = %s
    '''
    expense_params = [business_id]
    if salesperson:
        expense_query += ' AND u.username = %s'
        expense_params.append(salesperson)
    if start_date:
        expense_query += ' AND date(e.date) >= date(%s)'
        expense_params.append(start_date)
    if end_date:
        expense_query += ' AND date(e.date) <= date(%s)'
        expense_params.append(end_date)

    cur.execute(expense_query, expense_params)
    expense_result = cur.fetchone()
    total_expenses = int(expense_result['total_expense']) if expense_result and expense_result['total_expense'] else 0

    summary_query = '''
        SELECT COUNT(*) AS total_transactions,
               SUM(s.quantity) AS total_quantity,
               SUM(s.quantity * s.price) AS raw_revenue,
               SUM(s.quantity * p.buying_price) AS total_cost_price
        FROM sales s
        JOIN users u ON s.salesperson_id = u.id
        JOIN products p ON s.product_id = p.id
        WHERE p.business_id = %s
    '''
    summary_params = [business_id]
    if start_date:
        summary_query += ' AND date(s.date) >= date(%s)'
        summary_params.append(start_date)
    if end_date:
        summary_query += ' AND date(s.date) <= date(%s)'
        summary_params.append(end_date)
    if salesperson:
        summary_query += ' AND u.username = %s'
        summary_params.append(salesperson)
    if payment_method:
        summary_query += ' AND s.payment_method = %s'
        summary_params.append(payment_method)

    cur.execute(summary_query, summary_params)
    result = cur.fetchone()
    summary = {}
    if result:
        summary['total_transactions'] = result['total_transactions'] or 0
        summary['total_quantity'] = result['total_quantity'] or 0
        summary['total_cost_price'] = int(result['total_cost_price'] or 0)
        raw_revenue = int(result['raw_revenue'] or 0)
        summary['total_revenue'] = raw_revenue - total_expenses
        summary['total_profit'] = summary['total_revenue'] - summary['total_cost_price']

    net_balance = summary['total_revenue'] - summary['total_cost_price']

    top_query = '''
        SELECT u.username AS top_salesperson,
               SUM(s.quantity * s.price) AS total
        FROM sales s
        JOIN users u ON u.id = s.salesperson_id
        JOIN products p ON s.product_id = p.id
        WHERE p.business_id = %s
    '''
    top_params = [business_id]
    if start_date:
        top_query += ' AND date(s.date) >= date(%s)'
        top_params.append(start_date)
    if end_date:
        top_query += ' AND date(s.date) <= date(%s)'
        top_params.append(end_date)
    if salesperson:
        top_query += ' AND u.username = %s'
        top_params.append(salesperson)
    if payment_method:
        top_query += ' AND s.payment_method = %s'
        top_params.append(payment_method)

    top_query += ' GROUP BY s.salesperson_id, u.username ORDER BY total DESC LIMIT 1'
    cur.execute(top_query, top_params)
    top_salesperson = cur.fetchone()

    cur.execute('''
        SELECT COUNT(*) FROM distribution_log dl
        JOIN products p ON dl.product_id = p.id
        WHERE p.business_id = %s
    ''', (business_id,))
    total_logs = cur.fetchone()['count']
    total_pages = ceil(total_logs / per_page)

    cur.execute('''
        SELECT dl.timestamp, dl.quantity, dl.status,
               p.name AS product_name,
               u1.username AS from_salesperson,
               u2.username AS to_salesperson,
               dl.quantity * p.buying_price AS value_ugx
        FROM distribution_log dl
        JOIN products p ON dl.product_id = p.id
        JOIN users u1 ON dl.salesperson_id = u1.id
        JOIN users u2 ON dl.receiver_id = u2.id
        WHERE p.business_id = %s
        ORDER BY dl.timestamp DESC
        LIMIT %s OFFSET %s
    ''', (business_id, per_page, offset))
    distribution_log = cur.fetchall()

    for log in distribution_log:
        if log['timestamp']:
            log['timestamp'] = log['timestamp'].replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Africa/Kampala"))
    
        # Top 5 selling products
    top_product_query = '''
        SELECT p.name AS product_name, SUM(s.quantity) AS total_qty_sold
        FROM sales s
        JOIN products p ON s.product_id = p.id
        JOIN users u ON s.salesperson_id = u.id
        WHERE p.business_id = %s
    '''
    top_product_params = [business_id]

    if start_date:
        top_product_query += ' AND date(s.date) >= date(%s)'
        top_product_params.append(start_date)
    if end_date:
        top_product_query += ' AND date(s.date) <= date(%s)'
        top_product_params.append(end_date)
    if salesperson:
        top_product_query += ' AND u.username = %s'
        top_product_params.append(salesperson)

    top_product_query += '''
        GROUP BY p.name
        ORDER BY total_qty_sold DESC
        LIMIT 5
    '''
    cur.execute(top_product_query, top_product_params)
    top_products = cur.fetchall()

    # Bottom 5 selling products
    low_product_query = '''
        SELECT p.name AS product_name, SUM(s.quantity) AS total_qty_sold
        FROM sales s
        JOIN products p ON s.product_id = p.id
        JOIN users u ON s.salesperson_id = u.id
        WHERE p.business_id = %s
    '''
    low_product_params = [business_id]

    if start_date:
        low_product_query += ' AND date(s.date) >= date(%s)'
        low_product_params.append(start_date)
    if end_date:
        low_product_query += ' AND date(s.date) <= date(%s)'
        low_product_params.append(end_date)
    if salesperson:
        low_product_query += ' AND u.username = %s'
        low_product_params.append(salesperson)

    low_product_query += '''
        GROUP BY p.name
        ORDER BY total_qty_sold ASC
        LIMIT 5
    '''
    cur.execute(low_product_query, low_product_params)
    low_products = cur.fetchall()

    return render_template(
        'report.html',
        report=report_data,
        salespeople=salespeople,
        summary=summary,
        total_expenses=total_expenses,
        net_balance=net_balance,
        top_salesperson=top_salesperson,
        distribution_log=distribution_log,
        current_page=current_page,
        total_pages=total_pages,
        start_date=start_date,
        end_date=end_date,
        salesperson=salesperson,
        payment_method=payment_method,
        top_products=top_products,
        low_products=low_products,
        quick_range=quick_range
    )

@app.route('/export_report', methods=['POST'])
def export_report():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT business_id FROM users WHERE id = %s", (session['user_id'],))
    business = cur.fetchone()
    if not business:
        return "Business not found", 400
    business_id = business['business_id']

    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    salesperson = request.form.get('salesperson')
    payment_method = request.form.get('payment_method')

    query = '''
        SELECT 
            u.username AS salesperson,
            COUNT(s.id) AS sales_count,
            SUM(s.quantity) AS total_qty,
            s.payment_method,
            SUM(s.quantity * p.buying_price) AS total_buying_price,
            SUM(s.quantity * s.price) AS total_selling_price,
            SUM((s.quantity * s.price) - (s.quantity * p.buying_price)) AS profit
        FROM sales s
        JOIN users u ON s.salesperson_id = u.id
        JOIN products p ON s.product_id = p.id
        WHERE p.business_id = %s
    '''
    params = [business_id]

    if start_date:
        query += ' AND date(s.date) >= date(%s)'
        params.append(start_date)
    if end_date:
        query += ' AND date(s.date) <= date(%s)'
        params.append(end_date)
    if salesperson:
        query += ' AND u.username = %s'
        params.append(salesperson)
    if payment_method:
        query += ' AND s.payment_method = %s'
        params.append(payment_method)

    query += ' GROUP BY u.username, s.payment_method ORDER BY total_selling_price DESC'
    cur.execute(query, params)
    report_data = cur.fetchall()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["Salesperson", "Payment Type", "Sales Count", "Total Quantity",
                 "Buying Price", "Selling Price", "Profit"])
    for row in report_data:
        cw.writerow([
            row['salesperson'],
            row['payment_method'],
            row['sales_count'],
            row['total_qty'],
            row['total_buying_price'],
            row['total_selling_price'],
            row['profit']
        ])

    headers = {
        "Content-Disposition": "attachment; filename=sales_report.csv",
        "Content-Type": "text/csv"
    }

    return Response(si.getvalue(), mimetype="text/csv", headers=headers)

@app.route('/sales_upload_inventory', methods=['GET', 'POST'])
def sales_upload_inventory():
    if 'user_id' not in session or session['role'] != 'salesperson':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    # === Load allowed product names for this business ===
    cur.execute("SELECT name FROM products WHERE business_id = %s", (session['business_id'],))
    allowed_products = set(row['name'].strip().lower() for row in cur.fetchall())

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        # === Handle CSV/TSV Upload ===
        if form_type == 'csv_upload':
            file = request.files.get('file')
            if not file:
                flash("❌ Please upload a file.", "danger")
                return redirect(request.referrer or '/sales_upload_inventory')

            try:
                content = file.read().decode('utf-8-sig').splitlines()
                if not content:
                    flash("❌ The uploaded file is empty.", "danger")
                    return redirect(request.referrer or '/sales_upload_inventory')

                # Auto-detect CSV/TSV delimiter
                try:
                    dialect = csv.Sniffer().sniff('\n'.join(content[:2]), delimiters=',\t')
                except Exception:
                    dialect = csv.excel

                reader = csv.DictReader(content, dialect=dialect)
                inventory_rows = []
                error_count = 0
                skipped_products = 0
                row_number = 1

                for raw_row in reader:
                    row_number += 1
                    row = {k.strip().lower(): v.strip() for k, v in raw_row.items() if k}

                    try:
                        product_name = row['product name']
                        quantity = float(row['quantity'])  # allow 0
                        category = row['category']

                        if product_name.strip().lower() not in allowed_products:
                            skipped_products += 1
                            print(f"⚠️ Skipped row {row_number}: Unknown product '{product_name}' not in business inventory.")
                            continue

                        inventory_rows.append((product_name, quantity, category))

                    except Exception as e:
                        error_count += 1
                        print(f"⚠️ Skipped row {row_number} due to error: {raw_row} — {str(e)}")
                        continue

                if not inventory_rows:
                    flash("❌ Upload failed. All rows had errors or unknown products.", "danger")
                    return redirect(request.referrer or '/sales_upload_inventory')

                add_salesperson_stock_bulk(session['user_id'], inventory_rows)
                flash(
                    f"✅ Uploaded {len(inventory_rows)} product(s). "
                    f"Skipped {error_count} invalid row(s), {skipped_products} unknown product(s).",
                    "success"
                )
                return redirect('/dashboard')

            except Exception as e:
                flash(f"❌ Upload failed: {str(e)}", "danger")
                return redirect(request.referrer or '/sales_upload_inventory')

        # === Handle Manual Cart Upload ===
        cart_data = request.form.get('cart_data')
        if not cart_data:
            flash("❌ Error: No stock data submitted.", "danger")
            return redirect(request.referrer or '/sales_upload_inventory')

        try:
            items = json.loads(cart_data)
            inventory_rows = []
            error_count = 0
            skipped_products = 0

            for i, item in enumerate(items, start=1):
                try:
                    product_name = item['product_name'].strip()
                    quantity = float(item['quantity'])  # allow 0
                    category = item['category'].strip()

                    if product_name.lower() not in allowed_products:
                        skipped_products += 1
                        print(f"⚠️ Skipped manual item {i}: Unknown product '{product_name}' not in business inventory.")
                        continue

                    inventory_rows.append((product_name, quantity, category))

                except Exception as e:
                    error_count += 1
                    print(f"⚠️ Skipped manual item {i} due to error: {item} — {str(e)}")
                    continue

            if not inventory_rows:
                flash("❌ Upload failed. All items had errors or unknown products.", "danger")
                return redirect(request.referrer or '/sales_upload_inventory')

            added, skipped = add_salesperson_stock_bulk(session['user_id'], inventory_rows)
            flash(
                f"✅ Uploaded {added} product(s). "
                f"Skipped {error_count} invalid row(s), {skipped + skipped_products} unknown product(s).",
                "success"
            )
            return redirect('/dashboard')

        except Exception as e:
            flash(f"❌ Error processing cart: {str(e)}", "danger")
            return redirect(request.referrer or '/sales_upload_inventory')

    # === GET: Render Form ===
    cur.execute("SELECT name, category FROM products WHERE business_id = %s ORDER BY name", (session['business_id'],))
    products = cur.fetchall()
    product_names = [row['name'] for row in products]
    product_categories = {row['name']: row['category'] for row in products}

    return render_template(
        'sales_upload_inventory.html',
        product_names=product_names,
        product_categories=product_categories
    )

@app.route('/repayments', methods=['GET', 'POST'])
def repayments():
    if 'user_id' not in session or session['role'] != 'salesperson':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()
    selected_customer_id = None
    selected_credit_id = None
    total_owed = None

    if request.method == 'POST':
        # Detect offline (JSON) or online (form) submission
        if request.is_json:
            data = request.get_json()
            customer_id = data.get('customer_id')
            credit_id = int(data.get('credit_id'))
            amount = float(data.get('amount'))
            timestamp = data.get('timestamp')
        else:
            customer_id = request.form.get('customer_id')
            credit_id = int(request.form.get('credit_id'))
            amount = float(request.form.get('amount'))
            timestamp = None  # Optional for online
            selected_customer_id = customer_id
            selected_credit_id = credit_id

        # Insert repayment
        cur.execute("""
            INSERT INTO credit_repayments (credit_id, amount, paid_on)
            VALUES (%s, %s, %s)
        """, (credit_id, amount, timestamp or datetime.now()))

        # Update credit sale balance and status
        cur.execute("""
            UPDATE credit_sales
            SET balance = balance - %s,
                status = CASE
                    WHEN balance - %s <= 0 THEN 'paid'
                    WHEN balance - %s < amount THEN 'partial'
                    ELSE 'unpaid'
                END
            WHERE id = %s
        """, (amount, amount, amount, credit_id))

        conn.commit()

        if request.is_json:
            cur.close()
            conn.close()
            return jsonify({"status": "success"}), 200

    # -----------------------------
    # GET request - load repayment form
    # -----------------------------
    selected_customer_id = request.args.get('customer_id') or selected_customer_id

    # Get customers with credit sales for current salesperson
    cur.execute("""
        SELECT DISTINCT c.id, c.name
        FROM credit_sales cs
        JOIN customers c ON cs.customer_id = c.id
        JOIN sales s ON cs.sale_id = s.id
        WHERE s.salesperson_id = %s
    """, (session['user_id'],))
    customers = cur.fetchall()

    credit_sales = []
    if selected_customer_id:
        cur.execute("""
            SELECT cs.id AS credit_id, c.name AS customer_name, cs.amount, cs.balance, s.date
            FROM credit_sales cs
            JOIN sales s ON cs.sale_id = s.id
            JOIN customers c ON cs.customer_id = c.id
            WHERE cs.status IN ('unpaid', 'partial') AND s.salesperson_id = %s AND c.id = %s
            ORDER BY s.date DESC
        """, (session['user_id'], selected_customer_id))
        credit_sales = cur.fetchall()

        cur.execute("""
            SELECT SUM(balance) AS total_balance
            FROM credit_sales cs
            JOIN sales s ON cs.sale_id = s.id
            WHERE cs.status IN ('unpaid', 'partial') AND s.salesperson_id = %s AND cs.customer_id = %s
        """, (session['user_id'], selected_customer_id))

        result = cur.fetchone()
        total_owed = result['total_balance'] if result and result['total_balance'] is not None else 0



    # Get recent repayments
    cur.execute("""
        SELECT r.amount, r.paid_on, c.name AS customer_name
        FROM credit_repayments r
        JOIN credit_sales cs ON r.credit_id = cs.id
        JOIN customers c ON cs.customer_id = c.id
        JOIN sales s ON cs.sale_id = s.id
        WHERE s.salesperson_id = %s
        ORDER BY r.paid_on DESC
        LIMIT 10
    """, (session['user_id'],))
    repayments = cur.fetchall()

    # Get credit summary
    cur.execute("""
        SELECT 
            c.id AS customer_id,
            c.name AS customer_name,
            SUM(cs.amount) AS total_credit,
            SUM(cs.balance) AS total_balance
        FROM credit_sales cs
        JOIN customers c ON cs.customer_id = c.id
        JOIN sales s ON cs.sale_id = s.id
        WHERE s.salesperson_id = %s
        GROUP BY c.id, c.name
        ORDER BY c.name
    """, (session['user_id'],))
    credit_summary = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('repayments.html',
        customers=customers,
        selected_customer_id=selected_customer_id,
        selected_credit_id=selected_credit_id,
        credit_sales=credit_sales,
        repayments=repayments,
        total_owed=total_owed,
        credit_summary=credit_summary
    )

@app.route('/add_customer', methods=['GET', 'POST'])
def add_customer():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    user_id = session['user_id']

    # Get business ID
    cur.execute("SELECT business_id FROM users WHERE id = %s", (user_id,))
    business = cur.fetchone()
    if not business:
        flash("❌ Business not found.", "danger")
        return redirect('/dashboard')
    business_id = business['business_id']

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add_customer':
            name = request.form.get('name', '').strip()
            phone = request.form.get('phone', '').strip() or None

            if not name:
                flash("❌ Customer name is required.", "danger")
                return redirect('/add_customer')

            cur.execute("""
                SELECT id FROM customers 
                WHERE LOWER(name) = LOWER(%s) AND business_id = %s
            """, (name, business_id))
            existing = cur.fetchone()

            if existing:
                flash("⚠️ A customer with this name already exists.", "warning")
            else:
                cur.execute("""
                    INSERT INTO customers (name, phone, business_id)
                    VALUES (%s, %s, %s)
                """, (name, phone, business_id))
                conn.commit()
                flash("✅ Customer added successfully.", "success")

            return redirect('/add_customer')

        elif action == 'toggle_status':
            customer_id = request.form.get('customer_id')
            if not customer_id:
                flash("❌ No customer selected.", "danger")
                return redirect('/add_customer')

            # Verify customer belongs to business
            cur.execute("""
                SELECT id, is_active FROM customers 
                WHERE id = %s AND business_id = %s
            """, (customer_id, business_id))
            customer = cur.fetchone()

            if not customer:
                flash("⚠️ Customer not found or not part of your business.", "warning")
            else:
                new_status = not customer['is_active']
                cur.execute("UPDATE customers SET is_active = %s WHERE id = %s", (new_status, customer_id))
                conn.commit()
                flash(f"✅ Customer {'activated' if new_status else 'deactivated'} successfully.", "success")

            return redirect('/add_customer')

    # === GET: Fetch customers and credit summary ===
    cur.execute("""
        SELECT c.id, c.name, c.phone, c.created_at, c.is_active
        FROM customers c
        WHERE c.business_id = %s
        ORDER BY c.created_at DESC
    """, (business_id,))
    customers = cur.fetchall()

    cur.execute("""
        SELECT 
            c.name AS customer_name,
            cs.amount,
            cs.balance,
            cs.status,
            s.date,
            s.batch_no
        FROM credit_sales cs
        JOIN sales s ON cs.sale_id = s.id
        JOIN customers c ON cs.customer_id = c.id
        WHERE s.business_id = %s
        ORDER BY s.date DESC
    """, (business_id,))
    credit_summary = cur.fetchall()

    return render_template('add_customer.html',
                           customers=customers,
                           credit_summary=credit_summary)

@app.route('/toggle_customer_status', methods=['POST'])
def toggle_customer_status():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    customer_id = request.form.get('customer_id')
    if not customer_id:
        flash("❌ No customer selected.", "danger")
        return redirect('/add_customer')

    user_id = session['user_id']
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Get business ID
        cur.execute("SELECT business_id FROM users WHERE id = %s", (user_id,))
        biz = cur.fetchone()
        if not biz:
            flash("❌ Business not found.", "danger")
            return redirect('/add_customer')
        business_id = biz['business_id']

        # Check if customer belongs to the business
        cur.execute("""
            SELECT id, is_active FROM customers 
            WHERE id = %s AND business_id = %s
        """, (customer_id, business_id))
        customer = cur.fetchone()

        if not customer:
            flash("⚠️ Customer not found or not part of your business.", "warning")
            return redirect('/add_customer')

        # Toggle status
        new_status = not customer['is_active']
        cur.execute("""
            UPDATE customers SET is_active = %s WHERE id = %s
        """, (new_status, customer_id))
        conn.commit()

        flash(f"✅ Customer {'activated' if new_status else 'deactivated'} successfully.", "success")
        return redirect('/add_customer')

    except Exception as e:
        print("Error toggling customer status:", e)
        flash("❌ An unexpected error occurred.", "danger")
        return redirect('/add_customer')

    finally:
        cur.close()
        conn.close()

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session or session['role'] != 'super_admin':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    # Count summaries
    cur.execute("SELECT COUNT(*) AS total_businesses FROM businesses")
    total_businesses = cur.fetchone()['total_businesses']

    cur.execute("SELECT COUNT(*) AS total_salespeople FROM users WHERE role = 'salesperson'")
    total_salespeople = cur.fetchone()['total_salespeople']

    cur.execute("SELECT COUNT(*) AS total_owners FROM users WHERE role = 'owner'")
    total_owners = cur.fetchone()['total_owners']

    # Business list
    cur.execute("""
        SELECT b.id, b.name, b.type, b.phone, b.is_active, COUNT(u.id) AS user_count
        FROM businesses b
        LEFT JOIN users u ON b.id = u.business_id
        GROUP BY b.id
        ORDER BY b.name
    """)
    businesses = cur.fetchall()

    return render_template(
        'admin_dashboard.html',
        total_businesses=total_businesses,
        total_salespeople=total_salespeople,
        total_owners=total_owners,
        businesses=businesses
    )

# Toggle business active/inactive
@app.route('/toggle_business/<int:business_id>', methods=['POST'])
def toggle_business(business_id):
    if 'user_id' not in session or session['role'] != 'super_admin':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("SELECT is_active, name FROM businesses WHERE id = %s", (business_id,))
        business = cur.fetchone()

        if not business:
            flash("Business not found.", "error")
            return redirect('/admin_dashboard')

        new_status = not business['is_active']
        cur.execute("UPDATE businesses SET is_active = %s WHERE id = %s", (new_status, business_id))
        conn.commit()

        status_msg = "activated" if new_status else "deactivated"
        flash(f"{business['name']} has been {status_msg}.", "success")
        return redirect('/admin_dashboard')

    except Exception as e:
        conn.rollback()
        flash("Something went wrong while updating business status.", "error")
        print("ERROR in toggle_business:", e)
        return redirect('/admin_dashboard')

@app.route('/return_product', methods=['POST'])
def return_product():
    if 'user_id' not in session or session['role'] != 'salesperson':
        return redirect('/login')

    sale_id = request.form.get('sale_id')
    try:
        return_quantity = int(request.form.get('return_quantity'))
    except (TypeError, ValueError):
        flash("❌ Invalid return quantity.", "danger")
        return redirect(request.referrer or "/transactions")

    if return_quantity <= 0:
        flash("❌ Return quantity must be greater than zero.", "danger")
        return redirect(request.referrer or "/transactions")

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Fetch the original sale record
    cur.execute("SELECT * FROM sales WHERE id = %s", (sale_id,))
    sale = cur.fetchone()

    if not sale:
        flash("❌ Sale not found. Please try again.", "danger")
        cur.close()
        conn.close()
        return redirect("/transactions")

    # 🔐 Ensure only the salesperson who made the sale can return it
    if sale['salesperson_id'] != session['user_id']:
        flash("⚠️ You are not authorized to return this sale.", "warning")
        cur.close()
        conn.close()
        return redirect(f"/batch_sales/{sale['batch_no']}")

    # Get the total quantity already returned for this sale
    cur.execute("""
        SELECT COALESCE(SUM(-quantity), 0) AS total_returned
        FROM sales
        WHERE is_return = TRUE AND return_reference_id = %s
    """, (sale_id,))
    returned = cur.fetchone()['total_returned']

    remaining_qty = sale['quantity'] - returned

    # Prevent over-return
    if return_quantity > remaining_qty:
        flash(f"❌ You have returned all items, {remaining_qty} remaining", "danger")
        cur.close()
        conn.close()
        return redirect(f"/batch_sales/{sale['batch_no']}")

    # Insert return record
    cur.execute("""
        INSERT INTO sales (
            product_id,
            quantity,
            price,
            payment_method,
            date,
            salesperson_id,
            business_id,
            amount_paid,
            payment_status,
            customer_id,
            batch_no,
            is_return,
            return_reference_id
        ) VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s, TRUE, %s)
    """, (
        sale['product_id'],
        -return_quantity,
        sale['price'],
        sale['payment_method'],
        session['user_id'],
        sale['business_id'],
        -(sale['price'] * return_quantity),
        sale['payment_status'],
        sale['customer_id'],
        sale['batch_no'],
        sale['id']
    ))

    # Restore returned quantity to user's inventory
    cur.execute("""
        UPDATE user_inventory
        SET quantity = quantity + %s
        WHERE user_id = %s AND product_id = %s
    """, (
        return_quantity,
        session['user_id'],
        sale['product_id']
    ))

    conn.commit()
    cur.close()
    conn.close()

    flash("✅ Product return processed successfully.", "success")
    return redirect(f"/batch_sales/{sale['batch_no']}")

# OFFLINE SYNCS

@app.route("/record_sale", methods=["POST"])
def record_sale_post():
    if not request.is_json:
        return jsonify({"error": "Only JSON allowed"}), 400

    sale = request.get_json()

    cart_data = sale.get("cart_data")
    payment_method = sale.get("payment_method")
    customer_id = sale.get("customer_id")
    due_date = sale.get("due_date")
    timestamp = sale.get("timestamp")
    user_id = session.get("user_id")

    conn = get_db()
    cur = conn.cursor()

    for item in cart_data:
        product_id = item["productId"]
        quantity = item["quantity"]
        price = item["price"]
        subtotal = item["subtotal"]

        # Insert each sale item into sales table
        cur.execute("""
            INSERT INTO sales (user_id, product_id, quantity, price, subtotal, payment_method, customer_id, due_date, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id,
            product_id,
            quantity,
            price,
            subtotal,
            payment_method,
            customer_id if payment_method == "Credit" else None,
            due_date if payment_method == "Credit" else None,
            timestamp
        ))

        # Decrease from salesperson inventory
        cur.execute("""
            UPDATE user_inventory 
            SET quantity = quantity - %s 
            WHERE user_id = %s AND product_id = %s
        """, (quantity, user_id, product_id))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"status": "success"}), 200

@app.route('/upload_offline_sales', methods=['POST'])
def upload_offline_sales():
    if 'user_id' not in session or session['role'] != 'salesperson':
        return jsonify({"error": "Unauthorized"}), 403

    sales_data = request.get_json()
    if not sales_data:
        return jsonify({"error": "No sales data received"}), 400

    user_id = session['user_id']
    conn = get_db()
    cur = conn.cursor()

    try:
        # Get user's username and business ID
        cur.execute("SELECT username, business_id FROM users WHERE id = %s", (user_id,))
        user_row = cur.fetchone()
        if not user_row:
            raise ValueError("❌ User not found.")
        username = user_row['username']
        business_id = user_row['business_id']
        initials = ''.join(part[0] for part in username.strip().split()).upper()
        date_str = datetime.now().strftime("%Y%m%d")

        results = []

        for entry in sales_data:
            items = entry.get("cart_data")
            payment_method = entry.get("payment_method")
            customer_id = entry.get("customer_id") or None
            due_date = entry.get("due_date") or None

            if isinstance(items, str):
                items = json.loads(items)

            # 🆕 Generate batch number per cart
            cur.execute("SELECT COUNT(DISTINCT batch_no) FROM sales WHERE batch_no LIKE %s", (f"{initials}_{date_str}_%",))
            count_row = cur.fetchone()
            count = list(count_row.values())[0] + 1 if count_row else 1
            batch_no = f"{initials}_{date_str}_{count:03d}"

            for item in items:
                product_id = int(item["productId"])
                quantity = int(item["quantity"])
                price = float(item["price"])

                # Confirm product belongs to this business
                cur.execute("SELECT id FROM products WHERE id = %s AND business_id = %s", (product_id, business_id))
                if not cur.fetchone():
                    raise ValueError(f"❌ Product {product_id} not authorized for this business")

                # Deduct from user inventory
                cur.execute("""
                    UPDATE user_inventory
                    SET quantity = quantity - %s
                    WHERE user_id = %s AND product_id = %s
                """, (quantity, user_id, product_id))

                amount_paid = quantity * price if payment_method == 'Cash' else 0
                payment_status = 'paid' if payment_method == 'Cash' else 'unpaid'

                # Insert into sales
                if payment_method == 'Cash':
                    cur.execute("""
                        INSERT INTO sales (
                            product_id, quantity, salesperson_id, price, payment_method,
                            date, amount_paid, payment_status, business_id, batch_no
                        ) VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        product_id, quantity, user_id, price, payment_method,
                        amount_paid, payment_status, business_id, batch_no
                    ))
                else:
                    if not customer_id:
                        raise ValueError("❌ Credit sale missing customer.")
                    cur.execute("""
                        INSERT INTO sales (
                            product_id, quantity, salesperson_id, price, payment_method,
                            date, amount_paid, payment_status, business_id, customer_id, batch_no
                        ) VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        product_id, quantity, user_id, price, payment_method,
                        amount_paid, payment_status, business_id, int(customer_id), batch_no
                    ))

                sale_row = cur.fetchone()
                if not sale_row:
                    raise ValueError("❌ Could not retrieve inserted sale ID.")
                sale_id = sale_row['id']

                # Insert into credit sales if needed
                if payment_method == 'Credit' and customer_id:
                    total_amount = quantity * price
                    cur.execute("""
                        INSERT INTO credit_sales (
                            sale_id, customer_id, amount, balance, due_date, status
                        ) VALUES (%s, %s, %s, %s, %s, 'unpaid')
                    """, (
                        sale_id, int(customer_id), total_amount, total_amount, due_date
                    ))

            results.append(batch_no)

        conn.commit()
        return jsonify({"status": "offline sales synced", "batches": results}), 200

    except Exception as e:
        conn.rollback()
        import traceback
        print("❌ Offline Sale Sync Error:", traceback.format_exc())
        return jsonify({"error": str(e)}), 500

    finally:
        cur.close()
        conn.close()

@app.route("/offline_data")
def offline_data():
    if "user_id" not in session or session["role"] != "salesperson":
        return jsonify({"error": "Unauthorized"}), 403

    user_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()

    try:
        # Get business ID
        cur.execute("SELECT business_id FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if not row:
            raise Exception("User not found.")
        business_id = row["business_id"]

        # Fetch only products assigned to this business and user
        cur.execute("""
            SELECT p.id AS product_id, p.name AS product_name, 
                   p.retail_price, p.buying_price, ui.quantity
            FROM products p
            JOIN user_inventory ui ON p.id = ui.product_id
            WHERE ui.user_id = %s
        """, (user_id,))
        products = [
            {
                "product_id": r["product_id"],
                "product_name": r["product_name"],
                "retail_price": float(r["retail_price"]),
                "buying_price": float(r["buying_price"]),
                "quantity": int(r["quantity"]),
            }
            for r in cur.fetchall()
        ]

        # Fetch customers for this business
        cur.execute("SELECT id, name FROM customers WHERE business_id = %s", (business_id,))
        customers = [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]

        return jsonify({"products": products, "customers": customers})

    except Exception as e:
        print("❌ Offline data fetch error:", e)
        return jsonify({"error": "Server error"}), 500

    finally:
        cur.close()
        conn.close()

@app.route('/logout')
def logout():
    username = session.get('username')
    session.clear()

    # Optional: Flash message or logging
    flash("You have been logged out.", "info")
    print(f"User '{username}' has been logged out.")

    return redirect(url_for('login'))  # More robust than hardcoded '/login'


if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True)