<?php
declare(strict_types=1);

/**
 * Оптимизирует картинку: переводит в WEBP и подбирает размер/качество под целевой вес.
 *
 * Возвращает:
 * - ok=true, bytes, mime=image/webp, ext=webp, size, quality, width, height, resized
 * - ok=false, error=...
 */
function optimize_image_to_webp(
  string $sourceBytes,
  string $sourceMime,
  int $targetMinBytes = 500 * 1024,
  int $targetMaxBytes = 600 * 1024
): array {
  $mime = strtolower(trim($sourceMime));

  // SVG/AVIF и прочие форматы через GD обычно не декодируются.
  $supportedRaster = [
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/gif',
    'image/webp',
    'image/bmp',
  ];
  if (!in_array($mime, $supportedRaster, true)) {
    return ['ok' => false, 'error' => 'optimizer_unsupported_mime', 'mime' => $sourceMime];
  }

  if (!function_exists('imagecreatefromstring')) {
    return ['ok' => false, 'error' => 'gd_missing'];
  }
  if (!function_exists('imagewebp')) {
    return ['ok' => false, 'error' => 'webp_not_supported_by_gd'];
  }

  $src = @imagecreatefromstring($sourceBytes);
  if (!$src) {
    return ['ok' => false, 'error' => 'image_decode_failed'];
  }

  $origW = imagesx($src);
  $origH = imagesy($src);
  if ($origW <= 0 || $origH <= 0) {
    imagedestroy($src);
    return ['ok' => false, 'error' => 'invalid_image_dimensions'];
  }

  $scale = 1.0;
  $quality = 86;
  $lastGood = null;

  // Мягкий шаг деградации: сначала качество, потом размер.
  for ($attempt = 0; $attempt < 14; $attempt++) {
    $w = max(1, (int)floor($origW * $scale));
    $h = max(1, (int)floor($origH * $scale));

    if ($w === $origW && $h === $origH) {
      $canvas = imagecreatetruecolor($w, $h);
      imagealphablending($canvas, false);
      imagesavealpha($canvas, true);
      $transparent = imagecolorallocatealpha($canvas, 0, 0, 0, 127);
      imagefilledrectangle($canvas, 0, 0, $w, $h, $transparent);
      imagecopy($canvas, $src, 0, 0, 0, 0, $w, $h);
    } else {
      $canvas = imagecreatetruecolor($w, $h);
      imagealphablending($canvas, false);
      imagesavealpha($canvas, true);
      $transparent = imagecolorallocatealpha($canvas, 0, 0, 0, 127);
      imagefilledrectangle($canvas, 0, 0, $w, $h, $transparent);
      imagecopyresampled($canvas, $src, 0, 0, 0, 0, $w, $h, $origW, $origH);
    }

    ob_start();
    $ok = imagewebp($canvas, null, $quality);
    $webpBytes = (string)ob_get_clean();
    imagedestroy($canvas);

    if (!$ok || $webpBytes === '') {
      imagedestroy($src);
      return ['ok' => false, 'error' => 'webp_encode_failed'];
    }

    $size = strlen($webpBytes);

    if ($size >= $targetMinBytes && $size <= $targetMaxBytes) {
      $lastGood = [
        'bytes' => $webpBytes,
        'size' => $size,
        'quality' => $quality,
        'width' => $w,
        'height' => $h,
        'resized' => ($w !== $origW || $h !== $origH),
      ];
      break;
    }

    // Если файл уже меньше минимума, лучше не портить качество дальше.
    if ($size < $targetMinBytes) {
      $lastGood = [
        'bytes' => $webpBytes,
        'size' => $size,
        'quality' => $quality,
        'width' => $w,
        'height' => $h,
        'resized' => ($w !== $origW || $h !== $origH),
      ];
      break;
    }

    // Пока размер больше лимита — шаг вниз по качеству, затем по масштабу.
    if ($quality > 58) {
      $quality -= 6;
      continue;
    }

    if ($scale > 0.55) {
      $scale *= 0.90;
      $quality = min($quality + 4, 82);
      continue;
    }

    // Минимально приемлемая граница достигнута — возвращаем лучший найденный.
    $lastGood = [
      'bytes' => $webpBytes,
      'size' => $size,
      'quality' => $quality,
      'width' => $w,
      'height' => $h,
      'resized' => ($w !== $origW || $h !== $origH),
    ];
    break;
  }

  imagedestroy($src);

  if ($lastGood === null) {
    return ['ok' => false, 'error' => 'optimizer_no_result'];
  }

  return [
    'ok' => true,
    'bytes' => $lastGood['bytes'],
    'mime' => 'image/webp',
    'ext' => 'webp',
    'size' => $lastGood['size'],
    'quality' => $lastGood['quality'],
    'width' => $lastGood['width'],
    'height' => $lastGood['height'],
    'resized' => $lastGood['resized'],
  ];
}
