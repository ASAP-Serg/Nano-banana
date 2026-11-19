<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
require_once __DIR__ . '/image_optimizer.php';

$__cfg = require __DIR__ . '/config.php';
$UPLOAD_TOKEN = (string)$__cfg['api_token'];

// === настройки ===
$FILES_DIR = __DIR__ . '/files';
$BASE_URL  = (string)$__cfg['files_url'];

$MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024; // 32 MB (исходники с Я.Диска до ~29 MB)
$CURL_TIMEOUT       = 90;
$CURL_CONNECT_TO    = 10;
$DOWNLOAD_RETRIES   = 3;
$RETRY_BASE_MS      = 600;

$MAX_IMAGES_TOTAL     = 50;               // максимум картинок при обработке папки/zip
$MAX_ENTRY_BYTES      = 32 * 1024 * 1024; // 32MB на один файл (внутри zip или скачиваемый файл)

// === helpers ===
function jexit(array $data, int $code = 200): void {
  http_response_code($code);
  echo json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
  exit;
}

function ensure_dir(string $dir): void {
  if (!is_dir($dir)) {
    if (!mkdir($dir, 0775, true) && !is_dir($dir)) {
      jexit(['error' => 'mkdir_failed'], 500);
    }
  }
  if (!is_writable($dir)) {
    jexit(['error' => 'dir_not_writable', 'dir' => $dir], 500);
  }
}

function detect_mime(string $bytes): string {
  $finfo = new finfo(FILEINFO_MIME_TYPE);
  $mime = $finfo->buffer($bytes); 
  return $mime ?: 'application/octet-stream';
}

function ext_from_mime(string $mime): ?string {
  static $map = [
    'image/jpeg' => 'jpg',
    'image/jpg'  => 'jpg',
    'image/png'  => 'png',
    'image/gif'  => 'gif',
    'image/webp' => 'webp',
    'image/bmp'  => 'bmp',
    'image/tiff' => 'tif',
    'image/avif' => 'avif',
    'image/svg+xml' => 'svg',
  ];
  return $map[strtolower($mime)] ?? null;
}

function save_image_bytes(string $bytes, string $mime, string $filesDir, string $baseUrl): array {
  $optimized = optimize_image_to_webp($bytes, $mime);

  // Если оптимизация недоступна для формата (например SVG), сохраняем как раньше.
  if (($optimized['ok'] ?? false) === true) {
    $bytes = (string)$optimized['bytes'];
    $mime = 'image/webp';
    $ext = 'webp';
  } else {
    $ext = ext_from_mime($mime);
    if ($ext === null) {
      return ['ok' => false, 'error' => 'unsupported_image_mime', 'mime' => $mime];
    }
  }

  $name = 'img_' . uniqid('', true) . '.' . $ext;
  $path = rtrim($filesDir, '/\\') . DIRECTORY_SEPARATOR . $name;

  if (file_put_contents($path, $bytes) === false) {
    return ['ok' => false, 'error' => 'write_failed'];
  }

  return [
    'ok'   => true,
    'url'  => rtrim($baseUrl, '/') . '/' . $name,
    'mime' => $mime,
    'size' => filesize($path) ?: strlen($bytes),
  ];
}

function curl_fetch(string $url, string $method = 'GET', ?array $postFields = null, int $timeout = 30, int $connectTimeout = 10, int $maxBytes = 0): array {
  $ch = curl_init($url);
  if (!$ch) return ['ok' => false, 'error' => 'curl_init_failed'];

  $headers = [];
  $data = '';

  $opts = [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_FOLLOWLOCATION => true,
    CURLOPT_MAXREDIRS      => 10,
    CURLOPT_TIMEOUT        => $timeout,
    CURLOPT_CONNECTTIMEOUT => $connectTimeout,
    CURLOPT_USERAGENT      => 'UploaderByURL/2.4 (+https://uploader.ooneclickk.ru)',
    CURLOPT_SSL_VERIFYPEER => true,
    CURLOPT_SSL_VERIFYHOST => 2,
    CURLOPT_HEADERFUNCTION => function($curl, $headerLine) use (&$headers) {
      $len = strlen($headerLine);
      $headerLine = trim($headerLine);
      if ($headerLine === '' || strpos($headerLine, ':') === false) return $len;
      [$k, $v] = explode(':', $headerLine, 2);
      $headers[strtolower(trim($k))] = trim($v);
      return $len;
    },
  ];

  if ($method === 'POST') {
    $opts[CURLOPT_POST] = true;
    $opts[CURLOPT_POSTFIELDS] = $postFields ?? [];
  }

  // ограничение на размер ответа
  if ($maxBytes > 0) {
    $opts[CURLOPT_WRITEFUNCTION] = function($curl, $chunk) use (&$data, $maxBytes) {
      $data .= $chunk;
      if (strlen($data) > $maxBytes) return 0;
      return strlen($chunk);
    };
  }

  curl_setopt_array($ch, $opts);

  $ok = curl_exec($ch);
  $errno = curl_errno($ch);
  $err   = curl_error($ch);
  $http  = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
  $ct    = (string)curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
  curl_close($ch);

  if ($errno !== 0) {
    if ($maxBytes > 0 && strlen($data) > $maxBytes) {
      return ['ok' => false, 'error' => 'too_large', 'max' => $maxBytes];
    }
    return ['ok' => false, 'error' => 'curl_error', 'errno' => $errno, 'message' => $err];
  }

  if ($maxBytes === 0) $data = is_string($ok) ? $ok : '';

  return [
    'ok'      => true,
    'bytes'   => $data,
    'ct'      => $ct,
    'headers' => $headers,
    'http'    => $http,
  ];
}

function download_url(
  string $url,
  int $maxBytes,
  int $timeout,
  int $connectTimeout,
  int $retries = 1,
  int $retryBaseMs = 0
): array {
  $last = ['ok' => false, 'error' => 'download_failed'];
  $attempts = max(1, $retries);

  for ($attempt = 1; $attempt <= $attempts; $attempt++) {
    $r = curl_fetch($url, 'GET', null, $timeout, $connectTimeout, $maxBytes);
    $r['attempt'] = $attempt;
    $r['attemptsTotal'] = $attempts;

    if (!($r['ok'] ?? false)) {
      $last = $r;
      $shouldRetry = (($r['error'] ?? '') === 'curl_error');
      if ($shouldRetry && $attempt < $attempts) {
        $delayMs = max(0, $retryBaseMs) * (int)pow(2, $attempt - 1);
        if ($delayMs > 0) usleep($delayMs * 1000);
        continue;
      }
      return $last;
    }

    $http = (int)($r['http'] ?? 0);
    if ($http >= 200 && $http < 300) {
      return $r;
    }

    $last = [
      'ok' => false,
      'error' => 'bad_http',
      'http' => $http,
      'body' => substr((string)($r['bytes'] ?? ''), 0, 300),
      'attempt' => $attempt,
      'attemptsTotal' => $attempts,
    ];
    $shouldRetry = ($http >= 500 || $http === 429 || $http === 408);
    if ($shouldRetry && $attempt < $attempts) {
      $delayMs = max(0, $retryBaseMs) * (int)pow(2, $attempt - 1);
      if ($delayMs > 0) usleep($delayMs * 1000);
      continue;
    }
    return $last;
  }

  return $last;
}

function is_zip_mime(string $mime, string $ct): bool {
  $mime = strtolower($mime);
  $ct   = strtolower($ct);
  if (str_contains($mime, 'zip')) return true;
  if (str_contains($ct, 'zip')) return true;
  return false;
}

function looks_like_zip(string $bytes): bool {
  $p = substr($bytes, 0, 4);
  return $p === "PK\x03\x04" || $p === "PK\x05\x06" || $p === "PK\x07\x08";
}

function looks_like_html(string $bytes): bool {
  $head = strtolower(substr(ltrim($bytes), 0, 64));
  return str_starts_with($head, '<!doctype html') || str_starts_with($head, '<html') || str_contains($head, '<head');
}

function is_yandex_public(string $url): bool {
  return (bool)preg_match('~https?://(disk\.yandex\.ru|disk\.360\.yandex\.ru|yadi\.sk)/~i', $url);
}

function is_melon_public(string $url): bool {
  return (bool)preg_match('~^https?://cloud\.melonfashion\.ru/s/[^/?#]+~i', trim($url));
}

/**
 * Преобразуем публичную ссылку Nextcloud/Owncloud в прямую загрузку.
 * Пример: https://cloud.melonfashion.ru/s/<token> -> .../s/<token>/download
 */
function normalize_melon_url(string $url): string {
  $url = trim($url);

  if (!preg_match('~^(https?://cloud\.melonfashion\.ru/s/[^/?#]+)(?:/download)?(?:[?#].*)?$~i', $url, $m)) {
    return $url;
  }

  return rtrim($m[1], '/') . '/download';
}

/**
 * ✅ Нормализуем yandex ссылки:
 * - disk.360 -> disk.yandex
 * - НЕ РЕЖЕМ /d/<key>/<filename> (это конкретный файл!)
 * - убираем query/fragment
 */
function normalize_yandex_url(string $url): string {
  $url = trim($url);

  // 360 -> обычный домен (Public API стабильнее)
  $url = preg_replace('~^https?://disk\.360\.yandex\.ru/~i', 'https://disk.yandex.ru/', $url);

  // ✅ 1) /d/<key>/<filename> — оставить как есть без query/fragment
  if (preg_match('~^(https?://disk\.yandex\.ru/d/[^/?#]+/[^?#]+)(?:[?#].*)?$~i', $url, $m)) {
    return $m[1];
  }

  // ✅ 2) /d/<key> — папка/публичная, оставить без query/fragment
  if (preg_match('~^(https?://disk\.yandex\.ru/d/[^/?#]+)(?:[?#].*)?$~i', $url, $m)) {
    return $m[1];
  }

  // ✅ 3) /i/<id>
  if (preg_match('~^(https?://disk\.yandex\.ru/i/[^/?#]+)(?:[?#].*)?$~i', $url, $m)) {
    return $m[1];
  }

  // ✅ 4) yadi.sk/d/<id>
  if (preg_match('~^(https?://yadi\.sk/d/[^/?#]+)(?:[?#].*)?$~i', $url, $m)) {
    return $m[1];
  }

  return $url;
}

/**
 * Раскрываем редирект (нужно в основном для yadi.sk)
 * ВАЖНО: используем обычный GET, т.к. Яндекс иногда иначе редиректит.
 */
function resolve_redirect_url(string $url, int $timeout, int $connectTimeout): string {
  $ch = curl_init($url);
  if (!$ch) return $url;

  curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_FOLLOWLOCATION => true,
    CURLOPT_MAXREDIRS      => 10,
    CURLOPT_TIMEOUT        => $timeout,
    CURLOPT_CONNECTTIMEOUT => $connectTimeout,
    CURLOPT_USERAGENT      => 'UploaderByURL/2.4 (+https://uploader.ooneclickk.ru)',
    CURLOPT_SSL_VERIFYPEER => true,
    CURLOPT_SSL_VERIFYHOST => 2,
  ]);

  curl_exec($ch);
  $final = curl_getinfo($ch, CURLINFO_EFFECTIVE_URL);
  curl_close($ch);

  if (!is_string($final) || $final === '') return $url;

  // защита: если редирект привёл на "главную" — игнорим
  $ok = (bool)preg_match('~https?://(disk\.yandex\.ru|disk\.360\.yandex\.ru|yadi\.sk)/(d|i)/~i', $final);
  return $ok ? $final : $url;
}

/**
 * Получить JSON по Yandex Disk Public API
 */
function yandex_api_get(string $apiUrl, int $timeout, int $connectTimeout): array {
  $r = curl_fetch($apiUrl, 'GET', null, $timeout, $connectTimeout, 0);
  if (!($r['ok'] ?? false)) return ['ok'=>false,'error'=>'yandex_api_curl','detail'=>$r];
  if (($r['http'] ?? 0) < 200 || ($r['http'] ?? 0) >= 300) {
    return ['ok'=>false,'error'=>'yandex_api_http','http'=>$r['http'] ?? 0,'body'=>substr((string)$r['bytes'],0,800)];
  }
  $j = json_decode((string)$r['bytes'], true);
  if (!is_array($j)) return ['ok'=>false,'error'=>'yandex_api_bad_json','body'=>substr((string)$r['bytes'],0,800)];
  return ['ok'=>true,'json'=>$j];
}

/**
 * Скачать href для файла
 * https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key=...(&path=...)
 */
function yandex_get_download_href_for_file(string $publicKeyUrl, ?string $path, int $timeout, int $connectTimeout): array {
  $api = 'https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key=' . rawurlencode($publicKeyUrl);
  if ($path !== null && $path !== '') {
    $api .= '&path=' . rawurlencode($path);
  }
  $res = yandex_api_get($api, $timeout, $connectTimeout);
  if (!($res['ok'] ?? false)) return $res;
  $j = $res['json'];
  if (empty($j['href'])) return ['ok'=>false,'error'=>'yandex_no_href','json'=>$j];
  return ['ok'=>true,'href'=>(string)$j['href']];
}

/**
 * Получить список файлов (для папки) или вернуть один элемент (для файла)
 */
function yandex_list_folder_files(string $publicKeyUrl, int $limit, int $timeout, int $connectTimeout): array {
  $api = 'https://cloud-api.yandex.net/v1/disk/public/resources?public_key=' . rawurlencode($publicKeyUrl)
       . '&limit=' . (int)$limit;

  $res = yandex_api_get($api, $timeout, $connectTimeout);
  if (!($res['ok'] ?? false)) return $res;

  $j = $res['json'];

  // если это файл (public_key может быть /i/ или прямой файл)
  if (($j['type'] ?? '') === 'file') {
    return ['ok'=>true,'type'=>'file','items'=>[ ['path'=>null,'name'=>$j['name'] ?? null] ]];
  }

  if (empty($j['_embedded']['items']) || !is_array($j['_embedded']['items'])) {
    return ['ok'=>false,'error'=>'yandex_no_items','json'=>$j];
  }

  $out = [];
  foreach ($j['_embedded']['items'] as $it) {
    if (!is_array($it)) continue;
    if (($it['type'] ?? '') !== 'file') continue;

    // фильтруем картинки по media_type если есть
    $media = (string)($it['media_type'] ?? '');
    if ($media !== '' && !str_starts_with($media, 'image')) {
      continue;
    }

    $out[] = [
      'path' => (string)($it['path'] ?? ''),
      'name' => (string)($it['name'] ?? ''),
    ];
  }

  if (count($out) === 0) return ['ok'=>false,'error'=>'yandex_folder_no_images'];
  return ['ok'=>true,'type'=>'dir','items'=>$out];
}

/**
 * Определяет "корень" или "подпапка" по path
 */
function yandex_is_root_level(?string $path): bool {
  if ($path === null || $path === '') return true;
  $p = $path;
  if (str_starts_with($p, 'disk:/')) $p = substr($p, 6);
  $p = ltrim($p, '/');
  return (strpos($p, '/') === false);
}

function extract_images_from_zip(string $zipBytes, string $filesDir, string $baseUrl, int $maxImages, int $maxEntryBytes): array {
  $tmp = tempnam(sys_get_temp_dir(), 'upzip_');
  if ($tmp === false) return ['ok' => false, 'error' => 'tempfile_failed'];

  file_put_contents($tmp, $zipBytes);

  $za = new ZipArchive();
  $res = $za->open($tmp);
  if ($res !== true) {
    @unlink($tmp);
    return ['ok' => false, 'error' => 'zip_open_failed', 'code' => $res];
  }

  $items = [];
  $count = 0;

  for ($i = 0; $i < $za->numFiles; $i++) {
    $stat = $za->statIndex($i);
    if (!$stat || empty($stat['name'])) continue;

    $name = $stat['name'];

    if (str_ends_with($name, '/')) continue;
    if (str_starts_with($name, '__MACOSX/')) continue;

    if (isset($stat['size']) && (int)$stat['size'] > $maxEntryBytes) continue;

    $entryBytes = $za->getFromIndex($i);
    if ($entryBytes === false) continue;
    if (strlen($entryBytes) > $maxEntryBytes) continue;

    $mime = detect_mime($entryBytes);
    if (!str_starts_with($mime, 'image/')) continue;

    $saved = save_image_bytes($entryBytes, $mime, $filesDir, $baseUrl);
    if (!($saved['ok'] ?? false)) continue;

    $items[] = [
      'url'  => $saved['url'],
      'mime' => $saved['mime'],
      'size' => $saved['size'],
      'name' => basename($name),
      'path' => $name,
      'root' => (strpos($name, '/') === false),
    ];

    $count++;
    if ($count >= $maxImages) break;
  }

  $za->close();
  @unlink($tmp);

  if (count($items) === 0) return ['ok' => false, 'error' => 'no_images_in_zip'];
  return ['ok' => true, 'items' => $items];
}

// === main ===
ensure_dir($FILES_DIR);

$token = $_POST['token'] ?? '';
$src   = $_POST['src'] ?? '';

if ($token === '' || !hash_equals($UPLOAD_TOKEN, (string)$token)) {
  jexit(['error' => 'bad_token'], 403);
}
if ($src === '') jexit(['error' => 'no_src'], 400);
if (!preg_match('~^https?://~i', $src)) jexit(['error' => 'bad_src'], 400);

// =====================
// 1) Яндекс: получаем прямой href через Public API
// =====================
if (is_yandex_public($src)) {

  // нормализуем (disk.360 -> disk.yandex, НЕ режем filename)
  $yurl = normalize_yandex_url($src);

  // редиректы делаем ТОЛЬКО для yadi.sk
  if (stripos($yurl, 'yadi.sk/') !== false) {
    $resolved = resolve_redirect_url($yurl, $CURL_TIMEOUT, $CURL_CONNECT_TO);
    $yurl = normalize_yandex_url($resolved);
  }

  // ✅ КЕЙС: пришёл КОНКРЕТНЫЙ ФАЙЛ вида /d/<key>/<filename>
  if (preg_match('~^https?://disk\.yandex\.ru/d/([^/]+)/([^/?#]+)$~i', $yurl, $m)) {
    $key  = $m[1];
    $file = $m[2];

    $publicKey = 'https://disk.yandex.ru/d/' . $key;
    $path = '/' . $file;

    $hrefRes = yandex_get_download_href_for_file($publicKey, $path, $CURL_TIMEOUT, $CURL_CONNECT_TO);
    if (!($hrefRes['ok'] ?? false)) {
      jexit(['error'=>'yandex_file_href_failed','src'=>$src,'normalized'=>$yurl,'detail'=>$hrefRes], 400);
    }

    $dl = download_url(
      (string)$hrefRes['href'],
      $MAX_ENTRY_BYTES,
      $CURL_TIMEOUT,
      $CURL_CONNECT_TO,
      $DOWNLOAD_RETRIES,
      $RETRY_BASE_MS
    );
    if (!($dl['ok'] ?? false)) {
      jexit(['error'=>'yandex_file_download_failed','src'=>$src,'normalized'=>$yurl,'detail'=>$dl], 400);
    }

    $bytes = (string)$dl['bytes'];
    $mime  = detect_mime($bytes);
    if (!str_starts_with($mime, 'image/')) {
      jexit(['error'=>'not_image','mime'=>$mime,'src'=>$src,'normalized'=>$yurl], 400);
    }

    $saved = save_image_bytes($bytes, $mime, $FILES_DIR, $BASE_URL);
    if (!($saved['ok'] ?? false)) jexit($saved, 500);

    jexit([
      'from'   => 'yandex-file',
      'count'  => 1,
      'src'    => $src,
      'normalized' => $yurl,
      'url'    => $saved['url'],
      'main'   => $saved['url'],
      'extras' => [],
    ], 200);
  }

  // ВАЖНО: после нормализации должен быть /d/ или /i/
  if (!preg_match('~^https?://(disk\.yandex\.ru|yadi\.sk)/(d|i)/~i', $yurl)) {
    jexit([
      'error'      => 'yandex_bad_public_key',
      'src'        => $src,
      'normalized' => $yurl
    ], 400);
  }

  // Обычный кейс: папка или /i/ ресурс
  $list = yandex_list_folder_files($yurl, 1000, $CURL_TIMEOUT, $CURL_CONNECT_TO);
  if (!($list['ok'] ?? false)) {
    jexit([
      'error'      => 'yandex_api_failed',
      'src'        => $src,
      'normalized' => $yurl,
      'detail'     => $list
    ], 400);
  }

  $itemsIn = $list['items'];

  $savedItems = [];
  $count = 0;

  foreach ($itemsIn as $it) {
    $path = $it['path'] ?? null;

    $hrefRes = yandex_get_download_href_for_file($yurl, $path, $CURL_TIMEOUT, $CURL_CONNECT_TO);
    if (!($hrefRes['ok'] ?? false)) continue;

    $href = (string)$hrefRes['href'];

    $dl = download_url(
      $href,
      $MAX_ENTRY_BYTES,
      $CURL_TIMEOUT,
      $CURL_CONNECT_TO,
      $DOWNLOAD_RETRIES,
      $RETRY_BASE_MS
    );
    if (!($dl['ok'] ?? false)) continue;

    $bytes = (string)$dl['bytes'];
    $mime  = detect_mime($bytes);
    if (!str_starts_with($mime, 'image/')) continue;

    $saved = save_image_bytes($bytes, $mime, $FILES_DIR, $BASE_URL);
    if (!($saved['ok'] ?? false)) continue;

    $savedItems[] = [
      'url'  => $saved['url'],
      'mime' => $saved['mime'],
      'size' => $saved['size'],
      'name' => $it['name'] ?? null,
      'path' => $path,
      'root' => yandex_is_root_level($path),
    ];

    $count++;
    if ($count >= $MAX_IMAGES_TOTAL) break;
  }

  if (count($savedItems) === 0) {
    jexit([
      'error'      => 'yandex_no_images_downloaded',
      'src'        => $src,
      'normalized' => $yurl
    ], 400);
  }

  usort($savedItems, function($a, $b) {
    $ar = !empty($a['root']) ? 0 : 1;
    $br = !empty($b['root']) ? 0 : 1;
    if ($ar !== $br) return $ar <=> $br;
    return strcmp((string)($a['name'] ?? ''), (string)($b['name'] ?? ''));
  });

  $main = null;
  foreach ($savedItems as $it) {
    if (!empty($it['root'])) { $main = $it; break; }
  }
  if ($main === null) $main = $savedItems[0];

  $extras = [];
  foreach ($savedItems as $it) {
    if ($it['url'] === $main['url']) continue;
    $extras[] = $it['url'];
  }

  jexit([
    'from'       => 'yandex',
    'count'      => count($savedItems),
    'src'        => $src,
    'normalized' => $yurl,
    'url'        => $main['url'],
    'main'       => $main['url'],
    'extras'     => $extras,
    'items'      => $savedItems,
  ], 200);
}

// =====================
// 2) Не Яндекс: скачиваем как раньше
// =====================
$downloadSrc = $src;
$isMelon = false;
if (is_melon_public($src)) {
  $isMelon = true;
  $downloadSrc = normalize_melon_url($src);
}

$dl = download_url(
  $downloadSrc,
  $MAX_DOWNLOAD_BYTES,
  $CURL_TIMEOUT,
  $CURL_CONNECT_TO,
  $DOWNLOAD_RETRIES,
  $RETRY_BASE_MS
);
if (!($dl['ok'] ?? false)) jexit($dl, 400);

$bytes = (string)$dl['bytes'];
$ct    = (string)$dl['ct'];
$mime  = detect_mime($bytes);

// ZIP кейс
if (is_zip_mime($mime, $ct) || looks_like_zip($bytes)) {
  $unz = extract_images_from_zip($bytes, $FILES_DIR, $BASE_URL, $MAX_IMAGES_TOTAL, $MAX_ENTRY_BYTES);
  if (!($unz['ok'] ?? false)) {
    jexit(['error'=>$unz['error'] ?? 'zip_failed','mime'=>$mime,'ct'=>$ct], 400);
  }

  $items = $unz['items'];

  // main = первая из root если есть
  $main = null;
  foreach ($items as $it) { if (!empty($it['root'])) { $main = $it; break; } }
  if ($main === null) $main = $items[0];

  $extras = [];
  foreach ($items as $it) {
    if ($it['url'] === $main['url']) continue;
    $extras[] = $it['url'];
  }

  jexit([
    'from'   => 'zip',
    'count'  => count($items),
    'url'    => $main['url'],
    'main'   => $main['url'],
    'extras' => $extras,
    'items'  => $items,
  ], 200);
}

// обычная картинка
if (!str_starts_with($mime, 'image/')) {
  if (looks_like_html($bytes)) {
    jexit([
      'error' => 'not_direct_file',
      'mime' => $mime,
      'ct' => $ct,
      'src' => $src,
      'normalized' => $downloadSrc,
    ], 400);
  }
  jexit([
    'error' => 'not_image',
    'mime' => $mime,
    'ct' => $ct,
    'src' => $src,
    'normalized' => $downloadSrc,
  ], 400);
}

$saved = save_image_bytes($bytes, $mime, $FILES_DIR, $BASE_URL);
if (!($saved['ok'] ?? false)) jexit($saved, 500);

jexit([
  'from'   => $isMelon ? 'melon-direct' : 'direct',
  'src'    => $src,
  'normalized' => $downloadSrc,
  'url'    => $saved['url'],
  'main'   => $saved['url'],
  'extras' => [],
  'mime'   => $saved['mime'],
  'size'   => $saved['size'],
], 200);
