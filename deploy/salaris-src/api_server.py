"""
API для Google Sheets: одна кнопка — отправка строк с item_ids на сервер, проставление статусов в Mosaica (Selenium).
Шаг 1 (item_ids) пользователь делает на своём ПК (run.vbs + VPN). Сервер только шаг 2.
Endpoints: GET /health, GET /sheets-config, POST /process (синхронно), POST /process-async (фоново), GET /job/<id>.
"""

from __future__ import annotations

import os
import threading
import traceback
import uuid
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

load_dotenv()

app = Flask(__name__)
CORS(app)

API_KEY = os.getenv("API_KEY", "")
PROCESS_API_URL = os.getenv("PROCESS_API_URL", "")

# Фоновые задачи: job_id -> { status, results?, summary?, rows?, error? }
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def _parse_credentials_json(s: str):
    """Парсит JSON кредов из одной строки .env: как есть, с заменой переносов на \\n (если обрезало), затем base64."""
    import json
    import base64
    s = s.strip()
    if not s:
        return None
    # Прямой разбор + агрессивная починка private_key (\\n -> \n, выравнивание переносов)
    try:
        data = json.loads(s)
        pk = data.get("private_key")
        if isinstance(pk, str):
            # Частый кейс: в .env положили JSON одной строкой, где \n в ключе задвоили до \\n.
            # google-auth ожидает реальные переводы строк в PEM, иначе cryptography ругается
            # Unable to load PEM file / InvalidByte(0, 92).
            fixed_pk = pk.replace("\r\n", "\n").replace("\r", "\n").replace("\\n", "\n")
            data["private_key"] = fixed_pk
        return data
    except Exception:
        pass
    # В .env значение могло прийти с реальными переносами (например private_key обрезало или \\n превратилось в \n).
    # Заменяем реальные переносы на JSON-экранирование \\n, чтобы получить валидный JSON одной строки.
    try:
        fixed = s.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
        return json.loads(fixed)
    except Exception:
        pass
    # Base64: максимально удобно и безопасно — одна строка без кавычек и спецсимволов
    try:
        decoded = base64.b64decode(s).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        pass
    return None


def _get_sheets_client():
    """Клиент Google Sheets по кредам бота. Поддерживаются: путь к файлу, JSON строка (в т.ч. с переносами), base64(JSON)."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        return None
    import json
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.readonly"]

    def use_info(info):
        if not info or not isinstance(info, dict):
            return None
        try:
            creds = Credentials.from_service_account_info(info, scopes=scopes)
            return gspread.authorize(creds)
        except Exception:
            return None

    # 1) GOOGLE_SHEETS_CREDENTIALS: путь к файлу или JSON (или base64)
    raw = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
    if raw:
        raw = raw.strip()
        if os.path.isfile(raw):
            try:
                return gspread.authorize(Credentials.from_service_account_file(raw, scopes=scopes))
            except Exception:
                pass
        info = _parse_credentials_json(raw)
        if info:
            client = use_info(info)
            if client:
                return client

    # 2) GOOGLE_SHEETS_CREDENTIALS_JSON
    raw = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON")
    if raw:
        info = _parse_credentials_json(raw)
        if info:
            client = use_info(info)
            if client:
                return client

    # 3) GOOGLE_SHEETS_CREDENTIALS_B64 — только base64
    b64 = os.getenv("GOOGLE_SHEETS_CREDENTIALS_B64")
    if b64:
        info = _parse_credentials_json(b64.strip())
        if info:
            client = use_info(info)
            if client:
                return client

    # 4) Запас: GOOGLE_APPLICATION_CREDENTIALS (путь или JSON/base64)
    raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if raw:
        raw = raw.strip()
        if os.path.isfile(raw):
            try:
                return gspread.authorize(Credentials.from_service_account_file(raw, scopes=scopes))
            except Exception:
                pass
        info = _parse_credentials_json(raw)
        if info:
            client = use_info(info)
            if client:
                return client

    raw = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if raw:
        info = _parse_credentials_json(raw)
        if info:
            client = use_info(info)
            if client:
                return client

    return None


def _credentials_diagnostic() -> str:
    """Почему не поднялись креды — для подсказки в 501."""
    v = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
    if v:
        v = v.strip()
        if os.path.isfile(v):
            return "GOOGLE_SHEETS_CREDENTIALS указывает на файл, но авторизация не прошла (проверь содержимое JSON)."
        if _parse_credentials_json(v):
            return "JSON парсится, но gspread/oauth не приняли креды (проверь client_email и права)."
        return "GOOGLE_SHEETS_CREDENTIALS задан, но JSON не удалось разобрать (проверь одну строку, кавычки, \\n в private_key)."
    if os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON") or os.getenv("GOOGLE_SHEETS_CREDENTIALS_B64"):
        return "Переменная задана, но разбор или авторизация не прошли. Проверь валидность JSON/base64."
    return "GOOGLE_SHEETS_CREDENTIALS не задан в .env на сервере. Добавь (путь к файлу или JSON строкой), перезапусти контейнер."


def validate_api_key() -> bool:
    if not API_KEY:
        return True
    provided_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    return provided_key == API_KEY


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "message": "Server is running"})


@app.route("/sheets-config", methods=["GET"])
def sheets_config():
    """Конфиг для Google Sheets: URL шага 2 (этот сервер), API key."""
    base = request.url_root.rstrip("/")
    return jsonify({
        "process_api_url": PROCESS_API_URL or base,
        "api_key": API_KEY,
    })


@app.route("/process", methods=["POST"])
def process_data():
    """
    Запуск Salaris (Selenium). Item_ids приходят из листа (заполнены пользователем на ПК через run.vbs).
    """
    if not validate_api_key():
        return jsonify({"error": "Invalid API key"}), 401

    try:
        data = request.get_json()
        if not data or "rows" not in data:
            return jsonify({"error": "Invalid request format"}), 400

        rows = data["rows"]
        if not rows:
            return jsonify({"error": "No rows provided"}), 400

        results = []
        for r in rows:
            ids = r.get("item_ids") or []
            if isinstance(ids, str):
                ids = [x.strip() for x in ids.split(",") if x.strip()]
            results.append({
                "row_index": r.get("row_index", 0),
                "item_ids": ids,
                "item_ids_count": len(ids),
                "search_source": r.get("search_source") or "provided",
                "error": None,
            })

        print("Проставление статусов (Salaris)...")
        status_results = process_statuses(results)

        return jsonify({
            "results": status_results,
            "summary": {
                "total_rows": len(rows),
                "found_item_ids": sum(1 for r in status_results if r.get("item_ids_count", 0) > 0),
                "not_found": sum(1 for r in status_results if r.get("item_ids_count", 0) == 0),
                "status_changed": sum(1 for r in status_results if r.get("status_changed", False)),
                "status_errors": sum(1 for r in status_results if r.get("status_error")),
            },
        })

    except Exception as e:
        print(f"Ошибка обработки: {e}")
        print(traceback.format_exc())
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route("/process-async", methods=["POST"])
def process_async():
    """
    Запуск Salaris в фоне. Сразу возвращает job_id. Результат забирать через GET /job/<job_id>.
    Так Google Apps Script не упирается в лимит времени (6 мин): кнопка только шлёт запрос и показывает
    «Обрабатывается N айтемов, ~X мин. Позже нажмите „Проверить результат“ с job_id».
    """
    if not validate_api_key():
        return jsonify({"error": "Invalid API key"}), 401

    try:
        data = request.get_json()
        if not data or "rows" not in data:
            return jsonify({"error": "Invalid request format"}), 400

        rows = data["rows"]
        if not rows:
            return jsonify({"error": "No rows provided"}), 400

        results = []
        for r in rows:
            ids = r.get("item_ids") or []
            if isinstance(ids, str):
                ids = [x.strip() for x in ids.split(",") if x.strip()]
            results.append({
                "row_index": r.get("row_index", 0),
                "item_ids": ids,
                "item_ids_count": len(ids),
                "search_source": r.get("search_source") or "provided",
                "error": None,
            })

        total_items = sum(len(r.get("item_ids", [])) for r in results)
        job_id = str(uuid.uuid4())
        with _jobs_lock:
            _jobs[job_id] = {
                "status": "pending",
                "rows": results,
                "results": None,
                "summary": None,
                "error": None,
            }

        def run_job():
            with _jobs_lock:
                _jobs[job_id]["status"] = "running"
            try:
                status_results = process_statuses(results)
                summary = {
                    "total_rows": len(rows),
                    "found_item_ids": sum(1 for r in status_results if r.get("item_ids_count", 0) > 0),
                    "not_found": sum(1 for r in status_results if r.get("item_ids_count", 0) == 0),
                    "status_changed": sum(1 for r in status_results if r.get("status_changed", False)),
                    "status_errors": sum(1 for r in status_results if r.get("status_error")),
                }
                with _jobs_lock:
                    _jobs[job_id]["status"] = "done"
                    _jobs[job_id]["results"] = status_results
                    _jobs[job_id]["summary"] = summary
            except Exception as e:
                print(f"Ошибка фоновой задачи {job_id}: {e}")
                print(traceback.format_exc())
                with _jobs_lock:
                    _jobs[job_id]["status"] = "error"
                    _jobs[job_id]["error"] = str(e)

        threading.Thread(target=run_job, daemon=True).start()

        # ~2 мин на айтем — ориентир для пользователя
        est_min = max(1, total_items * 2)
        return jsonify({
            "job_id": job_id,
            "message": f"Задача принята. Обрабатывается {total_items} айтемов, ориентировочно ~{est_min} мин. Результат: GET /job/{job_id}",
            "total_items": total_items,
            "estimated_minutes": est_min,
        }), 202

    except Exception as e:
        print(f"Ошибка process-async: {e}")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/process-from-sheet", methods=["POST"])
def process_from_sheet():
    """
    Сервер сам читает лист по кредам бота, обрабатывает айтемы в Selenium, пишет в таблицу
    статус и раскраску и по окончании выставляет «Готово». Скрипт в таблице только дергает
    этот URL и сразу завершается — в лимит Google не упираемся.
    Тело: spreadsheet_id (обяз.), sheet_name (имя листа), id_column (буква/номер колонки с item_id), status_column (куда писать статус).
    """
    if not validate_api_key():
        return jsonify({"error": "Invalid API key"}), 401

    client = _get_sheets_client()
    if not client:
        hint = _credentials_diagnostic()
        return jsonify({
            "error": "Google Sheets credentials not configured",
            "hint": hint + " Расшарь таблицу на client_email из ключа.",
        }), 501

    try:
        data = request.get_json() or {}
        spreadsheet_id = (data.get("spreadsheet_id") or "").strip()
        if not spreadsheet_id:
            return jsonify({"error": "spreadsheet_id required"}), 400

        sheet_name = data.get("sheet_name") or None
        id_column = data.get("id_column")  # буква "D" или номер 1-based
        status_column = data.get("status_column")
        data_start_row = int(data.get("data_start_row") or 2)  # с какой строки данные (1-based)
        report_sheet_name = data.get("report_sheet_name") or None  # лист REPORT: очищаем и пишем статус + пастельная раскраска
        done_checkbox_cell = (data.get("done_checkbox_cell") or "").strip() or None  # ячейка «Готово» (например F1): по завершении ставим TRUE
        counter_cell = (data.get("counter_cell") or "").strip() or None  # ячейка счётчика «готово/всего» (например H1)

        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name) if sheet_name else spreadsheet.sheet1
        all_rows = worksheet.get_all_values()
        if not all_rows:
            return jsonify({"error": "Sheet is empty"}), 400

        headers = [str(h).strip().lower() for h in all_rows[0]]
        id_col_idx = None
        if id_column is not None:
            if isinstance(id_column, int):
                id_col_idx = max(0, id_column - 1)
            else:
                col_letter = str(id_column).strip().upper()
                id_col_idx = _a1_to_col(col_letter) - 1
        if id_col_idx is None:
            for i, h in enumerate(headers):
                if "item" in h and "id" in h:
                    id_col_idx = i
                    break
                if h in ("item_id", "item ids", "item_ids"):
                    id_col_idx = i
                    break
        if id_col_idx is None:
            id_col_idx = 0

        status_col_idx = status_column
        if status_col_idx is not None:
            if isinstance(status_col_idx, int):
                status_col_idx = max(0, status_col_idx - 1)
            else:
                status_col_idx = _a1_to_col(str(status_col_idx).strip().upper()) - 1
        else:
            status_col_idx = id_col_idx + 1

        results = []
        start_index = max(0, data_start_row - 1)  # 0-based: строка 3 → index 2
        for row_idx, row in enumerate(all_rows[start_index:], start=data_start_row):
            cell = row[id_col_idx] if id_col_idx < len(row) else ""
            if not cell:
                continue
            ids = [x.strip() for x in str(cell).split(",") if x.strip()]
            if not ids:
                continue
            results.append({
                "row_index": row_idx,
                "item_ids": ids,
                "item_ids_count": len(ids),
                "search_source": "sheet",
                "error": None,
            })

        if not results:
            return jsonify({"error": "No rows with item_ids found in sheet"}), 400

        job_id = str(uuid.uuid4())
        with _jobs_lock:
            _jobs[job_id] = {
                "status": "pending",
                "from_sheet": True,
                "spreadsheet_id": spreadsheet_id,
                "worksheet_title": worksheet.title,
                "results_template": results,
                "results": None,
                "summary": None,
                "error": None,
            }

        total_items_count = sum(len(r.get("item_ids", [])) for r in results)

        def run_sheet_job(
            _report_sheet_name=report_sheet_name,
            _spreadsheet_id=spreadsheet_id,
            _worksheet_title=worksheet.title,
            _done_checkbox_cell=done_checkbox_cell,
            _counter_cell=counter_cell,
        ):
            with _jobs_lock:
                _jobs[job_id]["status"] = "running"
            try:
                sheet2 = client.open_by_key(_spreadsheet_id).worksheet(_worksheet_title)
                if _counter_cell:
                    try:
                        sheet2.update_acell(_counter_cell, f"0/{total_items_count}")
                    except Exception:
                        pass

                _last_counter_update = [0]  # mutable to avoid nonlocal

                def _on_progress(k: int, n: int) -> None:
                    if _counter_cell and (k - _last_counter_update[0] >= 10 or k == n):
                        _last_counter_update[0] = k
                        try:
                            sheet2.update_acell(_counter_cell, f"{k}/{n}")
                        except Exception:
                            pass

                status_results = process_statuses(results, on_progress=_on_progress)
                with _jobs_lock:
                    _jobs[job_id]["results"] = status_results
                    _jobs[job_id]["summary"] = {
                        "total_rows": len(results),
                        "status_changed": sum(1 for r in status_results if r.get("status_changed")),
                        "status_errors": sum(1 for r in status_results if r.get("status_error")),
                    }
                    _jobs[job_id]["status"] = "done"

                # Пастельные цвета: зелёный — статус сменился, жёлтый — ошибка, красный — не сменился
                pastel_green = {"red": 0.85, "green": 1, "blue": 0.9}
                pastel_yellow = {"red": 1, "green": 1, "blue": 0.85}
                pastel_red = {"red": 1, "green": 0.9, "blue": 0.9}

                # Батч: один запрос на все статусы + один batch_update на раскраску (лимит 100 write/min)
                num_cols = max(len(all_rows[0]), status_col_idx + 2, 8)
                valid_results = [r for r in status_results if r.get("row_index")]
                if not valid_results:
                    pass
                else:
                    status_col_a1 = _col_to_a1(status_col_idx + 1)
                    min_row = min(r["row_index"] for r in valid_results)
                    max_row = max(r["row_index"] for r in valid_results)
                    row_to_result = {r["row_index"]: r for r in valid_results}
                    # Один update() на колонку статуса
                    status_values = []
                    for ri in range(min_row, max_row + 1):
                        r = row_to_result.get(ri)
                        if r:
                            status_values.append(
                                ["Готово" if r.get("status_changed") else ("Ошибка: " + (r.get("status_error") or "—")[:200])]
                            )
                        else:
                            status_values.append([""])
                    range_status = f"{status_col_a1}{min_row}:{status_col_a1}{max_row}"
                    try:
                        sheet2.update(range_status, status_values, value_input_option="USER_ENTERED")
                    except Exception as ex:
                        print(f"Ошибка batch update статусов: {ex}")
                    # Заголовок "Всё готово"
                    try:
                        sheet2.update_cell(1, status_col_idx + 1, "Всё готово · Salaris")
                    except Exception:
                        pass

                    # Раскраска: один batch_update на все строки (Sheet API)
                    spread = client.open_by_key(_spreadsheet_id)
                    sheet_id = sheet2.id
                    format_requests = []
                    for r in valid_results:
                        row_index = r["row_index"]
                        if r.get("status_changed"):
                            color = pastel_green
                        elif r.get("status_error"):
                            color = pastel_yellow
                        else:
                            color = pastel_red
                        format_requests.append({
                            "repeatCell": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": row_index - 1,
                                    "endRowIndex": row_index,
                                    "startColumnIndex": 0,
                                    "endColumnIndex": num_cols,
                                },
                                "cell": {"userEnteredFormat": {"backgroundColor": color}},
                                "fields": "userEnteredFormat.backgroundColor",
                            }
                        })
                    if format_requests:
                        try:
                            spread.batch_update({"requests": format_requests})
                        except Exception as ex:
                            print(f"Ошибка batch format: {ex}")

                # REPORT: один clear + один update диапазона + один batch format (если лист указан)
                if _report_sheet_name:
                    try:
                        report_ws = client.open_by_key(_spreadsheet_id).worksheet(_report_sheet_name)
                        report_spread = client.open_by_key(_spreadsheet_id)
                        report_sheet_id = report_ws.id
                        report_ws.batch_clear(["A2:H500"])
                        # Шапка: строка N в REPORT = строка N в NoStatus.
                        # D–F пишет BigQuery; G–H пишет Salaris (Да/Нет + ошибка). Цвет = итог.
                        try:
                            report_ws.update(
                                "A1:H2",
                                [
                                    [
                                        "REPORT = лог Salaris",
                                        "строка N = NoStatus N",
                                        "не править руками",
                                        "item_ids (BQ)",
                                        "кол-во id",
                                        "источник BQ",
                                        "статус сменён?",
                                        "ошибка / комментарий",
                                    ],
                                    [
                                        "зелёный = ок",
                                        "жёлтый = ошибка",
                                        "красный = не сменился",
                                        "",
                                        "",
                                        "",
                                        "Да / Нет",
                                        "текст от Selenium",
                                    ],
                                ],
                                value_input_option="USER_ENTERED",
                            )
                            try:
                                report_spread.batch_update({
                                    "requests": [{
                                        "updateSheetProperties": {
                                            "properties": {
                                                "sheetId": report_sheet_id,
                                                "gridProperties": {"frozenRowCount": 2},
                                            },
                                            "fields": "gridProperties.frozenRowCount",
                                        }
                                    }]
                                })
                            except Exception as ex:
                                print(f"Ошибка freeze REPORT: {ex}")
                        except Exception as ex:
                            print(f"Ошибка шапки REPORT: {ex}")
                        if valid_results:
                            min_r, max_r = min(r["row_index"] for r in valid_results), max(r["row_index"] for r in valid_results)
                            report_data = []
                            report_format_reqs = []
                            for ri in range(min_r, max_r + 1):
                                r = row_to_result.get(ri)
                                if r:
                                    report_data.append([
                                        "Да" if r.get("status_changed") else "Нет",
                                        (r.get("status_error") or "")[:500],
                                    ])
                                    if r.get("status_changed"):
                                        color = pastel_green
                                    elif r.get("status_error"):
                                        color = pastel_yellow
                                    else:
                                        color = pastel_red
                                    report_format_reqs.append({
                                        "repeatCell": {
                                            "range": {
                                                "sheetId": report_sheet_id,
                                                "startRowIndex": ri - 1,
                                                "endRowIndex": ri,
                                                "startColumnIndex": 0,
                                                "endColumnIndex": 8,
                                            },
                                            "cell": {"userEnteredFormat": {"backgroundColor": color}},
                                            "fields": "userEnteredFormat.backgroundColor",
                                        }
                                    })
                                else:
                                    report_data.append(["", ""])
                            if report_data:
                                report_ws.update(f"G{min_r}:H{max_r}", report_data, value_input_option="USER_ENTERED")
                            if report_format_reqs:
                                report_spread.batch_update({"requests": report_format_reqs})
                    except Exception as ex:
                        print(f"Ошибка записи в REPORT: {ex}")

                # Галочка «Готово»: по завершении ставим TRUE в указанную ячейку (например F1)
                if _done_checkbox_cell:
                    try:
                        sheet2.update_acell(_done_checkbox_cell, True)
                    except Exception as ex:
                        print(f"Ошибка установки галочки Готово: {ex}")
            except Exception as e:
                print(f"Ошибка process-from-sheet {job_id}: {e}")
                print(traceback.format_exc())
                with _jobs_lock:
                    _jobs[job_id]["status"] = "error"
                    _jobs[job_id]["error"] = str(e)

        threading.Thread(target=run_sheet_job, daemon=True).start()

        total_items = sum(len(r.get("item_ids", [])) for r in results)
        return jsonify({
            "job_id": job_id,
            "message": "Обработка запущена. Сервер обновит лист по окончании (статус и раскраска). Всё готово — в ячейке A1.",
            "total_rows": len(results),
            "total_items": total_items,
        }), 202

    except Exception as e:
        print(f"Ошибка process-from-sheet: {e}")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


def _a1_to_col(col_letter: str) -> int:
    """Буква колонки (A, B, ..., Z, AA, ...) -> номер 1-based."""
    col = 0
    for c in col_letter.upper():
        col = col * 26 + (ord(c) - ord("A") + 1)
    return col


def _col_to_a1(col: int) -> str:
    """Номер колонки 1-based -> буква (A, B, ..., Z, AA, ...)."""
    result = []
    while col:
        col, rem = divmod(col - 1, 26)
        result.append(chr(rem + ord("A")))
    return "".join(reversed(result))


@app.route("/job/<job_id>", methods=["GET"])
def job_status(job_id):
    """Статус и результат фоновой задачи. Когда status=done — в ответе results и summary (как у POST /process)."""
    if not validate_api_key():
        return jsonify({"error": "Invalid API key"}), 401

    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found", "job_id": job_id}), 404

    out = {"job_id": job_id, "status": job["status"]}
    if job["status"] == "done":
        out["results"] = job["results"]
        out["summary"] = job["summary"]
    if job["status"] == "error" and job.get("error"):
        out["error"] = job["error"]
    return jsonify(out)


def process_statuses(
    results: List[Dict[str, Any]],
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> List[Dict[str, Any]]:
    """Проставляет статусы в Mosaica для найденных item_id. on_progress(обработано, всего) — опционально."""
    all_item_ids: List[str] = []
    item_id_to_row_index: Dict[str, int] = {}

    for result in results:
        row_index = result["row_index"]
        for item_id in result.get("item_ids", []):
            all_item_ids.append(item_id)
            item_id_to_row_index[item_id] = row_index

    if not all_item_ids:
        for result in results:
            result["status_changed"] = False
            result["status_error"] = None
        return results

    status_results = run_status_processor(all_item_ids, on_progress=on_progress)

    row_status_map: Dict[int, Dict[str, Any]] = {}
    for status_result in status_results:
        item_id = status_result.get("item_id", "")
        row_index = item_id_to_row_index.get(item_id, 0)
        if row_index not in row_status_map:
            row_status_map[row_index] = {"status_changed": False, "status_errors": []}
        if status_result.get("status") == "changed":
            row_status_map[row_index]["status_changed"] = True
        elif status_result.get("status") == "error":
            row_status_map[row_index]["status_errors"].append(
                f"{item_id}: {status_result.get('message', 'Unknown error')}"
            )
        elif status_result.get("status") == "skipped_not_found":
            row_status_map[row_index]["status_errors"].append(
                f"{item_id}: {status_result.get('message', 'Не найден в full search')}"
            )

    for result in results:
        row_index = result["row_index"]
        row_status = row_status_map.get(row_index, {})
        result["status_changed"] = row_status.get("status_changed", False)
        errors = row_status.get("status_errors", [])
        result["status_error"] = "; ".join(errors) if errors else None

    return results


def run_status_processor(
    item_ids: List[str],
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> List[Dict[str, Any]]:
    """Запускает Selenium (process_items_no_status). on_progress(обработано, всего) вызывается после каждого айтема."""
    try:
        from process_items_no_status import ItemProcessResult, process_items

        result_dict = process_items(item_ids, on_progress=on_progress)
        results: List[ItemProcessResult] = result_dict.get("results", [])
        return [
            {"item_id": r.item_id, "status": r.status, "message": r.message}
            for r in results
        ]
    except Exception as e:
        print(f"Ошибка при проставлении статусов: {e}")
        print(traceback.format_exc())
        return [
            {"item_id": iid, "status": "error", "message": str(e)}
            for iid in item_ids
        ]


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("DEBUG", "False").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
