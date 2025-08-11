#####################################################################################
"""
Project: ESP32-C3 UART Controller for OWON XDM1041

File: main.py

Created: 2025-08-11 17:36:00 (Europe/Berlin)
Author: Elektroarzt

Description:
  MQTT SCPI bridge for OWON XDM1041:
    - Fast-Sampling on startup & soft-start
    - Offline detection after 2 missing measurements
    - Skip first measurement after function/range switch
    - Deduplicate MQTT commands within 20 ms
    - Structured logs with ms timestamps
    - Status published to xdm1041/status (retained)
    - Heartbeat every minute to xdm1041/heartbeat
    - Initial heartbeat & xdm1041/wifiquality publish on startup
    - System status header on cold start with hardware info and code timestamp
    - WiFi Manager captive portal (open AP): OWON-XDM-Remote-Setup

This build uses wifi_manager.py for WiFi + MQTT credentials (no secrets.py).
"""
#####################################################################################

from machine import UART, Pin, freq
import network
import time
import ubinascii
import gc
import os
from umqtt.simple import MQTTClient
from wifi_manager import WifiManager

# ─── UART / Pin configuration ─────────────────────────────────────────────────────
UART_NUM = 1
BAUDRATE = 115200
TX_PIN   = 21
RX_PIN   = 20
LED_PIN  = 8

# ─── Timing constants ─────────────────────────────────────────────────────────────
IDLE_TIMEOUT_MS         = 2000
IDLE_SAMPLE_INTERVAL_MS = 10
IDN_MAX_ATTEMPTS        = 10
IDN_QUERY_INTERVAL_S    = 1.0
SET_MAX_ATTEMPTS        = 10
COMMAND_RETRY_DELAY_S   = 1.0
COMMAND_DELAY_S         = 0.2
HEARTBEAT_INTERVAL_S    = 60

# ─── SCPI commands ────────────────────────────────────────────────────────────────
IDN_COMMAND           = b"*IDN?\r\n"
SET_COMMAND           = b"RATE F\r\n"
VERIFY_COMMAND        = b"RATE?\r\n"
EXPECTED_VERIFY_RESP  = b"F"
EXPECTED_IDN_KEYWORDS = (b"OWON", b"XDM")

# ─── LED blink patterns (active-low) ──────────────────────────────────────────────
SLOW_BLINK_COUNT_SUCCESS = 2
FAST_BLINK_COUNT_FAIL    = 10
FAST_BLINK_COUNT_BUSY    = 5
SLOW_BLINK_ON_S          = 0.5
SLOW_BLINK_OFF_S         = 0.5
FAST_BLINK_ON_S          = 0.1
FAST_BLINK_OFF_S         = 0.1

# ─── MQTT topics ──────────────────────────────────────────────────────────────────
RPC_TOPIC_CMD    = b"xdm1041/cmd"
RPC_TOPIC_RESP   = b"xdm1041/resp"
STATUS_TOPIC     = b"xdm1041/status"
HEARTBEAT_TOPIC  = b"xdm1041/heartbeat"
WIFI_QUAL_TOPIC  = b"xdm1041/wifiquality"   # quality in % (integer string)

# ─── Patterns ─────────────────────────────────────────────────────────────────────
PATTERN_SOFT_START = b"\x00\x01\x00"

# ─── Code timestamp (update each edit) ────────────────────────────────────────────
CODE_TIMESTAMP = "2025-08-11 17:36:00 (Europe/Berlin)"

# ─── Global state ─────────────────────────────────────────────────────────────────
device_offline        = False
uart_comm             = None
empty_resp_count      = 0
skip_next_measurement = False
last_cmd              = None
last_ts               = 0
last_heartbeat        = 0
mqtt_client           = None

# ─── Logging ──────────────────────────────────────────────────────────────────────

def log(tag, msg):
    t  = time.localtime()
    ms = time.ticks_ms() % 1000
    ts = "{:02d}:{:02d}:{:02d}.{:03d}".format(t[3], t[4], t[5], ms)
    print("[{}][{:>6}] {}".format(ts, tag, msg))


# ─── LED ──────────────────────────────────────────────────────────────────────────

def blink(times, on_t, off_t):
    for _ in range(times):
        led.value(0)
        time.sleep(on_t)
        led.value(1)
        time.sleep(off_t)


# ─── UART helpers ─────────────────────────────────────────────────────────────────

def init_uart():
    global uart_comm
    if uart_comm is None:
        uart_comm = UART(UART_NUM, BAUDRATE, tx=TX_PIN, rx=RX_PIN,
                         bits=8, parity=None, stop=1, timeout=500)
        time.sleep_ms(10)
    return uart_comm


def reopen_uart():
    global uart_comm
    if uart_comm is not None:
        try:
            uart_comm.deinit()
        except Exception:
            pass
        uart_comm = None
        time.sleep_ms(10)
    return init_uart()


# ─── MQTT credentials (written by wifi_manager.py) ────────────────────────────────

def read_mqtt_credentials():
    try:
        with open('mqtt.dat') as f:
            line = f.readline().strip()
            if line:
                broker, port, user, password = (line.split(';') + ['', '', '', ''])[:4]
                try:
                    port = int(port or '1883')
                except Exception:
                    port = 1883
                return broker or '', port, user or '', password or ''
    except Exception as e:
        log('MQTT', 'read_mqtt: {}'.format(e))
    return '', 1883, '', ''


# ─── WiFi (via WifiManager) ───────────────────────────────────────────────────────

def setup_wifi():
    log('WIFI', 'Using WifiManager (portal if needed)')
    wm = WifiManager(ssid='OWON-XDM-Remote-Setup', password='', reboot=False, debug=True)
    wm.connect()  # opens AP if needed; otherwise returns when connected
    ip = network.WLAN(network.STA_IF).ifconfig()[0]
    log('WIFI', 'Connected, IP={}'.format(ip))


# ─── MQTT ─────────────────────────────────────────────────────────────────────────

def setup_mqtt():
    global mqtt_client
    broker, port, user, password = read_mqtt_credentials()
    log('MQTT', 'Setting up MQTT client ({}:{})'.format(broker or 'unset', port))
    mqtt_client = MQTTClient(client_id=ubinascii.hexlify(network.WLAN().config('mac')).decode(),
                             server=broker, port=port, user=user or None, password=password or None)
    mqtt_client.set_callback(mqtt_callback)
    mqtt_client.connect()
    mqtt_client.subscribe(RPC_TOPIC_CMD)
    mqtt_client.publish(STATUS_TOPIC, b"online", retain=True)
    log('MQTT', 'MQTT ready & subscribed')


# ─── Stages ───────────────────────────────────────────────────────────────────────

def wait_idle():
    log('STAGE', '1 - Idle-line Check start')
    last = rx_pin.value()
    start = time.ticks_ms(); dots = 0
    while time.ticks_diff(time.ticks_ms(), start) < IDLE_TIMEOUT_MS:
        time.sleep_ms(IDLE_SAMPLE_INTERVAL_MS)
        if rx_pin.value() != last:
            log('STAGE', 'Abort: UART activity')
            return False
        if time.ticks_diff(time.ticks_ms(), start)//500 > dots:
            print('.', end=''); dots += 1
    print()
    log('STAGE', 'Idle for {} ms'.format(IDLE_TIMEOUT_MS))
    return True


def wait_ready():
    log('STAGE', '2 - Polling *IDN?')
    uart = init_uart()
    for _ in range(IDN_MAX_ATTEMPTS):
        log('UART', 'TX: *IDN?')
        uart.write(IDN_COMMAND)
        time.sleep(IDN_QUERY_INTERVAL_S)
        resp = uart.readline(); out = resp.decode().strip() if resp else ''
        log('UART', 'RX: {}'.format(out))
        if any(k.decode() in out for k in EXPECTED_IDN_KEYWORDS):
            return True
        time.sleep(COMMAND_RETRY_DELAY_S)
    return False


def set_and_verify_high():
    log('STAGE', '3 - Set & verify RATE F')
    uart = init_uart()
    for _ in range(SET_MAX_ATTEMPTS):
        log('UART', 'TX: RATE F')
        uart.write(SET_COMMAND)
        time.sleep(COMMAND_DELAY_S)
        log('UART', 'TX: RATE?')
        uart.write(VERIFY_COMMAND)
        time.sleep(COMMAND_DELAY_S)
        resp = uart.readline(); out = resp.decode().strip() if resp else ''
        log('UART', 'RX: {}'.format(out))
        if out == EXPECTED_VERIFY_RESP.decode():
            return True
        time.sleep(COMMAND_RETRY_DELAY_S)
    return False


def run_sequence():
    global device_offline
    log('RUN', 'Startup sequence begin')
    # Tri-state TX while checking for idle bus
    try:
        tx_pin.init(Pin.IN)
    except Exception:
        pass
    if not wait_idle():
        blink(FAST_BLINK_COUNT_BUSY, FAST_BLINK_ON_S, FAST_BLINK_OFF_S)
        return
    # Fresh UART after idle-check
    reopen_uart()
    ready = wait_ready()
    rate_ok = set_and_verify_high() if ready else False
    blink(SLOW_BLINK_COUNT_SUCCESS if (ready and rate_ok) else FAST_BLINK_COUNT_BUSY,
          SLOW_BLINK_ON_S if (ready and rate_ok) else FAST_BLINK_ON_S,
          SLOW_BLINK_OFF_S if (ready and rate_ok) else FAST_BLINK_OFF_S)
    device_offline = False
    mqtt_client.publish(STATUS_TOPIC, b"online", retain=True)
    log('RUN', 'Startup done ready={} rate_ok={}'.format(ready, rate_ok))


# ─── MQTT handling ────────────────────────────────────────────────────────────────

def mqtt_callback(topic, msg):
    global device_offline, empty_resp_count, skip_next_measurement, last_cmd, last_ts
    now = time.ticks_ms(); txt = msg.decode().strip()
    if txt == last_cmd and time.ticks_diff(now, last_ts) < 20:
        return
    last_cmd, last_ts = txt, now
    log('MQTT', '***** Recv: {} *****'.format(txt))
    if device_offline:
        log('MQTT', 'Device offline, ignoring command')
        return
    if txt.upper().startswith(('FUNC', 'CONF', 'SENS')):
        skip_next_measurement = True
    uart = init_uart(); uart.write(txt.encode() + b"\r\n"); log('UART', 'TX: {}'.format(txt)); time.sleep(COMMAND_DELAY_S)
    resp = b""; deadline = time.time() + 1
    while time.time() < deadline:
        if uart.any():
            chunk = uart.read(); resp += chunk or b''
        else:
            time.sleep_ms(10)
    out = resp.decode().strip() if resp else ''
    if txt.upper().startswith('MEAS') and txt.endswith('?') and out == '':
        empty_resp_count += 1
        if empty_resp_count >= 2:
            log('EVENT', 'No measurement x2 -> offline')
            device_offline = True
            mqtt_client.publish(STATUS_TOPIC, b"offline", retain=True)
            empty_resp_count = 0
        return
    empty_resp_count = 0
    if skip_next_measurement and txt.endswith('?'):
        log('MQTT', 'Skipping first meas for {}'.format(txt))
        skip_next_measurement = False
        return
    log('UART', 'RX: {}'.format(out))
    mqtt_client.publish(RPC_TOPIC_RESP, out.encode())


# ─── Main ─────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    tx_pin = Pin(TX_PIN, Pin.IN)
    rx_pin = Pin(RX_PIN, Pin.IN)
    led    = Pin(LED_PIN, Pin.OUT)
    led.on()

    # System Status Header
    log('SYS', '------------- System Status -------------')
    try:
        mac = ubinascii.hexlify(network.WLAN().config('mac'), ':').decode()
    except Exception:
        mac = ubinascii.hexlify(network.WLAN().config('mac')).decode()
    log('SYS', 'MAC: {}'.format(mac))
    log('SYS', 'Firmware: {}'.format(os.uname().release))
    log('SYS', 'CPU freq: {:.1f} MHz'.format(freq()/1e6))
    gc.collect()
    log('SYS', 'Heap free: {} bytes, used: {} bytes'.format(gc.mem_free(), gc.mem_alloc()))
    try:
        from esp import flash_size
        log('SYS', 'Flash size: {} B'.format(flash_size()))
    except Exception:
        pass
    log('SYS', 'Code timestamp: {}'.format(CODE_TIMESTAMP))
    log('SYS', 'Author: Elektroarzt')
    log('SYS', '----------------------------------------')

    setup_wifi()
    setup_mqtt()
    run_sequence()

    uart_soft = init_uart(); buffer = b''; last_heartbeat = time.time()

    # Initial heartbeat & wifi quality
    mqtt_client.publish(HEARTBEAT_TOPIC, b"alive")
    rssi = network.WLAN(network.STA_IF).status('rssi')
    quality = min(max((rssi + 100) * 2, 0), 100)
    mqtt_client.publish(WIFI_QUAL_TOPIC, str(int(quality)).encode(), retain=True)
    log('WIFI', 'Raw RSSI = {} dBm'.format(rssi))
    log('RUN', 'Listening & heartbeat')

    while True:
        mqtt_client.check_msg()
        if uart_soft.any():
            data = uart_soft.read(); buffer += data or b''
            if len(buffer) > 64:
                buffer = buffer[-64:]
            if PATTERN_SOFT_START in buffer:
                log('EVENT', 'Soft-start detected -> fast sampling only')
                buffer = b''; device_offline = False; empty_resp_count = 0
                mqtt_client.publish(STATUS_TOPIC, b"online", retain=True)
                ok = set_and_verify_high(); log('RUN', 'Fast sampling ok' if ok else 'Fast sampling failed')
        if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL_S:
            mqtt_client.publish(HEARTBEAT_TOPIC, b"alive")
            rssi = network.WLAN(network.STA_IF).status('rssi')
            quality = min(max((rssi + 100) * 2, 0), 100)
            mqtt_client.publish(WIFI_QUAL_TOPIC, str(int(quality)).encode(), retain=True)
            log('WIFI', 'Raw RSSI = {} dBm'.format(rssi))
            last_heartbeat = time.time()
        time.sleep_ms(100)
