<?php
declare(strict_types=1);

/**
 * Shared uploader settings. Override via env on the VPS if needed:
 *   UPLOADER_API_TOKEN, UPLOADER_PUBLIC_BASE
 */
$UPLOADER_PUBLIC_BASE = rtrim(
    getenv('UPLOADER_PUBLIC_BASE') ?: 'https://uploader.ooneclickk.ru',
    '/'
);

// Same token as Beget backup so existing Script property UPLOAD_TOKEN keeps working.
$UPLOADER_API_TOKEN = getenv('UPLOADER_API_TOKEN') ?: 'c906293434a6af27faa8dd31b68555c01e8148cffbbe100b';

return [
    'api_token' => $UPLOADER_API_TOKEN,
    'public_base' => $UPLOADER_PUBLIC_BASE,
    'files_url' => $UPLOADER_PUBLIC_BASE . '/files',
    'upload_by_url' => $UPLOADER_PUBLIC_BASE . '/upload_by_url.php',
];
