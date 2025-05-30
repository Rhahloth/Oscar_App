from flask import Flask, render_template, request, redirect, session, url_for, send_file, Response
from werkzeug.security import check_password_hash, generate_password_hash
from models import (
    init_db, get_user, get_sales, get_products, add_sale, get_user_inventory,
    add_salesperson_stock, approve_request, reject_request, get_pending_requests_for_user,
    initialize_salesperson_inventory, get_db
)

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
    if session['role'] == 'owner':
        sales = get_sales(conn)
        return render_template('dashboard_owner.html', sales=sales)
    else:
        inventory = get_user_inventory(session['user_id'])
        sales = get_sales(conn, salesperson_id=session['user_id'])
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
                    cur.execute("SELECT id, quantity_available FROM products WHERE name = ?", (row['product name'],))
                    existing = cur.fetchone()

                    if existing:
                        new_qty = existing['quantity_available'] + int(row['quantity available'])
                        cur.execute('''
                            UPDATE products
                            SET quantity_available = ?,
                                buying_price = ?,
                                agent_price = ?,
                                wholesale_price = ?,
                                retail_price = ?,
                                category = ?
                            WHERE id = ?
                        ''', (
                            new_qty,
                            float(row['buying price']),
                            float(row['agent price']),
                            float(row['wholesale price']),
                            float(row['retail price']),
                            row['category'],
                            existing['id']
                        ))
                    else:
                        cur.execute('''
                            INSERT INTO products (
                                category, name, quantity_available,
                                buying_price, agent_price, wholesale_price, retail_price
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            row['category'],
                            row['product name'],
                            int(row['quantity available']),
                            float(row['buying price']),
                            float(row['agent price']),
                            float(row['wholesale price']),
                            float(row['retail price'])
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

            cur.execute("SELECT id, quantity_available FROM products WHERE name = ?", (name,))
            existing = cur.fetchone()

            if existing:
                new_qty = existing['quantity_available'] + quantity_available
                cur.execute('''
                    UPDATE products
                    SET quantity_available = ?,
                        buying_price = ?,
                        agent_price = ?,
                        wholesale_price = ?,
                        retail_price = ?,
                        category = ?
                    WHERE id = ?
                ''', (
                    new_qty,
                    buying_price,
                    agent_price,
                    wholesale_price,
                    retail_price,
                    category,
                    existing['id']
                ))
            else:
                cur.execute('''
                    INSERT INTO products (
                        category, name, quantity_available,
                        buying_price, agent_price, wholesale_price, retail_price
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    category, name, quantity_available,
                    buying_price, agent_price, wholesale_price, retail_price
                ))
            conn.commit()

    # --- Filtering Logic ---
    selected_category = request.args.get('category', '')
    selected_product = request.args.get('product', '')

    query = "SELECT * FROM products WHERE 1=1"
    params = []

    if selected_category:
        query += " AND category = ?"
        params.append(selected_category)
    if selected_product:
        query += " AND name = ?"
        params.append(selected_product)

    cur.execute(query, params)
    products = cur.fetchall()

    # For dropdown options
    cur.execute("SELECT DISTINCT category FROM products")
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
            SET category = ?, name = ?, buying_price = ?,
                agent_price = ?, wholesale_price = ?, retail_price = ?
            WHERE id = ?
        ''', (category, name, buying_price,
              agent_price, wholesale_price, retail_price, id))
        conn.commit()
        return redirect('/products')

    cur.execute("SELECT * FROM products WHERE id = ?", (id,))
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
        SET quantity_available = quantity_available + ?
        WHERE id = ?
    ''', (restock_qty, id))

    conn.commit()
    return redirect('/products')

@app.route('/delete_product/<int:id>', methods=['POST'])
def delete_product(id):
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id = ?", (id,))
    conn.commit()
    return redirect('/products')

@app.route('/users', methods=['GET', 'POST'])
def manage_users():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = 'salesperson'
        password_hash = generate_password_hash(password)

        cur.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                    (username, password_hash, role))
        conn.commit()
        new_user_id = cur.lastrowid
        initialize_salesperson_inventory(new_user_id)


    cur.execute("SELECT id, username, role FROM users WHERE role = 'salesperson'")
    users = cur.fetchall()
    return render_template('users.html', users=users)

@app.route('/delete_user', methods=['POST'])
def delete_user():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    user_id = int(request.form['user_id'])

    # Prevent deleting the currently logged-in user or the owner
    if user_id == session['user_id']:
        return "You cannot delete yourself.", 403

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id = ? AND role = 'salesperson'", (user_id,))
    conn.commit()
    return redirect('/users')

@app.route('/reset_password', methods=['POST'])
def reset_password():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    user_id = int(request.form['user_id'])
    new_password = generate_random_password()
    password_hash = generate_password_hash(new_password)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET password = ? WHERE id = ? AND role = 'salesperson'", (password_hash, user_id))
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

        cur.execute("INSERT INTO businesses (name, type, location) VALUES (?, ?, ?)",
                    (business_name, business_type, location))
        business_id = cur.lastrowid

        password_hash = generate_password_hash(password)
        cur.execute("INSERT INTO users (username, password, role, business_id) VALUES (?, ?, 'owner', ?)",
                    (username, password_hash, business_id))

        conn.commit()
        return redirect('/login')

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

        return redirect('/dashboard')

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
    cur.execute('''
        SELECT category, name, quantity_available,
               buying_price, agent_price, wholesale_price, retail_price
        FROM products
    ''')
    products = cur.fetchall()

    def generate():
        data = csv.writer([])
        output = []
        writer = csv.writer(output)
        writer.writerow([
            "Category", "Product Name", "Quantity Available",
            "Buying Price", "Agent Price", "Wholesale Price", "Retail Price"
        ])
        for p in products:
            writer.writerow([
                p["category"], p["name"], p["quantity_available"],
                p["buying_price"], p["agent_price"], p["wholesale_price"], p["retail_price"]
            ])
        return "\n".join(output)

    headers = {
        "Content-Disposition": "attachment; filename=products.csv",
        "Content-Type": "text/csv"
    }

    # Alternative using StringIO if needed
    import io
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow([
        "Category", "Product Name", "Quantity Available",
        "Buying Price", "Agent Price", "Wholesale Price", "Retail Price"
    ])
    for p in products:
        cw.writerow([
            p["category"], p["name"], p["quantity_available"],
            p["buying_price"], p["agent_price"], p["wholesale_price"], p["retail_price"]
        ])

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
            WHERE ui.user_id = ? AND p.category = ?
        ''', (current_user_id, selected_category))
    else:
        cur.execute('''
            SELECT ui.product_id, ui.quantity, p.name AS product_name
            FROM user_inventory ui
            JOIN products p ON ui.product_id = p.id
            WHERE ui.user_id = ?
        ''', (current_user_id,))
    inventory = cur.fetchall()

    # Get list of other salespersons (to send request to)
    cur.execute("SELECT id, username FROM users WHERE role = 'salesperson' AND id != ?", (current_user_id,))
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
            ) VALUES (?, ?, ?, ?, ?, 'pending')
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
        WHERE ui.user_id = ?
    '''
    params = [user_id]

    if category:
        query += ' AND p.category = ?'
        params.append(category)

    if search_term:
        query += ' AND LOWER(p.name) LIKE ?'
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

    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    salesperson = request.form.get('salesperson')
    payment_method = request.form.get('payment_method')

    summary = {'total_transactions': 0, 'total_quantity': 0, 'total_revenue': 0}
    top_salesperson = {'top_salesperson': 'N/A', 'total': 0}
    report_data = []
    distribution_log = []

    # Report Data: Sales grouped by salesperson and payment method
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
        WHERE 1=1
    '''
    params = []

    if start_date:
        query += ' AND date(s.date) >= date(?)'
        params.append(start_date)
    if end_date:
        query += ' AND date(s.date) <= date(?)'
        params.append(end_date)
    if salesperson:
        query += ' AND u.username = ?'
        params.append(salesperson)
    if payment_method:
        query += ' AND s.payment_method = ?'
        params.append(payment_method)

    query += ' GROUP BY u.username, s.payment_method ORDER BY total_selling_price DESC'
    cur.execute(query, params)
    report_data = [dict(row) for row in (cur.fetchall() or [])]

    # Summary
    sum_query = '''
        SELECT COUNT(*) AS total_transactions,
               SUM(quantity) AS total_quantity,
               SUM(quantity * price) AS total_revenue
        FROM sales
        WHERE 1=1
    '''
    sum_params = []
    if start_date:
        sum_query += ' AND date(date) >= date(?)'
        sum_params.append(start_date)
    if end_date:
        sum_query += ' AND date(date) <= date(?)'
        sum_params.append(end_date)
    if payment_method:
        sum_query += ' AND payment_method = ?'
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
        WHERE 1=1
    '''
    top_params = []
    if start_date:
        top_query += ' AND date(s.date) >= date(?)'
        top_params.append(start_date)
    if end_date:
        top_query += ' AND date(s.date) <= date(?)'
        top_params.append(end_date)
    if payment_method:
        top_query += ' AND s.payment_method = ?'
        top_params.append(payment_method)

    top_query += ' GROUP BY s.salesperson_id ORDER BY total DESC LIMIT 1'
    cur.execute(top_query, top_params)
    top_result = cur.fetchone()
    if top_result:
        top_salesperson = top_result

    # Updated Distribution Log
    dist_query = '''
        SELECT d.timestamp,
               p.name as product_name,
               u_from.username as from_salesperson,
               u_to.username as to_salesperson,
               d.quantity,
               d.status
        FROM distribution_log d
        JOIN products p ON p.id = d.product_id
        JOIN users u_from ON u_from.id = d.salesperson_id
        JOIN users u_to ON u_to.id = d.receiver_id
        WHERE 1=1
    '''
    dist_params = []
    if start_date:
        dist_query += ' AND date(d.timestamp) >= date(?)'
        dist_params.append(start_date)
    if end_date:
        dist_query += ' AND date(d.timestamp) <= date(?)'
        dist_params.append(end_date)

    dist_query += ' ORDER BY d.timestamp DESC'
    cur.execute(dist_query, dist_params)
    distribution_log = [dict(row) for row in (cur.fetchall() or [])]

    # Salespeople dropdown
    cur.execute("SELECT username FROM users ORDER BY username")
    salespeople = [r['username'] for r in cur.fetchall()]

    return render_template('report.html',
                           report=report_data,
                           salespeople=salespeople,
                           summary=summary,
                           top_salesperson=top_salesperson,
                           distribution_log=distribution_log)
""
@app.route('/export_report', methods=['POST'])
def export_report():
    if 'user_id' not in session or session['role'] != 'owner':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

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
        WHERE 1=1
    '''
    params = []

    if start_date:
        query += ' AND date(s.date) >= date(?)'
        params.append(start_date)
    if end_date:
        query += ' AND date(s.date) <= date(?)'
        params.append(end_date)
    if salesperson:
        query += ' AND u.username = ?'
        params.append(salesperson)
    if payment_method:
        query += ' AND s.payment_method = ?'
        params.append(payment_method)

    query += ' GROUP BY u.username, s.payment_method ORDER BY total_selling_price DESC'

    cur.execute(query, params)
    report_data = cur.fetchall()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["Salesperson", "Payment Type", "Sales Count", "Total Quantity", "Buying Price", "Selling Price", "Profit"])
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

from models import add_salesperson_stock

@app.route('/sales_upload_inventory', methods=['GET', 'POST'])
def sales_upload_inventory():
    if 'user_id' not in session or session['role'] != 'salesperson':
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        # Handle CSV Upload
        if form_type == 'csv_upload':
            file = request.files.get('file')
            if not file or not file.filename.endswith('.csv'):
                return "Please upload a valid CSV file", 400

            import csv
            reader = csv.DictReader(file.read().decode('utf-8').splitlines())
            for row in reader:
                try:
                    product_name = row['Product Name'].strip()
                    quantity = int(row['Quantity'])
                    add_salesperson_stock(session['user_id'], product_name, quantity)
                except Exception as e:
                    return f"Error in row: {row} — {str(e)}", 400

            return redirect('/dashboard')

        # Handle Cart Upload
        cart_data = request.form.get('cart_data')
        if not cart_data:
            return "Error: No stock data submitted.", 400

        try:
            items = json.loads(cart_data)
            for item in items:
                product_name = item['product_name']
                quantity = int(item['quantity'])
                add_salesperson_stock(session['user_id'], product_name, quantity)
        except Exception as e:
            return f"Error processing cart: {str(e)}", 400

        return redirect('/dashboard')

    # Render form on GET
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
    