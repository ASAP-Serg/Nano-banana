<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');

$__cfg = require __DIR__ . '/config.php';
$API_TOKEN = (string)$__cfg['api_token'];


const JOB_DIR = __DIR__ . '/jobs';

function out(array $data, int $code = 200): void {
    http_response_code($code);
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function read_json_body(): array {
    $raw = file_get_contents('php://input') ?: '';
    $j = json_decode($raw, true);
    return is_array($j) ? $j : [];
}

$input = read_json_body();
$token = (string)($input['token'] ?? '');
$jobId = (string)($input['jobId'] ?? '');

if ($token !== $API_TOKEN) out(['ok' => false, 'error' => 'bad_token'], 401);
if ($jobId === '') out(['ok' => false, 'error' => 'empty_job_id'], 400);

$path = JOB_DIR . '/' . $jobId . '.json';
if (!is_file($path)) out(['ok' => false, 'error' => 'job_not_found'], 404);

$job = json_decode((string)file_get_contents($path), true);
if (!is_array($job)) out(['ok' => false, 'error' => 'job_corrupted'], 500);

$status = (string)($job['status'] ?? '');
if ($status !== 'done') {
    out([
        'ok' => true,
        'status' => $status ?: 'unknown',
        'progress' => $job['progress'] ?? null,
        'error' => $job['error'] ?? null,
        'result' => null,
    ]);
}

out([
    'ok' => true,
    'status' => 'done',
    'result' => $job['result'] ?? null,
]);
