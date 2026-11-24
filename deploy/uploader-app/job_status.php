<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');

$__cfg = require __DIR__ . '/config.php';
$API_TOKEN = (string)$__cfg['api_token'];


const JOB_DIR = __DIR__ . '/jobs';
$UPLOAD_BY_URL = (string)$__cfg['upload_by_url'];
const CHUNK_PER_POLL = 40;
const MAX_RETRY_PER_URL = 4;

function out(array $data, int $code = 200): void {
    http_response_code($code);
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function read_json_body(): array {
    $raw = file_get_contents('php://input') ?: '';
    $data = json_decode($raw, true);
    return is_array($data) ? $data : [];
}

function parse_json(string $s): ?array {
    $j = json_decode($s, true);
    return is_array($j) ? $j : null;
}

function load_job(string $jobId): array {
    $path = JOB_DIR . '/' . $jobId . '.json';
    if (!is_file($path)) out(['ok' => false, 'error' => 'job_not_found'], 404);
    $data = parse_json((string)file_get_contents($path));
    if (!$data) out(['ok' => false, 'error' => 'job_corrupted'], 500);
    return [$path, $data];
}

function save_job(string $path, array $job): void {
    $job['updatedAt'] = time();
    file_put_contents($path, json_encode($job, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
}

function normalize_cloud_url(string $url): string {
    $u = trim($url);
    $u = preg_replace('~^["\'\s]+|["\'\s]+$~u', '', $u) ?? $u;
    $patterns = [
        '~^(https?://disk\.(?:360\.)?yandex\.ru/d/[^/?#]+/[^?#]+)(?:[?#].*)?$~i',
        '~^(https?://disk\.(?:360\.)?yandex\.ru/d/[^/?#]+)(?:[?#].*)?$~i',
        '~^(https?://disk\.(?:360\.)?yandex\.ru/i/[^/?#]+)(?:[?#].*)?$~i',
        '~^(https?://yadi\.sk/d/[^/?#]+)(?:[?#].*)?$~i',
        '~^(https?://cloud\.melonfashion\.ru/s/[^/?#]+)(?:/download)?(?:[?#].*)?$~i',
        '~^(https?://[^\s?#]+\.(?:jpe?g|png|webp|gif|bmp|tiff|avif))(?:[?#].*)?$~i',
    ];
    foreach ($patterns as $p) {
        if (preg_match($p, $u, $m)) return $m[1];
    }
    return $u;
}

function is_yandex(string $u): bool {
    return (bool)preg_match('~(disk\.yandex\.ru|disk\.360\.yandex\.ru|yadi\.sk)~i', $u);
}
function is_melon(string $u): bool {
    return (bool)preg_match('~^https?://cloud\.melonfashion\.ru/s/[^/?#]+~i', trim($u));
}
function is_direct_image(string $u): bool {
    return (bool)preg_match('~^https?://[^\s?#]+\.(jpe?g|png|webp|gif|bmp|tiff|avif)(?:[?#].*)?$~i', trim($u));
}
function should_upload_url(string $u, bool $forceDirect): bool {
    return is_yandex($u) || is_melon($u) || ($forceDirect && is_direct_image($u));
}

function upload_one_request_(string $endpoint, string $hostHeader, string $srcUrl, string $apiToken, bool $insecureTls = false): array {
    $ch = curl_init($endpoint);
    $post = http_build_query([
        'token' => $apiToken,
        'src' => $srcUrl,
    ]);
    $headers = ['Content-Type: application/x-www-form-urlencoded'];
    if ($hostHeader !== '') {
        $headers[] = 'Host: ' . $hostHeader;
    }
    $opts = [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $post,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 10,
        CURLOPT_TIMEOUT => 120,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_FOLLOWLOCATION => true,
    ];
    if ($insecureTls) {
        $opts[CURLOPT_SSL_VERIFYPEER] = false;
        $opts[CURLOPT_SSL_VERIFYHOST] = 0;
    }
    curl_setopt_array($ch, $opts);
    $body = curl_exec($ch);
    $errno = curl_errno($ch);
    $err = curl_error($ch);
    $http = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    return [
        'body' => (string)$body,
        'errno' => $errno,
        'err' => $err,
        'http' => $http,
    ];
}

function upload_one(string $srcUrl, string $uploadByUrl, string $apiToken): array {
    if ($uploadByUrl === '' || !preg_match('~^https?://~i', $uploadByUrl)) {
        return ['ok' => false, 'error' => 'upload_by_url_not_configured'];
    }

    // Public HTTPS first; if VPS cannot hairpin to itself, fall back to loopback + Host.
    $attempts = [[$uploadByUrl, '', false]];
    $host = parse_url($uploadByUrl, PHP_URL_HOST);
    if (is_string($host) && $host !== '') {
        $attempts[] = ['https://127.0.0.1/upload_by_url.php', $host, true];
    }

    $last = ['errno' => 0, 'err' => '', 'http' => 0, 'body' => ''];
    foreach ($attempts as [$endpoint, $hostHeader, $insecureTls]) {
        $last = upload_one_request_($endpoint, $hostHeader, $srcUrl, $apiToken, $insecureTls);
        if ($last['errno'] === 0 && $last['http'] === 200) {
            break;
        }
        // Only fall back on transport / empty-url style failures.
        if ($last['errno'] === 0 && $last['http'] > 0 && $last['http'] !== 200) {
            break;
        }
    }

    if ($last['errno'] !== 0) {
        return ['ok' => false, 'error' => 'curl_' . $last['errno'] . ':' . $last['err']];
    }
    if ($last['http'] !== 200) {
        return ['ok' => false, 'error' => 'http_' . $last['http'], 'body' => $last['body']];
    }
    $body = $last['body'];

    $j = parse_json((string)$body);
    if (!$j) return ['ok' => false, 'error' => 'bad_json', 'body' => (string)$body];

    $main = trim((string)($j['main'] ?? $j['url'] ?? ''));
    $extra = '';
    if (isset($j['extras']) && is_array($j['extras']) && count($j['extras']) > 0) {
        $extra = implode(',', $j['extras']);
    } else {
        $extra = trim((string)($j['extra'] ?? ''));
    }
    if ($main === '' && $extra === '') {
        return ['ok' => false, 'error' => 'empty_response', 'body' => (string)$body];
    }
    return ['ok' => true, 'data' => ['main' => $main, 'extra' => $extra]];
}

function is_missing_source_error(array $up): bool {
    $err = mb_strtolower((string)($up['error'] ?? ''), 'UTF-8');
    $body = mb_strtolower((string)($up['body'] ?? ''), 'UTF-8');
    $text = $err . ' ' . $body;
    if (strpos($err, 'http_404') !== false) return true;
    if (strpos($text, ' 404') !== false) return true;
    if (strpos($text, 'not found') !== false) return true;
    if (strpos($text, 'не найден') !== false) return true;
    return false;
}

function replace_urls_by_map(string $text, array $map, string $take, bool $forceDirect): string {
    return preg_replace_callback('~https?://[^\s;,"\'()<>]+~iu', function ($m) use ($map, $take, $forceDirect) {
        $raw = trim((string)$m[0], "\"' \t\r\n");
        if (!should_upload_url($raw, $forceDirect)) return $m[0];
        $key = normalize_cloud_url($raw);
        $rec = $map[$key] ?? ($map[$raw] ?? null);
        if (!$rec) return $m[0];
        if (is_string($rec)) return $rec;
        $main = trim((string)($rec['main'] ?? $rec['url'] ?? ''));
        $extra = '';
        if (isset($rec['extras']) && is_array($rec['extras']) && count($rec['extras']) > 0) {
            $extra = implode(',', $rec['extras']);
        } else {
            $extra = trim((string)($rec['extra'] ?? ''));
        }
        if ($take === 'extra') return $extra !== '' ? $extra : ($main !== '' ? $main : $m[0]);
        return $main !== '' ? $main : $m[0];
    }, $text) ?? $text;
}

function build_result_rows(array $headers, array $rows, array $map, array $columns, bool $forceDirect): array {
    $genderCol = array_key_exists('gender', $columns) && $columns['gender'] !== null ? (int)$columns['gender'] : -1;
    $photoMain = isset($columns['photoMain']) ? (int)$columns['photoMain'] : -1;
    $photoExtras = isset($columns['photoExtras']) && is_array($columns['photoExtras']) ? $columns['photoExtras'] : [];
    $extraSet = [];
    foreach ($photoExtras as $x) $extraSet[(int)$x] = true;

    $out = [];
    foreach ($rows as $row) {
        $line = [];
        $rowArr = is_array($row) ? $row : [];
        for ($i = 0; $i < count($headers); $i++) {
            $cell = (string)($rowArr[$i] ?? '');
            if ($i === $genderCol) {
                $line[] = normalize_gender($cell);
                continue;
            }
            if (!preg_match('~https?://~i', $cell)) {
                $line[] = $cell;
                continue;
            }
            if ($i === $photoMain) {
                $line[] = replace_urls_by_map($cell, $map, 'main', $forceDirect);
            } elseif (isset($extraSet[$i])) {
                $line[] = replace_urls_by_map($cell, $map, 'extra', $forceDirect);
            } else {
                $line[] = replace_urls_by_map($cell, $map, 'main', $forceDirect);
            }
        }
        $out[] = $line;
    }
    return $out;
}

function trim_trailing_empty_columns(array $headers, array $rows): array {
    $width = count($headers);
    while ($width > 0) {
        $headerVal = trim((string)($headers[$width - 1] ?? ''));
        if ($headerVal !== '') break;

        $hasData = false;
        foreach ($rows as $r) {
            $cell = is_array($r) ? ($r[$width - 1] ?? '') : '';
            if (trim((string)$cell) !== '') {
                $hasData = true;
                break;
            }
        }
        if ($hasData) break;
        $width--;
    }

    $headersOut = array_slice($headers, 0, $width);
    $rowsOut = [];
    foreach ($rows as $r) {
        $row = is_array($r) ? array_slice($r, 0, $width) : [];
        while (count($row) < $width) $row[] = '';
        $rowsOut[] = $row;
    }
    return [$headersOut, $rowsOut];
}

function normalize_gender(string $gender): string {
    $g = mb_strtolower(trim($gender), 'UTF-8');
    $g = preg_replace('~[.,;:!?]+$~u', '', $g) ?? $g;
    if ($g === '') return $gender;

    $female = ['женское','женский','женская','жен','female','woman','women','w','wom','f','ж','женско'];
    foreach ($female as $v) {
        if ($g === $v) return 'female';
    }

    $male = ['мужское','мужской','мужская','муж','male','man','men','m','мужск','м'];
    foreach ($male as $v) {
        if ($g === $v) return 'male';
    }

    return $gender;
}

function write_csv_file(string $jobId, array $headers, array $rows): string {
    $path = JOB_DIR . '/' . $jobId . '.csv';
    $f = fopen($path, 'wb');
    if (!$f) return '';
    fwrite($f, csv_line($headers) . "\n");
    foreach ($rows as $r) {
        fwrite($f, csv_line(is_array($r) ? $r : []) . "\n");
    }
    fclose($f);
    return $path;
}

function csv_line(array $row): string {
    $out = [];
    foreach ($row as $v) {
        $s = clean_cell((string)($v ?? ''));
        // Историческое поведение: максимально "плоский" CSV без лишних кавычек.
        // Чтобы не ломать разделитель ';', заменяем его запятой внутри значения.
        if (strpos($s, ';') !== false) {
            $s = str_replace(';', ',', $s);
        }
        $out[] = $s;
    }
    // Оставляем закрывающий разделитель в конце строки (исторический формат).
    return implode(';', $out) . ';';
}

function clean_cell(string $s): string {
    $s = str_replace('""', '', $s);
    $s = preg_replace('~^"|"$~u', '', $s) ?? $s;
    $s = preg_replace('~\R+~u', ' ', $s) ?? $s;
    $s = str_replace("\0", '', $s);
    return trim($s);
}

function absolute_csv_url(string $jobId): string {
    $scheme = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
    $host = $_SERVER['HTTP_HOST'] ?? 'localhost';
    $base = rtrim(dirname($_SERVER['SCRIPT_NAME'] ?? ''), '/\\');
    return $scheme . '://' . $host . $base . '/jobs/' . rawurlencode($jobId) . '.csv';
}

$input = read_json_body();
$token = (string)($input['token'] ?? '');
$jobId = (string)($input['jobId'] ?? '');
if ($token !== $API_TOKEN) out(['ok' => false, 'error' => 'bad_token'], 401);
if ($jobId === '') out(['ok' => false, 'error' => 'empty_job_id'], 400);

[$path, $job] = load_job($jobId);

$status = (string)($job['status'] ?? 'queued');
if ($status !== 'done' && $status !== 'failed') {
    $job['status'] = 'running';
    $queue = isset($job['queue']) && is_array($job['queue']) ? $job['queue'] : [];
    $cursor = (int)($job['cursor'] ?? 0);
    $retries = isset($job['retries']) && is_array($job['retries']) ? $job['retries'] : [];
    $mapping = isset($job['mapping']) && is_array($job['mapping']) ? $job['mapping'] : [];
    $errors = isset($job['errors']) && is_array($job['errors']) ? $job['errors'] : [];

    $end = min(count($queue), $cursor + CHUNK_PER_POLL);
    for ($i = $cursor; $i < $end; $i++) {
        $src = (string)$queue[$i];
        $up = upload_one($src, $UPLOAD_BY_URL, $API_TOKEN);
        if ($up['ok'] ?? false) {
            $mapping[$src] = $up['data'];
            $cursor = $i + 1;
            continue;
        }

        // Источник недоступен (404/Not Found): не валим джобу, оставляем исходный URL.
        if (is_missing_source_error($up)) {
            $errors[] = [
                'url' => $src,
                'try' => (int)($retries[$src] ?? 0) + 1,
                'error' => (string)($up['error'] ?? 'source_not_found'),
                'detail' => isset($up['body']) ? mb_substr((string)$up['body'], 0, 400) : null,
                'skipped' => true,
                'at' => time(),
            ];
            $cursor = $i + 1;
            continue;
        }

        $retries[$src] = (int)($retries[$src] ?? 0) + 1;
        $errors[] = [
            'url' => $src,
            'try' => $retries[$src],
            'error' => (string)($up['error'] ?? 'upload_failed'),
            'detail' => isset($up['body']) ? mb_substr((string)$up['body'], 0, 400) : null,
            'at' => time(),
        ];

        if ($retries[$src] >= MAX_RETRY_PER_URL) {
            $job['status'] = 'failed';
            $job['error'] = 'url_failed_after_retries';
            $job['failedUrl'] = $src;
            $job['cursor'] = $i;
            $job['retries'] = $retries;
            $job['mapping'] = $mapping;
            $job['errors'] = $errors;
            $job['progress'] = [
                'done' => $i,
                'total' => count($queue),
                'message' => 'failed at url',
            ];
            save_job($path, $job);
            out([
                'ok' => true,
                'status' => 'failed',
                'error' => $job['error'],
                'failedUrl' => $src,
                'lastDetail' => isset($up['body']) ? mb_substr((string)$up['body'], 0, 400) : null,
                'progress' => $job['progress'],
            ]);
        }

        // Не двигаем cursor: на следующем poll повторим URL.
        break;
    }

    $job['cursor'] = $cursor;
    $job['retries'] = $retries;
    $job['mapping'] = $mapping;
    $job['errors'] = $errors;
    $job['progress'] = [
        'done' => $cursor,
        'total' => count($queue),
        'message' => $cursor >= count($queue) ? 'building_result' : 'uploading',
    ];

    if ($cursor >= count($queue)) {
        $headers = $job['sheet']['headers'] ?? [];
        $rows = $job['sheet']['rows'] ?? [];
        $columns = $job['config']['columns'] ?? [];
        $forceDirect = (bool)($job['config']['forceConvertDirectImages'] ?? false);
        $rowsDone = build_result_rows($headers, $rows, $mapping, $columns, $forceDirect);
        [$headersTrimmed, $rowsTrimmed] = trim_trailing_empty_columns($headers, $rowsDone);
        write_csv_file($jobId, $headersTrimmed, $rowsTrimmed);

        $job['result'] = [
            'downloadUrl' => absolute_csv_url($jobId),
            'downloadFilename' => 'export.csv',
            'mapping' => $mapping,
            'rows' => $rowsTrimmed,
        ];
        $job['status'] = 'done';
        $job['progress']['message'] = 'done';
    }

    save_job($path, $job);
}

$result = $job['result'] ?? null;
out([
    'ok' => true,
    'status' => $job['status'],
    'progress' => $job['progress'] ?? ['done' => 0, 'total' => 0, 'message' => 'unknown'],
    'error' => $job['error'] ?? null,
    'failedUrl' => $job['failedUrl'] ?? null,
    'result' => $job['status'] === 'done' ? $result : null,
]);
