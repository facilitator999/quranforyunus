<?php
/**
 * PHP built-in server router: adds HTTP Range (byte-serving) support for
 * static files so MP3 seeking works in browsers.
 */
$uri  = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
$file = __DIR__ . $uri;

// Let PHP handle .php files and directories normally
if (is_dir($file) || (is_file($file) && strtolower(pathinfo($file, PATHINFO_EXTENSION)) === 'php')) {
    return false;
}

// Serve static files with Range support
if (is_file($file)) {
    static $MIME = [
        'mp3'  => 'audio/mpeg',
        'ogg'  => 'audio/ogg',
        'wav'  => 'audio/wav',
        'json' => 'application/json',
        'js'   => 'application/javascript',
        'mjs'  => 'application/javascript',
        'css'  => 'text/css',
        'html' => 'text/html; charset=utf-8',
        'htm'  => 'text/html; charset=utf-8',
        'png'  => 'image/png',
        'jpg'  => 'image/jpeg',
        'jpeg' => 'image/jpeg',
        'gif'  => 'image/gif',
        'svg'  => 'image/svg+xml',
        'ico'  => 'image/x-icon',
        'woff' => 'font/woff',
        'woff2'=> 'font/woff2',
    ];

    $ext      = strtolower(pathinfo($file, PATHINFO_EXTENSION));
    $mime     = $MIME[$ext] ?? 'application/octet-stream';
    $fileSize = filesize($file);

    // No-cache for timestamp JSON
    if ($ext === 'json' && strpos($file, 'timestamps') !== false) {
        header('Cache-Control: no-store, no-cache, max-age=0, must-revalidate');
        header('Pragma: no-cache');
    }

    header('Accept-Ranges: bytes');

    $range = $_SERVER['HTTP_RANGE'] ?? null;
    if ($range && preg_match('/bytes=(\d+)-(\d*)/', $range, $m)) {
        $start = (int)$m[1];
        $end   = ($m[2] !== '') ? (int)$m[2] : $fileSize - 1;
        $end   = min($end, $fileSize - 1);

        if ($fileSize === 0 || $start > $end || $start >= $fileSize) {
            header('HTTP/1.1 416 Range Not Satisfiable');
            header("Content-Range: bytes */$fileSize");
            exit;
        }

        $length = $end - $start + 1;
        header('HTTP/1.1 206 Partial Content');
        header("Content-Type: $mime");
        header("Content-Range: bytes $start-$end/$fileSize");
        header("Content-Length: $length");

        $fp = fopen($file, 'rb');
        fseek($fp, $start);
        $remaining = $length;
        while ($remaining > 0 && !feof($fp)) {
            echo fread($fp, min(65536, $remaining));
            $remaining -= 65536;
        }
        fclose($fp);
        exit;
    }

    // Full file
    header("Content-Type: $mime");
    header("Content-Length: $fileSize");
    readfile($file);
    exit;
}

// File not found — fall through to PHP's default 404
return false;
