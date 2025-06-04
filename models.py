import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
from datetime import datetime


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def initialize_database():
    conn = get_db()
    cur = conn.cursor()

    # # Drop tables in order to avoid dependency issues
    # cur.execute('DROP TABLE IF EXISTS credit_repayments CASCADE;')
    # cur.execute('DROP TABLE IF EXISTS credit_sales CASCADE;')
    # cur.execute('DROP TABLE IF EXISTS stock_requests CASCADE;')
    # cur.execute('DROP TABLE IF EXISTS user_inventory CASCADE;')
    # cur.execute('DROP TABLE IF EXISTS distribution_log CASCADE;')
    # cur.execute('DROP TABLE IF EXISTS sales CASCADE;')
    # cur.execute('DROP TABLE IF EXISTS customers CASCADE;')
    # cur.execute('DROP TABLE IF EXISTS products CASCADE;')
    # cur.execute('DROP TABLE IF EXISTS users CASCADE;')
    # cur.execute('DROP TABLE IF EXISTS businesses CASCADE;')

    # Businesses
    cur.execute('''
        CREATE TABLE IF NOT EXISTS businesses (
            id SERIAL PRIMARY KEY,
            name TEXT,
            type TEXT,
            location TEXT
        );
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            business_id INTEGER REFERENCES businesses(id),
            is_active BOOLEAN DEFAULT TRUE
        );
    ''')


    # Products
    cur.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            category TEXT,
            name TEXT NOT NULL,
            quantity_available INTEGER,
            buying_price FLOAT,
            agent_price FLOAT,
            wholesale_price FLOAT,
            retail_price FLOAT,
            business_id INTEGER REFERENCES businesses(id)
        );
    ''')

    # Customers
    cur.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id SERIAL PRIMARY KEY,
            business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')

    # Sales
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES products(id),
            quantity INTEGER,
            price FLOAT,
            payment_method TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            salesperson_id INTEGER REFERENCES users(id),
            business_id INTEGER REFERENCES businesses(id),
            amount_paid FLOAT DEFAULT 0,
            payment_status TEXT DEFAULT 'unpaid',
            customer_id INTEGER REFERENCES customers(id),
            batch_no VARCHAR(50)
        );
    ''')


    # Credit Sales
    cur.execute('''
        CREATE TABLE IF NOT EXISTS credit_sales (
            id SERIAL PRIMARY KEY,
            sale_id INTEGER REFERENCES sales(id) ON DELETE CASCADE,
            customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
            amount NUMERIC NOT NULL,
            balance NUMERIC NOT NULL,
            due_date DATE,
            status TEXT CHECK (status IN ('unpaid', 'partial', 'paid')) DEFAULT 'unpaid'
        );
    ''')

    # Credit Repayments
    cur.execute('''
        CREATE TABLE IF NOT EXISTS credit_repayments (
            id SERIAL PRIMARY KEY,
            credit_id INTEGER REFERENCES credit_sales(id) ON DELETE CASCADE,
            amount NUMERIC NOT NULL,
            paid_on DATE DEFAULT CURRENT_DATE
        );
    ''')

    # Distribution Log
    cur.execute('''
        CREATE TABLE IF NOT EXISTS distribution_log (
            id SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES products(id),
            salesperson_id INTEGER REFERENCES users(id),
            receiver_id INTEGER REFERENCES users(id),
            quantity INTEGER,
            status TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')

    # User Inventory
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_inventory (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            product_id INTEGER REFERENCES products(id),
            quantity INTEGER DEFAULT 0,
            UNIQUE(user_id, product_id)
        );
    ''')

    # Stock Requests
    cur.execute('''
        CREATE TABLE IF NOT EXISTS stock_requests (
            id SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES products(id),
            requester_id INTEGER REFERENCES users(id),
            recipient_id INTEGER REFERENCES users(id),
            quantity INTEGER,
            requester_name TEXT,
            status TEXT DEFAULT 'pending',
            rejection_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')

    conn.commit()
    cur.close()
    conn.close()

def get_user(username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
    return cur.fetchone()

def get_products():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products ORDER BY id DESC")
    products = cur.fetchall()
    cur.close()
    conn.close()
    return products

def get_sales(conn, salesperson_id=None):
    cur = conn.cursor()
    if salesperson_id:
        cur.execute("""
            SELECT s.*, 
                   p.name AS product_name, 
                   p.retail_price AS unit_price, 
                   u.username AS salesperson_name,
                   (s.quantity * p.retail_price) AS total_price
            FROM sales s
            JOIN products p ON s.product_id = p.id
            JOIN users u ON s.salesperson_id = u.id
            WHERE s.salesperson_id = %s
            ORDER BY s.date DESC
            LIMIT 10
        """, (salesperson_id,))
    else:
        cur.execute("""
            SELECT s.*, 
                   p.name AS product_name, 
                   p.retail_price AS unit_price, 
                   u.username AS salesperson_name,
                   (s.quantity * p.retail_price) AS total_price
            FROM sales s
            JOIN products p ON s.product_id = p.id
            JOIN users u ON s.salesperson_id = u.id
            ORDER BY s.date DESC
            LIMIT 10
        """)
    return cur.fetchall()

def get_user_inventory(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT ui.*, p.name AS product_name, p.category,
               p.agent_price, p.wholesale_price, p.retail_price
        FROM user_inventory ui
        JOIN products p ON ui.product_id = p.id
        WHERE ui.user_id = %s
    """, (user_id,))
    return cur.fetchall()

def add_sale(product_id, quantity, salesperson_id, price, payment_method, customer_id=None, due_date=None):
    conn = get_db()
    cur = conn.cursor()

    # Step 1: Check inventory
    cur.execute("""
        SELECT quantity FROM user_inventory
        WHERE user_id = %s AND product_id = %s
    """, (salesperson_id, product_id))
    inv = cur.fetchone()

    if not inv or inv['quantity'] < quantity:
        raise ValueError("❌ Not enough stock in your inventory.")

    # Step 2: Update inventory
    cur.execute("""
        UPDATE user_inventory
        SET quantity = quantity - %s
        WHERE user_id = %s AND product_id = %s
    """, (quantity, salesperson_id, product_id))

    # Step 3: Get business ID
    cur.execute("""
        SELECT business_id FROM users WHERE id = %s
    """, (salesperson_id,))
    business = cur.fetchone()
    if not business:
        raise ValueError("❌ Salesperson has no associated business.")
    business_id = business['business_id']

    # Step 4: Determine payment details
    total_amount = quantity * price
    amount_paid = total_amount if payment_method.lower() == 'cash' else 0
    payment_status = 'paid' if payment_method.lower() == 'cash' else 'unpaid'

    # Step 5: Insert sale
    if payment_method.lower() == 'cash':
        cur.execute("""
            INSERT INTO sales (
                product_id, quantity, salesperson_id, price, payment_method,
                date, amount_paid, payment_status, business_id
            ) VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s)
            RETURNING id
        """, (product_id, quantity, salesperson_id, price, payment_method,
              amount_paid, payment_status, business_id))
    else:
        if not customer_id:
            raise ValueError("❌ Credit sales must have an assigned customer.")
        cur.execute("""
            INSERT INTO sales (
                product_id, quantity, salesperson_id, price, payment_method,
                date, amount_paid, payment_status, business_id, customer_id
            ) VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s)
            RETURNING id
        """, (product_id, quantity, salesperson_id, price, payment_method,
              amount_paid, payment_status, business_id, customer_id))

    sale_id = cur.fetchone()['id']

    # Step 6: Credit sale record
    if payment_method.lower() == 'credit':
        cur.execute("""
            INSERT INTO credit_sales (
                sale_id, customer_id, amount, balance, due_date, status
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """, (sale_id, customer_id, total_amount, total_amount, due_date, 'unpaid'))

    conn.commit()
    cur.close()
    conn.close()

def get_customers_for_business(business_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM customers WHERE business_id = %s ORDER BY name", (business_id,))
    return cur.fetchall()

def add_salesperson_stock_bulk(user_id, inventory_rows):
    conn = get_db()
    cur = conn.cursor()

    for product_name, quantity, category in inventory_rows:
        product_name = product_name.strip()
        category = category.strip()

        # Case-insensitive match
        cur.execute("""
            SELECT id FROM products
            WHERE LOWER(name) = LOWER(%s) AND LOWER(category) = LOWER(%s)
        """, (product_name, category))
        product = cur.fetchone()

        if not product:
            raise ValueError(f"❌ Product not found: '{product_name}' in category '{category}'. Please check spelling or upload via CSV for auto-match.")

        product_id = product['id']

        # Check for existing inventory
        cur.execute("""
            SELECT quantity FROM user_inventory
            WHERE user_id = %s AND product_id = %s
        """, (user_id, product_id))
        existing = cur.fetchone()

        if existing:
            new_qty = existing['quantity'] + quantity
            cur.execute("""
                UPDATE user_inventory
                SET quantity = %s
                WHERE user_id = %s AND product_id = %s
            """, (new_qty, user_id, product_id))
        else:
            cur.execute("""
                INSERT INTO user_inventory (user_id, product_id, quantity)
                VALUES (%s, %s, %s)
            """, (user_id, product_id, quantity))

    conn.commit()

def initialize_salesperson_inventory(user_id):
    conn = get_db()
    cur = conn.cursor()
    
    # Get business_id of the user
    cur.execute("SELECT business_id FROM users WHERE id = %s", (user_id,))
    result = cur.fetchone()
    if not result:
        raise ValueError("Business ID not found for user.")
    business_id = result['business_id']

    # Get all product IDs for that business
    cur.execute("SELECT id FROM products WHERE business_id = %s", (business_id,))
    products = cur.fetchall()

    for product in products:
        cur.execute(
            "INSERT INTO user_inventory (user_id, product_id, quantity) VALUES (%s, %s, 0)",
            (user_id, product['id'])
        )

    conn.commit()
    cur.close()
    conn.close()

def approve_request(request_id, user_id):
    conn = get_db()
    cur = conn.cursor()

    # Get request details
    cur.execute("""
        SELECT sr.product_id, sr.quantity, sr.requester_id
        FROM stock_requests sr
        WHERE sr.id = %s AND sr.recipient_id = %s AND sr.status = 'pending'
    """, (request_id, user_id))
    request = cur.fetchone()

    if not request:
        return "not_found"

    product_id = request['product_id']
    quantity = request['quantity']
    requester_id = request['requester_id']

    # ✅ Check recipient's stock
    cur.execute("""
        SELECT quantity FROM user_inventory
        WHERE user_id = %s AND product_id = %s
    """, (user_id, product_id))
    inventory = cur.fetchone()

    if not inventory or inventory['quantity'] < quantity:
        return "insufficient_stock"  # This will trigger the popup in your app.py

    # ✅ Proceed with transfer
    cur.execute("""
        UPDATE stock_requests
        SET status = 'approved'
        WHERE id = %s
    """, (request_id,))

    # Deduct from recipient
    cur.execute("""
        UPDATE user_inventory
        SET quantity = quantity - %s
        WHERE user_id = %s AND product_id = %s
    """, (quantity, user_id, product_id))

    # Add to requester (insert if doesn't exist)
    cur.execute("""
        INSERT INTO user_inventory (user_id, product_id, quantity)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, product_id)
        DO UPDATE SET quantity = user_inventory.quantity + %s
    """, (requester_id, product_id, quantity, quantity))

    # Optional: log the distribution
    cur.execute("""
        INSERT INTO distribution_log (product_id, salesperson_id, receiver_id, quantity, status)
        VALUES (%s, %s, %s, %s, 'approved')
    """, (product_id, user_id, requester_id, quantity))

    conn.commit()
    return "approved"

def generate_batch_number(salesperson_name, conn):
    initials = ''.join(part[0] for part in salesperson_name.strip().split()).upper()
    date_str = datetime.now().strftime("%Y%m%d")

    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM sales 
        WHERE batch_no LIKE %s
    """, (f"{initials}_{date_str}_%",))
    count = cur.fetchone()[0] + 1

    batch_number = f"{initials}_{date_str}_{count:03d}"
    return batch_number

def reject_request(request_id, user_id, reason):
    conn = get_db()
    cur = conn.cursor()

    # Log the rejection in distribution_log
    cur.execute("""
        INSERT INTO distribution_log (product_id, salesperson_id, receiver_id, quantity, status)
        SELECT product_id, recipient_id, requester_id, quantity, 'rejected'
        FROM stock_requests
        WHERE id = %s AND recipient_id = %s
    """, (request_id, user_id))

    # Update the request status to rejected
    cur.execute("""
        UPDATE stock_requests
        SET status = 'rejected', rejection_reason = %s
        WHERE id = %s AND recipient_id = %s
    """, (reason, request_id, user_id))

    conn.commit()

def get_all_categories(business_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT category FROM products
        WHERE business_id = %s
        ORDER BY category ASC
    """, (business_id,))
    rows = cur.fetchall()
    return [row['category'] for row in rows if row['category']]

def get_pending_requests_for_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT sr.*, 
               p.name AS product_name, 
               u.username AS requester_username,
               COALESCE(inv.quantity, 0) AS reviewer_stock
        FROM stock_requests sr
        JOIN products p ON sr.product_id = p.id
        JOIN users u ON sr.requester_id = u.id
        LEFT JOIN user_inventory inv 
            ON inv.user_id = sr.recipient_id AND inv.product_id = sr.product_id
        WHERE sr.recipient_id = %s AND sr.status = 'pending'
        ORDER BY sr.id DESC
    """, (user_id,))
    return cur.fetchall()
