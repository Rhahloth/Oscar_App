
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def initialize_database():
    conn = get_db()
    cur = conn.cursor()

   # cur.execute('DROP TABLE IF EXISTS users CASCADE;')
    # cur.execute('DROP TABLE IF EXISTS user_inventory CASCADE;')
    # cur.execute('DROP TABLE IF EXISTS products CASCADE;')
    # cur.execute('DROP TABLE IF EXISTS businesses CASCADE;')
    # cur.execute('DROP TABLE IF EXISTS distribution_log CASCADE;')
    # cur.execute('DROP TABLE IF EXISTS sales CASCADE;')

    # Businesses
    cur.execute('''
        CREATE TABLE IF NOT EXISTS businesses (
            id SERIAL PRIMARY KEY,
            name TEXT,
            type TEXT,
            location TEXT
        );
    ''')

    # Users
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            business_id INTEGER REFERENCES businesses(id)
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
            business_id INTEGER REFERENCES businesses(id)
        );
    ''')

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

def add_sale(product_id, quantity, salesperson_id, price, payment_method):
    conn = get_db()
    cur = conn.cursor()

    # Step 1: Check salesperson inventory
    cur.execute("""
        SELECT quantity FROM user_inventory
        WHERE user_id = %s AND product_id = %s
    """, (salesperson_id, product_id))
    inv = cur.fetchone()

    if not inv or inv['quantity'] < quantity:
        raise ValueError("❌ Not enough stock in your inventory.")

    # Step 2: Subtract quantity from salesperson's inventory
    new_quantity = inv['quantity'] - quantity
    cur.execute("""
        UPDATE user_inventory
        SET quantity = %s
        WHERE user_id = %s AND product_id = %s
    """, (new_quantity, salesperson_id, product_id))

    # Step 3: Record the sale
    cur.execute("""
        INSERT INTO sales (product_id, quantity, salesperson_id, price, payment_method, date)
        VALUES (%s, %s, %s, %s, %s, NOW())
    """, (product_id, quantity, salesperson_id, price, payment_method))

    # ✅ No update to warehouse stock in products table
    conn.commit()
    cur.close()
    conn.close()

def add_salesperson_stock_bulk(user_id, inventory_rows):
    conn = get_db()
    cur = conn.cursor()

    for product_name, quantity, category in inventory_rows:
        # Find product ID by name and category
        cur.execute("""
            SELECT id FROM products
            WHERE name = %s AND category = %s
        """, (product_name, category))
        product = cur.fetchone()

        if not product:
            raise ValueError(f"❌ Product not found: {product_name} - {category}")

        product_id = product['id']

        # Check if inventory already exists for this user/product
        cur.execute("""
            SELECT quantity FROM user_inventory
            WHERE user_id = %s AND product_id = %s
        """, (user_id, product_id))
        existing = cur.fetchone()

        if existing:
            # Update quantity
            new_qty = existing['quantity'] + quantity
            cur.execute("""
                UPDATE user_inventory
                SET quantity = %s
                WHERE user_id = %s AND product_id = %s
            """, (new_qty, user_id, product_id))
        else:
            # Insert new inventory row
            cur.execute("""
                INSERT INTO user_inventory (user_id, product_id, quantity)
                VALUES (%s, %s, %s)
            """, (user_id, product_id, quantity))

    conn.commit()

def initialize_salesperson_inventory(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM products")
    products = cur.fetchall()
    for product in products:
        cur.execute("INSERT INTO user_inventory (user_id, product_id, quantity) VALUES (%s, %s, 0)",
                    (user_id, product["id"]))
    conn.commit()

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
