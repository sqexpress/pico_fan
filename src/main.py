import network
import socket
from machine import Pin, PWM, Timer
import time
import gc
import sys

# === CONFIG ===
SSID = "YOUR_SSID"
PASSWORD = "YOUR_PASSWORD"
PORT = 80  # Change to 8080 if port 80 causes issues
PAGE_TITLE = "Family Fan Control"

# === Motor Setup ===
in1_pwm = PWM(Pin(0))
in2 = Pin(1, Pin.OUT)
in1_pwm.freq(25000)

# === LED Setup ===
led = Pin("LED", Pin.OUT)
led.value(1)  # Solid ON = power connected
blink_timer = Timer()

# === Fan State ===
speed = 0.9
direction = "forward"
enabled = False

# === LED Behavior ===
def start_blinking():
    blink_timer.init(freq=2, mode=Timer.PERIODIC, callback=lambda t: led.toggle())

def stop_blinking():
    blink_timer.deinit()
    led.value(1)

# === Fan Control ===
def update_motor():
    if not enabled:
        in1_pwm.duty_u16(0)
        in2.value(0)
        stop_blinking()
        return
    in2.value(0 if direction == "forward" else 1)
    in1_pwm.duty_u16(int(speed * 65535))
    start_blinking()

# === Connect to Wi-Fi ===
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(SSID, PASSWORD)
    timeout = 15
    print("Connecting to Wi-Fi...", end="")
    while not wlan.isconnected() and timeout > 0:
        time.sleep(1)
        print(".", end="")
        timeout -= 1
    print()
    if not wlan.isconnected():
        print("❌ Failed to connect to Wi-Fi")
        sys.exit()
    print("✅ Connected, IP:", wlan.ifconfig()[0])
    return wlan.ifconfig()[0]

ip = connect_wifi()

# === Web Page ===
def webpage():
    state = "ON" if enabled else "OFF"
    toggle_action = "off" if enabled else "on"
    toggle_label = "Turn OFF" if enabled else "Turn ON"
    toggle_class = "btn-off" if enabled else "btn-on"
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>{PAGE_TITLE}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
  <meta http-equiv="Pragma" content="no-cache" />
  <meta http-equiv="Expires" content="0" />
  <style>
    body {{
      font-family: sans-serif;
      background: #f0f4f8;
      text-align: center;
    }}
    .container {{
      background: #fff;
      padding: 2rem;
      border-radius: 1rem;
      margin: 3rem auto;
      max-width: 400px;
      box-shadow: 0 0 10px rgba(0,0,0,0.1);
    }}
    .status {{ font-size: 1.2rem; color: {"green" if enabled else "red"}; }}
    input[type=range] {{ width: 100%; }}
    .btn {{
      padding: 0.75rem 1.5rem;
      border: none;
      border-radius: 0.5rem;
      font-size: 1rem;
      cursor: pointer;
    }}
    .btn-on {{ background: #28a745; color: white; }}
    .btn-off {{ background: #dc3545; color: white; }}
  </style>
  <script>
    function pollState() {{
      fetch("/status").then(r => r.json()).then(data => {{
        document.getElementById("speed").value = data.speed;
        document.getElementById("speedLabel").innerText = "Speed: " + data.speed + "%";
        document.getElementById("dirFwd").checked = data.direction === "forward";
        document.getElementById("dirRev").checked = data.direction === "reverse";
        let s = document.getElementById("status");
        let b = document.getElementById("powerBtn");
        if (data.enabled) {{
          s.innerHTML = "Status: <strong>ON</strong>";
          s.style.color = "green";
          b.innerText = "Turn OFF"; b.value = "off"; b.className = "btn btn-off";
        }} else {{
          s.innerHTML = "Status: <strong>OFF</strong>";
          s.style.color = "red";
          b.innerText = "Turn ON"; b.value = "on"; b.className = "btn btn-on";
        }}
      }});
    }}
    setInterval(pollState, 2000);
  </script>
</head>
<body>
  <div class="container">
    <h2>{PAGE_TITLE}</h2>
    <p id="status" class="status">Status: <strong>{state}</strong></p>
    <form action="/" method="get">
      <label id="speedLabel">Speed: {int(speed*100)}%</label><br>
      <input type="range" id="speed" name="speed" min="0" max="100" value="{int(speed*100)}" oninput="this.form.submit()"><br><br>
      <label>Direction:</label><br>
      <input type="radio" id="dirFwd" name="direction" value="forward" {"checked" if direction=="forward" else ""} onchange="this.form.submit()"> Forward
      <input type="radio" id="dirRev" name="direction" value="reverse" {"checked" if direction=="reverse" else ""} onchange="this.form.submit()"><br><br>
      <button id="powerBtn" class="btn {toggle_class}" name="power" value="{toggle_action}">{toggle_label}</button>
    </form>
  </div>
</body>
</html>"""

# === Socket Setup ===
try:
    addr = socket.getaddrinfo("0.0.0.0", PORT)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(5)
    print(f"🌐 Server running at http://{ip}:{PORT}")
except OSError as e:
    print("Socket bind failed:", e)
    sys.exit()

# === Main Loop ===
while True:
    try:
        cl, addr = s.accept()
        cl.settimeout(5)  # kill dead clients
        request = cl.recv(1024).decode()
        if not request:
            cl.close()
            continue

        path = request.split(" ")[1]

        # Serve JSON status
        if path.startswith("/status"):
            cl.send("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n")
            cl.send('{{"speed":{speed},"direction":"{direction}","enabled":{enabled}}}'.format(
                speed=int(speed*100),
                direction=direction,
                enabled=str(enabled).lower()
            ))
            cl.close()
            continue

        # Handle GET query
        if "?" in path:
            query = path.split("?", 1)[1]
            for pair in query.split("&"):
                k, v = pair.split("=")
                if k == "speed":
                    speed = max(0.0, min(1.0, int(v)/100))
                elif k == "direction":
                    direction = v
                elif k == "power":
                    enabled = v == "on"

        update_motor()

        # Serve UI
        cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n")
        cl.sendall(webpage())
        cl.close()
        gc.collect()

    except Exception as e:
        print("⚠️ Error:", e)
        try:
            cl.close()
        except:
            pass
        gc.collect()
