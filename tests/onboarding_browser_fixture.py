"""Изолированная browser-проверка формы; API fixture, без auth/БД/production.

Запуск из корня: python tests/onboarding_browser_fixture.py
Открыть http://127.0.0.1:8766, добавить оборудование, проверить показанный payload.
Выполняются функции текущего app.js; business API заменён явно, это не полный E2E.
"""
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def page():
    source = Path('app/static/app.js').read_text()
    functions = []
    for name in ['esc', 'toast', 'closeModal', 'openModal', 'readableClientName',
                 'ensureEquipmentTypes', 'renderClientEquipment', 'openCreateEquipmentModal']:
        start = re.search(r'(?:async )?function ' + name + r'\(', source).start()
        following = re.search(r'\n(?:async )?function ', source[start + 1:])
        functions.append(source[start:start + 1 + following.start()] if following else source[start:])
    fixture = """
    const state = {me:{role:'client_site_user'},equipmentTypes:[],
      sites:[{id:'own-site',client_id:'client-a',name:'Пилотный объект',is_active:true}],
      clients:[{id:'client-a',name:'Тестовый клиент'}]};
    function stopAdminQrScan() {}
    async function ensureCustomers() {}
    async function api(path, options) {
      if(path==='/equipment-types')return [{id:7,name:'Поломоечная машина'}];
      if(path==='/client-portal/equipment')return [];
      if(path==='/equipment') {
        const payload = JSON.parse(options.body);
        document.getElementById('result').textContent = JSON.stringify(payload,null,2);
        return {id:'fixture-equipment'};
      }
      throw new Error('API fixture: неизвестный путь '+path);
    }
    async function openEquipmentPassport(id) {
      document.getElementById('outcome').textContent='Вызван паспорт: '+id;
    }
    renderClientEquipment(document.getElementById('content'));
    """
    return ('<!doctype html><html lang="ru"><meta charset="utf-8"><title>P0.1 — тест формы</title>'
        '<link rel="stylesheet" href="/style.css"><body><p>Изолированная проверка UI — тестовые данные, API fixture</p>'
        '<main id="content"></main><pre id="result"></pre><p id="outcome"></p><div id="toast-root"></div>'
        '<script>' + '\n'.join(functions) + '\n' + fixture + '</script></body></html>').encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/': body, mime = page(), 'text/html; charset=utf-8'
        elif self.path == '/style.css': body, mime = Path('app/static/styles.css').read_bytes(), 'text/css'
        else:
            self.send_error(404); return
        self.send_response(200); self.send_header('Content-Type',mime)
        self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)


if __name__ == '__main__':
    HTTPServer(('0.0.0.0',8766),Handler).serve_forever()
