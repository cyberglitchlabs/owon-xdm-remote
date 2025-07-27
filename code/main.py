#####################################################################################
"""
Project: ESP32-C3 UART Controller for OWON XDM1041

File: main.py

Created: 2025-05-24 11:50:00
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

Credentials in secrets.py.
"""
#####################################################################################

from machine import UART, Pin, freq
import network
import time
import ubinascii
import gc
import os
from umqtt.simple import MQTTClient
import secrets

# UART / Pin configuration
UART_NUM = 1
BAUDRATE = 115200
TX_PIN   = 21
RX_PIN   = 20
LED_PIN  = 8

# Timing constants
IDLE_TIMEOUT_MS         = 2000
IDLE_SAMPLE_INTERVAL_MS = 10
IDN_MAX_ATTEMPTS        = 10
IDN_QUERY_INTERVAL_S    = 1.0
SET_MAX_ATTEMPTS        = 10
COMMAND_RETRY_DELAY_S   = 1.0
COMMAND_DELAY_S         = 0.2
HEARTBEAT_INTERVAL_S    = 60

# SCPI commands
IDN_COMMAND           = b"*IDN?\r\n"
SET_COMMAND           = b"RATE F\r\n"
VERIFY_COMMAND        = b"RATE?\r\n"
EXPECTED_VERIFY_RESP  = b"F"
EXPECTED_IDN_KEYWORDS = (b"OWON", b"XDM")

# LED blink patterns (active-low)
SLOW_BLINK_COUNT_SUCCESS = 2
FAST_BLINK_COUNT_FAIL    = 10
FAST_BLINK_COUNT_BUSY    = 5
SLOW_BLINK_ON_S          = 0.5
SLOW_BLINK_OFF_S         = 0.5
FAST_BLINK_ON_S          = 0.1
FAST_BLINK_OFF_S         = 0.1

# MQTT topics and credentials
WIFI_SSID        = secrets.WIFI_SSID
WIFI_PASS        = secrets.WIFI_PASS
MQTT_BROKER      = secrets.MQTT_BROKER
MQTT_PORT        = secrets.MQTT_PORT
MQTT_USER        = secrets.MQTT_USER
MQTT_PASS        = secrets.MQTT_PASS
CLIENT_ID        = ubinascii.hexlify(network.WLAN().config('mac')).decode()
RPC_TOPIC_CMD    = b"xdm1041/cmd"
RPC_TOPIC_RESP   = b"xdm1041/resp"
STATUS_TOPIC     = b"xdm1041/status"
HEARTBEAT_TOPIC  = b"xdm1041/heartbeat"
WIFI_QUAL_TOPIC  = b"xdm1041/wifiquality"

# Soft-start pattern
PATTERN_SOFT_START    = b"\x00\x01\x00"

# Code timestamp
CODE_TIMESTAMP = "2025-05-24 11:50:00"

# Global state
device_offline        = False
uart_comm             = None
empty_resp_count      = 0
skip_next_measurement = False
last_cmd              = None
last_ts               = 0
last_heartbeat        = 0
mqtt_client           = None

# Initialize UART
def init_uart():
    global uart_comm
    if uart_comm is None:
        uart_comm = UART(
            UART_NUM, BAUDRATE,
            tx=TX_PIN, rx=RX_PIN,
            bits=8, parity=None, stop=1, timeout=500
        )
    return uart_comm

# Structured logger
def log(tag, msg):
    t  = time.localtime()
    ms = time.ticks_ms() % 1000
    ts = "{:02d}:{:02d}:{:02d}.{:03d}".format(t[3], t[4], t[5], ms)
    print(f"[{ts}][{tag:>6}] {msg}")

# LED blink for feedback
def blink(times, on_t, off_t):
    for _ in range(times):
        led.value(0)
        time.sleep(on_t)
        led.value(1)
        time.sleep(off_t)

# Connect to WiFi using secrets.py

def connect_wifi():
    log("WIFI", f"Connecting to SSID '{WIFI_SSID}'")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    start = time.time()
    wlan.connect(WIFI_SSID, WIFI_PASS)
    while not wlan.isconnected():
        time.sleep(1)
        log("WIFI", f"Waiting... {int(time.time()-start)}s")
    ip = wlan.ifconfig()[0]
    log("WIFI", f"Connected, IP={ip}")

# Stage 1: Idle-line check
def wait_idle():
    log("STAGE", "1 - Idle-line Check start")
    last = rx_pin.value()
    start = time.ticks_ms(); dots = 0
    while time.ticks_diff(time.ticks_ms(), start) < IDLE_TIMEOUT_MS:
        time.sleep_ms(IDLE_SAMPLE_INTERVAL_MS)
        if rx_pin.value() != last:
            log("STAGE", "Abort: UART activity")
            return False
        if time.ticks_diff(time.ticks_ms(), start)//500 > dots:
            print('.', end=''); dots += 1
    print()
    log("STAGE", f"Idle for {IDLE_TIMEOUT_MS} ms")
    return True

# Stage 2: Poll readiness
def wait_ready():
    log("STAGE", "2 - Polling *IDN?")
    uart = init_uart()
    for _ in range(IDN_MAX_ATTEMPTS):
        log("UART", "TX: *IDN?")
        uart.write(IDN_COMMAND)
        time.sleep(IDN_QUERY_INTERVAL_S)
        resp = uart.readline()
        out = resp.decode().strip() if resp else ''
        log("UART", f"RX: {out}")
        if any(k.decode() in out for k in EXPECTED_IDN_KEYWORDS):
            return True
        time.sleep(COMMAND_RETRY_DELAY_S)
    return False

# Stage 3: Set & verify fast sampling
def set_and_verify_high():
    log("STAGE", "3 - Set & verify RATE F")
    uart = init_uart()
    for _ in range(SET_MAX_ATTEMPTS):
        log("UART", "TX: RATE F")
        uart.write(SET_COMMAND)
        time.sleep(COMMAND_DELAY_S)
        log("UART", "TX: RATE?")
        uart.write(VERIFY_COMMAND)
        time.sleep(COMMAND_DELAY_S)
        resp = uart.readline()
        out = resp.decode().strip() if resp else ''
        log("UART", f"RX: {out}")
        if out == EXPECTED_VERIFY_RESP.decode():
            return True
        time.sleep(COMMAND_RETRY_DELAY_S)
    return False

# Startup sequence
def run_sequence():
    global device_offline
    log("RUN", "Startup sequence begin")
    if not wait_idle():
        blink(FAST_BLINK_COUNT_BUSY, FAST_BLINK_ON_S, FAST_BLINK_OFF_S)
        return
    ready = wait_ready()
    rate_ok = set_and_verify_high() if ready else False
    blink(
        SLOW_BLINK_COUNT_SUCCESS if ready and rate_ok else FAST_BLINK_COUNT_BUSY,
        SLOW_BLINK_ON_S if ready and rate_ok else FAST_BLINK_ON_S,
        SLOW_BLINK_OFF_S if ready and rate_ok else FAST_BLINK_OFF_S
    )
    device_offline=False
    mqtt_client.publish(STATUS_TOPIC, b"online", retain=True)
    log("RUN", f"Startup done ready={ready} rate_ok={rate_ok}")

# Handle incoming MQTT commands
def mqtt_callback(topic, msg):
    global device_offline, empty_resp_count, skip_next_measurement, last_cmd, last_ts
    now = time.ticks_ms(); txt = msg.decode().strip()
    if txt == last_cmd and time.ticks_diff(now, last_ts) < 20: return
    last_cmd, last_ts = txt, now
    log("MQTT", f"***** Recv: {txt} *****")
    if device_offline:
        log("MQTT", "Device offline, ignoring command")
        return
    if txt.upper().startswith(("FUNC", "CONF", "SENS")):
        skip_next_measurement = True
    uart = init_uart(); uart.write(txt.encode() + b"\r\n"); log("UART", f"TX: {txt}"); time.sleep(COMMAND_DELAY_S)
    resp = b""; deadline = time.time() + 1
    while time.time() < deadline:
        if uart.any(): chunk = uart.read(); resp += chunk or b''
        else: time.sleep_ms(10)
    out = resp.decode().strip() if resp else ''
    if txt.upper().startswith('MEAS') and txt.endswith('?') and out == '':
        empty_resp_count += 1
        if empty_resp_count >= 2:
            log("EVENT", "No measurement x2 -> offline")
            device_offline = True
            mqtt_client.publish(STATUS_TOPIC, b"offline", retain=True)
            empty_resp_count = 0
        return
    empty_resp_count = 0
    if skip_next_measurement and txt.endswith('?'):
        log("MQTT", f"Skipping first meas for {txt}")
        skip_next_measurement = False; return
    log("UART", f"RX: {out}"); mqtt_client.publish(RPC_TOPIC_RESP, out.encode())

# Setup MQTT
def setup_mqtt():
    global mqtt_client
    log("MQTT", "Setting up MQTT client")
    mqtt_client = MQTTClient(CLIENT_ID, MQTT_BROKER, port=MQTT_PORT, user=MQTT_USER, password=MQTT_PASS)
    mqtt_client.set_callback(mqtt_callback); mqtt_client.connect(); mqtt_client.subscribe(RPC_TOPIC_CMD)
    mqtt_client.publish(STATUS_TOPIC, b"online", retain=True)
    log("MQTT", "MQTT ready & subscribed")

# Main loop

if __name__ == '__main__':
    tx_pin = Pin(TX_PIN, Pin.IN); rx_pin = Pin(RX_PIN, Pin.IN); led = Pin(LED_PIN, Pin.OUT); led.on()

    # --- System Status Header ---
    log("SYS", "------------- System Status -------------")
    mac = ubinascii.hexlify(network.WLAN().config('mac'), ':').decode()
    log("SYS", f"MAC: {mac}")
    ver = os.uname().release
    log("SYS", f"Firmware: {ver}")
    log("SYS", f"CPU freq: {freq()/1e6:.1f} MHz")
    gc.collect()
    log("SYS", f"Heap free: {gc.mem_free()} bytes, used: {gc.mem_alloc()} bytes")
    try:
        from esp import flash_size, chip_id
        log("SYS", f"Flash size: {flash_size()} B, Chip ID: {chip_id()}")
    except:
        pass
    log("SYS", f"Code timestamp: {CODE_TIMESTAMP}")
    log("SYS", f"Author: Elektroarzt")
    log("SYS", "----------------------------------------")

    connect_wifi(); setup_mqtt(); run_sequence()
    uart_soft = init_uart(); buffer = b''; last_heartbeat = time.time()
    # initial heartbeat & wifiquality
    mqtt_client.publish(HEARTBEAT_TOPIC, b"alive")
    rssi = network.WLAN(network.STA_IF).status('rssi')
    quality = min(max((rssi+100)*2,0),100)
    mqtt_client.publish(WIFI_QUAL_TOPIC, str(int(quality)).encode(), retain=True)
    log("WIFI", f"Raw RSSI = {rssi} dBm")
    log("RUN", "Listening & heartbeat")

    while True:
        mqtt_client.check_msg()
        if uart_soft.any():
            data = uart_soft.read(); buffer += data
            if len(buffer) > 64: buffer = buffer[-64:]
            if PATTERN_SOFT_START in buffer:
                log("EVENT", "Soft-start detected -> fast sampling only")
                buffer = b''; device_offline = False; empty_resp_count = 0
                mqtt_client.publish(STATUS_TOPIC, b"online", retain=True)
                ok = set_and_verify_high(); log("RUN", "Fast sampling ok" if ok else "Fast sampling failed")
        if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL_S:
            mqtt_client.publish(HEARTBEAT_TOPIC, b"alive")
            rssi = network.WLAN(network.STA_IF).status('rssi')
            quality = min(max((rssi+100)*2,0),100)
            mqtt_client.publish(WIFI_QUAL_TOPIC, str(int(quality)).encode(), retain=True)
            log("WIFI", f"Raw RSSI = {rssi} dBm")
            last_heartbeat = time.time()
        time.sleep_ms(100)
