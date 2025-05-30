import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from werkzeug.security import generate_password_hash
from flask import flash
from urllib.parse import urlparse

DATABASE_URL = "postgresql://oscar_shop_user:opOR00LM9Lz1of5a4Sd8meciav8o8dMX@dpg-d0sm81p5pdvs738u26fg-a/oscar_shop"
parsed_url = urlparse(DATABASE_URL)

def get_db():
    return psycopg2.connect(
        dbname=parsed_url.path[1:],
        user=parsed_url.username,
        password=parsed_url.password,
        host=parsed_url.hostname,
        port=parsed_url.port,
        cursor_factory=RealDictCursor
    )

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS businesses (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT,
            location TEXT
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            business_id INTEGER REFERENCES businesses(id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            category TEXT,
            name TEXT,
            quantity_available INTEGER,
            buying_price REAL,
            agent_price REAL,
            wholesale_price REAL,
            retail_price REAL
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_inventory (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            product_id INTEGER REFERENCES products(id),
            quantity INTEGER DEFAULT 0,
            UNIQUE(user_id, product_id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS stock_requests (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id),
            requester_id INTEGER NOT NULL REFERENCES users(id),
            recipient_id INTEGER NOT NULL REFERENCES users(id),
            quantity INTEGER NOT NULL,
            requester_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES products(id),
            quantity INTEGER,
            price REAL,
            total_price REAL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            salesperson_id INTEGER REFERENCES users(id),
            payment_method TEXT
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS distribution_log (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id),
            salesperson_id INTEGER NOT NULL REFERENCES users(id),
            receiver_id INTEGER NOT NULL REFERENCES users(id),
            quantity INTEGER NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'approved'
        )
    ''')

    cur.execute("SELECT * FROM users WHERE username = %s", ('admin',))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                    ('admin', generate_password_hash('admin'), 'owner'))

    conn.commit()
    conn.close()

def get_user(username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cur.fetchone()
    conn.close()
    return user

def get_products():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products")
    products = cur.fetchall()
    conn.close()
    return products

def get_user_inventory(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        SELECT ui.*, 
               p.category,
               p.name AS product_name,  
               p.agent_price,
               p.wholesale_price,
               p.retail_price
        FROM user_inventory ui
        JOIN products p ON ui.product_id = p.id
        WHERE ui.user_id = %s
    ''', (user_id,))
    inventory = cur.fetchall()
    conn.close()
    return inventory

def add_sale(product_id, quantity, salesperson_id, price, payment_method):
    conn = get_db()
    cur = conn.cursor()
    total_price = price * quantity

    cur.execute("SELECT buying_price FROM products WHERE id = %s", (product_id,))
    product = cur.fetchone()
    if not product:
        conn.close()
        flash("Product not found.", "error")
        return

    buying_price = product['buying_price']
    if price < buying_price:
        conn.close()
        flash("Sale price cannot be below buying price.", "error")
        return

    cur.execute("SELECT quantity FROM user_inventory WHERE user_id = %s AND product_id = %s", (salesperson_id, product_id))
    row = cur.fetchone()

    if not row:
        cur.execute('''
            INSERT INTO user_inventory (user_id, product_id, quantity)
            VALUES (%s, %s, %s)
        ''', (salesperson_id, product_id, -quantity))
    else:
        cur.execute('''
            UPDATE user_inventory SET quantity = quantity - %s
            WHERE user_id = %s AND product_id = %s
        ''', (quantity, salesperson_id, product_id))

    cur.execute('''
        UPDATE products SET quantity_available = quantity_available - %s
        WHERE id = %s
    ''', (quantity, product_id))

    cur.execute('''
        INSERT INTO sales (product_id, quantity, price, total_price, salesperson_id, payment_method, date)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    ''', (product_id, quantity, price, total_price, salesperson_id, payment_method, datetime.now()))

    conn.commit()
    conn.close()
    flash("Sale recorded successfully!", "success")

def get_sales(conn, salesperson_id=None):
    cur = conn.cursor()
    if salesperson_id:
        cur.execute('''
            SELECT s.*, p.name as product_name
            FROM sales s
            JOIN products p ON s.product_id = p.id
            WHERE s.salesperson_id = %s
            ORDER BY date DESC
            LIMIT 10
        ''', (salesperson_id,))
    else:
        cur.execute('''
            SELECT s.*, p.name as product_name, u.username as salesperson
            FROM sales s
            JOIN products p ON s.product_id = p.id
            JOIN users u ON s.salesperson_id = u.id
            ORDER BY date DESC
            LIMIT 10
        ''')
    return cur.fetchall()

def approve_request(request_id, reviewer_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        SELECT product_id, quantity, requester_id
        FROM stock_requests
        WHERE id = %s AND recipient_id = %s AND status = 'pending'
    ''', (request_id, reviewer_id))
    req = cur.fetchone()
    if not req:
        return False

    product_id, quantity, requester_id = req['product_id'], req['quantity'], req['requester_id']
    cur.execute('''
        SELECT quantity FROM user_inventory
        WHERE user_id = %s AND product_id = %s
    ''', (reviewer_id, product_id))
    row = cur.fetchone()
    if not row or row['quantity'] < quantity:
        return "insufficient_stock"

    cur.execute('''
        UPDATE user_inventory
        SET quantity = quantity - %s
        WHERE user_id = %s AND product_id = %s
    ''', (quantity, reviewer_id, product_id))

    cur.execute('''
        INSERT INTO user_inventory (user_id, product_id, quantity)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, product_id) DO UPDATE
        SET quantity = user_inventory.quantity + EXCLUDED.quantity
    ''', (requester_id, product_id, quantity))

    cur.execute("UPDATE stock_requests SET status = 'approved' WHERE id = %s", (request_id,))

    cur.execute('''
        INSERT INTO distribution_log (product_id, salesperson_id, receiver_id, quantity, status)
        VALUES (%s, %s, %s, %s, %s)
    ''', (product_id, reviewer_id, requester_id, quantity, 'approved'))

    conn.commit()
    conn.close()
    return True

def reject_request(request_id, reviewer_id, reason=''):
    conn = get_db()
    cur = conn.cursor()

    cur.execute('''
        UPDATE stock_requests
        SET status = 'rejected'
        WHERE id = %s AND recipient_id = %s AND status = 'pending'
    ''', (request_id, reviewer_id))

    cur.execute('''
        SELECT product_id, requester_id, quantity
        FROM stock_requests
        WHERE id = %s
    ''', (request_id,))
    info = cur.fetchone()

    if info:
        cur.execute('''
            INSERT INTO distribution_log (product_id, salesperson_id, receiver_id, quantity, status)
            VALUES (%s, %s, %s, %s, %s)
        ''', (info['product_id'], reviewer_id, info['requester_id'], info['quantity'], 'rejected'))

    conn.commit()
    conn.close()

def initialize_salesperson_inventory(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM products")
    product_ids = [row['id'] for row in cur.fetchall()]

    for product_id in product_ids:
        cur.execute('''
            INSERT INTO user_inventory (user_id, product_id, quantity)
            VALUES (%s, %s, 0)
            ON CONFLICT (user_id, product_id) DO NOTHING
        ''', (user_id, product_id))

    conn.commit()
    conn.close()

def add_salesperson_stock(user_id, product_name, quantity):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM products WHERE name = %s", (product_name,))
    product = cur.fetchone()
    if not product:
        conn.close()
        raise ValueError("Product not found")

    product_id = product['id']

    cur.execute('''
        UPDATE products
        SET quantity_available = quantity_available + %s
        WHERE id = %s
    ''', (quantity, product_id))

    cur.execute('''
        INSERT INTO user_inventory (user_id, product_id, quantity)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, product_id) DO UPDATE
        SET quantity = user_inventory.quantity + EXCLUDED.quantity
    ''', (user_id, product_id, quantity))

    conn.commit()
    conn.close()
