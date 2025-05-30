from flask import Flask

app = Flask(__name__)

@app.route('/')
def hello():
    return "🎉 Hello from Render - it's working!"

# DO NOT include app.run() when using Gunicorn
