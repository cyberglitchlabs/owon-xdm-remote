#####################################################################################
# wifi_manager.py  (modified: MQTT fields, styled UI, robust HTTP & DNS captive)
#####################################################################################
# Author: Igor Ferreira (modified by Elektroarzt/assistant)
# License: MIT
# Version: 2.1.0-mqtt-ui12
# Description: WiFi Manager for ESP8266/ESP32 using MicroPython with MQTT config,
#              styled UI and basic DNS captive portal support.

import machine
import network
import socket
import re
import time
try:
    import _thread
except:  # may be unavailable on some ports
    _thread = None

# unified logger like main.py

def wm_log(tag, msg):
    t  = time.localtime()
    ms = time.ticks_ms() % 1000
    ts = "{:02d}:{:02d}:{:02d}.{:03d}".format(t[3], t[4], t[5], ms)
    print("[{}][{:>6}] {}".format(ts, tag, msg))

# Safer CRLF constants to avoid broken byte literals in edits
CRLF  = b"\r\n"
CRLF2 = CRLF + CRLF

class WifiManager:
    def __init__(self, ssid='OWON-XDM-Remote-Setup', password='', reboot=True, debug=False):
        self.wlan_sta = network.WLAN(network.STA_IF)
        self.wlan_sta.active(True)
        self.wlan_ap  = network.WLAN(network.AP_IF)
        if len(ssid) > 32:
            raise Exception('The SSID cannot be longer than 32 characters.')
        self.ap_ssid = ssid
        if password == '':
            self.ap_password = ''
            self.ap_authmode = 0  # open
        elif len(password) < 8:
            raise Exception('The password cannot be less than 8 characters long.')
        else:
            self.ap_password = password
            self.ap_authmode = 3  # WPA2-PSK
        self.wifi_credentials = 'wifi.dat'
        self.mqtt_credentials = 'mqtt.dat'
        try:
            self.wlan_sta.disconnect()
        except:
            pass
        self.reboot = reboot
        self.debug = debug

    # ---- WiFi connect ----
    def connect(self):
        if self.wlan_sta.isconnected():
            return
        profiles = self.read_credentials()
        try:
            scans = self.wlan_sta.scan()
        except Exception as e:
            scans = []
            if self.debug:
                wm_log('WIFI', 'scan failed: {}'.format(e))
        for ssid, *_ in scans:
            try:
                ssid = ssid.decode('utf-8')
            except:
                continue
            if ssid in profiles:
                if self.wifi_connect(ssid, profiles[ssid]):
                    return
        wm_log('WIFI', 'Could not connect to any WiFi network. Starting configuration portal...')
        self.web_server()

    def disconnect(self):
        if self.wlan_sta.isconnected():
            self.wlan_sta.disconnect()

    def is_connected(self):
        return self.wlan_sta.isconnected()

    def get_address(self):
        return self.wlan_sta.ifconfig()

    # ---- Files ----
    def write_credentials(self, profiles):
        try:
            with open(self.wifi_credentials, 'w') as f:
                for ssid, password in profiles.items():
                    f.write('{};{}\n'.format(ssid, password))
                    f.flush()
        except Exception as e:
            if self.debug:
                wm_log('WIFI', 'write_credentials: {}'.format(e))

    def read_credentials(self):
        profiles = {}
        try:
            with open(self.wifi_credentials) as f:
                for line in f.readlines():
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(';')
                    if len(parts) >= 2:
                        profiles[parts[0]] = parts[1]
        except Exception as e:
            if self.debug:
                wm_log('WIFI', 'read_credentials: {}'.format(e))
        return profiles

    def write_mqtt(self, broker, port, user, password):
        try:
            with open(self.mqtt_credentials, 'w') as f:
                f.write('{};{};{};{}\n'.format(broker, port, user, password))
                f.flush()
        except Exception as e:
            if self.debug:
                wm_log('WIFI', 'write_mqtt: {}'.format(e))

    def read_mqtt(self):
        try:
            with open(self.mqtt_credentials) as f:
                line = f.readline().strip()
                if line:
                    broker, port, user, password = (line.split(';') + ['', '', '', ''])[:4]
                    return broker, port, user, password
        except Exception as e:
            if self.debug:
                wm_log('WIFI', 'read_mqtt: {}'.format(e))
        return '', '1883', '', ''

    # ---- Connect helper ----
    def wifi_connect(self, ssid, password):
        wm_log('WIFI', 'Trying to connect to: {}'.format(ssid))
        self.wlan_sta.connect(ssid, password)
        for i in range(100):  # ~10s
            if self.wlan_sta.isconnected():
                wm_log('WIFI', 'Connected! IP: {}'.format(self.wlan_sta.ifconfig()[0]))
                return True
            if i % 10 == 0:
                wm_log('WIFI', 'Waiting... {}s'.format(i // 10))
            time.sleep_ms(100)
        wm_log('WIFI', 'Connection failed.')
        try:
            self.wlan_sta.disconnect()
        except:
            pass
        return False

    # ---- HTTP helpers ----
    def _read_request(self, client):
        data = b''
        # read headers (+maybe part of body)
        while CRLF2 not in data:
            chunk = client.recv(256)
            if not chunk:
                break
            data += chunk
        if CRLF2 in data:
            headers, body = data.split(CRLF2, 1)
        else:
            headers, body = data, b''
        # content-length
        clen = 0
        try:
            for line in headers.split(CRLF):
                ll = line.lower()
                if ll.startswith(b'content-length:'):
                    try:
                        clen = int(line.split(b':', 1)[1].strip())
                    except:
                        clen = 0
                    break
        except:
            clen = 0
        # read remaining body bytes if any
        if clen > len(body):
            need = clen - len(body)
            while need > 0:
                chunk = client.recv(256)
                if not chunk:
                    break
                body += chunk
                need -= len(chunk)
        if self.debug:
            try:
                first = headers.split(CRLF, 1)[0]
                wm_log('HTTP', 'first-line: {}'.format(first))
                wm_log('HTTP', 'len(headers)={} content-length={} len(body)={}'.format(len(headers), clen, len(body)))
            except Exception:
                pass
        return headers, body

    def _parse_path(self, headers):
        try:
            first = headers.split(CRLF, 1)[0]
            m = re.match(br'(GET|POST)\s+(/[^\s?]*)(?:\?[^\s]*)?\s+HTTP', first)
            if m:
                return m.group(2).decode('utf-8')
        except Exception:
            pass
        return '/'

    # ---- DNS captive portal (wildcard A -> AP IP) ----
    def _start_dns(self):
        if _thread is None:
            return
        ap_ip = self.wlan_ap.ifconfig()[0]
        ip_bytes = bytes(map(int, ap_ip.split('.')))
        def worker():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('', 53))
                while True:
                    try:
                        data, addr = s.recvfrom(256)
                        if not data or len(data) < 12:
                            continue
                        tid = data[0:2]
                        q = data[12:]
                        resp = tid + b'\x81\x80' + b'\x00\x01' + b'\x00\x01' + b'\x00\x00' + b'\x00\x00' + q
                        resp += b'\xc0\x0c' + b'\x00\x01' + b'\x00\x01' + b'\x00\x00\x00\x3c' + b'\x00\x04' + ip_bytes
                        s.sendto(resp, addr)
                    except Exception:
                        pass
            except Exception as e:
                if self.debug:
                    wm_log('WIFI', 'DNS: {}'.format(e))
        try:
            _thread.start_new_thread(worker, ())
        except Exception as e:
            if self.debug:
                wm_log('WIFI', 'DNS thread start: {}'.format(e))

    # ---- Captive portal ----
    def web_server(self):
        self.wlan_ap.active(False)
        time.sleep_ms(200)
        self.wlan_ap.active(True)
        try:
            self.wlan_ap.ifconfig(('192.168.4.1', '255.255.255.0', '192.168.4.1', '8.8.8.8'))
        except Exception:
            pass
        if self.ap_authmode == 0:
            self.wlan_ap.config(essid=self.ap_ssid, authmode=0, channel=6, hidden=0)
        else:
            self.wlan_ap.config(essid=self.ap_ssid, password=self.ap_password, authmode=self.ap_authmode, channel=6, hidden=0)
        time.sleep_ms(300)
        ap_ip = self.wlan_ap.ifconfig()[0]
        wm_log('WIFI', 'AP mode: connect to {} and browse to http://{}'.format(self.ap_ssid, ap_ip))
        self._start_dns()
        server_socket = socket.socket()
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('', 80))
        server_socket.listen(1)
        server_socket.settimeout(0.5)
        while True:
            # immediate reboot path if scheduled
            if hasattr(self, '_reboot_at') and (getattr(self, '_reboot_at', None) is not None):
                if time.ticks_diff(time.ticks_ms(), self._reboot_at) >= 0:
                    wm_log('WIFI', 'Rebooting now...')
                    machine.reset()
            try:
                client, addr = server_socket.accept()
            except OSError:
                # timeout to allow reboot check
                continue
            try:
                client.settimeout(5.0)
                headers, body = self._read_request(client)
                path = self._parse_path(headers)
                if self.debug:
                    try:
                        wm_log('HTTP', 'path={} body_len={}'.format(path, len(body)))
                    except Exception:
                        pass
                if path in ('/', '/index.html', '/hotspot-detect.html', '/generate_204', '/ncsi.txt', '/connecttest.txt'):
                    self.handle_root(client)
                elif path == '/configure':
                    self.handle_configure(client, body)
                else:
                    self.handle_root(client)
            except Exception as e:
                if self.debug:
                    wm_log('HTTP', 'loop err: {}'.format(e))
                try:
                    self.handle_root(client)
                except Exception:
                    pass
            finally:
                try:
                    client.close()
                except Exception:
                    pass

    def send_header(self, client, status_code=200):
        client.send('HTTP/1.1 {} OK\r\n'.format(status_code))
        client.send('Content-Type: text/html; charset=utf-8\r\n')
        client.send('Cache-Control: no-store, no-cache, must-revalidate\r\n')
        client.send('Pragma: no-cache\r\n')
        client.send('Expires: 0\r\n')
        client.send('Connection: close\r\n\r\n')

    def handle_root(self, client):
        # prefill from saved files
        profiles = self.read_credentials()
        saved_ssid = next(iter(profiles.keys())) if profiles else ''
        broker, port, user, password = self.read_mqtt()
        if not port:
            port = '1883'
        # if already connected, show status page
        if self.wlan_sta.isconnected():
            self.send_header(client)
            ip = self.wlan_sta.ifconfig()[0]
            client.send('<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OWON XDM Remote Setup</title></head><body><div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Inter,Arial,sans-serif;padding:24px">')
            client.send('<h2>Connected</h2><p>IP address: {}.</p>'.format(ip))
            client.send('</div></body></html>')
            return
        self.send_header(client)
        # scan networks
        seen = set(); nets = []
        try:
            for entry in self.wlan_sta.scan():
                ssid, bssid, channel, rssi, authmode, hidden = entry
                try:
                    ssid = ssid.decode('utf-8')
                except:
                    continue
                if (not ssid) or (ssid in seen):
                    continue
                seen.add(ssid)
                nets.append((ssid, channel, rssi, authmode))
        except Exception as e:
            if self.debug:
                wm_log('WIFI', 'scan in page: {}'.format(e))
        nets.sort(key=lambda x: x[2], reverse=True)
        # HTML
        client.send('<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OWON XDM Remote Setup</title>')
        client.send('<style>body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Inter,Arial,sans-serif;background:#eef1f7;color:#111;margin:0}.wrap{max-width:720px;margin:18px auto;padding:0 12px}h1{font-size:28px;text-align:center;margin:8px 0 14px;color:#0f172a}.card{background:#fff;border-radius:14px;box-shadow:0 6px 16px rgba(2,6,23,.06);margin:14px 0;overflow:hidden}.card h2{margin:0;padding:12px 16px;border-bottom:1px solid #edf2f7;font-size:18px}.list{padding:0}.row{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #f1f5f9}.row:last-child{border-bottom:0}.left{display:flex;align-items:center;gap:10px}.ssid{font-weight:600}.meta{font-size:12px;opacity:.8}.lock{opacity:.75}.section{padding:14px 16px}label.small{display:block;font-size:12px;margin:8px 0 6px;color:#334155}input[type=text],input[type=password],input[type=number]{width:100%;padding:10px 12px;border:1px solid #e2e8f0;border-radius:10px;box-sizing:border-box;background:#fbfdff}.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:12px}.btn{width:100%;padding:12px 14px;border:0;border-radius:12px;background:#2563eb;color:#fff;font-weight:700;margin:14px 0}</style></head><body><div class="wrap">')
        client.send('<h1>OWON XDM Remote Setup</h1>')
        client.send('<form action="/configure" method="post">')
        client.send('<div class="card"><h2>WiFi</h2><div class="list">')
        for ssid, ch, rssi, auth in nets:
            qual = int(max(min((rssi + 100) * 2, 100), 0))
            band = '2.4 GHz' if ch <= 14 else '5 GHz'
            lock = '&#128274;' if auth != 0 else '&#128275;'
            checked = ' checked' if saved_ssid and ssid == saved_ssid else ''
            row = '<label class="row"><span class="left"><input type="radio" name="ssid" value="' + ssid + '"' + checked + '><span class="ssid">' + ssid + '</span><span class="lock">' + lock + '</span></span><span class="meta">' + str(qual) + '% · ch ' + str(ch) + ' · ' + band + '</span></label>'
            client.send(row)
        client.send('</div><div class="section"><label class="small">WiFi Password</label><input type="password" name="password"></div></div>')
        client.send('<div class="card"><h2>MQTT</h2><div class="section grid-2">')
        client.send('<div><label class="small">Broker</label><input type="text" name="broker" value="' + (broker or '') + '"></div>')
        client.send('<div><label class="small">Port</label><input type="text" name="port" value="' + (port or '1883') + '"></div>')
        client.send('<div><label class="small">User</label><input type="text" name="muser" value="' + (user or '') + '"></div>')
        client.send('<div><label class="small">Pass</label><input type="password" name="mpass" value="' + (password or '') + '"></div>')
        client.send('</div><div class="section"><button class="btn" type="submit">Save & Connect</button></div></div>')
        client.send('</form></div></body></html>')

    def handle_configure(self, client, body_bytes):
        def parse_form(body):
            items = {}
            for part in (body or b'').split(b'&'):
                if b'=' in part:
                    k, v = part.split(b'=', 1)
                    v = v.replace(b'+', b' ')
                    try:
                        items[k.decode('utf-8')] = self.url_decode(v).decode('utf-8')
                    except Exception:
                        items[k.decode('utf-8')] = ''
            return items
        form = parse_form(body_bytes)
        ssid   = form.get('ssid', '')
        pwd    = form.get('password', '')
        broker = form.get('broker', '')
        port   = form.get('port', '1883') or '1883'
        muser  = form.get('muser', '')
        mpass  = form.get('mpass', '')
        if self.debug:
            try:
                masked_mpwd = '*' * len(mpass)
                wm_log('HTTP', "parsed form: ssid='{}' broker='{}' port='{}' user='{}' pass='{}'".format(ssid, broker, port, muser, masked_mpwd))
            except Exception:
                pass
        if len(ssid) == 0:
            self.send_header(client, 400)
            client.send('<html><body><p>SSID must be provided!</p><p><a href="/">← Back</a></p></body></html>')
            return
        profiles = self.read_credentials()
        profiles[ssid] = pwd
        self.write_credentials(profiles)
        self.write_mqtt(broker, port, muser, mpass)
        # success page, then immediate reboot to avoid portal reopen loop
        self.send_header(client)
        client.send('<html><body><p>Settings saved for <b>' + ssid + '</b>.</p><p>Rebooting now…</p></body></html>')
        try:
            client.close()
        except Exception:
            pass
        time.sleep_ms(400)
        machine.reset()

    def handle_not_found(self, client):
        self.send_header(client, 404)
        client.send('<p>Page not found!</p>')

    def url_decode(self, url_string):
        if not url_string:
            return b''
        if isinstance(url_string, str):
            url_string = url_string.encode('utf-8')
        bits = url_string.split(b'%')
        if len(bits) == 1:
            return url_string
        res = [bits[0]]
        hextobyte_cache = {}
        for item in bits[1:]:
            try:
                code = item[:2]
                char = hextobyte_cache.get(code)
                if char is None:
                    char = hextobyte_cache[code] = bytes([int(code, 16)])
                res.append(char)
                res.append(item[2:])
            except Exception:
                res.append(b'%')
                res.append(item)
        return b''.join(res)

