<?php
// If this file is included into an HTML page, don't send plain-text headers.
// If it is executed directly (CLI or direct web hit), default to plain text.
// Based on work done here: https://wttr.in/36.446985,-100.593767
// https://github.com/chubin/wttr.in

$isCli = (PHP_SAPI === 'cli');
$scriptFilename = isset($_SERVER['SCRIPT_FILENAME']) ? $_SERVER['SCRIPT_FILENAME'] : '';
$isDirectWebHit = (!$isCli && $scriptFilename && realpath($scriptFilename) === realpath(__FILE__));

// -------------------------
// Input helpers
// -------------------------
function clampInt($v, $min, $max, $default) {
    if ($v === null || $v === '') return $default;
    if (!is_numeric($v)) return $default;
    $i = (int)$v;
    if ($i < $min) return $min;
    if ($i > $max) return $max;
    return $i;
}

function parseKeyValueArg($arg) {
    // Accept "days=3" style args (CLI)
    $eq = strpos($arg, '=');
    if ($eq === false) return null;
    $k = trim(substr($arg, 0, $eq));
    $v = trim(substr($arg, $eq + 1));
    if ($k === '') return null;
    return array($k, $v);
}

function getRequestedDays($argv, $isCli) {
    $days = null;

    if (!$isCli) {
        if (isset($_GET['days'])) $days = $_GET['days'];
    } else {
        // Accept: php weather.php 90210 days=3
        for ($i = 1; $i < count($argv); $i++) {
            $kv = parseKeyValueArg($argv[$i]);
            if ($kv && strtolower($kv[0]) === 'days') {
                $days = $kv[1];
                break;
            }
        }
    }

    return clampInt($days, 1, 7, 7);
}

function getRequestedFormat($isCli, $isDirectWebHit) {
    // html/text selection:
    // - included => HTML (handled later)
    // - CLI => text
    // - direct endpoint => text unless ?format=html
    if ($isCli) return 'text';

    $format = isset($_GET['format']) ? strtolower(trim($_GET['format'])) : null;
    if ($format === 'html' || $format === 'text') {
        return $format;
    }

    return $isDirectWebHit ? 'text' : 'html';
}

// -------------------------
// HTTP headers (only when appropriate)
// -------------------------
$format = getRequestedFormat($isCli, $isDirectWebHit);
if (($isCli || $isDirectWebHit) && !headers_sent()) {
    if ($format === 'html') {
        header('Content-Type: text/html; charset=utf-8');
    } else {
        header('Content-Type: text/plain; charset=utf-8');
    }
}

// Fetch data from weather.gov API
function fetchWeatherData($url) {
    $ch = curl_init($url);
    curl_setopt_array($ch, array(
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_CONNECTTIMEOUT => 10,
        CURLOPT_TIMEOUT => 20,
        CURLOPT_USERAGENT => 'PHP Weather Script (contact: your-email@example.com)',
        CURLOPT_HTTPHEADER => array(
            'Accept: application/geo+json, application/json;q=0.9, */*;q=0.8'
        ),
    ));

    $response = curl_exec($ch);
    $curlErrNo = curl_errno($ch);
    $curlErr = curl_error($ch);
    $httpCode = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($response === false) {
        throw new Exception("API request failed (cURL $curlErrNo): $curlErr");
    }
    if ($httpCode !== 200) {
        throw new Exception("API request failed with status $httpCode");
    }

    $decoded = json_decode($response, true);
    if (!is_array($decoded)) {
        throw new Exception("API response was not valid JSON");
    }

    return $decoded;
}

// Load zip code data from CSV
function loadZipCodeData($file = '2024_Gaz_zcta_national.txt') {
    $zipData = array();
    if (($handle = fopen($file, 'r')) !== false) {
        while (($line = fgets($handle)) !== false) {
            $fields = explode("\t", trim($line));
            if (count($fields) >= 7) {
                $zipCode = $fields[0];
                $lat = (float)$fields[5];
                $lon = (float)$fields[6];
                $zipData[$zipCode] = array('lat' => $lat, 'lon' => $lon);
            }
        }
        fclose($handle);
    } else {
        throw new Exception("Unable to open $file");
    }
    return $zipData;
}

// Get grid coordinates from input
function getGridCoordinates($input) {
    $input = trim($input);

    // lat,long
    if (preg_match('/^-?\d+\.?\d*,-?\d+\.?\d*$/', $input)) {
        list($lat, $lon) = explode(',', $input);
        $data = fetchWeatherData("https://api.weather.gov/points/$lat,$lon");
    }
    // grid square (4 or 6 chars)
    elseif (preg_match('/^[A-R]{2}[0-9]{2}([a-x]{2})?$/i', $input)) {
        $grid = strtoupper($input);

        $lon = (ord($grid[0]) - 65) * 20 - 180;
        $lat = (ord($grid[1]) - 65) * 10 - 90;

        $squareNum = (int)substr($grid, 2, 2);
        $lon += (int)($squareNum / 10) * 2;
        $lat += $squareNum % 10;

        if (strlen($grid) == 6) {
            $lon += (ord($grid[4]) - 65) * (5 / 60);
            $lat += (ord($grid[5]) - 65) * (2.5 / 60);
            $lon += (5 / 60) / 2;
            $lat += (2.5 / 60) / 2;
        } else {
            $lon += 1;
            $lat += 0.5;
        }

        $data = fetchWeatherData("https://api.weather.gov/points/$lat,$lon");
    }
    // zip
    elseif (preg_match('/^\d{5}$/', $input)) {
        static $zipData = null;
        if ($zipData === null) {
            $zipData = loadZipCodeData('2024_Gaz_zcta_national.txt');
        }
        if (!isset($zipData[$input])) {
            throw new Exception("Zip code $input not found in '2024_Gaz_zcta_national.txt'");
        }
        $lat = $zipData[$input]['lat'];
        $lon = $zipData[$input]['lon'];
        $data = fetchWeatherData("https://api.weather.gov/points/$lat,$lon");
    }
    else {
        throw new Exception("Invalid input. Use: zip (12345), grid (EM12), or lat,long (39.95,-75.16)");
    }

    if (!isset($data['properties'])) {
        throw new Exception("Unable to resolve location");
    }

    $props = $data['properties'];
    $locProps = isset($props['relativeLocation']['properties']) ? $props['relativeLocation']['properties'] : array();

    return array(
        'gridId' => $props['gridId'],
        'gridX' => $props['gridX'],
        'gridY' => $props['gridY'],
        'location' => (isset($locProps['city']) ? $locProps['city'] : 'Unknown') . ", " .
            (isset($locProps['state']) ? $locProps['state'] : '--')
    );
}

function safeStr($v, $fallback) {
    if ($v === null) return $fallback;
    $s = trim((string)$v);
    return ($s === '') ? $fallback : $s;
}

/**
 * Weather symbol as ASCII art (5 lines).
 * (This is the "nice ASCII art" version for text/terminal output.)
 */
function getWeatherSymbol($condition) {
    $condition = strtolower((string)$condition);

    if (strpos($condition, 'sunny') !== false || strpos($condition, 'clear') !== false) {
        return array(
            "     \\   /     ",
            "      .-.      ",
            "  -- (   ) --  ",
            "      `-'      ",
            "     /   \\     "
        );
    }
    if (strpos($condition, 'partly cloudy') !== false) {
        return array(
            "    \\  /       ",
            "  _ /\"\".-.     ",
            "    \\_(   ).   ",
            "    /(___(__)  ",
            "               "
        );
    }
    if (strpos($condition, 'cloudy') !== false) {
        return array(
            "    .--.       ",
            " .-(    ).     ",
            "(___.__)__)    ",
            "               ",
            "               "
        );
    }
    if (strpos($condition, 'rain') !== false || strpos($condition, 'shower') !== false) {
        return array(
            "      .-.      ",
            "     (   ).    ",
            "    (___(__)   ",
            "     ' ' ' '   ",
            "    ' ' ' '    "
        );
    }
    if (strpos($condition, 'snow') !== false) {
        return array(
            "   _o/   \o_ ",
            "    _\\/ \\/_   ",
            " o>->=(o)=<-<o ",
            "    -/\\ /\\-   ",
            "   -o\   /o-  "
        );
    }
    if (strpos($condition, 'thunder') !== false) {
        return array(
            "      .-.      ",
            "     (   ).    ",
            "    (___(__)   ",
            "     ' \\\\ ' '  ",
            "    '  / ' '   "
        );
    }
    if (strpos($condition, 'fog') !== false) {
        return array(
            " _ - _ - _ - _ ",
            "  _ - _ - _ -  ",
            " _ - _ - _ - _ ",
            "               ",
            "               "
        );
    }

    // Default: generic cloud
    return array(
        "      .-.      ",
        "     (   ).    ",
        "    (___(__)   ",
        "               ",
        "               "
    );
}

// UTF-8 safe width helpers (fixes padding when using "°")
function utf8_len($s) {
    if (function_exists('mb_strlen')) return mb_strlen($s, 'UTF-8');
    return strlen($s); // fallback (byte-count)
}
function utf8_substr($s, $start, $len) {
    if (function_exists('mb_substr')) return mb_substr($s, $start, $len, 'UTF-8');
    return substr($s, $start, $len); // fallback (byte-count)
}
function utf8_str_pad_right($s, $targetLen, $padChar) {
    $cur = utf8_len($s);
    if ($cur >= $targetLen) return $s;
    return $s . str_repeat($padChar, $targetLen - $cur);
}
function utf8_str_pad_both($s, $targetLen, $padChar) {
    $cur = utf8_len($s);
    if ($cur >= $targetLen) return $s;
    $total = $targetLen - $cur;
    $left = (int)floor($total / 2);
    $right = $total - $left;
    return str_repeat($padChar, $left) . $s . str_repeat($padChar, $right);
}

function renderForecastCellText($p, $humidity) {
    if (!$p) return "--";

    $t = isset($p['temperature']) ? (int)$p['temperature'] : null;
    $u = isset($p['temperatureUnit']) ? $p['temperatureUnit'] : '';
    $sf = safeStr(isset($p['shortForecast']) ? $p['shortForecast'] : null, '--');
    $ws = safeStr(isset($p['windSpeed']) ? $p['windSpeed'] : null, '--');
    $wd = safeStr(isset($p['windDirection']) ? $p['windDirection'] : null, '--');
    $hum = ($humidity !== null) ? sprintf("%d%%", (int)$humidity) : '--%';

    $temp = ($t === null) ? '--' : (string)$t;

    // Put the ASCII art back on top
    $symbol = getWeatherSymbol($sf);

    $lines = array();
    for ($i = 0; $i < count($symbol); $i++) {
        $lines[] = $symbol[$i];
    }
    $lines[] = $temp . "°" . $u;
    $lines[] = $sf;
    $lines[] = "W: " . $ws . " " . $wd;
    $lines[] = "RH: " . $hum;

    $fixed_length_lines = array();
    $target_line_length = 22;

    for($i = 0; $i < count($lines); $i++) {
        if(utf8_len($lines[$i]) > $target_line_length) {
            $fixed_length_lines[] = utf8_substr($lines[$i], 0, $target_line_length);
        }
        if(utf8_len($lines[$i]) == $target_line_length){
            $fixed_length_lines[] = $lines[$i];
        }
        if(utf8_len($lines[$i]) < $target_line_length) {
            $fixed_length_lines[] = utf8_str_pad_right($lines[$i], $target_line_length, " ");
        }
    }

    return implode("\n", $fixed_length_lines);
}

function renderForecastCellHtml($p, $humidity) {
    if (!$p) return "<span class=\"text-muted\">--</span>";
    $t = isset($p['temperature']) ? (int)$p['temperature'] : null;
    $u = isset($p['temperatureUnit']) ? $p['temperatureUnit'] : '';
    $sf = safeStr(isset($p['shortForecast']) ? $p['shortForecast'] : null, '--');
    $ws = safeStr(isset($p['windSpeed']) ? $p['windSpeed'] : null, '--');
    $wd = safeStr(isset($p['windDirection']) ? $p['windDirection'] : null, '--');
    $hum = ($humidity !== null) ? sprintf("%d%%", (int)$humidity) : '--%';

    $temp = ($t === null) ? '--' : (string)$t;
    $symbol = implode("<br>",getWeatherSymbol($sf));

    $html = "";
    $html .= "<div class=\"text-muted\" style=\"font-size:0.85em;white-space:pre;font-family:monospace;\">" . $symbol ."</div>";
    $html .= "<div style=\"font-weight:600;\">" . htmlspecialchars($temp . "°" . $u, ENT_QUOTES, 'UTF-8') . "</div>";
    $html .= "<div>" . htmlspecialchars($sf, ENT_QUOTES, 'UTF-8') . "</div>";
    $html .= "<div class=\"text-muted\" style=\"font-size:0.85em;\">W: " . htmlspecialchars($ws . " " . $wd, ENT_QUOTES, 'UTF-8') . "</div>";
    $html .= "<div class=\"text-muted\" style=\"font-size:0.85em;\">RH: " . htmlspecialchars($hum, ENT_QUOTES, 'UTF-8') . "</div>";
    return $html;
}

function collectDaysData($input, $maxDays) {
    $coords = getGridCoordinates($input);
    $forecast = fetchWeatherData("https://api.weather.gov/gridpoints/{$coords['gridId']}/{$coords['gridX']},{$coords['gridY']}/forecast");
    $gridData = fetchWeatherData("https://api.weather.gov/gridpoints/{$coords['gridId']}/{$coords['gridX']},{$coords['gridY']}");

    if (!isset($forecast['properties']['periods']) || !isset($gridData['properties'])) {
        throw new Exception("Unable to fetch forecast data");
    }

    $periods = $forecast['properties']['periods'];
    $humidityData = isset($gridData['properties']['relativeHumidity']['values'])
        ? $gridData['properties']['relativeHumidity']['values']
        : array();

    $days = array();
    foreach ($periods as $period) {
        if (!isset($period['startTime'])) continue;

        $date = date('Y-m-d', strtotime($period['startTime']));
        if (!isset($days[$date])) {
            $days[$date] = array('date' => $date, 'day' => null, 'night' => null, 'humidity' => null);
        }

        if (!empty($period['isDaytime'])) {
            $days[$date]['day'] = $period;
        } else {
            $days[$date]['night'] = $period;
        }

        if ($days[$date]['humidity'] === null) {
            for ($i = 0; $i < count($humidityData); $i++) {
                $h = $humidityData[$i];
                if (!isset($h['validTime'])) continue;
                $hDate = date('Y-m-d', strtotime($h['validTime']));
                if ($hDate === $date && isset($h['value'])) {
                    $days[$date]['humidity'] = $h['value'];
                    break;
                }
            }
        }
    }

    // Keep first N unique dates
    $out = array();
    foreach ($days as $d) {
        $out[] = $d;
        if (count($out) >= $maxDays) break;
    }

    return array($coords, $out);
}

function buildWeatherHorizontalText($input, $daysCount) {
    list($coords, $days) = collectDaysData($input, $daysCount);

    $out = "";
    $out .= "Forecast for " . $coords['location'] . " (next " . (int)$daysCount . " days)\n";
    $out .= "Source: NOAA NWS • " . date('Y-m-d H:i T') . "\n\n";

    // Fixed-width columns for CLI/text endpoint
    $colW = 22;
    $sep = "+";
    for ($i = 0; $i < count($days); $i++) $sep .= str_repeat("-", $colW) . "+";
    $out .= $sep . "\n";

    // Header row: dates
    $row = "|";
    for ($i = 0; $i < count($days); $i++) {
        $label = date('D m/d', strtotime($days[$i]['date']));
        $row .= utf8_str_pad_both($label, $colW, " ") . "|";
    }
    $out .= $row . "\n";
    $out .= $sep . "\n";

    // Build per-cell line arrays (now includes ASCII art + details)
    $dayCells = array();
    $nightCells = array();

    for ($i = 0; $i < count($days); $i++) {
        $hum = $days[$i]['humidity'];
        $dayCells[$i] = explode("\n", renderForecastCellText($days[$i]['day'], $hum));
        $nightCells[$i] = explode("\n", renderForecastCellText($days[$i]['night'], $hum));
    }

    // DAY label row
    $out .= "|";
    for ($i = 0; $i < count($days); $i++) {
        $out .= utf8_str_pad_both("DAY", $colW, " ") . "|";
    }
    $out .= "\n";

    // Print all DAY lines (dynamic height)
    $maxDayLines = 0;
    for ($i = 0; $i < count($days); $i++) {
        $maxDayLines = max($maxDayLines, count($dayCells[$i]));
    }

    for ($line = 0; $line < $maxDayLines; $line++) {
        $out .= "|";
        for ($i = 0; $i < count($days); $i++) {
            $txt = isset($dayCells[$i][$line]) ? $dayCells[$i][$line] : "";
            if (utf8_len($txt) > $colW) $txt = utf8_substr($txt, 0, $colW);
            $out .= utf8_str_pad_right($txt, $colW, " ") . "|";
        }
        $out .= "\n";
    }

    $out .= $sep . "\n";

    // NIGHT label row
    $out .= "|";
    for ($i = 0; $i < count($days); $i++) {
        $out .= utf8_str_pad_both("NIGHT", $colW, " ") . "|";
    }
    $out .= "\n";

    // Print all NIGHT lines (dynamic height)
    $maxNightLines = 0;
    for ($i = 0; $i < count($days); $i++) {
        $maxNightLines = max($maxNightLines, count($nightCells[$i]));
    }

    for ($line = 0; $line < $maxNightLines; $line++) {
        $out .= "|";
        for ($i = 0; $i < count($days); $i++) {
            $txt = isset($nightCells[$i][$line]) ? $nightCells[$i][$line] : "";
            if (utf8_len($txt) > $colW) $txt = utf8_substr($txt, 0, $colW);
            $out .= utf8_str_pad_right($txt, $colW, " ") . "|";
        }
        $out .= "\n";
    }

    $out .= $sep . "\n";
    return $out;
}

function buildWeatherHorizontalHtml($input, $daysCount) {
    list($coords, $days) = collectDaysData($input, $daysCount);

    $html = "";
    $html .= "<div class=\"weather-forecast\" style=\"overflow-x:auto;\">";
    $html .= "<div style=\"margin-bottom:0.5rem;\">";
    $html .= "<strong>" . htmlspecialchars("Forecast for " . $coords['location'], ENT_QUOTES, 'UTF-8') . "</strong>";
    $html .= " <span class=\"text-muted\" style=\"font-size:0.9em;\">(" . (int)$daysCount . " days)</span>";
    $html .= "</div>";

    $colW = 160;
    $html .= "<table class=\"table table-sm table-bordered\" style=\"table-layout:fixed;width:auto;min-width:" . (count($days) * $colW) . "px;\">";
    $html .= "<thead><tr>";
    $html .= "<th style=\"width:60px;\">&nbsp;</th>";
    for ($i = 0; $i < count($days); $i++) {
        $label = date('D m/d', strtotime($days[$i]['date']));
        $html .= "<th style=\"text-align:center;width:" . $colW . "px;\">" . htmlspecialchars($label, ENT_QUOTES, 'UTF-8') . "</th>";
    }
    $html .= "</tr></thead>";

    $html .= "<tbody>";

    // Day row
    $html .= "<tr>";
    $html .= "<th style=\"vertical-align:top;\">Day</th>";
    for ($i = 0; $i < count($days); $i++) {
        $hum = $days[$i]['humidity'];
        $html .= "<td style=\"vertical-align:top;text-align:center;\">" . renderForecastCellHtml($days[$i]['day'], $hum) . "</td>";
    }
    $html .= "</tr>";

    // Night row
    $html .= "<tr>";
    $html .= "<th style=\"vertical-align:top;\">Night</th>";
    for ($i = 0; $i < count($days); $i++) {
        $hum = $days[$i]['humidity'];
        $html .= "<td style=\"vertical-align:top;text-align:center;\">" . renderForecastCellHtml($days[$i]['night'], $hum) . "</td>";
    }
    $html .= "</tr>";

    $html .= "</tbody></table>";
    $html .= "<div class=\"text-muted\" style=\"font-size:0.85em;\">Source: NOAA NWS &bull; " . htmlspecialchars(date('Y-m-d H:i T'), ENT_QUOTES, 'UTF-8') . "</div>";
    $html .= "</div>";

    return $html;
}

// -------------------------
// Entry point
// -------------------------
$input = isset($argv[1]) ? $argv[1] : (isset($_GET['q']) ? $_GET['q'] : null);
$daysCount = getRequestedDays(isset($argv) ? $argv : array(), $isCli);

if (!$input) {
    if ($isCli || $isDirectWebHit) {
        echo "Usage:\n";
        echo "  php weather.php <location> days=3\n";
        echo "  or via URL: ?q=<location>&days=3\n";
        echo "Optional:\n";
        echo "  &format=html   (web endpoint)\n";
        echo "Examples:\n";
        echo "  90210         (zip code)\n";
        echo "  EM12          (grid square)\n";
        echo "  39.95,-75.16  (lat,long)\n";
        exit;
    }
    // Included into a page and no input provided => default to a sensible value if present, else do nothing.
    // If you want a default location on the homepage, set it here.
    return;
}

try {
    // Included into a page => force HTML
    $includedIntoPage = (!$isCli && !$isDirectWebHit);

    if ($includedIntoPage || $format === 'html') {
        echo buildWeatherHorizontalHtml($input, $daysCount);
    } else {
        echo buildWeatherHorizontalText($input, $daysCount);
    }
} catch (Exception $e) {
    $msg = "┌─────────────┐\n";
    $msg .= "│   Error     │\n";
    $msg .= "└─────────────┘\n";
    $msg .= $e->getMessage() . "\n";

    $includedIntoPage = (!$isCli && !$isDirectWebHit);
    if ($includedIntoPage || $format === 'html') {
        echo "<pre>" . htmlspecialchars($msg, ENT_QUOTES, 'UTF-8') . "</pre>";
    } else {
        echo $msg;
    }
}