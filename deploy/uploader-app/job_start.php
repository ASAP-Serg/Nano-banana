<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');

$__cfg = require __DIR__ . '/config.php';
$API_TOKEN = (string)$__cfg['api_token'];


const JOB_DIR = __DIR__ . '/jobs';
const MAX_DONE_JOB_FILES_TO_KEEP = 50;

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

function ensure_job_dir(): void {
    if (!is_dir(JOB_DIR)) {
        @mkdir(JOB_DIR, 0775, true);
    }
    if (!is_dir(JOB_DIR) || !is_writable(JOB_DIR)) {
        out(['ok' => false, 'error' => 'jobs_dir_not_writable'], 500);
    }
}

function cleanup_old_jobs(int $keep = MAX_DONE_JOB_FILES_TO_KEEP): void {
    $keep = max(1, $keep);
    $jsonFiles = glob(JOB_DIR . '/job_*.json');
    if (!is_array($jsonFiles) || count($jsonFiles) === 0) return;

    $doneFiles = [];
    foreach ($jsonFiles as $jsonPath) {
        $raw = @file_get_contents($jsonPath);
        if ($raw === false || $raw === '') continue;
        $job = json_decode($raw, true);
        if (!is_array($job)) continue;
        if (($job['status'] ?? '') === 'done') {
            $doneFiles[] = $jsonPath;
        }
    }
    if (count($doneFiles) <= $keep) return;

    usort($doneFiles, static function (string $a, string $b): int {
        return (filemtime($b) ?: 0) <=> (filemtime($a) ?: 0);
    });

    $toDelete = array_slice($doneFiles, $keep);
    foreach ($toDelete as $jsonPath) {
        @unlink($jsonPath);
        $csvPath = substr($jsonPath, 0, -5) . '.csv';
        if (is_file($csvPath)) {
            @unlink($csvPath);
        }
    }
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
        if (preg_match($p, $u, $m)) {
            return $m[1];
        }
    }
    return $u;
}

function collect_unique_urls(array $headers, array $rows, array $columns, bool $forceDirect): array {
    $photoMain = isset($columns['photoMain']) ? (int)$columns['photoMain'] : -1;
    $photoExtras = isset($columns['photoExtras']) && is_array($columns['photoExtras']) ? $columns['photoExtras'] : [];
    $photoCols = [];
    if ($photoMain >= 0) $photoCols[] = $photoMain;
    foreach ($photoExtras as $x) {
        $ix = (int)$x;
        if ($ix >= 0) $photoCols[] = $ix;
    }
    $photoCols = array_values(array_unique($photoCols));

    $urlRe = '~https?://[^\s;,"\'()<>]+~iu';
    $set = [];

    foreach ($rows as $row) {
        if (!is_array($row)) continue;
        $cells = [];
        if (count($photoCols) > 0) {
            foreach ($photoCols as $ci) {
                $cells[] = (string)($row[$ci] ?? '');
            }
        } else {
            foreach ($row as $c) $cells[] = (string)$c;
        }

        foreach ($cells as $cell) {
            if (!preg_match_all($urlRe, $cell, $m)) continue;
            foreach ($m[0] as $u) {
                if (!should_upload_url($u, $forceDirect)) continue;
                $key = normalize_cloud_url($u);
                $set[$key] = true;
            }
        }
    }

    return array_keys($set);
}

$input = read_json_body();
$token = (string)($input['token'] ?? '');
if ($token !== $API_TOKEN) {
    out(['ok' => false, 'error' => 'bad_token'], 401);
}

$sheet = $input['sheet'] ?? [];
$headers = isset($sheet['headers']) && is_array($sheet['headers']) ? $sheet['headers'] : [];
$rows = isset($sheet['rows']) && is_array($sheet['rows']) ? $sheet['rows'] : [];
$config = isset($input['config']) && is_array($input['config']) ? $input['config'] : [];
$columns = isset($config['columns']) && is_array($config['columns']) ? $config['columns'] : [];
$forceDirect = (bool)($config['forceConvertDirectImages'] ?? false);

if (count($headers) === 0) {
    out(['ok' => false, 'error' => 'empty_headers'], 400);
}

ensure_job_dir();
cleanup_old_jobs();

$jobId = 'job_' . date('Ymd_His') . '_' . bin2hex(random_bytes(4));
$queue = collect_unique_urls($headers, $rows, $columns, $forceDirect);

$job = [
    'jobId' => $jobId,
    'status' => 'queued',
    'createdAt' => time(),
    'updatedAt' => time(),
    'sheet' => [
        'headers' => $headers,
        'rows' => $rows,
    ],
    'config' => [
        'forceConvertDirectImages' => $forceDirect,
        'columns' => $columns,
    ],
    'queue' => $queue,
    'progress' => [
        'done' => 0,
        'total' => count($queue),
        'message' => 'queued',
    ],
    'cursor' => 0,
    'mapping' => new stdClass(),
    'retries' => new stdClass(),
    'errors' => [],
    'result' => null,
];

$path = JOB_DIR . '/' . $jobId . '.json';
file_put_contents($path, json_encode($job, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));

out([
    'ok' => true,
    'jobId' => $jobId,
    'totalUrls' => count($queue),
]);
