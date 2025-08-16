from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is alive ✅", 200

@app.route('/ping-x92a7f')
def ping():
    return "Ping received ✅", 200

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():  
    t = Thread(target=run)
    t.start()
