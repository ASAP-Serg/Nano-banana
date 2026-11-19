/**
 * Только запуск: кнопка дергает сервер, всё остальное (чтение листа, Selenium, статус, раскраска, галочка, счётчик) — на сервере.
 * Кнопку привязать: правый клик по кнопке → Назначить скрипт → runSalarisOnly
 */

const SERVER_URL = 'https://ooneclickk.ru/salaris';
const DISABLED_SHEET_NAME = 'Disabled';
const REPORT_SHEET_NAME = 'REPORT';

function getConfig() {
  var url = SERVER_URL + '/sheets-config';
  var response = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  if (response.getResponseCode() !== 200) {
    throw new Error('Сервер недоступен (' + url + '): ' + response.getContentText());
  }
  return JSON.parse(response.getContentText());
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Обработка данных')
    .addItem('Запустить Salaris на сервере', 'runSalarisOnly')
    .addItem('Очистить результаты', 'clearResults')
    .addToUi();
}

/** Только запуск выполнения на сервере. Сервер сам читает лист, обрабатывает, пишет статус и раскраску. */
function runSalarisOnly() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var disabled = ss.getSheetByName(DISABLED_SHEET_NAME);
  if (!disabled) {
    SpreadsheetApp.getUi().alert('Лист "' + DISABLED_SHEET_NAME + '" не найден.');
    return;
  }
  var lastRow = disabled.getLastRow();
  if (lastRow < 3) {
    SpreadsheetApp.getUi().alert('Нет данных в листе.');
    return;
  }
  var colD = disabled.getRange(3, 4, lastRow, 4).getValues();
  var withIds = colD.filter(function(row) { return String(row[0] || '').trim().length > 0; }).length;
  if (withIds === 0) {
    SpreadsheetApp.getUi().alert('Нет строк с item_ids. Заполни колонку D (run.vbs на ПК с VPN), затем нажми кнопку.');
    return;
  }
  var ui = SpreadsheetApp.getUi();
  if (ui.alert('Запустить Salaris', 'Строк с item_id: ' + withIds + '. Запустить на сервере?', ui.ButtonSet.YES_NO) !== ui.Button.YES) return;

  try {
    clearReportSheet();
    disabled.getRange('F1').setValue(false);
    var config = getConfig();
    // Всегда SERVER_URL: сервер отдаёт process_api_url без префикса /salaris (Flask не видит прокси), иначе POST уходит на 8000 → 404.
    var baseUrl = SERVER_URL.replace(/\/$/, '');
    var response = UrlFetchApp.fetch(baseUrl + '/process-from-sheet', {
      method: 'post',
      contentType: 'application/json',
      headers: { 'X-API-Key': config.api_key || '' },
      payload: JSON.stringify({
        spreadsheet_id: ss.getId(),
        sheet_name: DISABLED_SHEET_NAME,
        id_column: 'D',
        status_column: 'E',
        data_start_row: 3,
        report_sheet_name: REPORT_SHEET_NAME,
        done_checkbox_cell: 'F1',
        counter_cell: 'H1'
      }),
      muteHttpExceptions: true
    });
    var code = response.getResponseCode();
    var body = JSON.parse(response.getContentText() || '{}');

    if (code === 202) {
      ui.alert('Запущено', (body.message || 'Сервер обрабатывает. Обнови страницу через несколько минут.') + '\n\nСтрок: ' + (body.total_rows || withIds), ui.ButtonSet.OK);
      return;
    }
    if (code === 501) {
      ui.alert('На сервере не настроены креды бота для таблиц. В .env на сервере добавь GOOGLE_SHEETS_CREDENTIALS (JSON строкой или путь к файлу), перезапусти контейнер и расшарь таблицу на client_email из ключа.');
      return;
    }
    ui.alert('Ошибка ' + code + ': ' + (body.error || body.hint || response.getContentText()));
  } catch (e) {
    SpreadsheetApp.getUi().alert('Ошибка: ' + e.toString());
  }
}

function clearReportSheet() {
  var report = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(REPORT_SHEET_NAME);
  if (!report) return;
  var rLast = report.getLastRow();
  if (rLast < 2) return;
  report.getRange(2, 1, rLast, 8).clearContent();
  report.getRange(2, 1, rLast, 8).setBackground(null);
}

function clearResults() {
  var ui = SpreadsheetApp.getUi();
  if (ui.alert('Очистка', 'Очистить item_ids в Disabled и данные в REPORT?', ui.ButtonSet.YES_NO) !== ui.Button.YES) return;
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var disabled = ss.getSheetByName(DISABLED_SHEET_NAME);
  if (disabled && disabled.getLastRow() >= 3) {
    var lastRow = disabled.getLastRow();
    disabled.getRange(3, 4, lastRow, 4).clearContent();
    disabled.getRange(3, 1, lastRow, 4).setBackground(null);
  }
  var report = ss.getSheetByName(REPORT_SHEET_NAME);
  if (report && report.getLastRow() >= 2) {
    var rLast = report.getLastRow();
    report.getRange(2, 1, rLast, 8).clearContent();
    report.getRange(2, 1, rLast, 8).setBackground(null);
  }
}
