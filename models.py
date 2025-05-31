
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
    
    # Drop incorrect table if it exists
    cur.execute('DROP TABLE IF EXISTS salesperson_inventory CASCADE;')
    
    # User Inventory
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_inventory (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            product_id INTEGER REFERENCES products(id),
            quantity INTEGER
        );
    ''')

    # Stock Requests
    cur.execute('''
        CREATE TABLE IF NOT EXISTS stock_requests (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            product_id INTEGER REFERENCES products(id),
            quantity INTEGER,
            status TEXT DEFAULT 'pending',
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

    # Check if user has enough inventory
    cur.execute("SELECT quantity FROM user_inventory WHERE user_id = %s AND product_id = %s", (salesperson_id, product_id))
    result = cur.fetchone()
    if not result or result["quantity"] < quantity:
        raise ValueError("Insufficient inventory")

    cur.execute("""
        INSERT INTO sales (product_id, quantity, salesperson_id, price, payment_method)
        VALUES (%s, %s, %s, %s, %s)
    """, (product_id, quantity, salesperson_id, price, payment_method))

    cur.execute("""
        UPDATE user_inventory SET quantity = quantity - %s
        WHERE user_id = %s AND product_id = %s
    """, (quantity, salesperson_id, product_id))

    conn.commit()

def add_salesperson_stock(user_id, product_name, quantity):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM products WHERE name = %s", (product_name,))
    product = cur.fetchone()
    if not product:
        raise ValueError("Product not found")

    product_id = product["id"]

    cur.execute("SELECT quantity FROM user_inventory WHERE user_id = %s AND product_id = %s", (user_id, product_id))
    existing = cur.fetchone()
    if existing:
        cur.execute("UPDATE user_inventory SET quantity = quantity + %s WHERE user_id = %s AND product_id = %s",
                    (quantity, user_id, product_id))
    else:
        cur.execute("INSERT INTO user_inventory (user_id, product_id, quantity) VALUES (%s, %s, %s)",
                    (user_id, product_id, quantity))

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

    cur.execute("""
        SELECT product_id, quantity FROM stock_requests
        WHERE id = %s AND recipient_id = %s AND status = 'pending'
    """, (request_id, user_id))
    req = cur.fetchone()
    if not req:
        return "not_found"

    product_id = req["product_id"]
    qty = req["quantity"]

    # Check if user has enough stock
    cur.execute("SELECT quantity FROM user_inventory WHERE user_id = %s AND product_id = %s", (user_id, product_id))
    inv = cur.fetchone()
    if not inv or inv["quantity"] < qty:
        return "insufficient_stock"

    # Update inventories
    cur.execute("UPDATE user_inventory SET quantity = quantity - %s WHERE user_id = %s AND product_id = %s",
                (qty, user_id, product_id))
    cur.execute("""
        INSERT INTO distribution_log (product_id, salesperson_id, receiver_id, quantity, status)
        VALUES (%s, %s, %s, %s, 'approved')
    """, (product_id, user_id, user_id, qty))  # Adjust receiver_id if needed
    cur.execute("UPDATE stock_requests SET status = 'approved' WHERE id = %s", (request_id,))
    conn.commit()
    return "approved"

def reject_request(request_id, user_id, reason):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE stock_requests SET status = 'rejected', rejection_reason = %s WHERE id = %s AND recipient_id = %s",
                (reason, request_id, user_id))
    conn.commit()

def get_pending_requests_for_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT sr.*, p.name AS product_name, u.username AS requester_username
        FROM stock_requests sr
        JOIN products p ON sr.product_id = p.id
        JOIN users u ON sr.requester_id = u.id
        WHERE sr.recipient_id = %s AND sr.status = 'pending'
        ORDER BY sr.id DESC
    """, (user_id,))
    return cur.fetchall()
