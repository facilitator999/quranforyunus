<?php
/**
 * Dynamic OG image generator for shared verse links.
 * Renders a card with Arabic text + English translation.
 * Usage: og-image.php?verse=113:5
 */

$verse = isset($_GET['verse']) ? $_GET['verse'] : null;
if (!$verse || !preg_match('/^(\d{1,3}):(\d{1,3})$/', $verse, $m)) {
    http_response_code(404);
    exit;
}

$surahNum = (int)$m[1];
$ayahNum  = (int)$m[2];
if ($surahNum < 1 || $surahNum > 114 || $ayahNum < 1) { http_response_code(404); exit; }

$surahNames = [1=>'Al-Fatiha',2=>'Al-Baqarah',3=>'Al-Imran',4=>"An-Nisa'",5=>"Al-Ma'idah",6=>"Al-An'am",7=>"Al-A'raf",8=>'Al-Anfal',9=>'At-Tawbah',10=>'Yunus',11=>'Hud',12=>'Yusuf',13=>"Ar-Ra'd",14=>'Ibrahim',15=>'Al-Hijr',16=>'An-Nahl',17=>'Al-Isra',18=>'Al-Kahf',19=>'Maryam',20=>'Ta Ha',21=>'Al-Anbiya',22=>'Al-Hajj',23=>'Al-Muminun',24=>'An-Nur',25=>'Al-Furqan',26=>"Ash-Shu'ara",27=>'An-Naml',28=>'Al-Qasas',29=>'Al-Ankabut',30=>'Ar-Rum',31=>'Luqman',32=>'As-Sajdah',33=>'Al-Ahzab',34=>'Saba',35=>'Fatir',36=>'Ya Sin',37=>'As-Saffat',38=>'Sad',39=>'Az-Zumar',40=>'Ghafir',41=>'Fussilat',42=>'Ash-Shura',43=>'Az-Zukhruf',44=>'Ad-Dukhan',45=>'Al-Jathiyah',46=>'Al-Ahqaf',47=>'Muhammad',48=>'Al-Fath',49=>'Al-Hujurat',50=>'Qaf',51=>'Ad-Dhariyat',52=>'At-Tur',53=>'An-Najm',54=>'Al-Qamar',55=>'Ar-Rahman',56=>"Al-Waqi'ah",57=>'Al-Hadid',58=>'Al-Mujadalah',59=>'Al-Hashr',60=>'Al-Mumtahanah',61=>'As-Saff',62=>'Al-Jumuah',63=>'Al-Munafiqun',64=>'At-Taghabun',65=>'At-Talaq',66=>'At-Tahrim',67=>'Al-Mulk',68=>'Al-Qalam',69=>'Al-Haqqah',70=>'Al-Maarij',71=>'Nuh',72=>'Al-Jinn',73=>'Al-Muzzammil',74=>'Al-Muddaththir',75=>'Al-Qiyamah',76=>'Al-Insan',77=>'Al-Mursalat',78=>'An-Naba',79=>"An-Nazi'at",80=>'Abasa',81=>'At-Takwir',82=>'Al-Infitar',83=>'Al-Mutaffifin',84=>'Al-Inshiqaq',85=>'Al-Buruj',86=>'At-Tariq',87=>"Al-A'la",88=>'Al-Ghashiyah',89=>'Al-Fajr',90=>'Al-Balad',91=>'Ash-Shams',92=>'Al-Layl',93=>'Ad-Duha',94=>'Ash-Sharh',95=>'At-Tin',96=>'Al-Alaq',97=>'Al-Qadr',98=>'Al-Bayyinah',99=>'Az-Zalzalah',100=>'Al-Adiyat',101=>"Al-Qari'ah",102=>'At-Takathur',103=>'Al-Asr',104=>'Al-Humazah',105=>'Al-Fil',106=>'Quraysh',107=>"Al-Ma'un",108=>'Al-Kawthar',109=>'Al-Kafirun',110=>'An-Nasr',111=>'Al-Masad',112=>'Al-Ikhlas',113=>'Al-Falaq',114=>'An-Nas'];

$surahName = $surahNames[$surahNum] ?? null;
if (!$surahName) { http_response_code(404); exit; }

// Find verse data
$raw = file_get_contents(__DIR__ . '/data/full_quran.json');
$raw = preg_replace('/^\xEF\xBB\xBF/', '', $raw);
$fq = json_decode($raw, true);
$ssp = [];
foreach ($fq as $pg => $inf) { foreach ($inf['surahs'] as $s) { if (!isset($ssp[$s])) $ssp[$s] = (int)$pg; } }
$startPg = $ssp[$surahNum] ?? 1;
$vk = $surahNum . ':' . $ayahNum;

$arabicText = '';
$translationText = '';
$found = false;

for ($i = 0; $i < 40; $i++) {
    $pg = $startPg + $i;
    if ($pg > 604) break;
    $path = __DIR__ . '/data/pages/' . $pg . '.json';
    if (!file_exists($path)) continue;
    $pgRaw = file_get_contents($path);
    $pgRaw = preg_replace('/^\xEF\xBB\xBF/', '', $pgRaw);
    $pd = json_decode($pgRaw, true);
    if (!$pd || !isset($pd['verses'])) continue;
    foreach ($pd['verses'] as $v) {
        if ($v['verse_key'] === $vk) {
            $ar = []; $tr = [];
            foreach ($v['words'] as $w) {
                if ($w['char_type_name'] === 'word') {
                    $ar[] = $w['text_uthmani'];
                    $tr[] = $w['translation']['text'] ?? '';
                }
            }
            $arabicText = implode(' ', $ar);
            $translationText = implode(' ', $tr);
            $found = true;
            break 2;
        }
    }
}

if (!$found) { http_response_code(404); exit; }

// --- Image generation ---
$W = 500;
$H = 500;
$pad = 36;
$im = imagecreatetruecolor($W, $H);
imagesavealpha($im, true);

// Colours — dark teal card
$bg       = imagecolorallocate($im, 17, 30, 30);
$teal     = imagecolorallocate($im, 45, 212, 191);
$tealDim  = imagecolorallocate($im, 20, 78, 74);
$white    = imagecolorallocate($im, 240, 240, 235);
$cream    = imagecolorallocate($im, 200, 200, 190);
$muted    = imagecolorallocate($im, 140, 140, 130);

imagefill($im, 0, 0, $bg);

// Subtle border
imagerectangle($im, 16, 16, $W - 17, $H - 17, $tealDim);

// Fonts
$arabicFont  = __DIR__ . '/fonts/UthmanicHafs1Ver18.ttf';
$latinFont   = '/usr/share/fonts/open-sans/OpenSans-Semibold.ttf';
$latinLight  = '/usr/share/fonts/open-sans/OpenSans-LightItalic.ttf';

// --- Header: Surah name + verse number (centered) ---
$header = "Surah $surahName — Verse $ayahNum";
$box = imagettfbbox(16, 0, $latinFont, $header);
$hw = abs($box[2] - $box[0]);
imagettftext($im, 16, 0, (int)(($W - $hw) / 2), 56, $teal, $latinFont, $header);

// Thin accent line under header
imagesetthickness($im, 2);
imageline($im, $pad, 72, $W - $pad, 72, $tealDim);

// --- Arabic text (centered, multi-line, auto-sized) ---
$maxWidth = $W - $pad * 2;
$arabicSize = 32;
while ($arabicSize > 16) {
    $box = imagettfbbox($arabicSize, 0, $arabicFont, $arabicText);
    if (abs($box[2] - $box[0]) <= $maxWidth) break;
    $arabicSize -= 2;
}

// Wrap into lines
$arabicLines = [];
$words = explode(' ', $arabicText);
$line = '';
foreach ($words as $word) {
    $test = $line ? $line . ' ' . $word : $word;
    $box = imagettfbbox($arabicSize, 0, $arabicFont, $test);
    if (abs($box[2] - $box[0]) > $maxWidth && $line) {
        $arabicLines[] = $line;
        $line = $word;
    } else {
        $line = $test;
    }
}
if ($line) $arabicLines[] = $line;

// Limit Arabic lines to fit
$maxArabicLines = 4;
if (count($arabicLines) > $maxArabicLines) {
    $arabicLines = array_slice($arabicLines, 0, $maxArabicLines);
    $arabicLines[$maxArabicLines - 1] .= ' ...';
}

$lineHeight = (int)($arabicSize * 1.8);
$totalArabicH = count($arabicLines) * $lineHeight;

// Vertically center the Arabic block in the middle zone (between header line and separator)
$arabicZoneTop = 90;
$arabicZoneBot = $H - 170;
$arabicY = $arabicZoneTop + (int)(($arabicZoneBot - $arabicZoneTop - $totalArabicH) / 2) + $arabicSize;

foreach ($arabicLines as $idx => $aLine) {
    $box = imagettfbbox($arabicSize, 0, $arabicFont, $aLine);
    $lw = abs($box[2] - $box[0]);
    $x = (int)(($W - $lw) / 2);
    $y = $arabicY + $idx * $lineHeight;
    imagettftext($im, $arabicSize, 0, $x, $y, $white, $arabicFont, $aLine);
}

// --- Decorative dots separator ---
$sepY = $arabicY + (count($arabicLines) - 1) * $lineHeight + 28;
$cx = (int)($W / 2);
for ($d = -2; $d <= 2; $d++) {
    imagefilledellipse($im, $cx + $d * 16, $sepY, $d == 0 ? 5 : 3, $d == 0 ? 5 : 3, $teal);
}

// --- Translation text (centered, multi-line) ---
$transSize = 14;
$transY = $sepY + 28;
$transMaxW = $W - $pad * 2 - 20;

$transWords = explode(' ', '"' . $translationText . '"');
$transLines = [];
$line = '';
foreach ($transWords as $word) {
    $test = $line ? $line . ' ' . $word : $word;
    $box = imagettfbbox($transSize, 0, $latinLight, $test);
    if (abs($box[2] - $box[0]) > $transMaxW && $line) {
        $transLines[] = $line;
        $line = $word;
    } else {
        $line = $test;
    }
}
if ($line) $transLines[] = $line;

if (count($transLines) > 3) {
    $transLines = array_slice($transLines, 0, 3);
    $transLines[2] = rtrim($transLines[2], ' .,;') . '...';
}

foreach ($transLines as $idx => $tLine) {
    $box = imagettfbbox($transSize, 0, $latinLight, $tLine);
    $lw = abs($box[2] - $box[0]);
    $x = (int)(($W - $lw) / 2);
    $y = $transY + $idx * 24;
    imagettftext($im, $transSize, 0, $x, $y, $cream, $latinLight, $tLine);
}

// --- Footer: site name ---
$footer = 'quranforyunus.com';
$box = imagettfbbox(12, 0, $latinFont, $footer);
$fw = abs($box[2] - $box[0]);
imagettftext($im, 12, 0, (int)(($W - $fw) / 2), $H - 30, $muted, $latinFont, $footer);

// --- Output ---
header('Content-Type: image/png');
header('Cache-Control: public, max-age=86400');
imagepng($im);
imagedestroy($im);
