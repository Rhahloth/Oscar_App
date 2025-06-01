from flask import Flask, render_template, request, redirect, session, url_for, send_file, Response
from werkzeug.security import check_password_hash, generate_password_hash
from models import (
    get_user, get_sales, get_products, add_sale, get_user_inventory,
    add_salesperson_stock_bulk, approve_request, reject_request, get_pending_requests_for_user,
    initialize_salesperson_inventory, get_db
)
from models import initialize_database
initialize_database()

import json
from datetime import datetime
import random
import string
import csv
import io

app = Flask(__name__)
app.secret_key = 'your-secret-key'

def generate_random_password(length=4):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

@app.route('/')
def home():
    return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = get_user(username)
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            return redirect('/dashboard')
        else:
            return render_template('login.html', error='Invalid credentials.')

    return render_template('login.html')

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

        # Fetch only sales for this business
        cur.execute('''
            SELECT s.*, p.name AS product_name, u.username AS salesperson_name
            FROM sales s
            JOIN products p ON s.product_id = p.id
            JOIN users u ON s.salesperson_id = u.id
            WHERE p.business_id = %s
            ORDER BY s.date DESC
        ''', (business_id,))
        sales = cur.fetchall()

        return render_template('dashboard_owner.html', sales=sales)

    else:  # salesperson
        # Get sales only for this salesperson
        cur.execute('''
            SELECT s.*, p.name AS product_name
            FROM sales s
            JOIN products p ON s.product_id = p.id
            WHERE s.salesperson_id = %s
            ORDER BY s.date DESC
        ''', (user_id,))
        sales = cur.fetchall()

        # Fetch user inventory
        cur.execute('''
            SELECT ui.*, p.name AS product_name, p.category
            FROM user_inventory ui
            JOIN products p ON ui.product_id = p.id
            WHERE ui.user_id = %s
        ''', (user_id,))
        inventory = cur.fetchall()

        return render_template('dashboard_sales.html', inventory=inventory, sales=sales, username=session['username'])

@app.route('/record_sale', methods=['GET'])
def record_sale():
    if 'user_id' not in session or session['role'] != 'salesperson':
        return redirect('/login')

    inventory = get_user_inventory(session['user_id'])

    # 🔁 Get all distinct categories from the products table
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL ORDER BY category")
    categories = [row['category'] for row in cur.fetchall()]

    return render_template("record_sale.html", products=inventory, categories=categories)


@app.route('/submit_sale', methods=['POST'])
def submit_sale():
    if 'user_id' not in session or session['role'] != 'salesperson':
        return redirect('/login')


    cart_data = request.form.get('cart_data')
    payment_method = request.form.get('payment_method')

    if not cart_data or not payment_method:
        return "Missing sale data or payment method", 400

    items = json.loads(cart_data)

    for item in items:
        product_id = int(item['productId'])
        quantity = int(item['quantity'])
        price = float(item['price'])
        try:
            add_sale(product_id, quantity, session['user_id'], price, payment_method)
        except ValueError as e:
            return str(e), 400

    return redirect('/dashboard')

@app.route('/products', methods=['GET', 'POST'])
def products():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    # Get the business ID for this owner
    cur.execute("SELECT business_id FROM users WHERE id = %s", (session['user_id'],))
    business = cur.fetchone()
    if not business:
        conn.close()
        return "Business not found", 400

    business_id = business['business_id']

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        if form_type == 'csv_upload':
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
                        SELECT id, quantity_available FROM products 
                        WHERE name = %s AND category = %s AND business_id = %s
                    """, (row['product name'], row['category'], business_id))
                    existing = cur.fetchone()

                    if existing:
                        new_qty = existing['quantity_available'] + int(row['quantity available'])
                        cur.execute("""
                            UPDATE products
                            SET quantity_available = %s,
                                buying_price = %s,
                                agent_price = %s,
                                wholesale_price = %s,
                                retail_price = %s
                            WHERE id = %s
                        """, (
                            new_qty,
                            float(row['buying price']),
                            float(row['agent price']),
                            float(row['wholesale price']),
                            float(row['retail price']),
                            existing['id']
                        ))
                    else:
                        cur.execute("""
                            INSERT INTO products (
                                category, name, quantity_available,
                                buying_price, agent_price, wholesale_price, retail_price, business_id
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            row['category'],
                            row['product name'],
                            int(row['quantity available']),
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

        elif form_type == 'manual_entry':
            category = request.form['category']
            name = request.form['name']
            quantity_available = int(request.form['quantity_available'])
            buying_price = float(request.form['buying_price'])
            agent_price = float(request.form['agent_price'])
            wholesale_price = float(request.form['wholesale_price'])
            retail_price = float(request.form['retail_price'])

            cur.execute("""
                SELECT id, quantity_available FROM products 
                WHERE name = %s AND category = %s AND business_id = %s
            """, (name, category, business_id))
            existing = cur.fetchone()

            if existing:
                new_qty = existing['quantity_available'] + quantity_available
                cur.execute("""
                    UPDATE products
                    SET quantity_available = %s,
                        buying_price = %s,
                        agent_price = %s,
                        wholesale_price = %s,
                        retail_price = %s
                    WHERE id = %s
                """, (
                    new_qty,
                    buying_price,
                    agent_price,
                    wholesale_price,
                    retail_price,
                    existing['id']
                ))
            else:
                cur.execute("""
                    INSERT INTO products (
                        category, name, quantity_available,
                        buying_price, agent_price, wholesale_price, retail_price, business_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    category, name, quantity_available,
                    buying_price, agent_price, wholesale_price, retail_price, business_id
                ))
            conn.commit()

    # --- Filtering Logic ---
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

    # For dropdown options
    cur.execute("SELECT DISTINCT category FROM products WHERE business_id = %s", (business_id,))
    categories = [row['category'] for row in cur.fetchall()]

    conn.close()
    return render_template('products.html', products=products,
                           categories=categories,
                           selected_category=selected_category,
                           selected_product=selected_product)

@app.route('/edit_product/<int:id>', methods=['GET', 'POST'])
def edit_product(id):
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

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
            WHERE id = %s
        ''', (category, name, buying_price,
              agent_price, wholesale_price, retail_price, id))
        conn.commit()
        return redirect('/products')

    cur.execute("SELECT * FROM products WHERE id = %s", (id,))
    product = cur.fetchone()
    if not product:
        return "Product not found", 404

    return render_template('edit_product.html', product=product)

@app.route('/restock_product/<int:id>', methods=['POST'])
def restock_product(id):
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    restock_qty = int(request.form['restock_qty'])

    conn = get_db()
    cur = conn.cursor()
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
    cur.execute("DELETE FROM products WHERE id = %s", (id,))
    conn.commit()
    return redirect('/products')

@app.route('/users', methods=['GET', 'POST'])
def manage_users():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    # Get the owner's business_id
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

        # Assign the new salesperson to the same business
        cur.execute("""
            INSERT INTO users (username, password, role, business_id)
            VALUES (%s, %s, %s, %s)
        """, (username, password_hash, role, business_id))
        conn.commit()
        new_user_id = cur.lastrowid
        initialize_salesperson_inventory(new_user_id)

    # Only list salespeople from this owner's business
    cur.execute("""
        SELECT id, username, role FROM users
        WHERE role = 'salesperson' AND business_id = %s
    """, (business_id,))
    users = cur.fetchall()

    return render_template('users.html', users=users)

@app.route('/delete_user', methods=['POST'])
def delete_user():
    user_id = request.form.get('user_id')
    conn = get_db()
    cur = conn.cursor()

    # Check if user has sales
    cur.execute("SELECT COUNT(*) FROM sales WHERE salesperson_id = %s", (user_id,))
    if cur.fetchone()[0] > 0:
        flash("❌ Cannot delete user: They have recorded sales.", "error")
        return redirect('/manage_users')

    # Safe to delete
    cur.execute("DELETE FROM users WHERE id = %s AND role = 'salesperson'", (user_id,))
    conn.commit()
    flash("✅ User deleted successfully.", "success")
    return redirect('/manage_users')

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

@app.route('/register_owner', methods=['GET', 'POST'])
def register_owner():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        fullname = request.form['fullname']
        business_name = request.form['business_name']
        business_type = request.form['business_type']
        location = request.form['location']

        conn = get_db()
        cur = conn.cursor()

        try:
            cur.execute(
                "INSERT INTO businesses (name, type, location) VALUES (%s, %s, %s) RETURNING id",
                (business_name, business_type, location)
            )
            result = cur.fetchone()
            print("DEBUG: Insert result =", result)

            # ✅ Updated access
            if result is None:
                print("ERROR: Business ID not returned.")
                conn.rollback()
                return "Failed to insert business.", 500

            business_id = result['id']

            password_hash = generate_password_hash(password)
            cur.execute(
                "INSERT INTO users (username, password, role, business_id) VALUES (%s, %s, 'owner', %s)",
                (username, password_hash, business_id)
            )

            conn.commit()
            return redirect('/login')

        except Exception as e:
            print("ERROR:", e)
            conn.rollback()
            return f"An error occurred: {e}", 500

    return render_template('register_owner.html')


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
    cur = conn.cursor()

    # Fetch logged-in user's ID
    current_user_id = session['user_id']

    # Get categories for filter dropdown
    cur.execute("SELECT DISTINCT category FROM products")
    categories = [row['category'] for row in cur.fetchall()]
    selected_category = request.args.get('category')

    # Get user's current inventory (filtered by category if needed)
    if selected_category:
        cur.execute('''
            SELECT ui.product_id, ui.quantity, p.name AS product_name
            FROM user_inventory ui
            JOIN products p ON ui.product_id = p.id
            WHERE ui.user_id = %s AND p.category = %s
        ''', (current_user_id, selected_category))
    else:
        cur.execute('''
            SELECT ui.product_id, ui.quantity, p.name AS product_name
            FROM user_inventory ui
            JOIN products p ON ui.product_id = p.id
            WHERE ui.user_id = %s
        ''', (current_user_id,))
    inventory = cur.fetchall()

    # Get list of other salespersons (to send request to)
    cur.execute("SELECT id, username FROM users WHERE role = 'salesperson' AND id != %s", (current_user_id,))
    recipients = cur.fetchall()

    # Handle form submission
    if request.method == 'POST':
        product_id = int(request.form['product_id'])
        recipient_id = int(request.form['recipient_id'])
        quantity = int(request.form['quantity'])
        requester_name = request.form['requester_name']

        cur.execute('''
            INSERT INTO stock_requests (
                product_id, requester_id, recipient_id, quantity, requester_name, status
            ) VALUES (%s, %s, %s, %s, %s, 'pending')
        ''', (product_id, current_user_id, recipient_id, quantity, requester_name))


        conn.commit()
        return redirect('/dashboard')

    return render_template('request_stock.html',
                           categories=categories,
                           selected_category=selected_category,
                           inventory=inventory,
                           recipients=recipients)

@app.route('/my_inventory', methods=['GET'])
def my_inventory():
    if 'user_id' not in session or session['role'] != 'salesperson':
        return redirect('/login')

    user_id = session['user_id']
    category = request.args.get('category', '')
    search_term = request.args.get('search', '')

    conn = get_db()
    cur = conn.cursor()

    # Get all categories for dropdown
    cur.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL ORDER BY category")
    categories = [row['category'] for row in cur.fetchall()]

    # Build query based on filters
    query = '''
        SELECT ui.*, 
               p.category,
               p.name AS product_name,  
               p.agent_price,
               p.wholesale_price,
               p.retail_price
        FROM user_inventory ui
        JOIN products p ON ui.product_id = p.id
        WHERE ui.user_id = %s
    '''
    params = [user_id]

    if category:
        query += ' AND p.category = %s'
        params.append(category)

    if search_term:
        query += ' AND LOWER(p.name) LIKE %s'
        params.append(f"%{search_term.lower()}%")

    cur.execute(query, params)
    inventory = cur.fetchall()

    return render_template('my_inventory.html',
                           inventory=inventory,
                           categories=categories,
                           selected_category=category,
                           search_term=search_term)

""
@app.route('/report', methods=['GET', 'POST'])
def report():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    # Get business_id for this owner
    cur.execute("SELECT business_id FROM users WHERE id = %s", (session['user_id'],))
    business = cur.fetchone()
    if not business:
        return "Business not found", 400
    business_id = business['business_id']

    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    salesperson = request.form.get('salesperson')
    payment_method = request.form.get('payment_method')

    summary = {'total_transactions': 0, 'total_quantity': 0, 'total_revenue': 0}
    top_salesperson = {'top_salesperson': 'N/A', 'total': 0}

    # Report Data
    query = '''
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

    # Summary
    sum_query = '''
        SELECT COUNT(*) AS total_transactions,
               SUM(quantity) AS total_quantity,
               SUM(quantity * price) AS total_revenue
        FROM sales s
        JOIN products p ON s.product_id = p.id
        WHERE p.business_id = %s
    '''
    sum_params = [business_id]
    if start_date:
        sum_query += ' AND date(s.date) >= date(%s)'
        sum_params.append(start_date)
    if end_date:
        sum_query += ' AND date(s.date) <= date(%s)'
        sum_params.append(end_date)
    if payment_method:
        sum_query += ' AND s.payment_method = %s'
        sum_params.append(payment_method)

    cur.execute(sum_query, sum_params)
    sum_result = cur.fetchone()
    if sum_result and sum_result['total_transactions'] is not None:
        summary = sum_result

    # Top Salesperson
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
    if payment_method:
        top_query += ' AND s.payment_method = %s'
        top_params.append(payment_method)

    top_query += ' GROUP BY s.salesperson_id, u.username ORDER BY total DESC LIMIT 1'
    cur.execute(top_query, top_params)
    top_result = cur.fetchone()
    if top_result:
        top_salesperson = top_result

    # Distribution Log — filtered by business_id
    dist_query = '''
        SELECT d.timestamp,
            p.name as product_name,
            u_from.username as from_salesperson,
            u_to.username as to_salesperson,
            d.quantity,
            d.status
        FROM distribution_log d
        JOIN products p ON d.product_id = p.id
        JOIN users u_from ON u_from.id = d.salesperson_id
        JOIN users u_to ON u_to.id = d.receiver_id
        WHERE p.business_id = %s
    '''
    dist_params = [business_id]

    if start_date:
        dist_query += ' AND date(d.timestamp) >= date(%s)'
        dist_params.append(start_date)
    if end_date:
        dist_query += ' AND date(d.timestamp) <= date(%s)'
        dist_params.append(end_date)

    dist_query += ' ORDER BY d.timestamp DESC'
    cur.execute(dist_query, dist_params)
    distribution_log = [dict(row) for row in cur.fetchall()]


    return render_template('report.html',
                       report=report_data,
                       salespeople=salespeople,
                       summary=summary,
                       top_salesperson=top_salesperson,
                       distribution_log=distribution_log)

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

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        # === Handle CSV Upload ===
        if form_type == 'csv_upload':
            file = request.files.get('file')
            if not file or not file.filename.endswith('.csv'):
                return "Please upload a valid CSV file", 400

            import csv
            reader = csv.DictReader(file.read().decode('utf-8').splitlines())
            inventory_rows = []

            for row in reader:
                try:
                    product_name = row['Product Name'].strip()
                    quantity = int(row['Quantity'])
                    category = row['Category'].strip()
                    inventory_rows.append((product_name, quantity, category))
                except Exception as e:
                    return f"Error in row: {row} — {str(e)}", 400

            try:
                add_salesperson_stock_bulk(session['user_id'], inventory_rows)
            except Exception as e:
                return f"Upload failed: {str(e)}", 500

            return redirect('/dashboard')

        # === Handle Cart Upload ===
        cart_data = request.form.get('cart_data')
        if not cart_data:
            return "Error: No stock data submitted.", 400

        try:
            items = json.loads(cart_data)
            inventory_rows = [
                (item['product_name'], int(item['quantity']), item['category'])
                for item in items
            ]
            add_salesperson_stock_bulk(session['user_id'], inventory_rows)
        except Exception as e:
            return f"Error processing cart: {str(e)}", 400

        return redirect('/dashboard')

    # === Render form on GET ===
    cur.execute("SELECT name FROM products ORDER BY name")
    products = cur.fetchall()
    product_names = [row['name'] for row in products]

    return render_template('sales_upload_inventory.html', product_names=product_names)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True)