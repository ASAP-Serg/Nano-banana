<?php
declare(strict_types=1);

/**
 * Shared uploader settings.
 * Prefer env UPLOADER_API_TOKEN / UPLOADER_PUBLIC_BASE, else config.local.php (not in git).
 */
$UPLOADER_PUBLIC_BASE = rtrim(
    getenv('UPLOADER_PUBLIC_BASE') ?: 'https://uploader.ooneclickk.ru',
    '/'
);

$UPLOADER_API_TOKEN = trim((string)(getenv('UPLOADER_API_TOKEN') ?: ''));
$localPath = __DIR__ . '/config.local.php';
if ($UPLOADER_API_TOKEN === '' && is_readable($localPath)) {
    $local = require $localPath;
    if (is_array($local)) {
        $UPLOADER_API_TOKEN = trim((string)($local['api_token'] ?? ''));
        if (!empty($local['public_base'])) {
            $UPLOADER_PUBLIC_BASE = rtrim((string)$local['public_base'], '/');
        }
    }
}

if ($UPLOADER_API_TOKEN === '' || strlen($UPLOADER_API_TOKEN) < 32) {
    error_log('[uploader] UPLOADER_API_TOKEN missing — set env or config.local.php');
    $UPLOADER_API_TOKEN = '';
}

return [
    'api_token' => $UPLOADER_API_TOKEN,
    'public_base' => $UPLOADER_PUBLIC_BASE,
    'files_url' => $UPLOADER_PUBLIC_BASE . '/files',
    'upload_by_url' => $UPLOADER_PUBLIC_BASE . '/upload_by_url.php',
];
