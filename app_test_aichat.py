from flask import Flask, render_template_string, request, jsonify
import requests
import socket
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser
import ollama  # Make sure this is installed!

app = Flask(__name__)

# --- CONFIG ---
THIS_NAME = "RIFT"  # Change per app (FRIDAY, NORA, KIDA00...)
THIS_PORT = 5000      # Change per app
MODEL_NAME = "llama3" # The model you have pulled in Ollama
TYPE = "_flask-chat._tcp.local."

found_servers = {} 
chat_history = []

# --- NETWORKING HELPERS ---
def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except: return '127.0.0.1'
    finally: s.close()

class MyListener:
    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        if info:
            addr = socket.inet_ntoa(info.addresses[0])
            short_name = name.split('.')[0]
            if short_name != THIS_NAME:
                found_servers[short_name] = f"http://{addr}:{info.port}"
    def remove_service(self, z, t, name):
        short_name = name.split('.')[0]
        found_servers.pop(short_name, None)

# --- ZEROCONF STARTUP ---
my_ip = get_ip()
zeroconf = Zeroconf()
info = ServiceInfo(TYPE, f"{THIS_NAME}.{TYPE}", addresses=[socket.inet_aton(my_ip)], port=THIS_PORT)
zeroconf.register_service(info)
browser = ServiceBrowser(zeroconf, TYPE, MyListener())

# --- ROUTES ---

@app.route("/")
def index():
    return render_template_string("""
        <html>
            <head>
                <title>{THIS_NAME} Chat</title>
                <style>
                    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #121212; color: white; margin: 0; display: flex; flex-direction: column; height: 100vh; }
                    header { background: #1f1f1f; padding: 15px; text-align: center; border-bottom: 1px solid #333; }
                    #chat-container { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 10px; }
                    
                    /* Chat Bubbles */
                    .msg { max-width: 70%; padding: 10px 15px; border-radius: 15px; font-size: 0.95em; line-height: 1.4; position: relative; }
                    .msg.user { align-self: flex-end; background: #007bff; color: white; border-bottom-right-radius: 2px; }
                    .msg.ai { align-self: flex-start; background: #333; color: #e0e0e0; border-bottom-left-radius: 2px; }
                    
                    .sender-name { font-size: 0.75em; font-weight: bold; margin-bottom: 4px; display: block; color: #aaa; }
                    
                    /* Input Area */
                    footer { padding: 20px; background: #1f1f1f; display: flex; gap: 10px; }
                    input { flex: 1; padding: 12px; border-radius: 25px; border: none; background: #333; color: white; outline: none; }
                    button { padding: 0 20px; border-radius: 25px; border: none; background: #007bff; color: white; font-weight: bold; cursor: pointer; }
                    button:hover { background: #0056b3; }
                </style>
                <script>
                    let lastCount = 0;
                    async function refreshChat() {
                        const res = await fetch('/get_messages');
                        const data = await res.json();
                        
                        if(data.length !== lastCount) {
                            const container = document.getElementById('chat-container');
                            container.innerHTML = data.map(m => {
                                const isYou = m.sender === "YOU" || m.sender === "{THIS_NAME}";
                                return `
                                    <div class="msg ${isYou ? 'user' : 'ai'}">
                                        <span class="sender-name">${m.sender}</span>
                                        ${m.text}
                                    </div>
                                `;
                            }).join('');
                            container.scrollTop = container.scrollHeight; // Auto-scroll
                            lastCount = data.length;
                        }
                    }
                    setInterval(refreshChat, 1000);

                    async function send() {
                        const input = document.getElementById('msg');
                        const text = input.value;
                        if(!text) return;
                        input.value = '';
                        await fetch('/broadcast', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({text})
                        });
                    }
                    
                    // Allow "Enter" key to send
                    function checkEnter(e) { if(e.key === "Enter") send(); }
                </script>
            </head>
            <body>
                <header>
                    <h2>{THIS_NAME} AI Network</h2>
                </header>
                <div id="chat-container"></div>
                <footer>
                    <input id="msg" type="text" placeholder="Type a command..." onkeypress="checkEnter(event)">
                    <button onclick="send()">Send</button>
                </footer>
            </body>
        </html>
    """.replace("{THIS_NAME}", THIS_NAME))

@app.route("/get_messages")
def get_messages():
    return jsonify(chat_history)

@app.route("/receive", methods=['POST'])
def receive():
    data = request.json
    sender = data.get('sender')
    text = data.get('text')
    
    # 1. Add human message to history
    chat_history.append({"sender": sender, "text": text})
    
    # 2. Trigger Ollama to respond to this message
    try:
        response = ollama.chat(model=MODEL_NAME, messages=[{'role': 'user', 'content': text}])
        ai_reply = response['message']['content']
        chat_history.append({"sender": THIS_NAME, "text": ai_reply})
    except Exception as e:
        print(f"Ollama Error: {e}")
        
    return "OK"

@app.route("/broadcast", methods=['POST'])
def broadcast():
    text = request.json.get('text')
    chat_history.append({"sender": "YOU", "text": text})
    
    # Send this message to every online server found by Zeroconf
    for name, url in found_servers.items():
        try:
            requests.post(f"{url}/receive", json={"sender": "User", "text": text}, timeout=1)
        except: pass
    return "OK"

@app.route("/ping")
def ping(): return "ready"

if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=THIS_PORT, debug=False, threaded=True)
    finally:
        zeroconf.unregister_service(info)
        zeroconf.close()
